import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.biodiversity_observation import BiodiversityObservation


class BiodiversityObservationRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_paginated(
        self,
        page: int,
        page_size: int,
        dataset_id: uuid.UUID | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        min_latitude: float | None = None,
        max_latitude: float | None = None,
        min_longitude: float | None = None,
        max_longitude: float | None = None,
    ) -> tuple[list[BiodiversityObservation], int]:
        stmt = select(BiodiversityObservation)
        count_stmt = select(func.count()).select_from(BiodiversityObservation)

        if dataset_id is not None:
            stmt = stmt.where(BiodiversityObservation.dataset_id == dataset_id)
            count_stmt = count_stmt.where(BiodiversityObservation.dataset_id == dataset_id)
        if start_date is not None:
            stmt = stmt.where(BiodiversityObservation.timestamp >= start_date)
            count_stmt = count_stmt.where(BiodiversityObservation.timestamp >= start_date)
        if end_date is not None:
            stmt = stmt.where(BiodiversityObservation.timestamp <= end_date)
            count_stmt = count_stmt.where(BiodiversityObservation.timestamp <= end_date)
        if min_latitude is not None:
            stmt = stmt.where(BiodiversityObservation.latitude >= min_latitude)
            count_stmt = count_stmt.where(BiodiversityObservation.latitude >= min_latitude)
        if max_latitude is not None:
            stmt = stmt.where(BiodiversityObservation.latitude <= max_latitude)
            count_stmt = count_stmt.where(BiodiversityObservation.latitude <= max_latitude)
        if min_longitude is not None:
            stmt = stmt.where(BiodiversityObservation.longitude >= min_longitude)
            count_stmt = count_stmt.where(BiodiversityObservation.longitude >= min_longitude)
        if max_longitude is not None:
            stmt = stmt.where(BiodiversityObservation.longitude <= max_longitude)
            count_stmt = count_stmt.where(BiodiversityObservation.longitude <= max_longitude)

        total = self.db.execute(count_stmt).scalar_one()
        stmt = (
            stmt.order_by(BiodiversityObservation.timestamp.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list(self.db.execute(stmt).scalars())
        return items, total
