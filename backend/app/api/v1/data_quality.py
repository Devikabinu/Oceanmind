import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.repositories.quality_report_repository import QualityReportRepository
from app.schemas.data_quality import DataQualityReportRead

router = APIRouter(prefix="/data-quality", tags=["data-quality"])


@router.get(
    "/{dataset_id}",
    response_model=list[DataQualityReportRead],
    dependencies=[Depends(get_current_user)],
)
def get_quality_reports(dataset_id: uuid.UUID, db: Session = Depends(get_db)) -> list:
    return QualityReportRepository(db).list_for_dataset(dataset_id)
