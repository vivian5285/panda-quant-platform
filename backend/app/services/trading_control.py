"""User + platform trading control (pause, risk level, entry sizing)."""
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

# Defaults match historical hardcode: 20% margin × 5× leverage (= 1× equity notional).
DEFAULT_MARGIN_PCT_FRAC = 0.20
DEFAULT_LEVERAGE = 5
MIN_MARGIN_PCT_FRAC = 0.01
MAX_MARGIN_PCT_FRAC = 1.0
MIN_LEVERAGE = 1
MAX_LEVERAGE_ADMIN = 125


def clamp_margin_pct_frac(raw) -> float:
    try:
        v = float(raw)
    except (TypeError, ValueError):
        raise ValueError("invalid margin_pct_frac") from None
    if v != v:  # NaN
        raise ValueError("invalid margin_pct_frac")
    # Accept either fraction (0.2) or percent (20) for admin convenience.
    if v > 1.0 + 1e-12:
        v = v / 100.0
    if v < MIN_MARGIN_PCT_FRAC - 1e-12 or v > MAX_MARGIN_PCT_FRAC + 1e-12:
        raise ValueError("margin_pct_frac out of range")
    return round(max(MIN_MARGIN_PCT_FRAC, min(MAX_MARGIN_PCT_FRAC, v)), 6)


def clamp_leverage(raw) -> int:
    try:
        v = int(float(raw))
    except (TypeError, ValueError):
        raise ValueError("invalid leverage") from None
    if v < MIN_LEVERAGE or v > MAX_LEVERAGE_ADMIN:
        raise ValueError("leverage out of range")
    return v


def _default_state() -> dict:
    return {
        "trading_paused": False,
        "risk_level": "balanced",
        "risk_multiplier": RISK_MULTIPLIERS["balanced"],
        "margin_pct_frac": DEFAULT_MARGIN_PCT_FRAC,
        "leverage": DEFAULT_LEVERAGE,
        "settlement_fee_deferred": False,
        "settlement_defer_note": "",
        "referral_invite_override": False,
        "referral_override_note": "",
        "settlement_awaiting_flat": False,
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
    try:
        margin = clamp_margin_pct_frac(
            data.get("margin_pct_frac", DEFAULT_MARGIN_PCT_FRAC)
        )
    except ValueError:
        margin = DEFAULT_MARGIN_PCT_FRAC
    try:
        lev = clamp_leverage(data.get("leverage", DEFAULT_LEVERAGE))
    except ValueError:
        lev = DEFAULT_LEVERAGE
    return {
        "trading_paused": bool(data.get("trading_paused", False)),
        "risk_level": level,
        "risk_multiplier": RISK_MULTIPLIERS[level],
        "margin_pct_frac": margin,
        "leverage": lev,
        "settlement_fee_deferred": bool(data.get("settlement_fee_deferred", False)),
        "settlement_defer_note": str(data.get("settlement_defer_note") or ""),
        "referral_invite_override": bool(data.get("referral_invite_override", False)),
        "referral_override_note": str(data.get("referral_override_note") or ""),
        "settlement_awaiting_flat": bool(data.get("settlement_awaiting_flat", False)),
    }


def get_user_control(db: Session, user_id: int) -> dict:
    row = db.query(UserTradingState).filter(UserTradingState.user_id == user_id).first()
    return _parse(row)


def apply_sizing_to_supervisors(user_id: int, *, margin_pct_frac: float, leverage: int) -> int:
    """Hot-apply sizing to live supervisors so next open uses new values immediately."""
    try:
        from app.services.dispatcher import supervisor_pool
    except Exception:
        return 0
    n = 0
    try:
        for s in supervisor_pool.get_all_for_user(int(user_id)):
            try:
                s.entry_margin_pct = float(margin_pct_frac)
                s.entry_leverage = int(leverage)
                s.leverage = int(leverage)
                n += 1
            except Exception:
                pass
    except Exception:
        return n
    return n


def set_user_control(
    db: Session,
    user_id: int,
    *,
    trading_paused: bool | None = None,
    risk_level: str | None = None,
    margin_pct_frac: float | None = None,
    leverage: int | None = None,
    settlement_fee_deferred: bool | None = None,
    settlement_defer_note: str | None = None,
    referral_invite_override: bool | None = None,
    referral_override_note: str | None = None,
    settlement_awaiting_flat: bool | None = None,
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
    if margin_pct_frac is not None:
        state["margin_pct_frac"] = clamp_margin_pct_frac(margin_pct_frac)
    if leverage is not None:
        state["leverage"] = clamp_leverage(leverage)
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
    if settlement_awaiting_flat is not None:
        state["settlement_awaiting_flat"] = settlement_awaiting_flat
    payload = {
        "trading_paused": state["trading_paused"],
        "risk_level": state["risk_level"],
        "margin_pct_frac": state["margin_pct_frac"],
        "leverage": state["leverage"],
        "settlement_fee_deferred": state.get("settlement_fee_deferred", False),
        "settlement_defer_note": state.get("settlement_defer_note", ""),
        "referral_invite_override": state.get("referral_invite_override", False),
        "referral_override_note": state.get("referral_override_note", ""),
        "settlement_awaiting_flat": state.get("settlement_awaiting_flat", False),
    }
    if row:
        row.state_json = json.dumps(payload)
    else:
        db.add(UserTradingState(user_id=user_id, state_json=json.dumps(payload)))
    db.commit()
    out = get_user_control(db, user_id)
    if margin_pct_frac is not None or leverage is not None:
        apply_sizing_to_supervisors(
            user_id,
            margin_pct_frac=float(out["margin_pct_frac"]),
            leverage=int(out["leverage"]),
        )
    return out


def clear_settlement_fee_deferred(db: Session, user_id: int) -> None:
    set_user_control(db, user_id, settlement_fee_deferred=False, settlement_defer_note="")


def set_settlement_awaiting_flat(db: Session, user_id: int, awaiting: bool) -> None:
    set_user_control(db, user_id, settlement_awaiting_flat=awaiting)


def clear_settlement_awaiting_flat(db: Session, user_id: int) -> None:
    set_user_control(db, user_id, settlement_awaiting_flat=False)


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
    """PAUSE DISABLED: 永远返回 False - 交易永不暂停"""
    return False  # 永远不暂停交易


def build_trading_control_response(db: Session, user) -> dict:
    from app.services.settlement import get_pending_settlement
    from app.services.credit_control import (
        user_trading_blocked_by_credit,
        user_is_credit_default,
        referral_block_reason,
        user_api_operations_blocked,
    )

    ctrl = get_user_control(db, user.id)
    pending = get_pending_settlement(db, user.id)
    settlement_blocked = pending is not None
    settlement_fee_deferred = bool(ctrl.get("settlement_fee_deferred")) and settlement_blocked
    credit_blocked, credit_reason = user_trading_blocked_by_credit(db, user.id)
    api_bind_blocked, api_bind_block_reason = user_api_operations_blocked(db, user.id)
    awaiting_flat = bool(ctrl.get("settlement_awaiting_flat"))
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
        "settlement_awaiting_flat": awaiting_flat,
        "family_credit_blocked": credit_reason == "family_credit_default",
        "referral_blocked": bool(referral_block_reason(db, user.id)),
        "referral_block_reason": referral_block_reason(db, user.id),
        "referral_invite_override": bool(ctrl.get("referral_invite_override")),
        "api_bind_blocked": api_bind_blocked,
        "api_bind_block_reason": api_bind_block_reason,
        "effective_paused": ctrl["trading_paused"] or settlement_pause or global_paused or awaiting_flat,
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
