import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AlignmentRunRequest(BaseModel):
    spatial_radius_km: float = Field(default=25.0, gt=0, le=1000)
    temporal_window_hours: float = Field(default=24.0, gt=0, le=24 * 30)
    biodiversity_dataset_id: uuid.UUID | None = None


class AlignmentRunResponse(BaseModel):
    matches_created: int
    spatial_radius_km: float
    temporal_window_hours: float


class EnvironmentBiodiversityMatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    biodiversity_observation_id: uuid.UUID
    ocean_observation_id: uuid.UUID
    distance_km: float
    time_difference_hours: float
    matched_sst: float | None
    matched_sst_anomaly: float | None
    spatial_radius_km: float
    temporal_window_hours: float
    created_at: datetime


class PaginatedMatches(BaseModel):
    items: list[EnvironmentBiodiversityMatchRead]
    total: int
    page: int
    page_size: int
