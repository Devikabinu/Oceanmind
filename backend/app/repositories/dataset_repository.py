import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.dataset import Dataset


class DatasetRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, dataset_id: uuid.UUID) -> Dataset | None:
        return self.db.get(Dataset, dataset_id)

    def list_paginated(
        self,
        page: int,
        page_size: int,
        data_source_id: uuid.UUID | None = None,
    ) -> tuple[list[Dataset], int]:
        stmt = select(Dataset)
        count_stmt = select(func.count()).select_from(Dataset)

        if data_source_id is not None:
            stmt = stmt.where(Dataset.data_source_id == data_source_id)
            count_stmt = count_stmt.where(Dataset.data_source_id == data_source_id)

        total = self.db.execute(count_stmt).scalar_one()
        stmt = stmt.order_by(Dataset.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        items = list(self.db.execute(stmt).scalars())
        return items, total

    def create(self, dataset: Dataset) -> Dataset:
        self.db.add(dataset)
        self.db.commit()
        self.db.refresh(dataset)
        return dataset

    def update(self, dataset: Dataset) -> Dataset:
        self.db.add(dataset)
        self.db.commit()
        self.db.refresh(dataset)
        return dataset
