"""Master + sub exchange account binding validation and registry."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core.binance_client import BinanceClient
from app.core.exchange_factory import exchange_requires_passphrase, parse_exchange
from app.core.okx_client import OkxClient
from app.models import ExchangeAccountRegistry, ExchangeSubAccountFiling, User
from app.services.api_validation import validate_exchange_api
from app.services.credit_control import is_filed_sub_uid_taken, is_master_uid_blocked

logger = logging.getLogger(__name__)

STRICT_SUB_EXCHANGES = frozenset({"binance", "okx"})
RELAXED_SUB_EXCHANGES = frozenset({"gate", "deepcoin"})


def _normalize_uid(val: str | None) -> str:
    return (val or "").strip()


def _trading_client(exchange: str, api_key: str, api_secret: str, passphrase: str, user_id: int):
    ex = parse_exchange(exchange)
    if ex == "binance":
        return BinanceClient(api_key, api_secret, user_id)
    if ex == "okx":
        return OkxClient(api_key, api_secret, passphrase, user_id)
    return None


def probe_trading_api_role(
    exchange: str,
    api_key: str,
    api_secret: str,
    passphrase: str = "",
    user_id: int = 0,
) -> dict:
    """Detect master vs sub trading API (Binance/OKX); Gate/Deepcoin return unknown."""
    ex = parse_exchange(exchange)
    if ex is None:
        return {"role": "unknown", "resolved_uid": None}
    client = _trading_client(ex, api_key, api_secret, passphrase, user_id)
    if client and hasattr(client, "probe_trading_api_role"):
        return client.probe_trading_api_role()
    if client and hasattr(client, "get_exchange_uid"):
        return {"role": "unknown", "resolved_uid": client.get_exchange_uid()}
    return {"role": "unknown", "resolved_uid": None}


def scan_master_sub_accounts(
    exchange: str,
    master_api_key: str,
    master_api_secret: str,
    master_passphrase: str = "",
    user_id: int = 0,
    *,
    require_sub_list: bool = False,
) -> dict:
    """
    Scan master API for UID + all sub-accounts (备案).
    On Binance/OKX, require_sub_list=True enforces sub-account query permission.
    """
    ex = parse_exchange(exchange)
    if ex is None:
        return {"ok": False, "message_key": "api.unsupported_exchange"}

    client = _master_client(ex, master_api_key, master_api_secret, master_passphrase, user_id)
    if not client:
        if ex in RELAXED_SUB_EXCHANGES:
            conn = validate_exchange_api(
                ex, master_api_key, master_api_secret, user_id, master_passphrase,
                skip_trading_checks=True,
            )
            return {
                "ok": bool(conn.get("valid")),
                "uid": None,
                "sub_accounts": [],
                "strict": False,
                "relaxed": True,
            }
        return {"ok": False, "message_key": "api.unsupported_exchange"}

    resolved_uid = client.get_exchange_uid() if hasattr(client, "get_exchange_uid") else None
    role_info = {}
    if hasattr(client, "probe_trading_api_role"):
        role_info = client.probe_trading_api_role()
        if not resolved_uid:
            resolved_uid = role_info.get("resolved_uid")

    subs = client.list_sub_accounts() if hasattr(client, "list_sub_accounts") else []
    can_list = bool(role_info.get("can_list_subs")) or (ex in STRICT_SUB_EXCHANGES and role_info.get("role") == "master")

    if ex in STRICT_SUB_EXCHANGES and require_sub_list:
        if role_info.get("role") == "sub" and role_info.get("confirmed_sub"):
            return {
                "ok": False,
                "message_key": "api.sub_api_in_master_mode",
                "uid": resolved_uid,
                "sub_accounts": [],
            }
        if not can_list and not subs:
            return {
                "ok": False,
                "message_key": "api.master_sub_perm_required",
                "uid": resolved_uid,
                "sub_accounts": [],
            }

    return {
        "ok": True,
        "uid": resolved_uid,
        "sub_accounts": subs,
        "strict": ex in STRICT_SUB_EXCHANGES,
        "can_list_subs": can_list or bool(subs),
    }


def file_exchange_sub_accounts(
    db: Session,
    user_id: int,
    exchange: str,
    master_uid: str,
    sub_accounts: list[dict],
) -> int:
    """备案主账户下扫描到的全部子 UID；返回备案条数。"""
    master = _normalize_uid(master_uid)
    if not master:
        return 0
    db.query(ExchangeSubAccountFiling).filter(
        ExchangeSubAccountFiling.user_id == user_id,
        ExchangeSubAccountFiling.exchange == exchange,
        ExchangeSubAccountFiling.is_active.is_(True),
    ).update({"is_active": False})

    count = 0
    for row in sub_accounts or []:
        sub_uid = _normalize_uid(str(row.get("uid") or ""))
        if not sub_uid:
            continue
        db.add(
            ExchangeSubAccountFiling(
                user_id=user_id,
                exchange=exchange,
                master_exchange_uid=master,
                sub_exchange_uid=sub_uid,
                sub_label=str(row.get("label") or sub_uid)[:128],
                is_active=True,
            )
        )
        count += 1
    return count


def deactivate_sub_account_filings(db: Session, user_id: int) -> None:
    db.query(ExchangeSubAccountFiling).filter(
        ExchangeSubAccountFiling.user_id == user_id,
        ExchangeSubAccountFiling.is_active.is_(True),
    ).update({"is_active": False})


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


def _merge_trading_result(base: dict, overlay: dict) -> dict:
    """Merge validation layers without letting a failed overlay keep a success message_key."""
    skip = frozenset({"valid", "message_key"})
    merged = {k: v for k, v in base.items() if k not in skip}
    merged.update({k: v for k, v in overlay.items() if k not in skip})
    merged["valid"] = bool(overlay.get("valid", base.get("valid")))
    if "message_key" in overlay:
        merged["message_key"] = overlay["message_key"]
    elif "message_key" in base:
        merged["message_key"] = base["message_key"]
    return merged


def _master_scan_failure(trading_result: dict, scan: dict, message_key: str) -> dict:
    return _merge_trading_result(
        trading_result,
        {
            "valid": False,
            "message_key": message_key,
            "exchange_uid": scan.get("uid"),
            "checks": trading_result.get("checks") or [],
        },
    )


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

    if is_filed_sub_uid_taken(db, ex, sub_uid, exclude_user_id=user_id):
        return {"valid": False, "message_key": "api.exchange_uid_taken"}

    scan = scan_master_sub_accounts(
        ex, master_api_key, master_api_secret, master_passphrase, user_id,
        require_sub_list=True,
    )
    if not scan.get("ok"):
        return {"valid": False, "message_key": scan.get("message_key") or "api.master_connect_failed"}

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
    sub_result["discovered_sub_accounts"] = scan.get("sub_accounts") or []
    sub_result["filed_sub_count"] = len(sub_result["discovered_sub_accounts"])
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
    """Master bind: trading API + mandatory master UID scan/filing of all sub-accounts."""
    ex = parse_exchange(exchange)
    if ex is None:
        return {"valid": False, "message_key": "api.unsupported_exchange"}

    result = validate_exchange_api(ex, api_key, api_secret, user_id, passphrase)
    if not result.get("valid"):
        return result

    scan = scan_master_sub_accounts(
        ex, api_key, api_secret, passphrase, user_id, require_sub_list=True,
    )
    sub_scan_warning_key: str | None = None
    if not scan.get("ok"):
        scan_message_key = scan.get("message_key") or "api.master_sub_perm_required"

        # Trading APIs often lack sub-account list permission; retry relaxed scan for UID.
        relaxed = scan_master_sub_accounts(
            ex, api_key, api_secret, passphrase, user_id, require_sub_list=False,
        )
        if relaxed.get("ok"):
            scan = relaxed
            if scan_message_key in ("api.master_sub_perm_required", "api.sub_api_in_master_mode"):
                sub_scan_warning_key = "api.master_sub_perm_recommended"
        else:
            return _master_scan_failure(result, scan, scan_message_key)

    resolved_uid = scan.get("uid")
    uid = _normalize_uid(master_exchange_uid) or _normalize_uid(resolved_uid)
    if not uid:
        return {"valid": False, "message_key": "api.master_uid_required"}

    if resolved_uid and master_exchange_uid and _normalize_uid(master_exchange_uid) != str(resolved_uid):
        return {"valid": False, "message_key": "api.master_uid_mismatch"}

    if is_master_uid_blocked(db, ex, uid):
        return {"valid": False, "message_key": "api.master_uid_blocked"}

    if is_exchange_uid_taken(db, ex, uid, exclude_user_id=user_id):
        return {"valid": False, "message_key": "api.exchange_uid_taken"}

    discovered = scan.get("sub_accounts") or []
    result["account_mode"] = "master"
    result["exchange_uid"] = uid
    result["master_exchange_uid"] = uid
    result["exchange"] = ex
    result["discovered_sub_accounts"] = discovered
    result["filed_sub_count"] = len(discovered)
    if sub_scan_warning_key:
        result["sub_scan_warning_key"] = sub_scan_warning_key
    return result
