"""
Schemas for the digital twin (Phase 12).

The contract between the backend and the 3D view.

Every metric is optional and `None` means exactly one thing: this
deployment does not measure it. That distinction matters more
than it looks. A twin showing a plausible AQI that was never
measured is worse than one showing a dash, because a reader will
take the number as fact. Nothing in this layer invents a value.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TwinMetrics(BaseModel):
    """
    Live readings for one zone.

    Only five of these can currently be populated: temperature,
    humidity, CO2, occupancy and energy. The remainder describe
    sensors this deployment does not have and remain null rather
    than being filled with a plausible constant.
    """

    temperature: Optional[float] = None

    humidity: Optional[float] = None

    # Physical air pressure. No sensor.
    pressure: Optional[float] = None

    # Composite air quality index. No sensor.
    aqi: Optional[float] = None

    # Total volatile organics. No sensor.
    tvoc: Optional[float] = None

    # Carbon dioxide in ppm. Measured; the stored metric is
    # named `co2`.
    eco2: Optional[float] = None

    # Illuminance. No sensor.
    light: Optional[float] = None

    # Sound pressure. No sensor.
    sound: Optional[float] = None

    # Ultraviolet index. No sensor.
    uv: Optional[float] = None

    # People counted, as a headcount. NOT a percentage; use
    # occupancy_ratio for that.
    occupancy: Optional[float] = None

    # Occupancy as a fraction of capacity. Derived, and the
    # field the status rules are applied to.
    occupancy_ratio: Optional[float] = None

    # Instantaneous draw in kW.
    energy: Optional[float] = None

    capacity: Optional[int] = None


class TwinEntity(BaseModel):
    """
    One zone as the 3D view sees it.
    """

    # Stable and readable: derived from the zone code so it can
    # be used as a React key and in a URL.
    id: str

    # The database authority, kept alongside so nothing has to
    # reverse-engineer the id.
    zone_id: str

    code: str

    name: str

    type: str

    status: str = Field(
        description="normal, warning, critical or offline"
    )

    metrics: TwinMetrics = Field(default_factory=TwinMetrics)

    # Why it holds that status, in plain language.
    reasons: List[str] = Field(default_factory=list)

    # Open incidents and the latest correlation finding, so the
    # panel explains the colour using the same records the
    # operational engine raised rather than a second narrative.
    active_issues: List[str] = Field(default_factory=list)

    # Links into the decision loop, so a click can carry on to
    # the analysis and the recommendation.
    open_incident_count: int = 0

    correlation_run_id: Optional[str] = None

    correlation_status: Optional[str] = None

    root_cause: Optional[str] = None

    pending_approvals: int = 0

    # The name of the object this entity maps to inside the GLB.
    # Supplied by the database rather than hardcoded in the
    # browser, so adding a zone needs no frontend change.
    model_object: Optional[str] = None

    # Placement hint, when the database supplies one.
    position: Optional[List[float]] = None

    scale: Optional[float] = None

    latitude: Optional[float] = None

    longitude: Optional[float] = None

    # When this entity's readings were last refreshed. Reported so
    # a client can show its own staleness.
    observed_at: Optional[str] = None

    metadata: Dict[str, Any] = Field(default_factory=dict)


class TwinSnapshot(BaseModel):
    """
    The whole campus, as of one moment.
    """

    timestamp: datetime

    entities: List[TwinEntity] = Field(default_factory=list)

    # Counts by status, so a client can render a legend without
    # walking the list.
    counts: Dict[str, int] = Field(default_factory=dict)