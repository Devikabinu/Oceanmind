import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.api.query_validation import validate_filter_ranges
from app.repositories.sst_forecast_repository import SSTForecastRepository
from app.schemas.sst_forecast import PaginatedSSTForecasts, SSTForecastRead

router = APIRouter(prefix="/forecast", tags=["forecast"])


@router.get("", response_model=PaginatedSSTForecasts, dependencies=[Depends(get_current_user)])
def list_sst_forecasts(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    min_latitude: float | None = Query(None, ge=-90, le=90),
    max_latitude: float | None = Query(None, ge=-90, le=90),
    min_longitude: float | None = Query(None, ge=-180, le=180),
    max_longitude: float | None = Query(None, ge=-180, le=180),
    forecast_horizon_days: int | None = Query(None, ge=1),
    db: Session = Depends(get_db),
) -> PaginatedSSTForecasts:
    validate_filter_ranges(start_date, end_date, min_latitude, max_latitude, min_longitude, max_longitude)
    items, total = SSTForecastRepository(db).list_paginated(
        page=page,
        page_size=page_size,
        start_date=start_date,
        end_date=end_date,
        min_latitude=min_latitude,
        max_latitude=max_latitude,
        min_longitude=min_longitude,
        max_longitude=max_longitude,
        forecast_horizon_days=forecast_horizon_days,
    )
    return PaginatedSSTForecasts(items=items, total=total, page=page, page_size=page_size)


@router.get("/{item_id}", response_model=SSTForecastRead, dependencies=[Depends(get_current_user)])
def get_sst_forecast(item_id: uuid.UUID, db: Session = Depends(get_db)) -> SSTForecastRead:
    item = SSTForecastRepository(db).get_by_id(item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Forecast not found")
    return item
