"""
Tests for the vision detector.

Nothing here loads real weights, imports ultralytics or opens
a socket. The inference runtime is replaced by a fake, so the
tests exercise the reduction from raw model output to an
accepted, explainable count without needing the model.

The focus is the behaviour that protects the caller: a
missing model must never look like an empty room, a corrupt
upload must never reach the model, and a non-person detection
must never be counted.
"""

import io
import math

import pytest

from vision_fakes import (
    FakeBoxes,
    FakeModel,
    FakeResult,
    install_model,
    make_jpeg,
    make_png,
    people_result,
)
from vision.config import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    DEFAULT_IOU_THRESHOLD,
    MODEL_FILENAME,
    PERSON_CLASS_ID,
)
from vision.detector import (
    ImageValidationError,
    InferenceError,
    ModelUnavailableError,
    PersonDetector,
    UnsupportedFormatError,
    UploadTooLargeError,
    _aggregate_confidence,
    _sanitize_confidence,
    validate_image,
)


@pytest.fixture
def detector():
    return PersonDetector()


# ============================================================
# IMAGE VALIDATION
# ============================================================


def test_valid_png_is_accepted():
    info = validate_image(make_png(640, 480))

    assert info.image_format == "PNG"
    assert (info.width, info.height) == (640, 480)


def test_valid_jpeg_is_accepted():
    info = validate_image(make_jpeg(800, 600))

    assert info.image_format == "JPEG"
    assert (info.width, info.height) == (800, 600)


def test_empty_upload_is_rejected():
    with pytest.raises(ImageValidationError):
        validate_image(b"")


def test_truncated_png_is_rejected():
    with pytest.raises(ImageValidationError):
        validate_image(make_png(truncate=True))


def test_truncated_jpeg_is_rejected():
    with pytest.raises(ImageValidationError):
        validate_image(make_jpeg(truncate=True))


def test_corrupt_png_header_is_rejected():
    with pytest.raises(ImageValidationError):
        validate_image(make_png(drop_header=True))


def test_zero_dimension_jpeg_is_rejected():
    with pytest.raises(ImageValidationError):
        validate_image(make_jpeg(empty_frame=True))


def test_non_image_bytes_are_rejected():
    with pytest.raises(UnsupportedFormatError):
        validate_image(b"this is a text file, not an image")


def test_oversized_upload_is_rejected():
    payload = make_png()

    with pytest.raises(UploadTooLargeError):
        validate_image(payload, max_bytes=10)


def test_unsupported_content_type_is_rejected():
    with pytest.raises(UnsupportedFormatError):
        validate_image(
            make_png(),
            declared_content_type="image/gif",
        )


def test_mislabelled_content_type_is_still_decoded():
    # The bytes decide. A caller that mislabels a PNG as a
    # JPEG has still uploaded a usable image.
    info = validate_image(
        make_png(),
        declared_content_type="image/jpeg",
    )

    assert info.image_format == "PNG"


# ============================================================
# MODEL AVAILABILITY
# ============================================================


class _NoWeightsDetector(PersonDetector):
    """
    A detector that can never resolve weights.

    Used instead of relying on the weights being absent, so the
    test means the same thing on a developer machine that has
    downloaded the model and on CI that has not.
    """

    def resolve_weights_path(self):
        return None


def test_missing_weights_raise_unavailable_not_empty():
    # A detector with no weights must refuse rather than report
    # an empty room.
    with pytest.raises(ModelUnavailableError):
        _NoWeightsDetector().detect(make_png())


def test_unavailable_message_is_actionable():
    with pytest.raises(ModelUnavailableError) as exc:
        _NoWeightsDetector().detect(make_png())

    message = str(exc.value)

    assert MODEL_FILENAME in message
    assert "VISION_MODEL_PATH" in message


def test_is_available_is_false_without_weights():
    assert _NoWeightsDetector().is_available() is False


