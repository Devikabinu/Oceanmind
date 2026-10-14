from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_roles
from app.models.enums import UserRole
from app.repositories.match_repository import MatchRepository
from app.schemas.alignment import AlignmentRunRequest, AlignmentRunResponse, PaginatedMatches
from app.services.alignment_service import AlignmentService

router = APIRouter(prefix="/alignment", tags=["alignment"])

_CAN_ALIGN = require_roles(UserRole.ADMIN, UserRole.RESEARCHER)


@router.post("/run", response_model=AlignmentRunResponse, dependencies=[Depends(_CAN_ALIGN)])
def run_alignment(request: AlignmentRunRequest, db: Session = Depends(get_db)) -> AlignmentRunResponse:
    matches_created = AlignmentService(db).run(
        spatial_radius_km=request.spatial_radius_km,
        temporal_window_hours=request.temporal_window_hours,
        biodiversity_dataset_id=request.biodiversity_dataset_id,
    )
    return AlignmentRunResponse(
        matches_created=matches_created,
        spatial_radius_km=request.spatial_radius_km,
        temporal_window_hours=request.temporal_window_hours,
    )


@router.get("/results", response_model=PaginatedMatches, dependencies=[Depends(get_current_user)])
def get_alignment_results(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> PaginatedMatches:
    items, total = MatchRepository(db).list_paginated(page, page_size)
    return PaginatedMatches(items=items, total=total, page=page, page_size=page_size)
