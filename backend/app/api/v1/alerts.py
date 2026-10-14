import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_roles
from app.api.query_validation import validate_filter_ranges
from app.models.enums import AlertSeverity, AlertStatus, UserRole
from app.repositories.alert_repository import AlertRepository
from app.schemas.alert import AlertRead, AlertStatusUpdate, PaginatedAlerts
from app.services.alert_service import AlertService, AlertNotFoundError, InvalidAlertTransitionError

router = APIRouter(prefix="/alerts", tags=["alerts"])

_CAN_UPDATE_ALERTS = require_roles(UserRole.ADMIN, UserRole.RESEARCHER)


@router.get("", response_model=PaginatedAlerts, dependencies=[Depends(get_current_user)])
def list_alerts(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    status: AlertStatus | None = None,
    severity: AlertSeverity | None = None,
    alert_type: str | None = Query(None, min_length=1, max_length=50),
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    db: Session = Depends(get_db),
) -> PaginatedAlerts:
    validate_filter_ranges(start_date=start_date, end_date=end_date)
    items, total = AlertRepository(db).list_paginated(
        page=page,
        page_size=page_size,
        status=status,
        severity=severity,
        alert_type=alert_type,
        start_date=start_date,
        end_date=end_date,
    )
    return PaginatedAlerts(items=items, total=total, page=page, page_size=page_size)


@router.get("/{alert_id}", response_model=AlertRead, dependencies=[Depends(get_current_user)])
def get_alert(alert_id: uuid.UUID, db: Session = Depends(get_db)) -> AlertRead:
    alert = AlertRepository(db).get_by_id(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert


@router.patch("/{alert_id}", response_model=AlertRead, dependencies=[Depends(_CAN_UPDATE_ALERTS)])
def update_alert_status(
    alert_id: uuid.UUID,
    payload: AlertStatusUpdate,
    db: Session = Depends(get_db),
) -> AlertRead:
    try:
        return AlertService(db).update_status(alert_id, payload.status)
    except AlertNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except InvalidAlertTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
