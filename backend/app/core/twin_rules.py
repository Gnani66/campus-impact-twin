"""
Twin status rules (Phase 12).

The status a 3D marker shows is decided here, on the backend, and
nowhere else. A browser that computed its own status would be able
to disagree with the operational record, and two disagreeing
sources of truth is worse than one that is merely simple.

OCCUPANCY IS A RATIO, NOT A HEADCOUNT.

This is the one place the obvious implementation is wrong. Stored
occupancy is a number of people; zones carry a capacity. The
thresholds below are percentages, so they are applied to the
ratio.

Applying them to the raw headcount would read 83 people in a
60-seat hall as 83 percent, which is not what it is: that is 138
percent occupancy, the most serious condition in the list, and it
would render amber. Worse, for any zone with a capacity under 80
the warning threshold would be unreachable and every room would
permanently read normal.

THRESHOLDS ARE ASSUMPTIONS.

They are the values the specification proposes, and they are not
calibrated against this building's sensors. They live in one
frozen dataclass so that they can be argued with and changed
deliberately rather than discovered buried in a conditional.
"""

from dataclasses import dataclass
from typing import Optional


STATUS_NORMAL = "normal"
STATUS_WARNING = "warning"
STATUS_CRITICAL = "critical"
STATUS_OFFLINE = "offline"


@dataclass(frozen=True)
class TwinThresholds:
    """
    Limits at which a zone moves from normal to warning to
    critical. Percentages except where noted.
    """

    # Comfort band for a seated lecture space.
    temperature_warning_c: float = 27.0
    temperature_critical_c: float = 30.0

    humidity_warning_pct: float = 70.0
    humidity_critical_pct: float = 85.0

    # Indoor air quality on the 0-500 index.
    aqi_warning: float = 100.0
    aqi_critical: float = 200.0

    # Humidity is two-sided and the bounds are NOT symmetric.
    # Dry air at 30 percent is uncomfortable for a seated
    # audience and drives complaints; a single upper bound would
    # have ignored it entirely.
    humidity_dry_warning_pct: float = 30.0
    humidity_dry_critical_pct: float = 20.0

    # Carbon dioxide in ppm. A seated lecture generates roughly
    # 25 ppm per person, so this is where ventilation is failing
    # rather than merely being uncool.
    co2_warning_ppm: float = 1000.0
    co2_critical_ppm: float = 1500.0

    # Occupancy as a fraction of capacity. This is the field the
    # specification's thresholds assume and it is the field the
    # stored data does not provide, so the conversion happens
    # before comparison.
    occupancy_warning_ratio: float = 0.80
    occupancy_critical_ratio: float = 0.95

    # Noise in dB, measured at the seating plane.
    sound_warning_db: float = 70.0
    sound_critical_db: float = 85.0

    # A zone whose telemetry is older than this is reported
    # OFFLINE rather than being drawn with stale numbers. Reused
    # from the correlation engine so the twin and the decision
    # engine agree about what "live" means.
    telemetry_offline_after_seconds: float = 30.0


DEFAULT_TWIN_THRESHOLDS = TwinThresholds()


def occupancy_ratio(
    people: Optional[float],
    capacity: Optional[float],
) -> Optional[float]:
    """
    Headcount as a fraction of capacity.

    Returns None when the ratio cannot be established. Unknown
    capacity is different from an empty room, and the caller needs
    to be able to tell them apart: one is "we cannot tell", the
    other is "nobody is here".
    """

    if people is None or capacity is None:
        return None

    try:
        count = float(people)
        room = float(capacity)
    except (TypeError, ValueError):
        return None

    if room <= 0:
        return None

    if count < 0:
        return None

    return count / room


