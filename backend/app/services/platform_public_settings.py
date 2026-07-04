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
