import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DataQualityReport(Base):
    __tablename__ = "data_quality_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    ingestion_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), index=True
    )

    records_read: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_valid: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_rejected: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    missing_values: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicate_records: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    invalid_coordinates: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    invalid_timestamps: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    invalid_sst: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    outliers: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    schema_mismatches: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    dataset: Mapped["Dataset"] = relationship()
    ingestion_job: Mapped["IngestionJob"] = relationship(back_populates="quality_reports")
