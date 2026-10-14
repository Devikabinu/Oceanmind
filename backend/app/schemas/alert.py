import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import AlertSeverity, AlertStatus


class AlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    alert_type: str
    severity: AlertSeverity
    latitude: float
    longitude: float
    timestamp: datetime
    message: str
    status: AlertStatus
    related_forecast_id: uuid.UUID | None
    related_anomaly_id: uuid.UUID | None
    related_risk_id: uuid.UUID | None
    created_at: datetime
    resolved_at: datetime | None


class AlertStatusUpdate(BaseModel):
    status: AlertStatus


class PaginatedAlerts(BaseModel):
    items: list[AlertRead]
    total: int
    page: int
    page_size: int
