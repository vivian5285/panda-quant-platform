"""Master + sub exchange account binding validation and registry."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core.binance_client import BinanceClient
from app.core.exchange_factory import exchange_requires_passphrase, parse_exchange
from app.core.okx_client import OkxClient
from app.models import ExchangeAccountRegistry, User
from app.services.api_validation import validate_exchange_api

logger = logging.getLogger(__name__)

STRICT_SUB_EXCHANGES = frozenset({"binance", "okx"})
RELAXED_SUB_EXCHANGES = frozenset({"gate", "deepcoin"})


def _normalize_uid(val: str | None) -> str:
    return (val or "").strip()


def _master_client(exchange: str, api_key: str, api_secret: str, passphrase: str, user_id: int):
    ex = parse_exchange(exchange)
    if ex == "binance":
        return BinanceClient(api_key, api_secret, user_id)
    if ex == "okx":
        return OkxClient(api_key, api_secret, passphrase, user_id)
    return None


def discover_master_sub_accounts(
    exchange: str,
    master_api_key: str,
    master_api_secret: str,
    master_passphrase: str = "",
    user_id: int = 0,
) -> dict:
    """Query master API for UID and sub-account list (bind-time helper)."""
    ex = parse_exchange(exchange)
    if ex is None:
        return {"ok": False, "message_key": "api.unsupported_exchange", "uid": None, "sub_accounts": []}

    client = _master_client(ex, master_api_key, master_api_secret, master_passphrase, user_id)
    if client and hasattr(client, "verify_master_readonly"):
        result = client.verify_master_readonly()
        return {
            "ok": bool(result.get("ok")),
            "uid": result.get("uid"),
            "sub_accounts": result.get("sub_accounts") or [],
            "strict": ex in STRICT_SUB_EXCHANGES,
            "exchange": ex,
        }

    # Gate / Deepcoin: master connect only, user supplies UID
    sub_result = validate_exchange_api(
        ex, master_api_key, master_api_secret, user_id, master_passphrase,
        skip_trading_checks=True,
    ) if ex in RELAXED_SUB_EXCHANGES else {"valid": False}

    return {
        "ok": bool(sub_result.get("valid")) if ex in RELAXED_SUB_EXCHANGES else False,
        "uid": None,
        "sub_accounts": [],
        "strict": False,
        "exchange": ex,
        "relaxed": ex in RELAXED_SUB_EXCHANGES,
    }


def _sub_belongs_to_master(
    exchange: str,
    master_uid: str,
    sub_uid: str,
    master_api_key: str,
    master_api_secret: str,
    master_passphrase: str,
    user_id: int,
) -> tuple[bool, str | None]:
    ex = parse_exchange(exchange)
    master_uid = _normalize_uid(master_uid)
    sub_uid = _normalize_uid(sub_uid)
    if not master_uid or not sub_uid:
        return False, "api.sub_uid_required"

    if ex in STRICT_SUB_EXCHANGES:
        client = _master_client(ex, master_api_key, master_api_secret, master_passphrase, user_id)
        if not client:
            return False, "api.unsupported_exchange"
        subs = client.list_sub_accounts() if hasattr(client, "list_sub_accounts") else []
        allowed = {str(s.get("uid")) for s in subs}
        # Also allow label/email match for Binance email-based subs
        allowed |= {str(s.get("label")) for s in subs}
        if sub_uid not in allowed and subs:
            return False, "api.sub_not_under_master"
        if not subs:
            # Master has no subs listed — allow if master UID verified and user declares sub
            resolved_master = client.get_exchange_uid() if hasattr(client, "get_exchange_uid") else None
            if resolved_master and resolved_master != master_uid:
                return False, "api.master_uid_mismatch"
        return True, None

    if ex in RELAXED_SUB_EXCHANGES:
        # Relaxed: master API must connect; user-declared master UID + sub API validated separately
        return True, None

    return False, "api.unsupported_exchange"


def is_exchange_uid_taken(
    db: Session,
    exchange: str,
    exchange_uid: str,
    exclude_user_id: int | None = None,
) -> bool:
    uid = _normalize_uid(exchange_uid)
    if not uid:
        return False
    q = db.query(ExchangeAccountRegistry).filter(
        ExchangeAccountRegistry.exchange == exchange,
        ExchangeAccountRegistry.exchange_uid == uid,
        ExchangeAccountRegistry.is_active.is_(True),
    )
    if exclude_user_id:
        q = q.filter(ExchangeAccountRegistry.user_id != exclude_user_id)
    return q.first() is not None


def is_master_uid_blocked(db: Session, exchange: str, master_uid: str) -> bool:
    """Block if same master UID was tied to a deactivated platform user."""
    uid = _normalize_uid(master_uid)
    if not uid:
        return False
    rows = (
        db.query(ExchangeAccountRegistry)
        .join(User, User.id == ExchangeAccountRegistry.user_id)
        .filter(
            ExchangeAccountRegistry.exchange == exchange,
            ExchangeAccountRegistry.is_active.is_(True),
            User.is_active.is_(False),
        )
        .filter(
            (ExchangeAccountRegistry.master_exchange_uid == uid)
            | (
                (ExchangeAccountRegistry.account_mode == "master")
                & (ExchangeAccountRegistry.exchange_uid == uid)
            )
        )
        .all()
    )
    return len(rows) > 0


def register_exchange_account(
    db: Session,
    user: User,
    *,
    exchange: str,
    account_mode: str,
    exchange_uid: str,
    master_exchange_uid: str | None = None,
) -> None:
    uid = _normalize_uid(exchange_uid)
    if not uid:
        return
    db.query(ExchangeAccountRegistry).filter(
        ExchangeAccountRegistry.user_id == user.id,
        ExchangeAccountRegistry.exchange == exchange,
        ExchangeAccountRegistry.is_active.is_(True),
    ).update({"is_active": False})

    row = ExchangeAccountRegistry(
        user_id=user.id,
        exchange=exchange,
        account_mode=account_mode,
        exchange_uid=uid,
        master_exchange_uid=_normalize_uid(master_exchange_uid) or None,
        is_active=True,
    )
    db.add(row)


def deactivate_exchange_registry(db: Session, user_id: int) -> None:
    db.query(ExchangeAccountRegistry).filter(
        ExchangeAccountRegistry.user_id == user_id,
        ExchangeAccountRegistry.is_active.is_(True),
    ).update({"is_active": False})


def get_linked_accounts_for_master(db: Session, exchange: str, master_uid: str) -> list[dict]:
    uid = _normalize_uid(master_uid)
    if not uid:
        return []
    rows = (
        db.query(ExchangeAccountRegistry, User)
        .join(User, User.id == ExchangeAccountRegistry.user_id)
        .filter(
            ExchangeAccountRegistry.exchange == exchange,
            ExchangeAccountRegistry.is_active.is_(True),
            ExchangeAccountRegistry.master_exchange_uid == uid,
        )
        .all()
    )
    return [
        {
            "user_id": u.id,
            "platform_uid": u.uid,
            "exchange_uid": r.exchange_uid,
            "account_mode": r.account_mode,
            "is_active": u.is_active,
        }
        for r, u in rows
    ]


def validate_sub_account_binding(
    db: Session,
    user_id: int,
    exchange: str,
    *,
    sub_api_key: str,
    sub_api_secret: str,
    sub_passphrase: str = "",
    master_api_key: str,
    master_api_secret: str,
    master_passphrase: str = "",
    master_exchange_uid: str,
    sub_exchange_uid: str,
) -> dict:
    """Full sub-mode bind validation: master link + sub trading API."""
    ex = parse_exchange(exchange)
    if ex is None:
        return {"valid": False, "message_key": "api.unsupported_exchange"}

    master_uid = _normalize_uid(master_exchange_uid)
    sub_uid = _normalize_uid(sub_exchange_uid)

    if not master_uid:
        return {"valid": False, "message_key": "api.master_uid_required"}
    if not sub_uid:
        return {"valid": False, "message_key": "api.sub_uid_required"}

    if is_master_uid_blocked(db, ex, master_uid):
        return {"valid": False, "message_key": "api.master_uid_blocked"}

    if is_exchange_uid_taken(db, ex, sub_uid, exclude_user_id=user_id):
        return {"valid": False, "message_key": "api.exchange_uid_taken"}

    ok, hint = _sub_belongs_to_master(
        ex, master_uid, sub_uid,
        master_api_key, master_api_secret, master_passphrase, user_id,
    )
    if not ok:
        return {"valid": False, "message_key": hint or "api.sub_not_under_master"}

    # Validate sub trading API (full trading checks)
    sub_result = validate_exchange_api(
        ex, sub_api_key, sub_api_secret, user_id, sub_passphrase,
    )
    if not sub_result.get("valid"):
        sub_result["message_key"] = sub_result.get("message_key") or "api.sub_api_invalid"
        return sub_result

    sub_result["account_mode"] = "sub"
    sub_result["exchange_uid"] = sub_uid
    sub_result["master_exchange_uid"] = master_uid
    sub_result["exchange"] = ex
    return sub_result


def validate_master_account_binding(
    db: Session,
    user_id: int,
    exchange: str,
    api_key: str,
    api_secret: str,
    passphrase: str = "",
    master_exchange_uid: str | None = None,
) -> dict:
    """Master-only bind: validate trading API and record exchange UID."""
    ex = parse_exchange(exchange)
    if ex is None:
        return {"valid": False, "message_key": "api.unsupported_exchange"}

    result = validate_exchange_api(ex, api_key, api_secret, user_id, passphrase)
    if not result.get("valid"):
        return result

    client = _master_client(ex, api_key, api_secret, passphrase, user_id)
    resolved_uid = None
    if client and hasattr(client, "get_exchange_uid"):
        resolved_uid = client.get_exchange_uid()

    uid = _normalize_uid(master_exchange_uid) or _normalize_uid(resolved_uid)
    if not uid:
        return {"valid": False, "message_key": "api.master_uid_required"}

    if resolved_uid and master_exchange_uid and _normalize_uid(master_exchange_uid) != resolved_uid:
        return {"valid": False, "message_key": "api.master_uid_mismatch"}

    if is_master_uid_blocked(db, ex, uid):
        return {"valid": False, "message_key": "api.master_uid_blocked"}

    if is_exchange_uid_taken(db, ex, uid, exclude_user_id=user_id):
        return {"valid": False, "message_key": "api.exchange_uid_taken"}

    result["account_mode"] = "master"
    result["exchange_uid"] = uid
    result["master_exchange_uid"] = uid
    result["exchange"] = ex
    return result
