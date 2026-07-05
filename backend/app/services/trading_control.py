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
    return {
        "trading_paused": False,
        "risk_level": "balanced",
        "risk_multiplier": RISK_MULTIPLIERS["balanced"],
        "settlement_fee_deferred": False,
        "settlement_defer_note": "",
        "referral_invite_override": False,
        "referral_override_note": "",
    }


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
        "settlement_fee_deferred": bool(data.get("settlement_fee_deferred", False)),
        "settlement_defer_note": str(data.get("settlement_defer_note") or ""),
        "referral_invite_override": bool(data.get("referral_invite_override", False)),
        "referral_override_note": str(data.get("referral_override_note") or ""),
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
    settlement_fee_deferred: bool | None = None,
    settlement_defer_note: str | None = None,
    referral_invite_override: bool | None = None,
    referral_override_note: str | None = None,
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
    if settlement_fee_deferred is not None:
        state["settlement_fee_deferred"] = settlement_fee_deferred
        if not settlement_fee_deferred:
            state["settlement_defer_note"] = ""
    if settlement_defer_note is not None:
        state["settlement_defer_note"] = settlement_defer_note[:500]
    if referral_invite_override is not None:
        state["referral_invite_override"] = referral_invite_override
        if not referral_invite_override:
            state["referral_override_note"] = ""
    if referral_override_note is not None:
        state["referral_override_note"] = referral_override_note[:500]
    payload = {
        "trading_paused": state["trading_paused"],
        "risk_level": state["risk_level"],
        "settlement_fee_deferred": state.get("settlement_fee_deferred", False),
        "settlement_defer_note": state.get("settlement_defer_note", ""),
        "referral_invite_override": state.get("referral_invite_override", False),
        "referral_override_note": state.get("referral_override_note", ""),
    }
    if row:
        row.state_json = json.dumps(payload)
    else:
        db.add(UserTradingState(user_id=user_id, state_json=json.dumps(payload)))
    db.commit()
    return get_user_control(db, user_id)


def clear_settlement_fee_deferred(db: Session, user_id: int) -> None:
    set_user_control(db, user_id, settlement_fee_deferred=False, settlement_defer_note="")


def count_settlement_gate_stats(db: Session) -> dict[str, int]:
    from app.models import Settlement, PaymentStatus

    unsettled = (
        db.query(Settlement.user_id)
        .filter(Settlement.payment_status.in_((PaymentStatus.PENDING.value, PaymentStatus.PAID.value)))
        .distinct()
        .all()
    )
    blocked = 0
    deferred = 0
    for (uid,) in unsettled:
        if get_user_control(db, uid).get("settlement_fee_deferred"):
            deferred += 1
        else:
            blocked += 1
    return {"blocked": blocked, "deferred": deferred}


def is_user_paused(db: Session, user_id: int) -> bool:
    ctrl = get_user_control(db, user_id)
    if ctrl["trading_paused"]:
        return True
    from app.services.credit_control import user_trading_blocked_by_credit

    blocked, _reason = user_trading_blocked_by_credit(db, user_id)
    return blocked


def build_trading_control_response(db: Session, user) -> dict:
    from app.services.settlement import get_pending_settlement
    from app.services.credit_control import user_trading_blocked_by_credit, user_is_credit_default, referral_block_reason

    ctrl = get_user_control(db, user.id)
    pending = get_pending_settlement(db, user.id)
    settlement_blocked = pending is not None
    settlement_fee_deferred = bool(ctrl.get("settlement_fee_deferred")) and settlement_blocked
    credit_blocked, credit_reason = user_trading_blocked_by_credit(db, user.id)
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
    settlement_pause = credit_blocked
    return {
        **ctrl,
        "trading_paused": ctrl["trading_paused"],
        "settlement_blocked": settlement_blocked,
        "settlement_fee_deferred": settlement_fee_deferred,
        "credit_default": user_is_credit_default(db, user.id),
        "family_credit_blocked": credit_reason == "family_credit_default",
        "referral_blocked": bool(referral_block_reason(db, user.id)),
        "referral_block_reason": referral_block_reason(db, user.id),
        "referral_invite_override": bool(ctrl.get("referral_invite_override")),
        "effective_paused": ctrl["trading_paused"] or settlement_pause or global_paused,
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
