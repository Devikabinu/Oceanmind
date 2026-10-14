import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_roles
from app.ingestion.base import IngestionParams
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.ingestion_job_repository import IngestionJobRepository
from app.schemas.ingestion import IngestionJobRead, IngestionRequest
from app.services.ingestion_service import IngestionService, run_ingestion_job

router = APIRouter(prefix="/ingestion", tags=["ingestion"])

_CAN_INGEST = require_roles(UserRole.ADMIN, UserRole.RESEARCHER)


def _start_ingestion(
    source_key: str,
    request: IngestionRequest,
    background_tasks: BackgroundTasks,
    db: Session,
    current_user: User,
) -> IngestionJobRead:
    params = IngestionParams(
        start_date=request.start_date,
        end_date=request.end_date,
        min_latitude=request.min_latitude,
        max_latitude=request.max_latitude,
        min_longitude=request.min_longitude,
        max_longitude=request.max_longitude,
    )
    job = IngestionService(db).start_job(source_key, params, current_user.id)
    background_tasks.add_task(run_ingestion_job, job.id, source_key, params)
    return job


@router.post(
    "/noaa",
    response_model=IngestionJobRead,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(_CAN_INGEST)],
)
def ingest_noaa(
    request: IngestionRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(_CAN_INGEST),
) -> IngestionJobRead:
    return _start_ingestion("noaa", request, background_tasks, db, current_user)


@router.post(
    "/copernicus",
    response_model=IngestionJobRead,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(_CAN_INGEST)],
)
def ingest_copernicus(
    request: IngestionRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(_CAN_INGEST),
) -> IngestionJobRead:
    return _start_ingestion("copernicus", request, background_tasks, db, current_user)


@router.post(
    "/obis",
    response_model=IngestionJobRead,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(_CAN_INGEST)],
)
def ingest_obis(
    request: IngestionRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(_CAN_INGEST),
) -> IngestionJobRead:
    return _start_ingestion("obis", request, background_tasks, db, current_user)


@router.get("/jobs", response_model=list[IngestionJobRead], dependencies=[Depends(get_current_user)])
def list_jobs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list:
    return IngestionJobRepository(db).list_all(page, page_size)


@router.get(
    "/jobs/{job_id}", response_model=IngestionJobRead, dependencies=[Depends(get_current_user)]
)
def get_job(job_id: uuid.UUID, db: Session = Depends(get_db)) -> IngestionJobRead:
    job = IngestionJobRepository(db).get_by_id(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ingestion job not found")
    return job
