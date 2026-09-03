import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class OceanObservationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dataset_id: uuid.UUID
    timestamp: datetime
    latitude: float
    longitude: float
    sst: float | None
    sst_anomaly: float | None
    measurement_error: float | None
    ice_concentration: float | None
    source_record_id: str | None


class PaginatedOceanObservations(BaseModel):
    items: list[OceanObservationRead]
    total: int
    page: int
    page_size: int
