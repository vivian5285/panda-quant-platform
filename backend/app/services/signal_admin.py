"""Admin TV signal templates and dispatch logging."""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.platform import SignalDispatchLog, TvSignalTemplate
from app.core.symbol_precision import normalize_entry_payload
from app.services.dispatch_persistence import finalize_dispatch_log, save_dispatch_user_results


DEFAULT_TEMPLATE = {
    "strategy_id": "gemini_eth_v3",
    "action": "LONG",
    "regime": 1,
    "atr": 12.5,
    "price": 3500,
    "tv_tp1": 3600,
    "tv_tp2": 3700,
    "tv_tp3": 3800,
    "reason": "AI high confidence",
}


def seed_default_template(db: Session) -> None:
    if db.query(TvSignalTemplate).count() > 0:
        return
    db.add(
        TvSignalTemplate(
            name="ETH Trend Long",
            description="Default TradingView alert format for ETHUSDT long entries",
            payload_json=json.dumps(DEFAULT_TEMPLATE),
            enabled=True,
        )
    )
    db.commit()


def template_to_dict(row: TvSignalTemplate) -> dict:
    try:
        payload = json.loads(row.payload_json or "{}")
    except json.JSONDecodeError:
        payload = {}
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "payload": payload,
        "enabled": row.enabled,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def log_dispatch(
    db: Session,
    *,
    action: str,
    payload: dict,
    dispatched: int,
    errors: int,
    status: str,
    source: str = "webhook",
    template_id: int | None = None,
    skipped: int = 0,
) -> SignalDispatchLog:
    row = SignalDispatchLog(
        template_id=template_id,
        action=action,
        payload_json=json.dumps(payload),
        dispatched_count=dispatched,
        error_count=errors,
        skipped_count=skipped,
        status=status,
        source=source,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def run_signal_dispatch(
    db: Session,
    payload: dict,
    *,
    source: str = "webhook",
    template_id: int | None = None,
) -> tuple[SignalDispatchLog, dict]:
    """Dispatch signal to all eligible users and persist per-user results."""
    from app.services.dispatcher import signal_dispatcher

    action = str(payload.get("action", "UNKNOWN")).upper()
    if action in ("LONG", "SHORT"):
        payload = normalize_entry_payload(payload)
    row = log_dispatch(
        db,
        action=action,
        payload=payload,
        dispatched=0,
        errors=0,
        skipped=0,
        status="processing",
        source=source,
        template_id=template_id,
    )
    result = signal_dispatcher.dispatch(payload)
    results = result.get("results") or []
    save_dispatch_user_results(db, row.id, results)
    reason = result.get("reason")
    status = reason if reason in ("global_pause", "all_users_paused") else None
    finalize_dispatch_log(db, row, results, status=status or None)
    return row, result


def dispatch_payload(payload: dict) -> dict:
    """Legacy entry — dispatch without DB persistence (prefer run_signal_dispatch)."""
    from app.services.dispatcher import signal_dispatcher

    return signal_dispatcher.dispatch(payload)


def build_test_payload(template_payload: dict | None = None) -> dict:
    payload = dict(template_payload or DEFAULT_TEMPLATE)
    payload["secret"] = get_settings().WEBHOOK_SECRET
    return payload


def record_webhook_hit(action: str) -> None:
    from app.services.redis_client import get_redis

    redis = get_redis()
    if not redis:
        return
    try:
        redis.incr("stats:webhook:total")
        redis.set("stats:webhook:last_at", datetime.utcnow().isoformat())
        redis.set("stats:webhook:last_action", action)
    except Exception:
        pass