def determine_status(
    temperature: Optional[float] = None,
    humidity: Optional[float] = None,
    aqi: Optional[float] = None,
    co2_ppm: Optional[float] = None,
    occupancy_ratio_value: Optional[float] = None,
    sound: Optional[float] = None,
    offline: bool = False,
    thresholds: TwinThresholds = DEFAULT_TWIN_THRESHOLDS,
) -> str:
    """
    Grades one zone as normal, warning, critical or offline.

    Every dimension is optional and a missing one is skipped
    rather than treated as zero. A zone with no AQI sensor is not
    thereby in perfect air quality, and a zone with no sound
    meter is not thereby quiet.

    Offline dominates everything. A stale reading is not a
    measurement, and colouring a dead sensor green would be the
    single most misleading thing this endpoint could do.
    """

    if offline:
        return STATUS_OFFLINE

    critical = False
    warning = False
    reasons = []

    def grade(value, warn, crit, name, unit=""):
        nonlocal critical, warning

        if value is None:
            return

        # Rounded for display only. The stored value keeps its
        # full precision; a reason reading "0.9166666666666666
        # of capacity" is technically accurate and unreadable.
        value = round(float(value), 2)

        suffix = f" {unit}" if unit else ""

        if value >= crit:
            critical = True
            reasons.append(
                f"{name} {value}{suffix} is at or above the "
                f"critical limit of {crit}{suffix}"
            )
        elif value >= warn:
            warning = True
            reasons.append(
                f"{name} {value}{suffix} is at or above the "
                f"warning limit of {warn}{suffix}"
            )

    grade(
        temperature,
        thresholds.temperature_warning_c,
        thresholds.temperature_critical_c,
        "Temperature",
        "C",
    )

    grade(
        humidity,
        thresholds.humidity_warning_pct,
        thresholds.humidity_critical_pct,
        "Humidity",
        "%",
    )

    # Dry air is graded separately because the severity runs
    # downwards while everything else runs upwards.
    if humidity is not None:
        if humidity <= thresholds.humidity_dry_critical_pct:
            critical = True
            reasons.append(
                f"Humidity {humidity}% is at or below the dry "
                f"critical limit of "
                f"{thresholds.humidity_dry_critical_pct}%"
            )
        elif humidity <= thresholds.humidity_dry_warning_pct:
            warning = True
            reasons.append(
                f"Humidity {humidity}% is at or below the dry "
                f"warning limit of "
                f"{thresholds.humidity_dry_warning_pct}%"
            )

    grade(aqi, thresholds.aqi_warning,
          thresholds.aqi_critical, "Air quality")

    grade(
        co2_ppm,
        thresholds.co2_warning_ppm,
        thresholds.co2_critical_ppm,
        "CO2",
        "ppm",
    )

    # Applied to the ratio, never to a headcount.
    grade(
        occupancy_ratio_value,
        thresholds.occupancy_warning_ratio,
        thresholds.occupancy_critical_ratio,
        "Occupancy",
        "of capacity",
    )

    grade(
        sound,
        thresholds.sound_warning_db,
        thresholds.sound_critical_db,
        "Noise",
        "dB",
    )

    if critical:
        return STATUS_CRITICAL

    if warning:
        return STATUS_WARNING

    return STATUS_NORMAL


def status_reasons(
    temperature: Optional[float] = None,
    humidity: Optional[float] = None,
    aqi: Optional[float] = None,
    co2_ppm: Optional[float] = None,
    occupancy_ratio_value: Optional[float] = None,
    sound: Optional[float] = None,
    thresholds: TwinThresholds = DEFAULT_TWIN_THRESHOLDS,
) -> list:
    """
    Why a zone holds the status it does.

    A marker with a colour and no explanation is decoration. The
    panel needs to be able to say which reading caused it.
    """

    out = []

    def collect(value, warn, crit, name, unit=""):
        if value is None:
            return

        # Rounded for display, matching `determine_status`.
        value = round(float(value), 2)

        suffix = f" {unit}" if unit else ""

        if value >= crit:
            out.append(
                f"{name} {value}{suffix} exceeds the critical "
                f"limit of {crit}{suffix}"
            )
        elif value >= warn:
            out.append(
                f"{name} {value}{suffix} exceeds the warning "
                f"limit of {warn}{suffix}"
            )

    collect(temperature, thresholds.temperature_warning_c,
            thresholds.temperature_critical_c, "Temperature", "C")
    collect(humidity, thresholds.humidity_warning_pct,
            thresholds.humidity_critical_pct, "Humidity", "%")

    if humidity is not None:
        if humidity <= thresholds.humidity_dry_critical_pct:
            out.append(
                f"Humidity {humidity}% is below the dry critical "
                f"limit of {thresholds.humidity_dry_critical_pct}%"
            )
        elif humidity <= thresholds.humidity_dry_warning_pct:
            out.append(
                f"Humidity {humidity}% is below the dry warning "
                f"limit of {thresholds.humidity_dry_warning_pct}%"
            )

    collect(aqi, thresholds.aqi_warning,
            thresholds.aqi_critical, "Air quality")
    collect(co2_ppm, thresholds.co2_warning_ppm,
            thresholds.co2_critical_ppm, "CO2", "ppm")
    collect(occupancy_ratio_value,
            thresholds.occupancy_warning_ratio,
            thresholds.occupancy_critical_ratio,
            "Occupancy", "of capacity")
    collect(sound, thresholds.sound_warning_db,
            thresholds.sound_critical_db, "Noise", "dB")

    return out


