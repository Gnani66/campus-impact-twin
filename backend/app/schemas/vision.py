"""
Schemas for the vision observation engine (Phase 7).

An observation records what was seen in one uploaded image.
It is a measurement, not a verdict: nothing here creates an
incident, changes an IoT sensor or drives equipment. A later
phase may compare a camera count against IoT occupancy and
record the discrepancy, which is why the raw count and its
evidence are both preserved.

Field naming follows the Phase 5/6 convention: a `confidence`
is always a 0..1 score, and evidence is a JSON-compatible
list of objects.
"""

from datetime import datetime
from typing import (
    Any,
    Dict,
    List,
    Optional,
)

from pydantic import (
    BaseModel,
    Field,
    field_validator,
)


class BoundingBox(BaseModel):
    """Pixel coordinates in the uploaded image, top-left."""

    x1: float
    y1: float
    x2: float
    y2: float


class PersonDetection(BaseModel):
    """One accepted person detection."""

    label: str

    confidence: float = Field(ge=0.0, le=1.0)

    bbox: BoundingBox


class VisionObservation(BaseModel):
    """
    A stored vision observation, as persisted in
    `vision_observations`.

    `value` is the person count and `unit` is always "people".
    `confidence` is the mean confidence of the accepted
    detections; see `vision.detector._aggregate_confidence` for
    exactly what it does and does not mean. It is 0.0 when no
    person was detected, and it is not a calibrated
    probability that the count is correct.
    """

    camera_id: str

    zone_code: str

    observation_type: str

    value: int = Field(ge=0)

    unit: str

    confidence: float = Field(ge=0.0, le=1.0)

    observed_at: datetime

    evidence: List[Dict[str, Any]] = Field(
        default_factory=list
    )


class VisionAnalysisResponse(BaseModel):
    """
    The result of analysing one uploaded image.

    Returned only after the observation has been persisted. If
    the database write fails the request fails; a successful
    response never precedes a successful insert.
    """

    camera_id: str

    zone_code: str

    people_count: int = Field(ge=0)

    confidence: float = Field(ge=0.0, le=1.0)

    observed_at: datetime

    detections: List[PersonDetection] = Field(
        default_factory=list
    )


class VisionObservationResponse(BaseModel):
    """
    A stored observation, as returned by the latest-observation
    endpoint.

    Carries the id and the zone's canonical code so a caller
    never has to trust an identifier they supplied.
    """

    id: str

    camera_id: str

    zone_code: str

    observation_type: str

    value: int = Field(ge=0)

    unit: str

    confidence: float = Field(ge=0.0, le=1.0)

    observed_at: datetime

    evidence: List[Dict[str, Any]] = Field(
        default_factory=list
    )

    created_at: Optional[datetime] = None

    @field_validator("evidence", mode="before")
    @classmethod
    def _coerce_evidence(
        cls,
        value: Any,
    ) -> Any:
        """
        Accepts the shapes jsonb can legitimately hold.

        A row written outside the API could carry a JSON
        object, a string or null. None becomes an empty list
        rather than raising, so one malformed row does not take
        the endpoint down. Anything that is not a list is
        dropped, because it cannot be evidence.
        """

        if value is None:
            return []

        if isinstance(value, list):
            return [
                item for item in value
                if isinstance(item, dict)
            ]

        return []


class ZoneObservationSummary(BaseModel):
    """Optional aggregate used by the service for logging."""

    zone_code: str

    observation_count: int

    latest_observed_at: Optional[datetime] = None