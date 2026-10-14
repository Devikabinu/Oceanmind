import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.anomaly_detection import AnomalyDetection
from app.repositories._filters import apply_time_and_bbox
from app.repositories._pagination import paginate


class AnomalyDetectionRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, item_id: uuid.UUID) -> AnomalyDetection | None:
        return self.db.get(AnomalyDetection, item_id)

    def list_paginated(
        self,
        page: int,
        page_size: int,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        min_latitude: float | None = None,
        max_latitude: float | None = None,
        min_longitude: float | None = None,
        max_longitude: float | None = None,
        is_anomaly: bool | None = None,
    ) -> tuple[list[AnomalyDetection], int]:
        stmt = apply_time_and_bbox(
            select(AnomalyDetection),
            AnomalyDetection,
            start_date,
            end_date,
            min_latitude,
            max_latitude,
            min_longitude,
            max_longitude,
        )
        if is_anomaly is not None:
            stmt = stmt.where(AnomalyDetection.is_anomaly.is_(is_anomaly))

        return paginate(
            self.db,
            stmt,
            AnomalyDetection,
            page,
            page_size,
            order_by=(AnomalyDetection.timestamp.desc(), AnomalyDetection.id),
        )
