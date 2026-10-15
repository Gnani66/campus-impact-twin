"""
Image validation and YOLO person inference.

Three responsibilities, deliberately separated so each can be
tested without the others:

1. `validate_image` proves the upload is genuine JPEG or PNG
   content. It reads the container structure directly, so a
   corrupt or truncated file is rejected even when Pillow is
   not installed.
2. `PersonDetector` lazily loads YOLO once and runs
   person-only inference.
3. The results are reduced to a `DetectionResult`: a count, an
   aggregate confidence and structured per-detection evidence.

Nothing in this module downloads weights. A missing model is
reported as `ModelUnavailableError`; it is never reported as a
successful zero-person result.
"""

import io
import logging
import math
import os
import struct
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import (
    Any,
    List,
    Optional,
    Sequence,
    Tuple,
)

from vision.config import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    DEFAULT_IOU_THRESHOLD,
    DEFAULT_MAX_UPLOAD_BYTES,
    DEFAULT_WEIGHTS_DIRNAME,
    MODEL_FILENAME,
    PERSON_CLASS_ID,
    PERSON_LABEL,
    SUPPORTED_CONTENT_TYPES,
    SUPPORTED_FORMATS,
)


logger = logging.getLogger(__name__)


PACKAGE_DIR = Path(__file__).resolve().parent


# ============================================================
# ERRORS
# ============================================================


class VisionError(Exception):
    """Base class for every vision failure."""


class ImageValidationError(VisionError):
    """The upload is not usable image content."""


class UnsupportedFormatError(ImageValidationError):
    """The upload is a real image, but not JPEG or PNG."""


class UploadTooLargeError(ImageValidationError):
    """The upload exceeds the documented size limit."""


class ModelUnavailableError(VisionError):
    """
    The detector cannot run: the runtime or the weights are
    missing. Raised instead of returning an empty result,
    because "no people" and "no model" are different facts.
    """


class InferenceError(VisionError):
    """The model was available but inference failed."""


# ============================================================
# VALUE OBJECTS
# ============================================================


@dataclass(frozen=True)
class ImageInfo:
    """What `validate_image` proved about an upload."""

    image_format: str
    width: int
    height: int
    size_bytes: int


@dataclass(frozen=True)
class Detection:
    """
    One accepted person detection.

    Bounding boxes are in pixel coordinates of the uploaded
    image, top-left origin, matching what the model returns.
    """

    label: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float

    def as_dict(self) -> dict:
        return {
            "label": self.label,
            "confidence": self.confidence,
            "bbox": {
                "x1": self.x1,
                "y1": self.y1,
                "x2": self.x2,
                "y2": self.y2,
            },
        }


@dataclass(frozen=True)
class DetectionResult:
    """
    The reduced outcome of one inference run.

    `confidence` is the arithmetic mean of the accepted
    detections. It describes how sure the model was about the
    boxes it drew. It is NOT a calibrated probability that the
    count is correct, and it is not comparable across images.
    """

    people_count: int
    confidence: float
    detections: Tuple[Detection, ...]
    model_name: str
    image: ImageInfo

    @property
    def evidence(self) -> List[dict]:
        return [d.as_dict() for d in self.detections]


# ============================================================
# IMAGE VALIDATION
# ============================================================

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

PNG_HEADER_CHUNK = b"IHDR"
PNG_TRAILER_CHUNK = b"IEND"

# Start-of-frame markers that carry the frame dimensions.
# C4 (DHT), C8 (JPG) and CC (DAC) sit inside the same numeric
# range but are not frame headers.
_JPEG_SOF_MARKERS = frozenset(
    {
        0xC0, 0xC1, 0xC2, 0xC3,
        0xC5, 0xC6, 0xC7,
        0xC9, 0xCA, 0xCB,
        0xCD, 0xCE, 0xCF,
    }
)


