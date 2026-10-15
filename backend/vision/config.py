"""
Detector configuration and safe defaults.

Everything here is a constant. Nothing in this module imports
a model, reads the network or touches the filesystem, so it is
safe to import from a test or from application startup.

Runtime overrides live in `app.core.config.Settings`. The
values in this module are the defaults used when no override
is supplied, and they are also the values documented in the
Phase 7 specification.
"""

from typing import FrozenSet


# ============================================================
# MODEL
# ============================================================

# YOLO11 nano. The smallest of the family: fast enough for a
# per-request analysis on CPU, and the weights file is small
# enough to keep out of version control.
MODEL_FILENAME = "yolo11n.pt"

# Directory the weights are expected in when no explicit path
# is configured. The detector never downloads anything.
DEFAULT_WEIGHTS_DIRNAME = "weights"


# ============================================================
# DETECTION
# ============================================================

# COCO category 0 is `person`. Every other class is discarded
# before a detection is ever counted.
PERSON_CLASS_ID = 0

PERSON_LABEL = "person"

# A detection below this confidence is not accepted. 0.45
# keeps true people while discarding the low-confidence
# furniture-and-texture detections that a small model produces
# on an empty scene.
DEFAULT_CONFIDENCE_THRESHOLD = 0.45

# Non-maximum suppression IoU threshold. 0.50 keeps two boxes
# that overlap by half; anything more similar is one person
# seen twice, not two people.
DEFAULT_IOU_THRESHOLD = 0.50

# Observation type and unit recorded for a person count.
OBSERVATION_TYPE = "people_count"
OBSERVATION_UNIT = "people"


# ============================================================
# UPLOAD LIMITS
# ============================================================

# 10 MiB. Large enough for a modern camera frame, small enough
# that a rejected upload cannot exhaust backend memory.
DEFAULT_MAX_UPLOAD_BYTES = 10 * 1024 * 1024

# Formats accepted. Anything else is refused rather than
# transcoded, because silently re-encoding an upload hides
# what the caller actually sent.
SUPPORTED_FORMATS: FrozenSet[str] = frozenset(
    {"JPEG", "PNG"}
)

SUPPORTED_CONTENT_TYPES: FrozenSet[str] = frozenset(
    {
        "image/jpeg",
        "image/jpg",
        "image/png",
    }
)

# Extensions accepted, used only for logging clarity. The
# decoded format is what actually decides.
SUPPORTED_SUFFIXES: FrozenSet[str] = frozenset(
    {".jpg", ".jpeg", ".png"}
)