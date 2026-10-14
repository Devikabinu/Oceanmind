import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ecological_risk_score import EcologicalRiskScore
from app.models.enums import RiskLevel
from app.repositories._filters import apply_time_and_bbox
from app.repositories._pagination import paginate


class EcologicalRiskScoreRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, item_id: uuid.UUID) -> EcologicalRiskScore | None:
        return self.db.get(EcologicalRiskScore, item_id)

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
        risk_level: RiskLevel | None = None,
    ) -> tuple[list[EcologicalRiskScore], int]:
        stmt = apply_time_and_bbox(
            select(EcologicalRiskScore),
            EcologicalRiskScore,
            start_date,
            end_date,
            min_latitude,
            max_latitude,
            min_longitude,
            max_longitude,
        )
        if risk_level is not None:
            stmt = stmt.where(EcologicalRiskScore.risk_level == risk_level)

        return paginate(
            self.db,
            stmt,
            EcologicalRiskScore,
            page,
            page_size,
            order_by=(EcologicalRiskScore.timestamp.desc(), EcologicalRiskScore.id),
        )
