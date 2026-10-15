"""
Shared builders and fakes for the vision tests.

Images are built with Pillow, which is a declared backend
dependency, so they are genuinely decodable rather than merely
structurally plausible. That matters: the detector decodes an
upload before inference, and hand-assembled bytes that pass a
signature check are not the same thing as a real image.

The corrupt variants are still produced by damaging real image
bytes, so "corrupt" means what it says.
"""

import io
import struct
import zlib
from typing import Any, List, Optional


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _png_chunk(
    chunk_type: bytes,
    payload: bytes,
) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + chunk_type
        + payload
        + struct.pack(
            ">I", zlib.crc32(chunk_type + payload)
        )
    )


def make_png(
    width: int = 640,
    height: int = 480,
    colour_type: int = 2,
    truncate: bool = False,
    drop_header: bool = False,
) -> bytes:
    """
    Builds genuinely decodable PNG bytes.

    `truncate` cuts the file before its end marker.
    `drop_header` corrupts the header chunk length.
    """

    from PIL import Image

    buffer = io.BytesIO()

    Image.new(
        "RGB", (width, height), (32, 64, 96)
    ).save(buffer, format="PNG")

    data = buffer.getvalue()

    if drop_header:
        # Overwrite the IHDR length with an impossible value so
        # the chunk walker rejects the file.
        damaged = bytearray(data)
        damaged[8:12] = b"\x00\x00\x00\x20"
        data = bytes(damaged)

    if truncate:
        # Drop the trailing IEND chunk.
        data = data[:-12]

    return data


def make_jpeg(
    width: int = 800,
    height: int = 600,
    truncate: bool = False,
    empty_frame: bool = False,
) -> bytes:
    """
    Builds genuinely decodable JPEG bytes.

    `truncate` drops the end-of-image marker. `empty_frame`
    produces a hand-built header declaring zero dimensions,
    which no encoder will emit and which the structural
    validator must reject.
    """

    if empty_frame:
        return _handmade_jpeg(width=0, height=0)

    from PIL import Image

    buffer = io.BytesIO()

    Image.new(
        "RGB", (width, height), (96, 64, 32)
    ).save(buffer, format="JPEG", quality=90)

    data = buffer.getvalue()

    if truncate:
        data = data[:-2]

    return data


def _handmade_jpeg(
    width: int = 800,
    height: int = 600,
) -> bytes:
    """
    A JPEG header carrying a single start-of-frame segment.

    Hand-built on purpose: it declares dimensions no encoder
    would produce, which is what the validator needs to catch.
    """

    sof = (
        struct.pack(">B", 8)
        + struct.pack(">HH", height, width)
        + struct.pack(">B", 3)
        + b"\x01\x11\x00"
        + b"\x02\x11\x01"
        + b"\x03\x11\x01"
    )

    return (
        b"\xff\xd8"
        + b"\xff\xc0"
        + struct.pack(">H", len(sof) + 2)
        + sof
        + b"\xff\xd9"
    )

    return body


class FakeBoxes:
    """
    Mimics the subset of `ultralytics` result boxes that the
    detector reads: `xyxy`, `conf` and `cls`.
    """

    def __init__(
        self,
        xyxy: Optional[List[list]] = None,
        conf: Optional[List[float]] = None,
        cls: Optional[List[float]] = None,
    ) -> None:
        self.xyxy = xyxy
        self.conf = conf
        self.cls = cls


class FakeResult:
    def __init__(self, boxes: Any = None) -> None:
        if isinstance(boxes, FakeBoxes) or boxes is None:
            self.boxes = boxes
        else:
            self.boxes = FakeBoxes(*boxes)


