"""User + platform trading control (pause, risk level)."""
import json
from sqlalchemy.orm import Session

from app.models import UserTradingState
from app.services.platform_runtime import (
    get_global_risk_multiplier,
    is_global_trading_paused,
    set_global_risk_multiplier,
    set_global_trading_paused,
)
RISK_LEVELS = frozenset({"conservative", "balanced", "aggressive"})
RISK_MULTIPLIERS = {"conservative": 0.6, "balanced": 1.0, "aggressive": 1.4}


def _default_state() -> dict:
    return {"trading_paused": False, "risk_level": "balanced"}


def _parse(row: UserTradingState | None) -> dict:
    if not row or not row.state_json:
        return _default_state()
    try:
        data = json.loads(row.state_json)
    except json.JSONDecodeError:
        return _default_state()
    level = data.get("risk_level", "balanced")
    if level not in RISK_LEVELS:
        level = "balanced"
    return {
        "trading_paused": bool(data.get("trading_paused", False)),
        "risk_level": level,
        "risk_multiplier": RISK_MULTIPLIERS[level],
    }


def get_user_control(db: Session, user_id: int) -> dict:
    row = db.query(UserTradingState).filter(UserTradingState.user_id == user_id).first()
    return _parse(row)


def set_user_control(
    db: Session,
    user_id: int,
    *,
    trading_paused: bool | None = None,
    risk_level: str | None = None,
) -> dict:
    row = db.query(UserTradingState).filter(UserTradingState.user_id == user_id).first()
    state = _parse(row)
    if trading_paused is not None:
        state["trading_paused"] = trading_paused
    if risk_level is not None:
        if risk_level not in RISK_LEVELS:
            raise ValueError("invalid risk_level")
        state["risk_level"] = risk_level
        state["risk_multiplier"] = RISK_MULTIPLIERS[risk_level]
    payload = {"trading_paused": state["trading_paused"], "risk_level": state["risk_level"]}
    if row:
        row.state_json = json.dumps(payload)
    else:
        db.add(UserTradingState(user_id=user_id, state_json=json.dumps(payload)))
    db.commit()
    return get_user_control(db, user_id)


def is_user_paused(db: Session, user_id: int) -> bool:
    if get_user_control(db, user_id)["trading_paused"]:
        return True
    from app.services.settlement import user_has_unsettled_payment

    return user_has_unsettled_payment(db, user_id)


def build_trading_control_response(db: Session, user) -> dict:
    from app.services.settlement import get_pending_settlement

    ctrl = get_user_control(db, user.id)
    pending = get_pending_settlement(db, user.id)
    settlement_blocked = pending is not None
    pending_out = None
    if pending:
        pending_out = {
            "id": pending.id,
            "user_payable": pending.user_payable,
            "payment_status": pending.payment_status,
            "period_start": pending.period_start.isoformat(),
            "period_end": pending.period_end.isoformat(),
        }
    global_paused = is_globally_paused()
    return {
        **ctrl,
        "trading_paused": ctrl["trading_paused"],
        "settlement_blocked": settlement_blocked,
        "effective_paused": ctrl["trading_paused"] or settlement_blocked or global_paused,
        "pending_settlement": pending_out,
        "api_status": user.api_status,
        "global_paused": global_paused,
    }


def is_globally_paused() -> bool:
    return is_global_trading_paused()


def set_global_pause(paused: bool) -> dict:
    set_global_trading_paused(paused)
    return get_global_control()


def get_global_control() -> dict:
    return {
        "global_trading_paused": is_globally_paused(),
        "global_risk_multiplier": get_global_risk_multiplier(),
    }


def set_global_risk(value: float) -> dict:
    set_global_risk_multiplier(value)
    return get_global_control()
