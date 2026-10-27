import uuid
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.alert import Alert
from app.models.enums import AlertSeverity, AlertStatus
from app.repositories._pagination import paginate


def dataset_filter(dataset: str):
    """Alerts of one dataset. Alerts written before datasets existed carry no `dataset` in details and belong to the NE Pacific."""
    col = Alert.details["dataset"].as_string()
    return or_(Alert.details.is_(None), col.is_(None), col == "ne_pacific") if dataset == "ne_pacific" else col == dataset


class AlertRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, alert_id: uuid.UUID) -> Alert | None:
        return self.db.get(Alert, alert_id)

    def list_paginated(
        self,
        page: int,
        page_size: int,
        status: AlertStatus | None = None,
        severity: AlertSeverity | None = None,
        alert_type: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        dataset: str | None = None,
        region: str | None = None,
    ) -> tuple[list[Alert], int]:
        stmt = select(Alert)
        if dataset is not None:
            stmt = stmt.where(dataset_filter(dataset))
        if region is not None and region != "pacific":
            # alerts of datasets that record the regions their location lies in (details.regions); older alerts have none
            stmt = stmt.where(Alert.details["regions"].as_string().like(f'%"{region}"%'))
        if status is not None:
            stmt = stmt.where(Alert.status == status)
        if severity is not None:
            stmt = stmt.where(Alert.severity == severity)
        if alert_type is not None:
            stmt = stmt.where(Alert.alert_type == alert_type)
        if start_date is not None:
            stmt = stmt.where(Alert.timestamp >= start_date)
        if end_date is not None:
            stmt = stmt.where(Alert.timestamp <= end_date)

        return paginate(self.db, stmt, Alert, page, page_size, order_by=(Alert.timestamp.desc(), Alert.id))

    def update(self, alert: Alert) -> Alert:
        self.db.add(alert)
        self.db.commit()
        self.db.refresh(alert)
        return alert