def test_configured_weights_path_is_honoured(tmp_path):
    weights = tmp_path / "custom.pt"
    weights.write_bytes(b"not really weights")

    configured = PersonDetector(model_path=str(weights))

    assert configured.resolve_weights_path() == weights


def test_corrupt_weights_do_not_crash_resolution(tmp_path):
    # Resolution only answers "is there a file". Loading is
    # what would fail, and that is reported separately.
    weights = tmp_path / "custom.pt"
    weights.write_bytes(b"")

    configured = PersonDetector(model_path=str(weights))

    assert configured.resolve_weights_path() == weights


# ============================================================
# DETECTION
# ============================================================


def test_successful_person_detection(detector):
    model = install_model(
        detector, people_result(count=3, confidence=0.88)
    )

    result = detector.detect(make_png())

    assert result.people_count == 3
    assert result.confidence == pytest.approx(0.88)
    assert len(result.detections) == 3
    assert model.calls, "the model was called"


def test_zero_person_image(detector):
    install_model(detector, people_result(count=0))

    result = detector.detect(make_png())

    assert result.people_count == 0
    assert result.detections == ()
    assert result.confidence == 0.0


def test_thresholds_are_sent_to_the_model(detector):
    model = install_model(
        detector, people_result(count=1)
    )

    detector.detect(make_png())

    call = model.calls[0]

    assert call["conf"] == DEFAULT_CONFIDENCE_THRESHOLD
    assert call["iou"] == DEFAULT_IOU_THRESHOLD
    assert call["classes"] == [PERSON_CLASS_ID]


def test_detection_below_threshold_is_filtered(detector):
    # The model returned a box anyway; the detector must drop
    # it rather than trust the caller's threshold argument.
    install_model(
        detector,
        FakeResult(
            (
                [[0.0, 0.0, 10.0, 10.0]],
                [0.30],
                [0.0],
            )
        ),
    )

    result = detector.detect(make_png())

    assert result.people_count == 0


def test_non_person_classes_are_discarded(detector):
    # COCO 0 is person, 56 is chair. A chair is not a person.
    install_model(
        detector,
        FakeResult(
            (
                [
                    [0.0, 0.0, 10.0, 10.0],
                    [20.0, 20.0, 30.0, 30.0],
                    [40.0, 40.0, 50.0, 50.0],
                ],
                [0.95, 0.99, 0.93],
                [0.0, 56.0, 57.0],
            )
        ),
    )

    result = detector.detect(make_png())

    assert result.people_count == 1
    assert result.detections[0].confidence == pytest.approx(0.95)


def test_multiple_detections_with_mixed_confidence(detector):
    install_model(
        detector,
        FakeResult(
            (
                [
                    [0.0, 0.0, 10.0, 10.0],
                    [20.0, 20.0, 30.0, 30.0],
                    [40.0, 40.0, 50.0, 50.0],
                ],
                [0.95, 0.44, 0.70],
                [0.0, 0.0, 0.0],
            )
        ),
    )

    result = detector.detect(make_png())

    assert result.people_count == 2
    assert result.confidence == pytest.approx((0.95 + 0.70) / 2)


def test_nan_confidence_is_discarded(detector):
    # NaN is not a low score, it is a missing score. Averaging
    # it would poison the aggregate.
    install_model(
        detector,
        FakeResult(
            (
                [
                    [0.0, 0.0, 10.0, 10.0],
                    [20.0, 20.0, 30.0, 30.0],
                ],
                [0.90, float("nan")],
                [0.0, 0.0],
            )
        ),
    )

    result = detector.detect(make_png())

    assert result.people_count == 1
    assert math.isfinite(result.confidence)


def test_evidence_carries_box_and_label(detector):
    install_model(detector, people_result(count=1))

    result = detector.detect(make_png())

    evidence = result.evidence[0]

    assert evidence["label"] == "person"
    assert set(evidence["bbox"]) == {"x1", "y1", "x2", "y2"}
    assert 0.0 <= evidence["confidence"] <= 1.0


