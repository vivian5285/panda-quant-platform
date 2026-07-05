import logging
import os
from flask import request

from app.config import get_settings
from app.utils.rate_limit import rate_limiter

logger = logging.getLogger(__name__)
settings = get_settings()

VALID_ACTIONS = frozenset({"LONG", "SHORT", "CLOSE", "CLOSE_PROTECT", "CLOSE_TP3"})
ENTRY_ACTIONS = frozenset({"LONG", "SHORT"})


def is_close_signal(action: str) -> bool:
    """True for TV exit actions (CLOSE / CLOSE_TP3 / CLOSE_PROTECT*)."""
    act = str(action or "").upper().strip()
    return act in ("CLOSE", "CLOSE_TP3") or act.startswith("CLOSE")


def _client_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def check_webhook_access() -> tuple[bool, str, int]:
    """Returns (ok, message, http_status)."""
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

    if action not in VALID_ACTIONS and "CLOSE_PROTECT" not in action:
        return False, f"Unsupported action: {action}"

    if action in ENTRY_ACTIONS:
        for field in ("regime", "atr", "price"):
            if data.get(field) is None:
                return False, f"Missing required field for {action}: {field}"
        for field in ("tv_tp1", "tv_tp2", "tv_tp3"):
            if data.get(field) is None:
                return False, f"Missing required field for {action}: {field}"
        try:
            regime = int(data.get("regime"))
            if regime not in (1, 2, 3, 4):
                return False, "regime must be 1-4"
            if float(data.get("atr", 0)) <= 0:
                return False, "atr must be > 0"
            if float(data.get("price", 0)) <= 0:
                return False, "price must be > 0"
        except (TypeError, ValueError):
            return False, "Invalid numeric fields in payload"

    return True, ""
