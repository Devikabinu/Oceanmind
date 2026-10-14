import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.sst_forecast import SSTForecast
from app.repositories._filters import apply_time_and_bbox
from app.repositories._pagination import paginate


class SSTForecastRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, item_id: uuid.UUID) -> SSTForecast | None:
        return self.db.get(SSTForecast, item_id)

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
        forecast_horizon_days: int | None = None,
    ) -> tuple[list[SSTForecast], int]:
        stmt = apply_time_and_bbox(
            select(SSTForecast),
            SSTForecast,
            start_date,
            end_date,
            min_latitude,
            max_latitude,
            min_longitude,
            max_longitude,
        )
        if forecast_horizon_days is not None:
            stmt = stmt.where(SSTForecast.forecast_horizon_days == forecast_horizon_days)

        return paginate(
            self.db,
            stmt,
            SSTForecast,
            page,
            page_size,
            order_by=(SSTForecast.timestamp.desc(), SSTForecast.id),
        )
