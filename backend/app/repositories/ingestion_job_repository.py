import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ingestion_job import IngestionJob


class IngestionJobRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, job: IngestionJob) -> IngestionJob:
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def update(self, job: IngestionJob) -> IngestionJob:
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def get_by_id(self, job_id: uuid.UUID) -> IngestionJob | None:
        return self.db.get(IngestionJob, job_id)

    def list_all(self, page: int = 1, page_size: int = 20) -> list[IngestionJob]:
        stmt = (
            select(IngestionJob)
            .order_by(IngestionJob.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(self.db.execute(stmt).scalars())
