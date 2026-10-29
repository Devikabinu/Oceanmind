import logging
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.ingestion.base import BaseIngestionAdapter, IngestionParams
from app.ingestion.noaa_adapter import NOAAAdapter
from app.ingestion.obis_adapter import OBISAdapter
from app.models.data_quality_report import DataQualityReport
from app.models.dataset import Dataset
from app.models.enums import IngestionJobStatus
from app.models.ingestion_job import IngestionJob
from app.repositories.data_source_repository import DataSourceRepository
from app.repositories.dataset_repository import DatasetRepository
from app.repositories.ingestion_job_repository import IngestionJobRepository
from app.repositories.quality_report_repository import QualityReportRepository

logger = logging.getLogger("ocean_platform")

ADAPTERS: dict[str, type[BaseIngestionAdapter]] = {
    "noaa": NOAAAdapter,
    "obis": OBISAdapter,
}


class UnknownDataSourceError(Exception):
    pass


class IngestionService:
    def __init__(self, db: Session):
        self.db = db

    def start_job(self, source_key: str, params: IngestionParams, user_id: uuid.UUID) -> IngestionJob:
        adapter_cls = ADAPTERS.get(source_key)
        if adapter_cls is None:
            raise UnknownDataSourceError(f"Unknown ingestion source: {source_key}")

        data_source = DataSourceRepository(self.db).get_by_name(adapter_cls.data_source_name)
        if data_source is None:
            raise UnknownDataSourceError(
                f"Data source '{adapter_cls.data_source_name}' is not registered"
            )

        dataset = DatasetRepository(self.db).create(
            Dataset(
                data_source_id=data_source.id,
                name=f"{adapter_cls.data_source_name} {params.start_date}_{params.end_date}",
                kind=adapter_cls.dataset_kind,
                temporal_start=datetime.combine(params.start_date, datetime.min.time(), tzinfo=timezone.utc),
                temporal_end=datetime.combine(params.end_date, datetime.min.time(), tzinfo=timezone.utc),
                min_latitude=params.min_latitude,
                max_latitude=params.max_latitude,
                min_longitude=params.min_longitude,
                max_longitude=params.max_longitude,
                record_count=0,
            )
        )

        job = IngestionJobRepository(self.db).create(
            IngestionJob(
                data_source_id=data_source.id,
                dataset_id=dataset.id,
                created_by=user_id,
                status=IngestionJobStatus.PENDING,
                params={
                    "start_date": params.start_date.isoformat(),
                    "end_date": params.end_date.isoformat(),
                    "min_latitude": params.min_latitude,
                    "max_latitude": params.max_latitude,
                    "min_longitude": params.min_longitude,
                    "max_longitude": params.max_longitude,
                },
            )
        )
        return job


def run_ingestion_job(job_id: uuid.UUID, source_key: str, params: IngestionParams) -> None:
    """Executed as a FastAPI background task with its own DB session, since the
    request-scoped session is already closed by the time background tasks run.
    """
    db = SessionLocal()
    try:
        job_repo = IngestionJobRepository(db)
        job = job_repo.get_by_id(job_id)
        if job is None:
            logger.error("Ingestion job %s vanished before it could run", job_id)
            return

        job.status = IngestionJobStatus.RUNNING
        job.started_at = datetime.now(timezone.utc)
        job_repo.update(job)

        adapter_cls = ADAPTERS[source_key]
        adapter = adapter_cls()

        started = time.perf_counter()
        try:
            metrics, records_loaded = adapter.run(params, job.dataset_id, db)
        except Exception as exc:  # noqa: BLE001 - reported on the job, not swallowed
            logger.exception("Ingestion job %s failed", job_id)
            job.status = IngestionJobStatus.FAILED
            job.error_message = str(exc)
            job.completed_at = datetime.now(timezone.utc)
            job.execution_time_seconds = time.perf_counter() - started
            job_repo.update(job)
            return

        execution_time = time.perf_counter() - started

        dataset_repo = DatasetRepository(db)
        dataset = dataset_repo.get_by_id(job.dataset_id)
        if dataset is not None:
            dataset.record_count = records_loaded
            dataset_repo.update(dataset)

        QualityReportRepository(db).create(
            DataQualityReport(
                dataset_id=job.dataset_id,
                ingestion_job_id=job.id,
                records_read=metrics.records_read,
                records_valid=metrics.records_valid,
                records_rejected=metrics.records_rejected,
                missing_values=metrics.missing_values,
                duplicate_records=metrics.duplicate_records,
                invalid_coordinates=metrics.invalid_coordinates,
                invalid_timestamps=metrics.invalid_timestamps,
                invalid_sst=metrics.invalid_sst,
                outliers=metrics.outliers,
                schema_mismatches=metrics.schema_mismatches,
                details=metrics.details,
            )
        )

        job.status = IngestionJobStatus.COMPLETED
        job.records_read = metrics.records_read
        job.records_valid = metrics.records_valid
        job.records_rejected = metrics.records_rejected
        job.records_modified = metrics.records_modified
        job.execution_time_seconds = execution_time
        job.completed_at = datetime.now(timezone.utc)
        job_repo.update(job)
    finally:
        db.close()
