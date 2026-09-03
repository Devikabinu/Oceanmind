import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_source import DataSource


class DataSourceRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_all(self) -> list[DataSource]:
        return list(self.db.execute(select(DataSource).order_by(DataSource.name)).scalars())

    def get_by_id(self, data_source_id: uuid.UUID) -> DataSource | None:
        return self.db.get(DataSource, data_source_id)

    def get_by_name(self, name: str) -> DataSource | None:
        stmt = select(DataSource).where(DataSource.name == name)
        return self.db.execute(stmt).scalar_one_or_none()

    def create(self, data_source: DataSource) -> DataSource:
        self.db.add(data_source)
        self.db.commit()
        self.db.refresh(data_source)
        return data_source
