"""API bind / rebind policy: single exchange, settlement clear, master+UID filing."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import ApiStatus, User
from app.services.credit_control import (
    is_master_uid_blocked,
    referral_block_reason,
    user_api_bind_blocked,
    user_is_credit_default,
)
from app.services.trading_control import get_user_control


def _norm(val: str | None) -> str:
    return (val or "").strip()


def user_has_active_api(user: User) -> bool:
    return bool(user.api_key_enc and user.api_status == ApiStatus.ACTIVE.value)


def api_gate_blocked(db: Session, user_id: int) -> tuple[bool, str | None]:
    """
    Block bind / verify / discover / unbind when:
    - own unpaid performance fee (unless admin deferred)
    - referrer has L1/L2 downline with unpaid fee (失信连坐，防马甲换绑)
    """
    blocked, reason = user_api_bind_blocked(db, user_id)
    if blocked:
        return True, reason
    ref_reason = referral_block_reason(db, user_id)
    if ref_reason == "downline_credit_default":
        return True, "downline_credit_default"
    return False, None


def assert_api_gate_allowed(db: Session, user_id: int) -> None:
    from app.i18n.errors import raise_i18n

    blocked, reason = api_gate_blocked(db, user_id)
    if not blocked:
        return
    key = {
        "own_credit_default": "api.credit_default_bind_blocked",
        "downline_credit_default": "api.downline_credit_bind_blocked",
    }.get(reason or "", "api.credit_default_bind_blocked")
    raise_i18n(403, key)


def bind_identity_changed(
    user: User,
    *,
    exchange: str,
    account_mode: str,
    exchange_uid: str | None,
    master_exchange_uid: str | None,
) -> bool:
    """True when exchange / UID / mode changes — requires new profit cycle on bind."""
    if not user_has_active_api(user):
        return True
    mode = (account_mode or "master").strip().lower()
    prev_mode = (user.api_account_mode or "master").strip().lower()
    if _norm(user.exchange) != _norm(exchange):
        return True
    if prev_mode != mode:
        return True
    if mode == "sub":
        if _norm(user.exchange_uid) != _norm(exchange_uid):
            return True
        if _norm(user.master_exchange_uid) != _norm(master_exchange_uid):
            return True
    elif _norm(user.exchange_uid) != _norm(exchange_uid):
        return True
    return False


def describe_bind_action(
    user: User,
    *,
    exchange: str,
    account_mode: str,
) -> str:
    if not user_has_active_api(user):
        return "first_bind"
    if _norm(user.exchange) != _norm(exchange):
        return "exchange_switch"
    if (user.api_account_mode or "master") != (account_mode or "master"):
        return "mode_switch"
    return "rebind"


def validate_bind_target_family(
    db: Session,
    *,
    exchange: str,
    master_exchange_uid: str | None,
) -> None:
    """Reject bind when target master UID family is credit-blocked or inactive."""
    from app.i18n.errors import raise_i18n

    master_uid = _norm(master_exchange_uid)
    if not master_uid:
        return
    if is_master_uid_blocked(db, exchange, master_uid):
        raise_i18n(403, "api.family_credit_bind_blocked")
