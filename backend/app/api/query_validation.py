from datetime import datetime

from fastapi import HTTPException, status


def validate_filter_ranges(
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    min_latitude: float | None = None,
    max_latitude: float | None = None,
    min_longitude: float | None = None,
    max_longitude: float | None = None,
) -> None:
    """Reject logically inverted ranges with a 422, like Module 1's IngestionRequest does.

    Per-field bounds (e.g. latitude within -90..90) are already enforced by Query().
    """
    problems = []

    def _problem(field: str, msg: str) -> None:
        # Same shape as FastAPI's own validation errors, so clients parse one format.
        problems.append({"type": "value_error", "loc": ["query", field], "msg": msg})

    if start_date is not None and end_date is not None and start_date > end_date:
        _problem("start_date", "start_date must not be after end_date")
    if min_latitude is not None and max_latitude is not None and min_latitude > max_latitude:
        _problem("min_latitude", "min_latitude must not be greater than max_latitude")
    if min_longitude is not None and max_longitude is not None and min_longitude > max_longitude:
        _problem("min_longitude", "min_longitude must not be greater than max_longitude")
    if problems:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=problems)
