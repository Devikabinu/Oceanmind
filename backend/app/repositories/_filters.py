from datetime import datetime

from sqlalchemy import Select


def apply_time_and_bbox(
    stmt: Select,
    model,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    min_latitude: float | None = None,
    max_latitude: float | None = None,
    min_longitude: float | None = None,
    max_longitude: float | None = None,
) -> Select:
    """Shared WHERE clauses for tables with timestamp/latitude/longitude columns."""
    if start_date is not None:
        stmt = stmt.where(model.timestamp >= start_date)
    if end_date is not None:
        stmt = stmt.where(model.timestamp <= end_date)
    if min_latitude is not None:
        stmt = stmt.where(model.latitude >= min_latitude)
    if max_latitude is not None:
        stmt = stmt.where(model.latitude <= max_latitude)
    if min_longitude is not None:
        stmt = stmt.where(model.longitude >= min_longitude)
    if max_longitude is not None:
        stmt = stmt.where(model.longitude <= max_longitude)
    return stmt
