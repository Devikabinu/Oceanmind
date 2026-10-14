import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import DatasetKind


class DatasetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    data_source_id: uuid.UUID
    name: str
    kind: DatasetKind
    temporal_start: datetime | None
    temporal_end: datetime | None
    min_latitude: float | None
    max_latitude: float | None
    min_longitude: float | None
    max_longitude: float | None
    record_count: int
    created_at: datetime
    updated_at: datetime


class PaginatedDatasets(BaseModel):
    items: list[DatasetRead]
    total: int
    page: int
    page_size: int