class FakeModel:
    """
    A stand-in for `YOLO`.

    Records the keyword arguments it was called with so a test
    can assert the thresholds and class filter that were
    actually sent to the model.
    """

    def __init__(
        self,
        result: Any = None,
        raises: Optional[Exception] = None,
        returns_none: bool = False,
        wrap_in_list: bool = False,
    ) -> None:
        self._result = (
            FakeResult() if result is None else result
        )
        self._raises = raises
        self._returns_none = returns_none
        self._wrap_in_list = wrap_in_list
        self.calls: List[dict] = []

    def predict(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)

        if self._raises is not None:
            raise self._raises

        if self._returns_none:
            return None

        # Real `YOLO.predict` returns a list of Results, one per
        # image. `wrap_in_list` reproduces that so the detector's
        # unwrapping is covered.
        if self._wrap_in_list:
            return [self._result]

        return self._result


def people_result(count: int, confidence: float = 0.9):
    """A result containing `count` person boxes."""

    return FakeResult(
        FakeBoxes(
            xyxy=[
                [10.0 * i, 10.0 * i, 50.0 + i, 90.0 + i]
                for i in range(count)
            ],
            conf=[confidence] * count,
            cls=[0.0] * count,
        )
    )


def install_model(
    detector,
    model: Any,
) -> FakeModel:
    """
    Puts a fake model into a detector as though it had already
    loaded one, so no test ever touches real weights.

    A bare result may be passed instead of a model; it is
    wrapped so the returned object always records its calls.
    """

    if not isinstance(model, FakeModel):
        model = FakeModel(result=model)

    detector._model = model
    detector._model_loaded = True

    return model


# ============================================================
# DETECTOR-LEVEL STUB
# ============================================================

# These live here rather than in a test module because pytest
# imports test files under their bare name, so one test module
# cannot import from another. Shared helpers belong in a module
# that is not itself collected.


def detection_result(
    count: int = 0,
    confidence: float = 0.0,
    detections: Optional[List[Any]] = None,
) -> Any:
    """A `DetectionResult` shaped like a real inference run."""

    from vision.detector import (
        Detection,
        DetectionResult,
        ImageInfo,
    )

    if detections is None:
        detections = [
            Detection(
                label="person",
                confidence=0.9,
                x1=1.0,
                y1=2.0,
                x2=3.0,
                y2=4.0,
            )
            for _ in range(count)
        ]

    return DetectionResult(
        people_count=count,
        confidence=confidence,
        detections=tuple(detections),
        model_name="yolo11n.pt",
        image=ImageInfo(
            image_format="PNG",
            width=640,
            height=480,
            size_bytes=len(make_png()),
        ),
    )


class StubDetector:
    """
    A detector stand-in for service- and API-level tests.

    Returns a canned result or raises, and records the calls it
    received so a test can assert that detection was or was not
    attempted.
    """

    def __init__(
        self,
        result: Any = None,
        raises: Optional[Exception] = None,
        available: bool = True,
    ) -> None:
        self._result = result
        self._raises = raises
        self._available = available

        self.calls: List[tuple] = []

        self.confidence_threshold = 0.45
        self.iou_threshold = 0.50
        self.model_name = "yolo11n.pt"

    def detect(
        self,
        data: bytes,
        declared_content_type: Optional[str] = None,
    ) -> Any:
        self.calls.append((data, declared_content_type))

        if self._raises is not None:
            raise self._raises

        return self._result

    def is_available(self) -> bool:
        return self._available

def make_png_corrupt_pixels(
    width: int = 64,
    height: int = 64,
) -> bytes:
    """
    A PNG that is structurally complete but whose pixel data
    is not decodable.

    It passes a signature and chunk-walk check, so only a real
    decoder rejects it. Used to prove that such an upload
    raises rather than counting as zero people.
    """

    ihdr = struct.pack(
        ">IIBBBBB", width, height, 8, 2, 0, 0, 0
    )

    return (
        PNG_SIGNATURE
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(
            b"IDAT", b"\x78\x9c\xff\xff\xff\xffgarbage"
        )
        + _png_chunk(b"IEND", b"")
    )
