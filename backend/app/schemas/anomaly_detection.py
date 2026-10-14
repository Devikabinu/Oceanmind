import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AnomalyDetectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: uuid.UUID
    observation_id: uuid.UUID
    timestamp: datetime
    latitude: float
    longitude: float
    anomaly_score: float
    is_anomaly: bool
    model_version: str
    created_at: datetime


class PaginatedAnomalyDetections(BaseModel):
    items: list[AnomalyDetectionRead]
    total: int
    page: int
    page_size: int
