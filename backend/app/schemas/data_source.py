import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import DataSourceStatus


class DataSourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    provider: str
    dataset: str
    version: str
    description: str
    source_url: str
    status: DataSourceStatus
    last_updated: datetime
