import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DataQualityReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dataset_id: uuid.UUID
    ingestion_job_id: uuid.UUID
    records_read: int
    records_valid: int
    records_rejected: int
    missing_values: int
    duplicate_records: int
    invalid_coordinates: int
    invalid_timestamps: int
    invalid_sst: int
    outliers: int
    schema_mismatches: int
    details: dict
    created_at: datetime
