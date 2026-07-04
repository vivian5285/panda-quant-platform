"""Admin-configurable public platform settings: open exchanges and support Telegram."""

from __future__ import annotations

from app.services.platform_runtime import read_runtime_file, write_runtime_file

ALL_EXCHANGES = ("binance", "okx", "gate", "deepcoin")
DEFAULT_ENABLED = ("binance",)


def _normalize_exchange(val: str) -> str | None:
    v = (val or "").strip().lower()
    if v == "gateio":
        v = "gate"
    return v if v in ALL_EXCHANGES else None


def get_platform_public_settings() -> dict:
    block = read_runtime_file().get("platform_public") or {}
    raw_enabled = block.get("enabled_exchanges")
    if isinstance(raw_enabled, list) and raw_enabled:
        enabled = [e for e in (_normalize_exchange(x) for x in raw_enabled) if e]
    else:
        enabled = list(DEFAULT_ENABLED)
    if not enabled:
        enabled = list(DEFAULT_ENABLED)
    telegram = (block.get("support_telegram") or "").strip()
    return {
        "enabled_exchanges": enabled,
        "all_exchanges": list(ALL_EXCHANGES),
        "support_telegram": telegram,
    }


def is_exchange_enabled(exchange: str) -> bool:
    ex = _normalize_exchange(exchange)
    if not ex:
        return False
    return ex in get_platform_public_settings()["enabled_exchanges"]


def user_exchange_trading_allowed(user) -> bool:
    """True when user's bound exchange is admin-enabled for托管交易."""
    from app.core.exchange_factory import user_exchange

    return is_exchange_enabled(user_exchange(user))


def sync_supervisors_for_enabled_exchanges() -> dict:
    """Apply admin exchange policy: stop disabled-exchange托管, start newly enabled."""
    from app.database import SessionLocal
    from app.models import ApiStatus, User
    from app.core.exchange_factory import user_exchange, user_has_api_credentials
    from app.services.dispatcher import supervisor_pool
    from app.services.trade_logger import TradeLogger

    enabled = set(get_platform_public_settings()["enabled_exchanges"])
    db = SessionLocal()
    removed = 0
    added = 0
    try:
        for sup in list(supervisor_pool.get_all()):
            user = db.query(User).filter(User.id == sup.user_id).first()
            if user and user_exchange(user) not in enabled:
                supervisor_pool.remove_user(user.id)
                TradeLogger(db).log_event(
                    user.id,
                    "WARNING",
                    "交易所托管已暂停（平台未开放该交易所）",
                    {"exchange": user_exchange(user), "enabled_exchanges": list(enabled)},
                )
                removed += 1
        db.commit()

        users = (
            db.query(User)
            .filter(
                User.is_active.is_(True),
                User.api_status == ApiStatus.ACTIVE.value,
                User.api_key_enc.isnot(None),
            )
            .all()
        )
        for user in users:
            if not user_has_api_credentials(user):
                continue
            if user_exchange(user) not in enabled:
                continue
            if supervisor_pool.get(user.id) is None:
                audit = supervisor_pool.add_user(user, db=db)
                if audit and not audit.get("error"):
                    added += 1
    finally:
        db.close()
    return {"removed_supervisors": removed, "added_supervisors": added}


def update_platform_public_settings(
    *,
    enabled_exchanges: list[str] | None = None,
    support_telegram: str | None = None,
) -> dict:
    data = read_runtime_file()
    block = dict(data.get("platform_public") or {})

    if enabled_exchanges is not None:
        normalized = []
        for item in enabled_exchanges:
            ex = _normalize_exchange(item)
            if ex and ex not in normalized:
                normalized.append(ex)
        if not normalized:
            raise ValueError("At least one exchange must remain enabled")
        block["enabled_exchanges"] = normalized

    if support_telegram is not None:
        block["support_telegram"] = (support_telegram or "").strip()[:128]

    data["platform_public"] = block
    write_runtime_file(data)
    return get_platform_public_settings()
