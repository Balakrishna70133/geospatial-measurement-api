from typing import Any, Optional
from pydantic import BaseModel, Field


class FileSummary(BaseModel):
    id: str
    filename: str
    feature_count: int
    crs: Optional[str] = None
    status: str


class FeatureMeasurement(BaseModel):
    feature_id: int
    geometry_type: str
    geometry: dict[str, Any] | None
    crs: Optional[str] = None
    properties: dict[str, Any]
    measurement: Optional[float] = None
    measurement_unit: Optional[str] = None
    measurement_status: str
    measurement_crs: Optional[str] = None


class MeasurementsResponse(BaseModel):
    file_id: str
    filename: str
    feature_count: int
    measurements: list[FeatureMeasurement]
