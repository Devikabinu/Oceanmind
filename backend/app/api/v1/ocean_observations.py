import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.repositories.ocean_observation_repository import OceanObservationRepository
from app.schemas.ocean_observation import PaginatedOceanObservations

router = APIRouter(prefix="/ocean-observations", tags=["ocean-observations"])


@router.get("", response_model=PaginatedOceanObservations, dependencies=[Depends(get_current_user)])
def list_ocean_observations(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    dataset_id: uuid.UUID | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    min_latitude: float | None = Query(None, ge=-90, le=90),
    max_latitude: float | None = Query(None, ge=-90, le=90),
    min_longitude: float | None = Query(None, ge=-180, le=180),
    max_longitude: float | None = Query(None, ge=-180, le=180),
    db: Session = Depends(get_db),
) -> PaginatedOceanObservations:
    items, total = OceanObservationRepository(db).list_paginated(
        page=page,
        page_size=page_size,
        dataset_id=dataset_id,
        start_date=start_date,
        end_date=end_date,
        min_latitude=min_latitude,
        max_latitude=max_latitude,
        min_longitude=min_longitude,
        max_longitude=max_longitude,
    )
    return PaginatedOceanObservations(items=items, total=total, page=page, page_size=page_size)
