"""Webhook access + v6.5.6 signal validation (all exchanges)."""

import logging
import os
from flask import request

from app.config import get_settings
from app.utils.rate_limit import rate_limiter

logger = logging.getLogger(__name__)
settings = get_settings()

# v6.5.6 final: TV only sends open + reverse-protect; VPS owns TP/SL fills
VALID_ACTIONS = frozenset({
    "LONG",
    "SHORT",
    "CLOSE_QUICK_EXIT",
    "CLOSE_RSI_EXIT",
})
ENTRY_ACTIONS = frozenset({"LONG", "SHORT"})

# Legacy TV reconcile actions — ignored (VPS order monitor owns TP/SL)
LEGACY_TV_RECONCILE_ACTIONS = frozenset({
    "CLOSE_TP",
    "CLOSE_TRAIL",
    "CLOSE_SL_INITIAL",
    "CLOSE_SL_BREAKEVEN",
})
# Keep alias for old call sites; empty = no TV-driven reconcile
RECONCILE_ONLY_ACTIONS = frozenset()

# TV must force market flatten (radar cannot know multi-TF / RSI exit)
FORCE_FLAT_ACTIONS = frozenset({
    "CLOSE_QUICK_EXIT",
    "CLOSE_RSI_EXIT",
})


def is_close_signal(action: str) -> bool:
    act = str(action or "").upper().strip()
    return act in FORCE_FLAT_ACTIONS or act.startswith("CLOSE")


def is_reconcile_only_close(action: str) -> bool:
    """Deprecated: TV no longer sends reconcile closes; always False."""
    return False


def is_legacy_tv_reconcile(action: str) -> bool:
    return str(action or "").upper().strip() in LEGACY_TV_RECONCILE_ACTIONS


def is_force_flat_close(action: str) -> bool:
    return str(action or "").upper().strip() in FORCE_FLAT_ACTIONS


def _client_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def check_webhook_access() -> tuple[bool, str, int]:
    ip = _client_ip()
    allowed = (os.getenv("WEBHOOK_ALLOWED_IPS") or settings.WEBHOOK_ALLOWED_IPS or "").strip()
    if allowed:
        whitelist = {x.strip() for x in allowed.split(",") if x.strip()}
        if ip not in whitelist:
            logger.warning("[Webhook] Blocked IP: %s", ip)
            return False, "IP not allowed", 403

    limit = int(os.getenv("WEBHOOK_RATE_LIMIT_PER_MIN", settings.WEBHOOK_RATE_LIMIT_PER_MIN))
    if not rate_limiter.allow(f"webhook:{ip}", limit=limit, window_seconds=60):
        logger.warning("[Webhook] Rate limit exceeded: %s", ip)
        return False, "Rate limit exceeded", 429

    return True, "", 200


def validate_signal_payload(data: dict) -> tuple[bool, str]:
    action = str(data.get("action", "")).upper().strip()
    if not action:
        return False, "Missing action"

    # Legacy CLOSE_TP/TRAIL/SL_* — TV must not send; VPS monitors fills itself
    if action in LEGACY_TV_RECONCILE_ACTIONS:
        return False, f"legacy_ignored:{action}"

    if action not in VALID_ACTIONS:
        return False, f"Unsupported action: {action}"

    from app.core.symbol_registry import extract_payload_symbol

    can = extract_payload_symbol(data, require=True)
    if not can:
        raw = data.get("symbol") or data.get("ticker") or data.get("pair")
        if raw:
            return False, f"Unsupported symbol: {raw}"
        return False, "Missing symbol (ETHUSDT / XAUUSDT required)"

    if action in ENTRY_ACTIONS:
        if data.get("price") is None or float(data.get("price") or 0) <= 0:
            return False, f"Missing required field for {action}: price"
        # Hard SL
        try:
            sl = float(data.get("stop_loss") or data.get("tv_sl") or 0)
            if sl <= 0:
                return False, f"Missing required field for {action}: stop_loss"
        except (TypeError, ValueError):
            return False, "Invalid stop_loss"
        # TP1/TP2 required (limit legs); TP3 reference recommended
        for field, aliases in (
            ("tp1", ("tp1", "tv_tp1")),
            ("tp2", ("tp2", "tv_tp2")),
        ):
            ok = False
            for a in aliases:
                try:
                    if float(data.get(a) or 0) > 0:
                        ok = True
                        break
                except (TypeError, ValueError):
                    return False, f"Invalid {field}"
            if not ok:
                return False, f"Missing required field for {action}: {field}"
        if data.get("atr") is not None:
            try:
                if float(data.get("atr", 0)) <= 0:
                    return False, "atr must be > 0 when provided"
            except (TypeError, ValueError):
                return False, "Invalid atr"

    return True, ""
