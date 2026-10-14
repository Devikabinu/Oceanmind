import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import DatasetKind


class Dataset(Base):
    """A logical, ingested slice of data from a DataSource (e.g. one ingestion's output)."""

    __tablename__ = "datasets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    data_source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_sources.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[DatasetKind] = mapped_column(Enum(DatasetKind, name="dataset_kind"), nullable=False)

    temporal_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    temporal_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    min_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)

    record_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    data_source: Mapped["DataSource"] = relationship(back_populates="datasets")
