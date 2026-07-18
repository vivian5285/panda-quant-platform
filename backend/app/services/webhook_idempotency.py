"""Webhook signal deduplication (TV retries / duplicate alerts).

Prefer TradingView bar_index+seq keys (24h TTL) when present; otherwise
content hash with short TTL.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.symbol_precision import round_price

logger = logging.getLogger(__name__)
settings = get_settings()

IDEMPOTENCY_TTL_SEC = 120
SEQ_IDEMPOTENCY_TTL_SEC = 86400


def _seq_action_token(action: str) -> str:
    """Normalize action for seq idempotency (OPEN/LONG/SHORT share open family)."""
    a = str(action or "").upper().strip()
    if a in ("LONG", "SHORT", "BUY", "SELL") or a.startswith("OPEN"):
        return f"OPEN_{a}" if a in ("LONG", "SHORT", "BUY", "SELL") else a
    if a.startswith("CLOSE"):
        return a
    return a or "UNKNOWN"


def compute_fingerprint(payload: dict) -> str:
    explicit = (
        str(payload.get("idempotency_key") or payload.get("signal_id") or "").strip()
    )
    if explicit:
        return f"id:{explicit}"

    bi = payload.get("bar_index")
    seq = payload.get("seq")
    action = str(payload.get("action", "")).upper()
    if bi is not None and seq is not None:
        try:
            bi_i = int(bi)
            seq_i = int(seq)
        except (TypeError, ValueError):
            bi_i = seq_i = None
        if bi_i is not None and seq_i is not None and seq_i >= 1:
            from app.core.symbol_registry import extract_payload_symbol

            symbol = extract_payload_symbol(payload, require=False) or "UNKNOWN"
            # V1.6.10: {symbol}_{bar}_{seq}_{action}_{price}_{tps}
            # Same bar may recycle seq (open→close→open = 1-2-1). Action alone is not
            # enough when both opens are LONG — include price/TP so the second open
            # is not treated as a TV retry of the first.
            act = _seq_action_token(action)
            px = round_price(payload.get("price") or 0)
            tps = (
                f"{round_price(payload.get('tv_tp1') or 0)}_"
                f"{round_price(payload.get('tv_tp2') or 0)}_"
                f"{round_price(payload.get('tv_tp3') or 0)}"
            )
            return f"seq:{symbol}_{bi_i}_{seq_i}_{act}_{px}_{tps}"

    from app.core.symbol_registry import extract_payload_symbol

    core = {
        "action": action,
        "symbol": extract_payload_symbol(payload, require=False) or "UNKNOWN",
        "regime": payload.get("regime"),
        "price": round_price(payload.get("price") or 0),
        "atr": round(float(payload.get("atr") or 0), 4),
        "tv_tp1": round_price(payload.get("tv_tp1") or 0),
        "tv_tp2": round_price(payload.get("tv_tp2") or 0),
        "tv_tp3": round_price(payload.get("tv_tp3") or 0),
        "reason": str(payload.get("reason") or "")[:200],
    }
    if payload.get("side"):
        core["side"] = str(payload.get("side")).upper().strip()
    raw = json.dumps(core, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _ttl_seconds(fingerprint: str | None = None) -> int:
    if fingerprint and str(fingerprint).startswith("seq:"):
        return max(
            3600,
            int(getattr(settings, "WEBHOOK_SEQ_IDEMPOTENCY_TTL_SEC", SEQ_IDEMPOTENCY_TTL_SEC)),
        )
    return max(30, int(getattr(settings, "WEBHOOK_IDEMPOTENCY_TTL_SEC", IDEMPOTENCY_TTL_SEC)))


def try_acquire(db: Session, fingerprint: str) -> tuple[bool, int | None]:
    """
    Attempt to claim fingerprint for processing.
    Returns (acquired, existing_dispatch_log_id).
    """
    ttl = _ttl_seconds(fingerprint)
    from app.services.redis_client import get_redis

    redis = get_redis()
    if redis:
        try:
            key = f"webhook:idempotency:{fingerprint}"
            existing = redis.get(key)
            if existing:
                parts = str(existing).split(":", 1)
                dispatch_id = int(parts[0]) if parts and parts[0].isdigit() else None
                return False, dispatch_id
            if redis.set(key, "pending", nx=True, ex=ttl):
                return True, None
            existing = redis.get(key)
            if existing and existing != "pending":
                parts = str(existing).split(":", 1)
                return False, int(parts[0]) if parts[0].isdigit() else None
            return False, None
        except Exception as e:
            logger.warning("Redis idempotency failed, falling back to DB: %s", e)

    from app.models.platform import WebhookIdempotencyKey

    cutoff = datetime.utcnow() - timedelta(seconds=ttl)
    db.query(WebhookIdempotencyKey).filter(WebhookIdempotencyKey.created_at < cutoff).delete()
    db.commit()

    row = db.query(WebhookIdempotencyKey).filter(
        WebhookIdempotencyKey.fingerprint == fingerprint,
        WebhookIdempotencyKey.created_at >= cutoff,
    ).first()
    if row:
        return False, row.dispatch_log_id

    db.add(WebhookIdempotencyKey(fingerprint=fingerprint))
    try:
        db.commit()
        return True, None
    except Exception:
        db.rollback()
        row = db.query(WebhookIdempotencyKey).filter(
            WebhookIdempotencyKey.fingerprint == fingerprint,
        ).first()
        return False, row.dispatch_log_id if row else None


def finalize(db: Session, fingerprint: str, dispatch_log_id: int) -> None:
    from app.services.redis_client import get_redis
    from app.models.platform import WebhookIdempotencyKey

    ttl = _ttl_seconds(fingerprint)
    redis = get_redis()
    if redis:
        try:
            redis.setex(f"webhook:idempotency:{fingerprint}", ttl, str(dispatch_log_id))
        except Exception:
            pass

    row = db.query(WebhookIdempotencyKey).filter(
        WebhookIdempotencyKey.fingerprint == fingerprint,
    ).first()
    if row:
        row.dispatch_log_id = dispatch_log_id
        db.commit()
