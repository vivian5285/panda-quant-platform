"""Shared date-range filters for trades and logs."""
from datetime import date, datetime, time

from sqlalchemy.orm import Query


def parse_date_param(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def apply_trade_date_filter(query: Query, start: date | None, end: date | None, model) -> Query:
    """Filter trades by closed_at if set, else created_at."""
    if start:
        start_dt = datetime.combine(start, time.min)
        query = query.filter(
            (model.closed_at >= start_dt) | ((model.closed_at.is_(None)) & (model.created_at >= start_dt))
        )
    if end:
        end_dt = datetime.combine(end, time.max)
        query = query.filter(
            (model.closed_at <= end_dt) | ((model.closed_at.is_(None)) & (model.created_at <= end_dt))
        )
    return query


def apply_log_date_filter(query: Query, start: date | None, end: date | None, model) -> Query:
    if start:
        query = query.filter(model.created_at >= datetime.combine(start, time.min))
    if end:
        query = query.filter(model.created_at <= datetime.combine(end, time.max))
    return query
