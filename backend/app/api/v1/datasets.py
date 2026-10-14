import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.repositories.dataset_repository import DatasetRepository
from app.schemas.dataset import PaginatedDatasets

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.get("", response_model=PaginatedDatasets, dependencies=[Depends(get_current_user)])
def list_datasets(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    data_source_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
) -> PaginatedDatasets:
    items, total = DatasetRepository(db).list_paginated(page, page_size, data_source_id)
    return PaginatedDatasets(items=items, total=total, page=page, page_size=page_size)