def entity_id_for_code(code: str) -> str:
    """
    A stable, readable twin identifier derived from the zone code.

    LH01 becomes lecture-hall-01. Used as the React key and in the
    entity URL, so it has to survive across environments and be
    readable by a person in a browser address bar. The database
    UUID travels separately and remains the authority.

    Letters are expanded to words because a bare LH01 tells a
    reader nothing; the digits are kept as a two-digit suffix so
    LH01 and LH02 stay distinct.
    """

    if not code:
        return "unknown"

    text = code.strip().upper()

    digits = "".join(ch for ch in text if ch.isdigit())
    letters = "".join(
        ch for ch in text if ch.isalpha()
    )

    words = {
        "LH": "lecture-hall",
        "LAB": "laboratory",
        "LIB": "library",
        "HOST": "hostel",
        "BLD": "building",
    }

    for prefix, word in sorted(
        words.items(), key=lambda item: -len(item[0])
    ):
        if letters.startswith(prefix):
            return f"{word}-{digits or '00'}"

    if letters:
        return f"{letters.lower()}-{digits or '00'}"

    return f"zone-{digits or '00'}"

# ============================================================
# RECONCILING READINGS WITH INCIDENTS
# ============================================================
#
# determine_status() grades readings. It cannot see an incident,
# because an incident is a finding in the database and the rules
# above take numbers. That is the right split - they are pure
# functions of different facts - but it produced a screen that
# contradicted itself:
#
#   status: normal        <- every reading inside its band
#   active issues:        <- "Overheating in an occupied zone"
#
# Both statements were true and together they were misleading. A
# zone with a confirmed energy anomaly is not normal, whatever its
# thermometer says, and an operator shown "normal" beside a list of
# critical incidents has to work out which one to believe.
#
# The reconciliation lives here, as a pure function, for the same
# reason the thresholds do: it is a rule that should be argued with
# in one place and tested without a database.

# Ordered worst last. Unknown severities are treated as absent
# rather than guessed at.
INCIDENT_SEVERITY_ORDER = (
    "low",
    "medium",
    "high",
    "critical",
)

# An open incident at high or above means the zone is not fine,
# even when every reading is inside its band. The distinction
# matters: these are derived findings (energy against baseline, a
# correlation gate) rather than a threshold crossing, so they will
# never show up in determine_status().
_INCIDENT_ESCALATION = {
    "critical": STATUS_CRITICAL,
    "high": STATUS_WARNING,
}


def reconcile_status_with_incidents(
    status: str,
    incidents: Optional[list] = None,
) -> tuple:
    """
    Raises a zone's status to match its open incidents.

    Returns the status and any reason worth showing. Never lowers a
    status: offline stays offline, and a zone already graded
    critical by its readings keeps that grade.

    Offline is deliberately left alone even when critical incidents
    are open. "Offline" means the numbers are unknown, and
    overwriting that with "critical" would assert a measurement that
    was never taken. The incidents are still returned to the caller
    and still shown - the zone is unknown *and* troubled, and both
    are true.
    """

    open_incidents = [
        item
        for item in (incidents or [])
        if str(
            (item or {}).get("status", "open")
        ).lower()
        not in ("resolved", "dismissed")
    ]

    if status == STATUS_OFFLINE or not open_incidents:
        return status, []

    worst = max(
        (
            str(item.get("severity", "")).lower()
            for item in open_incidents
        ),
        key=lambda severity: (
            INCIDENT_SEVERITY_ORDER.index(severity)
            if severity in INCIDENT_SEVERITY_ORDER
            else -1
        ),
        default="",
    )

    escalated = _INCIDENT_ESCALATION.get(worst)

    if escalated is None:
        return status, []

    critical_count = sum(
        1
        for item in open_incidents
        if str(item.get("severity", "")).lower()
        == "critical"
    )

    count = len(open_incidents)

    summary = (
        f"{count} open incident{'s' if count != 1 else ''}"
        + (
            f", {critical_count} critical"
            if critical_count
            else ""
        )
    )

    titles = [
        str(item.get("title") or "").strip()
        for item in open_incidents
        if str(item.get("title") or "").strip()
    ]

    named = "; ".join(titles[:2])

    if named and len(titles) > 2:
        named = f"{named} and {len(titles) - 2} more"

    reason = (
        f"{summary} ({named}). The readings themselves are within "
        "their limits, so this status comes from the incidents "
        "rather than from a threshold crossing."
    ).strip()

    if status == STATUS_NORMAL:
        return escalated, [reason]

    # Already warning or critical on the readings. The incidents
    # are additional context, not a change of grade.
    return status, [reason]
