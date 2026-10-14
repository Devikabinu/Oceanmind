import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class EnvironmentBiodiversityMatch(Base):
    """Result of a spatiotemporal join between a biodiversity observation and the
    nearest valid environmental (SST) observation within a configurable radius/window.
    """

    __tablename__ = "environment_biodiversity_matches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    biodiversity_observation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("biodiversity_observations.id", ondelete="CASCADE"),
        index=True,
    )
    ocean_observation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ocean_observations.id", ondelete="CASCADE"), index=True
    )

    distance_km: Mapped[float] = mapped_column(Float, nullable=False)
    time_difference_hours: Mapped[float] = mapped_column(Float, nullable=False)

    matched_sst: Mapped[float | None] = mapped_column(Float, nullable=True)
    matched_sst_anomaly: Mapped[float | None] = mapped_column(Float, nullable=True)

    spatial_radius_km: Mapped[float] = mapped_column(Float, nullable=False)
    temporal_window_hours: Mapped[float] = mapped_column(Float, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    biodiversity_observation: Mapped["BiodiversityObservation"] = relationship()
    ocean_observation: Mapped["OceanObservation"] = relationship()