def test_null_boxes_yield_no_detections(detector):
    install_model(
        detector, FakeResult(FakeBoxes(xyxy=None))
    )

    result = detector.detect(make_png())

    assert result.people_count == 0


def test_inference_failure_raises(detector):
    install_model(
        detector,
        FakeModel(raises=RuntimeError("cuda exploded")),
    )

    with pytest.raises(InferenceError) as exc:
        detector.detect(make_png())

    assert "cuda exploded" in str(exc.value)


def test_none_result_raises(detector):
    install_model(
        detector, FakeModel(returns_none=True)
    )

    with pytest.raises(InferenceError):
        detector.detect(make_png())


def test_corrupt_image_never_reaches_the_model(detector):
    model = install_model(
        detector, people_result(count=5)
    )

    with pytest.raises(ImageValidationError):
        detector.detect(b"corrupt")

    assert model.calls == [], (
        "the model must not run on an unvalidated upload"
    )


# ============================================================
# CONFIDENCE SANITISATION
# ============================================================


@pytest.mark.parametrize(
    "raw,expected",
    [
        (0.5, 0.5),
        (0, 0.0),
        (1, 1.0),
        (1.5, 1.0),
        (-0.2, 0.0),
        (float("nan"), None),
        (float("inf"), None),
        ("0.7", 0.7),
        (None, None),
        ("abc", None),
    ],
)
def test_sanitize_confidence(raw, expected):
    assert _sanitize_confidence(raw) == expected


def test_aggregate_of_empty_is_zero():
    assert _aggregate_confidence([]) == 0.0


def test_aggregate_is_mean():
    from vision.detector import Detection

    detections = [
        Detection("person", 0.5, 0, 0, 1, 1),
        Detection("person", 1.0, 0, 0, 1, 1),
    ]

    assert _aggregate_confidence(detections) == 0.75


# ============================================================
# LAZY LOADING
# ============================================================


def test_construction_does_not_load_a_model():
    # Building a detector must be free: no import of the
    # inference runtime, no filesystem probe.
    assert PersonDetector()._model_loaded is False

# ============================================================
# REGRESSIONS FOUND BY REAL INFERENCE
#
# Both of these passed against the fake model and only failed
# against the real Ultralytics runtime, which is why they are
# pinned here.
# ============================================================


def test_list_result_is_unwrapped(detector):
    """
    `YOLO.predict` returns a LIST of Results, one per image.

    Reading `.boxes` straight off that list yields None, so the
    detector silently reported zero people for an image
    containing two. This pins the unwrapping.
    """

    model = FakeModel(
        result=people_result(count=2, confidence=0.8),
        wrap_in_list=True,
    )

    install_model(detector, model)

    result = detector.detect(make_png())

    assert result.people_count == 2
    assert result.confidence == pytest.approx(0.8)


def test_empty_list_result_raises(detector):
    model = FakeModel(
        result=people_result(count=1), wrap_in_list=True
    )
    model.predict = lambda **kw: []

    install_model(detector, model)

    with pytest.raises(InferenceError):
        detector.detect(make_png())


def test_predict_receives_a_decoded_image(detector):
    """
    Ultralytics rejects a raw BytesIO source outright.

    The detector must decode before calling, so this asserts the
    source handed to the model is a decoded image rather than a
    byte stream.
    """

    from PIL import Image

    model = install_model(
        detector, people_result(count=1)
    )

    detector.detect(make_png())

    source = model.calls[0]["source"]

    assert not isinstance(source, (bytes, io.BytesIO))
    assert isinstance(source, Image.Image)


def test_undecodable_image_raises_inference_error(
    detector,
):
    # Structurally valid PNG whose pixel data is nonsense.
    # It must fail loudly rather than count as zero people.
    from vision_fakes import make_png_corrupt_pixels

    model = install_model(
        detector, people_result(count=9)
    )

    with pytest.raises(InferenceError):
        detector.detect(make_png_corrupt_pixels())

    assert model.calls == [], (
        "a corrupt image must not reach the model"
    )
