import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, model_validator

from app.models.enums import IngestionJobStatus


class IngestionRequest(BaseModel):
    start_date: date
    end_date: date
    min_latitude: float
    max_latitude: float
    min_longitude: float
    max_longitude: float

    @model_validator(mode="after")
    def validate_bounds(self) -> "IngestionRequest":
        if self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date")
        if not (-90 <= self.min_latitude <= self.max_latitude <= 90):
            raise ValueError("latitude bounds must satisfy -90 <= min <= max <= 90")
        if not (-180 <= self.min_longitude <= self.max_longitude <= 180):
            raise ValueError("longitude bounds must satisfy -180 <= min <= max <= 180")
        return self


class IngestionJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    data_source_id: uuid.UUID
    dataset_id: uuid.UUID | None
    status: IngestionJobStatus
    params: dict
    records_read: int
    records_valid: int
    records_rejected: int
    records_modified: int
    execution_time_seconds: float | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
