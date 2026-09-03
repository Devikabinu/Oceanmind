import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.environment_biodiversity_match import EnvironmentBiodiversityMatch


class MatchRepository:
    def __init__(self, db: Session):
        self.db = db

    def bulk_create(self, matches: list[EnvironmentBiodiversityMatch]) -> int:
        if not matches:
            return 0
        self.db.add_all(matches)
        self.db.commit()
        return len(matches)

    def list_paginated(
        self, page: int, page_size: int
    ) -> tuple[list[EnvironmentBiodiversityMatch], int]:
        total = self.db.execute(
            select(func.count()).select_from(EnvironmentBiodiversityMatch)
        ).scalar_one()
        stmt = (
            select(EnvironmentBiodiversityMatch)
            .order_by(EnvironmentBiodiversityMatch.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list(self.db.execute(stmt).scalars())
        return items, total

    def get_by_id(self, match_id: uuid.UUID) -> EnvironmentBiodiversityMatch | None:
        return self.db.get(EnvironmentBiodiversityMatch, match_id)
