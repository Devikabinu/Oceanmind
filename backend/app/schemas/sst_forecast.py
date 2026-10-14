import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SSTForecastRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: uuid.UUID
    dataset_id: uuid.UUID
    timestamp: datetime
    latitude: float
    longitude: float
    predicted_sst: float
    forecast_horizon_days: int
    model_version: str
    created_at: datetime


class PaginatedSSTForecasts(BaseModel):
    items: list[SSTForecastRead]
    total: int
    page: int
    page_size: int