def _png_dimensions(data: bytes) -> Tuple[int, int]:
    """
    Walks the PNG chunk list far enough to read IHDR and
    confirm the stream is terminated by IEND.

    Checking for IEND is what separates a complete image from
    a truncated upload that still has a valid signature.
    """

    if len(data) < 8 + 25:
        raise ImageValidationError(
            "PNG is truncated: stream is too short to hold "
            "a header and an end marker"
        )

    offset = 8
    width: Optional[int] = None
    height: Optional[int] = None

    while offset + 8 <= len(data):
        (length,) = struct.unpack(
            ">I", data[offset : offset + 4]
        )
        chunk_type = data[offset + 4 : offset + 8]

        # length, type, payload, CRC
        end = offset + 8 + length + 4

        if end > len(data):
            raise ImageValidationError(
                "PNG is truncated: chunk "
                f"{chunk_type.decode('ascii', 'replace')} "
                "runs past the end of the upload"
            )

        if (
            width is None
            and chunk_type == PNG_HEADER_CHUNK
        ):
            if length != 13:
                raise ImageValidationError(
                    "PNG header chunk is malformed: "
                    f"expected 13 bytes, found {length}"
                )

            width, height = struct.unpack(
                ">II", data[offset + 8 : offset + 16]
            )

        if chunk_type == PNG_TRAILER_CHUNK:
            if width is None or height is None:
                raise ImageValidationError(
                    "PNG is malformed: end marker reached "
                    "before the header chunk"
                )

            return width, height

        offset = end

    raise ImageValidationError(
        "PNG is truncated: no end marker (IEND) found"
    )


def _jpeg_dimensions(data: bytes) -> Tuple[int, int]:
    """
    Finds the first start-of-frame segment and reads the
    frame height and width from it.
    """

    offset = 2
    total = len(data)

    while offset + 4 <= total:
        if data[offset] != 0xFF:
            raise ImageValidationError(
                "JPEG is malformed: expected a marker at "
                f"offset {offset}"
            )

        # Skip fill bytes.
        while (
            offset < total
            and data[offset] == 0xFF
            and data[offset + 1 : offset + 2] == b"\xff"
        ):
            offset += 1

        if offset + 1 >= total:
            break

        marker = data[offset + 1]

        # Standalone markers carry no payload.
        if marker == 0xD8 or 0xD0 <= marker <= 0xD9:
            offset += 2
            continue

        if marker in _JPEG_SOF_MARKERS:
            if offset + 9 > total:
                raise ImageValidationError(
                    "JPEG is truncated inside its frame "
                    "header"
                )

            height, width = struct.unpack(
                ">HH", data[offset + 5 : offset + 9]
            )

            if width == 0 or height == 0:
                raise ImageValidationError(
                    "JPEG frame header declares a zero "
                    "dimension"
                )

            return width, height

        if offset + 4 > total:
            break

        (segment_length,) = struct.unpack(
            ">H", data[offset + 2 : offset + 4]
        )

        if segment_length < 2:
            raise ImageValidationError(
                "JPEG is malformed: segment length "
                f"{segment_length} is invalid"
            )

        offset += 2 + segment_length

    raise ImageValidationError(
        "JPEG is malformed or truncated: no frame header found"
    )


