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
# TEMPORAL SMOOTHING
# ============================================================

# A single frame is not an occupancy. One missed detection reads
# as a fall from 47 to 0 and one phantom box reads as a surge,
# and either would move the reported count for a room that never
# actually changed. Counts are therefore smoothed over a short
# window before they are reported.
#
# Five frames is the default because it is long enough to absorb
# one bad frame in either direction and short enough that a real
# change in occupancy still shows up promptly.
DEFAULT_SMOOTHING_WINDOW = 5

# The window is summarised with a median rather than a mean. A
# mean lets a single badly-wrong frame move the reported figure:
# in [47, 45, 46, 46, 0] the mean is 36.8, which is worse than
# either the truth or the outlier. The median is 46.
#
# A median of an even-sized window is the lower of the two
# central values rather than their average, so the result is
# always an observed count and never a fraction nobody counted.
SMOOTHING_METHOD = "median"


# ============================================================
# SOURCE COMPARISON
# ============================================================

# Bands for disagreeing occupancy readings, measured as the
# absolute difference between the camera count and the sensor
# count for the same zone.
#
# The consistent band is not zero-width on purpose. Two systems
# counting the same room by different means will rarely agree
# exactly: a camera cannot see someone behind a pillar, and an
# occupancy sensor counts a body heat signature rather than a
# person. Demanding exact agreement would report a permanent
# discrepancy and train everyone to ignore it.
CONSISTENCY_TOLERANCE = 5

# Above this the two sources are far enough apart that one of them
# is probably wrong, which is the condition worth surfacing.
SIGNIFICANT_DISCREPANCY_THRESHOLD = 10


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