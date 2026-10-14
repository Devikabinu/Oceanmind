import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import RiskLevel


class EcologicalRiskScoreRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    biodiversity_observation_id: uuid.UUID
    timestamp: datetime
    latitude: float
    longitude: float
    risk_score: float
    risk_level: RiskLevel
    contributing_factors: dict
    created_at: datetime


class PaginatedEcologicalRiskScores(BaseModel):
    items: list[EcologicalRiskScoreRead]
    total: int
    page: int
    page_size: int
