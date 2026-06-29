"""Admin user list metrics and risk flags."""
from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Trade, TradeLog, User
from app.utils.crypto import decrypt_text


def mask_api_key(user: User) -> str | None:
    if not user.api_key_enc:
        return None
    try:
        key = decrypt_text(user.api_key_enc)
        if len(key) >= 4:
            return f"****{key[-4:]}"
        return "****"
    except Exception:
        return "****"


def user_cumulative_pnl(db: Session, user_id: int) -> float:
    total = db.query(func.coalesce(func.sum(Trade.realized_pnl), 0)).filter(
        Trade.user_id == user_id,
        Trade.status == "closed",
    ).scalar()
    return round(float(total or 0), 2)


def user_execution_success_rate(db: Session, user_id: int) -> float | None:
    success = db.query(TradeLog).filter(
        TradeLog.user_id == user_id,
        TradeLog.event_type.in_(["OPEN", "CLOSE"]),
    ).count()
    failed = db.query(TradeLog).filter(
        TradeLog.user_id == user_id,
        TradeLog.event_type == "ERROR",
    ).count()
    total = success + failed
    if total == 0:
        closed = db.query(Trade).filter(Trade.user_id == user_id, Trade.status == "closed").count()
        if closed == 0:
            return None
        wins = db.query(Trade).filter(
            Trade.user_id == user_id,
            Trade.status == "closed",
            Trade.realized_pnl > 0,
        ).count()
        return round(wins / closed * 100, 1)
    return round(success / total * 100, 1)


def user_risk_flag(
    user: User,
    *,
    trading_paused: bool,
    cumulative_pnl: float,
    exec_rate: float | None,
) -> tuple[bool, str | None]:
    if user.api_status == "error":
        return True, "api_error"
    if not user.is_active:
        return True, "disabled"
    if exec_rate is not None and exec_rate < 45:
        return True, "low_exec_rate"
    if cumulative_pnl < -500:
        return True, "heavy_loss"
    if trading_paused:
        return True, "paused"
    return False, None
