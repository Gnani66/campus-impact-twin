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
