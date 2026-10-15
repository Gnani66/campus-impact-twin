"""
Telemetry message contract.

One instance represents a single reading for one sensor and
carries exactly the fields the existing `telemetry_readings`
table needs, so a message can be written without a second
translation step.

The allowed metrics and units are not invented here. They come
from the `sensor_type` CHECK constraint in
`migrations/001_smart_campus.sql` and the five sensors seeded
by `migrations/002_seed_smart_campus.sql`:

    OCC-LH01     occupancy     people
    TEMP-LH01    temperature   °C
    HUM-LH01     humidity      %
    CO2-LH01     co2           ppm
    ENERGY-LH01  energy        kW

`metric` is the sensor type, and `unit` must be the unit the
database records for that sensor. Anything else is rejected
rather than coerced.
"""

from datetime import datetime
from typing import (
    Any,
    Dict,
    Optional,
    Tuple,
)
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


# sensor_type -> the units the seeded sensors report for it.
SEED_METRIC_UNITS: Dict[str, Tuple[str, ...]] = {
    "co2": ("ppm",),
    "energy": ("kW",),
    "humidity": ("%",),
    "occupancy": ("people",),
    "temperature": ("°C",),
}

# Mirrors the `source` and `quality` CHECK constraints on
# telemetry_readings.
ALLOWED_SOURCES = ("sensor", "simulator", "import", "manual")
ALLOWED_QUALITIES = ("good", "suspect", "bad")

TelemetrySource = str
TelemetryQuality = str


class TelemetryMessage(BaseModel):
    """
    A validated reading from one sensor.

    Unknown fields are rejected so a malformed broker payload
    cannot be silently persisted as a partial reading.
    """

    model_config = ConfigDict(
        extra="forbid",
    )

    sensor_id: UUID
    metric: str
    value: float = Field(
        ...,
        # Rejects NaN and +/-Infinity. Postgres accepts them in
        # `double precision`, so this has to be caught here.
        allow_inf_nan=False,
    )
    unit: str

    # `timestamp` on a timestamptz column: a naive datetime
    # would be stored in the server's zone without saying so.
    timestamp: datetime

    source: TelemetrySource = "sensor"
    quality: TelemetryQuality = "good"

    # Location identifiers are nullable on telemetry_readings,
    # so they stay optional here and are filled from the
    # registry rather than the broker payload.
    campus_id: Optional[UUID] = None
    building_id: Optional[UUID] = None
    floor_id: Optional[UUID] = None
    zone_id: Optional[UUID] = None
    equipment_id: Optional[UUID] = None

    metadata: Dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator("metric")
    @classmethod
    def _known_metric(
        cls,
        value: str,
    ) -> str:
        if value not in SEED_METRIC_UNITS:
            raise ValueError(
                f"unknown metric '{value}'; seeded "
                "sensors report "
                f"{sorted(SEED_METRIC_UNITS)}"
            )

        return value

    @model_validator(mode="after")
    def _unit_matches_metric(self) -> "TelemetryMessage":
        allowed = SEED_METRIC_UNITS[self.metric]

        if self.unit not in allowed:
            raise ValueError(
                f"unit '{self.unit}' is not valid for "
                f"metric '{self.metric}'; expected "
                f"{list(allowed)}"
            )

        return self

    @field_validator("source")
    @classmethod
    def _known_source(
        cls,
        value: str,
    ) -> str:
        if value not in ALLOWED_SOURCES:
            raise ValueError(
                f"unknown source '{value}'; "
                f"expected one of {list(ALLOWED_SOURCES)}"
            )

        return value

    @field_validator("quality")
    @classmethod
    def _known_quality(
        cls,
        value: str,
    ) -> str:
        if value not in ALLOWED_QUALITIES:
            raise ValueError(
                f"unknown quality '{value}'; expected "
                f"one of {list(ALLOWED_QUALITIES)}"
            )

        return value

    @field_validator("timestamp")
    @classmethod
    def _timezone_aware(
        cls,
        value: datetime,
    ) -> datetime:
        if (
            value.tzinfo is None
            or value.tzinfo.utcoffset(value) is None
        ):
            raise ValueError(
                "timestamp must be timezone-aware"
            )

        return value

    def to_row(self) -> Dict[str, Any]:
        """
        Maps the message onto `telemetry_readings` columns.

        Every value must be JSON-serialisable, because the
        PostgREST client serialises the insert body itself.
        UUIDs become strings for the same reason, and the
        timestamp becomes an ISO-8601 string that keeps its
        UTC offset, which PostgreSQL reads back as the same
        instant in `timestamptz`.

        `id` is left out so the database default applies.
        """

        row: Dict[str, Any] = {
            "metric": self.metric,
            "value": self.value,
            "unit": self.unit,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "quality": self.quality,
            "metadata": self.metadata,
        }

        for column in (
            "sensor_id",
            "campus_id",
            "building_id",
            "floor_id",
            "zone_id",
            "equipment_id",
        ):
            identifier = getattr(self, column)

            row[column] = (
                str(identifier)
                if identifier is not None
                else None
            )

        return row