def validate_image(
    data: bytes,
    max_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
    declared_content_type: Optional[str] = None,
) -> ImageInfo:
    """
    Proves that `data` is complete JPEG or PNG image content.

    The declared content type is treated as a hint only. The
    bytes decide, because a caller can label anything it likes
    and a mislabelled upload that decodes cleanly is still
    usable.

    Raises `UploadTooLargeError`, `UnsupportedFormatError` or
    `ImageValidationError`.
    """

    if data is None or len(data) == 0:
        raise ImageValidationError(
            "Uploaded image is empty"
        )

    size = len(data)

    if size > max_bytes:
        raise UploadTooLargeError(
            f"Uploaded image is {size} bytes, which "
            f"exceeds the {max_bytes} byte limit"
        )

    if declared_content_type:
        normalised = (
            declared_content_type.split(";")[0].strip().lower()
        )

        if normalised not in SUPPORTED_CONTENT_TYPES:
            raise UnsupportedFormatError(
                f"Content type '{normalised}' is not "
                "supported. Upload a JPEG or PNG image."
            )

    if data.startswith(PNG_SIGNATURE):
        width, height = _png_dimensions(data)

        image_format = "PNG"
    elif (
        len(data) >= 3
        and data[0] == 0xFF
        and data[1] == 0xD8
        and data[2] == 0xFF
    ):
        if not data.endswith(b"\xff\xd9"):
            raise ImageValidationError(
                "JPEG is truncated: no end-of-image marker"
            )

        width, height = _jpeg_dimensions(data)

        image_format = "JPEG"
    else:
        raise UnsupportedFormatError(
            "Uploaded bytes are not a JPEG or PNG image"
        )

    if image_format not in SUPPORTED_FORMATS:
        raise UnsupportedFormatError(
            f"Detected format {image_format} is not supported"
        )

    logger.info(
        "Validated %s upload: %dx%d, %d bytes",
        image_format,
        width,
        height,
        size,
    )

    return ImageInfo(
        image_format=image_format,
        width=width,
        height=height,
        size_bytes=size,
    )


# ============================================================
# CONFIDENCE
# ============================================================


def _sanitize_confidence(value: Any) -> Optional[float]:
    """
    Coerces a model-supplied score into a finite float in
    0..1, or returns None when it is not a number at all.

    Models can emit NaN on a degenerate frame; NaN is not a
    low score, it is a missing score, and averaging it would
    poison the aggregate.
    """

    try:
        score = float(value)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(score):
        return None

    if score < 0.0:
        return 0.0

    if score > 1.0:
        return 1.0

    return score


def _aggregate_confidence(
    detections: Sequence[Detection],
) -> float:
    """
    Mean confidence of the accepted detections.

    Documented deliberately: this summarises model certainty
    about the boxes it drew. It is not a calibrated
    probability that `people_count` is correct, it is not
    comparable between images, and it is 0.0 when nothing
    was detected rather than None so the column stays
    numeric.
    """

    if not detections:
        return 0.0

    total = sum(d.confidence for d in detections)

    return total / len(detections)


# ============================================================
# DETECTOR
# ============================================================


