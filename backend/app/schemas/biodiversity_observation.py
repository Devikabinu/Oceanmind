import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class BiodiversityObservationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dataset_id: uuid.UUID
    timestamp: datetime
    latitude: float
    longitude: float
    scientific_name: str
    occurrence_status: str | None
    min_depth: float | None
    max_depth: float | None
    source_record_id: str | None


class PaginatedBiodiversityObservations(BaseModel):
    items: list[BiodiversityObservationRead]
    total: int
    page: int
    page_size: int
