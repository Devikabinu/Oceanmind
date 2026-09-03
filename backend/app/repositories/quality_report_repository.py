import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_quality_report import DataQualityReport


class QualityReportRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, report: DataQualityReport) -> DataQualityReport:
        self.db.add(report)
        self.db.commit()
        self.db.refresh(report)
        return report

    def list_for_dataset(self, dataset_id: uuid.UUID) -> list[DataQualityReport]:
        stmt = (
            select(DataQualityReport)
            .where(DataQualityReport.dataset_id == dataset_id)
            .order_by(DataQualityReport.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars())