class PersonDetector:
    """
    Person-only YOLO detector with lazy weight loading.

    The model is loaded on first use inside a lock, so
    concurrent first requests load it once. Construction is
    free: no import of the inference runtime, no filesystem
    access, no network.
    """

    def __init__(
        self,
        confidence_threshold: float = (
            DEFAULT_CONFIDENCE_THRESHOLD
        ),
        iou_threshold: float = DEFAULT_IOU_THRESHOLD,
        model_path: Optional[str] = None,
        max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
    ) -> None:
        self._confidence_threshold = float(
            confidence_threshold
        )
        self._iou_threshold = float(iou_threshold)
        self._model_path = model_path
        self._max_upload_bytes = int(max_upload_bytes)

        self._model: Any = None
        self._model_loaded = False
        self._lock = threading.Lock()

    # --- configuration ---------------------------------------------

    @property
    def confidence_threshold(self) -> float:
        return self._confidence_threshold

    @property
    def iou_threshold(self) -> float:
        return self._iou_threshold

    @property
    def model_name(self) -> str:
        return self._model_path or MODEL_FILENAME

    # --- weights ----------------------------------------------------

    def resolve_weights_path(self) -> Optional[Path]:
        """
        Locates the weights file on disk, or returns None.

        Search order is the configured path, then the
        `vision/weights` directory, then the working
        directory. Download is never attempted.
        """

        candidates = []

        if self._model_path:
            candidates.append(Path(self._model_path))

        candidates.append(
            PACKAGE_DIR
            / DEFAULT_WEIGHTS_DIRNAME
            / MODEL_FILENAME
        )
        candidates.append(Path(MODEL_FILENAME))

        for candidate in candidates:
            try:
                if candidate.is_file():
                    return candidate
            except OSError:
                # A path that cannot be stat'd is simply not a
                # match; keep looking rather than fail here.
                continue

        return None

    def _load_model(self) -> Any:
        """
        Imports the inference runtime and constructs the
        model. Raises `ModelUnavailableError` when either the
        runtime or the weights are missing.
        """

        weights = self.resolve_weights_path()

        if weights is None:
            raise ModelUnavailableError(
                f"YOLO weights '{MODEL_FILENAME}' were not "
                "found and automatic download is disabled. "
                f"Place the file in "
                f"{PACKAGE_DIR / DEFAULT_WEIGHTS_DIRNAME} or "
                "set VISION_MODEL_PATH to an existing file."
            )

        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise ModelUnavailableError(
                "The 'ultralytics' package is not installed, "
                "so person detection cannot run. Install the "
                "backend requirements to enable it."
            ) from exc

        try:
            # A local path is passed explicitly, which is what
            # keeps YOLO from fetching weights over the network.
            return YOLO(str(weights))
        except Exception as exc:
            raise ModelUnavailableError(
                f"YOLO weights at '{weights}' could not be "
                f"loaded: {exc}"
            ) from exc

    def _get_model(self) -> Any:
        if self._model_loaded:
            return self._model

        with self._lock:
            if not self._model_loaded:
                self._model = self._load_model()
                self._model_loaded = True

                logger.info(
                    "Loaded YOLO person detector: %s",
                    self.model_name,
                )

        return self._model

    def is_available(self) -> bool:
        """
        Whether inference could run right now, without running
        it and without raising.
        """

        if self.resolve_weights_path() is None:
            return False

        try:
            import ultralytics  # noqa: F401
        except ImportError:
            return False

        return True

    # --- detection ---------------------------------------------------

    def detect(
        self,
        data: bytes,
        declared_content_type: Optional[str] = None,
    ) -> DetectionResult:
        """
        Validates the upload and counts people in it.

        Order matters: the image is proved valid first, so a
        corrupt upload reports a validation problem rather than
        an inference problem. A successful return means the
        model actually ran.
        """

        image = validate_image(
            data,
            max_bytes=self._max_upload_bytes,
            declared_content_type=declared_content_type,
        )

        model = self._get_model()

        raw = self._run_inference(model, data)

        detections = self._extract_person_detections(raw)

        return DetectionResult(
            people_count=len(detections),
            confidence=_aggregate_confidence(detections),
            detections=tuple(detections),
            model_name=self.model_name,
            image=image,
        )

    def _decode_image(self, data: bytes) -> Any:
        """
        Decodes the upload into an image the model accepts.

        Ultralytics does not take a raw byte stream as a
        prediction source; it wants a path, an array or a
        decoded image. Decoding here rather than in
        `validate_image` keeps structural validation
        dependency-free, and puts the pixel decode on the
        inference path where a real model actually needs it.

        `load()` forces a full decode, so image data that is
        structurally intact but pixel-wise corrupt fails here
        with an explicit error rather than producing a
        fabricated zero-person result.
        """

        try:
            from PIL import Image
        except ImportError as exc:
            raise ModelUnavailableError(
                "Pillow is not installed, so the uploaded "
                "image cannot be decoded for detection."
            ) from exc

        try:
            decoded = Image.open(io.BytesIO(data))
            decoded.load()
        except Exception as exc:
            raise InferenceError(
                "Uploaded image could not be decoded: "
                f"{exc}"
            ) from exc

        if decoded.mode != "RGB":
            decoded = decoded.convert("RGB")

        return decoded

    def _run_inference(self, model: Any, data: bytes) -> Any:
        try:
            result = model.predict(
                source=self._decode_image(data),
                conf=self._confidence_threshold,
                iou=self._iou_threshold,
                classes=[PERSON_CLASS_ID],
                verbose=False,
            )
        except ModelUnavailableError:
            raise
        except VisionError:
            raise
        except Exception as exc:
            raise InferenceError(
                "Person detection failed while running the "
                f"model: {exc}"
            ) from exc

        if result is None:
            raise InferenceError(
                "Person detection returned no result"
            )

        # `YOLO.predict` returns a list with one Results per
        # image, even for a single source. Reading `.boxes`
        # straight off that list silently yields None and an
        # empty count, so the list is unwrapped here.
        if isinstance(result, (list, tuple)):
            if not result:
                raise InferenceError(
                    "Person detection returned no result"
                )

            result = result[0]

        if result is None:
            raise InferenceError(
                "Person detection returned no result"
            )

        return result

    def _extract_person_detections(
        self,
        raw: Any,
    ) -> List[Detection]:
        """
        Reduces raw YOLO output to accepted person detections.

        The class filter is applied here as well as being
        passed to the model. The model call is an optimisation;
        this is the guarantee. A box labelled `person` that
        arrives with a lower score than the configured
        threshold is discarded, so a caller cannot widen the
        net by relaxing one side only.
        """

        boxes = getattr(raw, "boxes", None)

        if boxes is None:
            return []

        try:
            xyxy = boxes.xyxy
            confidences = boxes.conf
            classes = boxes.cls
        except AttributeError as exc:
            raise InferenceError(
                "Detection output is missing bounding box "
                "data"
            ) from exc

        if xyxy is None or confidences is None:
            return []

        detections: List[Detection] = []

        try:
            iterator = range(len(xyxy))
        except TypeError as exc:
            raise InferenceError(
                "Detection output is not iterable"
            ) from exc

        for index in iterator:
            class_value = (
                _scalar(classes[index])
                if classes is not None
                else None
            )

            if class_value is None:
                continue

            try:
                class_id = int(class_value)
            except (TypeError, ValueError):
                continue

            if class_id != PERSON_CLASS_ID:
                continue

            score = _sanitize_confidence(
                _scalar(confidences[index])
            )

            if score is None:
                continue

            if score < self._confidence_threshold:
                continue

            try:
                x1, y1, x2, y2 = (
                    float(value)
                    for value in xyxy[index][:4]
                )
            except (TypeError, ValueError) as exc:
                raise InferenceError(
                    "Detection output contains a "
                    "malformed bounding box"
                ) from exc

            if not all(
                math.isfinite(v)
                for v in (x1, y1, x2, y2)
            ):
                continue

            detections.append(
                Detection(
                    label=PERSON_LABEL,
                    confidence=score,
                    x1=x1,
                    y1=y1,
                    x2=x2,
                    y2=y2,
                )
            )

        return detections


def _scalar(value: Any) -> Any:
    """
    Unwraps a single-element tensor/array so the result can be
    used as a plain Python number.
    """

    item = getattr(value, "item", None)

    if callable(item):
        try:
            return item()
        except (TypeError, ValueError):
            return None

    if isinstance(value, (list, tuple)) and len(value) == 1:
        return value[0]

    return value


# Module-level instance shared by the service. Constructing it
# imports nothing heavy.
detector = PersonDetector()


def build_detector_from_settings(
    settings: Any = None,
) -> PersonDetector:
    """
    Builds a detector from application settings. Used by the
    service and by tests that want explicit thresholds.
    """

    if settings is None:
        from app.core.config import settings as resolved

        settings = resolved

    return PersonDetector(
        confidence_threshold=(
            settings.vision_confidence_threshold
        ),
        iou_threshold=settings.vision_iou_threshold,
        model_path=(
            settings.vision_model_path
            or os.environ.get("VISION_MODEL_PATH")
            or ""
        ),
        max_upload_bytes=settings.vision_max_upload_bytes,
    )