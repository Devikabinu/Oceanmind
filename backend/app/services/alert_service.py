import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.alert import Alert
from app.models.enums import AlertStatus
from app.repositories.alert_repository import AlertRepository

# Alerts only move forward: NEW -> ACKNOWLEDGED -> RESOLVED. Resolving straight
# from NEW is allowed (an alert can be dismissed without a separate ack step).
_ALLOWED_TRANSITIONS: dict[AlertStatus, set[AlertStatus]] = {
    AlertStatus.NEW: {AlertStatus.ACKNOWLEDGED, AlertStatus.RESOLVED},
    AlertStatus.ACKNOWLEDGED: {AlertStatus.RESOLVED},
    AlertStatus.RESOLVED: set(),
}


class AlertNotFoundError(Exception):
    pass


class InvalidAlertTransitionError(Exception):
    pass


class AlertService:
    def __init__(self, db: Session):
        self.repo = AlertRepository(db)

    def update_status(self, alert_id: uuid.UUID, new_status: AlertStatus) -> Alert:
        alert = self.repo.get_by_id(alert_id)
        if alert is None:
            raise AlertNotFoundError(f"Alert {alert_id} not found")
        if new_status not in _ALLOWED_TRANSITIONS[alert.status]:
            raise InvalidAlertTransitionError(
                f"Cannot change alert status from {alert.status.value} to {new_status.value}"
            )
        alert.status = new_status
        if new_status == AlertStatus.RESOLVED:
            alert.resolved_at = datetime.now(timezone.utc)
        return self.repo.update(alert)
