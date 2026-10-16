"""
Response schemas for the campus intelligence engine.
"""

from datetime import datetime
from typing import (
    Any,
    Dict,
    List,
    Optional,
)

from pydantic import BaseModel, Field


class IncidentResponse(BaseModel):
    """
    One campus incident.

    Carries the location identifiers alongside the rule
    outcome so an evidence panel can show which sensor, zone and
    building an incident belongs to without a second request.
    """

    id: str

    category: str
    severity: str
    status: str

    title: str
    description: str

    impact_score: float
    confidence_score: Optional[float] = None

    detection_method: str

    evidence: List[Dict[str, Any]] = Field(
        default_factory=list
    )

    campus_id: Optional[str] = None
    building_id: Optional[str] = None
    zone_id: Optional[str] = None
    sensor_id: Optional[str] = None
    equipment_id: Optional[str] = None

    # The human-readable code for `zone_id`, resolved on read.
    # An incident is stored by id, which is not something anyone
    # recognises in a list of problems.
    zone_code: Optional[str] = None

    detected_at: datetime
    acknowledged_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None


class IntelligenceSummary(BaseModel):
    """
    Aggregate incident counts for a campus.
    """

    campus_code: str
    total_incidents: int
    critical: int
    high: int
    medium: int
    low: int
    open_incidents: int
    highest_impact: float


class RuleEvaluationResponse(BaseModel):
    """
    A rule outcome returned without persisting it.

    Useful for tuning thresholds and for showing a judge why a
    rule did or did not fire on a given reading.
    """

    metric: str
    value: float
    fired: bool
    rule: Optional[str] = None
    category: Optional[str] = None
    severity: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    impact_score: Optional[float] = None
    confidence_score: Optional[float] = None
    evidence: List[Dict[str, Any]] = Field(
        default_factory=list
    )
