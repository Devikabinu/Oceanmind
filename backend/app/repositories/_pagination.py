from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session


def paginate(db: Session, stmt: Select, model, page: int, page_size: int, order_by) -> tuple[list, int]:
    """Run stmt as a count + one ordered page, matching Module 1's list_paginated shape."""
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = db.execute(count_stmt).scalar_one()
    page_stmt = stmt.order_by(*order_by).offset((page - 1) * page_size).limit(page_size)
    return list(db.execute(page_stmt).scalars()), total
