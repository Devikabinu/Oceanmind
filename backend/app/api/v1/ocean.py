"""Ocean regions and data-coverage catalogue (what exists where, and what this installation has loaded)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.services import coverage_service

router = APIRouter(prefix="/ocean", tags=["ocean"], dependencies=[Depends(get_current_user)])


@router.get("/regions")
def ocean_regions(db: Session = Depends(get_db)) -> dict:
    return coverage_service.regions(db)


@router.get("/coverage")
def ocean_coverage(db: Session = Depends(get_db)) -> dict:
    return coverage_service.sources(db)
