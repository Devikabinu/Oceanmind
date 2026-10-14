import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, Float, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class BiodiversityObservation(Base):
    """A single normalized marine species occurrence record (from OBIS)."""

    __tablename__ = "biodiversity_observations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )

    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    latitude: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    longitude: Mapped[float] = mapped_column(Float, nullable=False, index=True)

    scientific_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    occurrence_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    min_depth: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_depth: Mapped[float | None] = mapped_column(Float, nullable=True)

    source_record_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    geometry: Mapped[str] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    dataset: Mapped["Dataset"] = relationship()

    # Note: the spatial (GIST) index on `geometry` is created automatically by
    # GeoAlchemy2 (Geometry columns default to spatial_index=True) - no explicit
    # Index() for it here, to avoid creating a duplicate index.
    __table_args__ = (
        Index("ix_biodiversity_observations_dataset_timestamp", "dataset_id", "timestamp"),
    )
