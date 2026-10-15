from datetime import datetime
from typing import (
    Any,
    Dict,
    List,
    Optional,
)

from pydantic import BaseModel, Field


class CampusResponse(BaseModel):
    id: str
    code: str
    name: str
    description: Optional[str]
    timezone: str
    metadata: Dict[str, Any] = Field(
        default_factory=dict
    )
    created_at: datetime
    updated_at: datetime


class BuildingResponse(BaseModel):
    id: str
    campus_id: str
    code: str
    name: str
    description: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    metadata: Dict[str, Any] = Field(
        default_factory=dict
    )
    created_at: datetime
    updated_at: datetime


class FloorResponse(BaseModel):
    id: str
    building_id: str
    code: str
    name: str
    floor_number: int
    metadata: Dict[str, Any] = Field(
        default_factory=dict
    )
    created_at: datetime
    updated_at: datetime


class ZoneResponse(BaseModel):
    id: str
    floor_id: str
    code: str
    name: str
    zone_type: str
    capacity: Optional[int]
    area_sq_meters: Optional[float]
    schedule_start_hour: Optional[int]
    schedule_end_hour: Optional[int]
    active_days: Optional[List[int]]
    twin_model_object: Optional[str]
    metadata: Dict[str, Any] = Field(
        default_factory=dict
    )
    created_at: datetime
    updated_at: datetime


class EquipmentResponse(BaseModel):
    id: str
    zone_id: Optional[str]
    code: str
    name: str
    equipment_type: str
    status: str
    manufacturer: Optional[str]
    model_number: Optional[str]
    installation_date: Optional[str]
    rated_power_kw: Optional[float]
    twin_model_object: Optional[str]
    metadata: Dict[str, Any] = Field(
        default_factory=dict
    )
    created_at: datetime
    updated_at: datetime


class SensorResponse(BaseModel):
    id: str
    zone_id: Optional[str]
    equipment_id: Optional[str]
    code: str
    name: str
    sensor_type: str
    unit: Optional[str]
    status: str
    sampling_interval_seconds: Optional[int]
    twin_model_object: Optional[str]
    metadata: Dict[str, Any] = Field(
        default_factory=dict
    )
    created_at: datetime
    updated_at: datetime


class IncidentResponse(BaseModel):
    id: str
    campus_id: str
    building_id: Optional[str]
    zone_id: Optional[str]
    sensor_id: Optional[str]
    equipment_id: Optional[str]
    category: str
    severity: str
    status: str
    title: str
    description: str
    impact_score: float
    confidence_score: Optional[float]
    detection_method: str
    evidence: List[Any] = Field(
        default_factory=list
    )
    detected_at: datetime
    acknowledged_at: Optional[datetime]
    resolved_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class TelemetryReadingResponse(BaseModel):
    id: str
    campus_id: str
    building_id: Optional[str]
    floor_id: Optional[str]
    zone_id: Optional[str]
    sensor_id: Optional[str]
    equipment_id: Optional[str]
    metric: str
    value: float
    unit: str
    timestamp: datetime
    source: str
    quality: str
    metadata: Dict[str, Any] = Field(
        default_factory=dict
    )


class CampusTwinResponse(BaseModel):
    """
    The complete digital-twin entity graph for one campus.

    Campus -> Building -> Floor -> Zone
                                -> Equipment
                                -> Sensors
    """

    campus: CampusResponse
    buildings: List[BuildingResponse]
    floors: List[FloorResponse]
    zones: List[ZoneResponse]
    equipment: List[EquipmentResponse]
    sensors: List[SensorResponse]
    incidents: List[IncidentResponse]


class LatestTelemetryReadingResponse(BaseModel):
    """
    The most recent stored reading for one sensor.

    `sensor_code`, `sensor_type` and the location codes come
    from the sensor registry, not from the reading row, so a
    reading stays identifiable even if the registry and the
    stored row disagree about naming.
    """

    sensor_id: str
    sensor_code: Optional[str] = None
    sensor_type: Optional[str] = None

    metric: str
    value: float
    unit: str
    timestamp: datetime

    source: str
    quality: str

    campus_id: Optional[str] = None
    building_id: Optional[str] = None
    floor_id: Optional[str] = None
    zone_id: Optional[str] = None

    campus_code: Optional[str] = None
    building_code: Optional[str] = None
    floor_code: Optional[str] = None
    zone_code: Optional[str] = None

    metadata: Dict[str, Any] = Field(
        default_factory=dict
    )


class LatestTelemetryResponse(BaseModel):
    """
    Latest readings for every registered sensor in scope.

    Sensors with no stored readings are reported by code in
    `sensors_without_readings` rather than being given a
    fabricated value.
    """

    campus_code: str
    campus_id: str

    zone_code: Optional[str] = None

    sensors_considered: int = 0
    reading_count: int = 0

    readings: List[LatestTelemetryReadingResponse] = Field(
        default_factory=list
    )
    sensors_without_readings: List[str] = Field(
        default_factory=list
    )

    generated_at: datetime
