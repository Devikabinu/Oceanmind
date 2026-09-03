from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.repositories.data_source_repository import DataSourceRepository
from app.schemas.data_source import DataSourceRead

router = APIRouter(prefix="/data-sources", tags=["data-sources"])


@router.get("", response_model=list[DataSourceRead], dependencies=[Depends(get_current_user)])
def list_data_sources(db: Session = Depends(get_db)) -> list:
    return DataSourceRepository(db).list_all()
