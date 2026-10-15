import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Species(Base):
    """Marine species catalogue entry.

    Taxonomy comes from OBIS (WoRMS-backed), English common names from WoRMS, and the conservation category from
    the IUCN Red List as exposed by the OBIS red-list checklist. Nothing here is typed in by hand except `watchlist`
    (which species the platform syncs observations for).
    """

    __tablename__ = "species"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    aphia_id: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)
    scientific_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    common_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    taxon_group: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    class_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    order_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    family: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # IUCN Red List category (VU/EN/CR/EX) ONLY when OBIS lists the species as threatened. NULL means "not listed as
    # threatened by this source", which is NOT the same as Least Concern: the status is simply not confirmed here.
    iucn_category: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    iucn_source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sources: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    watchlist: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
