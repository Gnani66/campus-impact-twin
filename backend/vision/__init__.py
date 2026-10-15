"""
Offline computer-vision observation engine (Phase 7).

This package turns an uploaded still image into a person count.
It is not a camera client and it does not open a stream.

Importing this package is cheap: it does not import
`ultralytics`, load weights or touch the filesystem. The heavy
model is loaded the first time a detection actually runs, and
a missing model surfaces as `ModelUnavailableError` rather
than an import error at startup.
"""

from vision.config import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    DEFAULT_IOU_THRESHOLD,
    MODEL_FILENAME,
    PERSON_CLASS_ID,
)
from vision.detector import (
    Detection,
    DetectionResult,
    ImageInfo,
    ImageValidationError,
    InferenceError,
    ModelUnavailableError,
    PersonDetector,
    UnsupportedFormatError,
    UploadTooLargeError,
    VisionError,
    detector,
)


__all__ = [
    "DEFAULT_CONFIDENCE_THRESHOLD",
    "DEFAULT_IOU_THRESHOLD",
    "Detection",
    "DetectionResult",
    "ImageInfo",
    "ImageValidationError",
    "InferenceError",
    "MODEL_FILENAME",
    "ModelUnavailableError",
    "PERSON_CLASS_ID",
    "PersonDetector",
    "UnsupportedFormatError",
    "UploadTooLargeError",
    "VisionError",
    "detector",
]