"""Purge aged TradeLog / webhook / dispatch / admin alert rows (checklist §12.4)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.config import get_settings

logger = logging.getLogger(__name__)


def purge_old_logs(db: Session, *, days: int | None = None) -> dict:
    """Delete rows older than retention window. Returns counts per table."""
    settings = get_settings()
    retain_days = max(1, int(days if days is not None else getattr(settings, "LOG_RETENTION_DAYS", 30) or 30))
    cutoff = datetime.utcnow() - timedelta(days=retain_days)
    counts: dict[str, int] = {"cutoff": cutoff.isoformat() + "Z", "days": retain_days}

    from app.models import TradeLog, AdminAlert
    from app.models.platform import (
        WebhookReceiveLog,
        WebhookIdempotencyKey,
        SignalDispatchUserResult,
        SignalDispatchLog,
    )

    def _delete(model, label: str, col) -> None:
        try:
            n = db.query(model).filter(col < cutoff).delete(synchronize_session=False)
            counts[label] = int(n or 0)
        except Exception as e:
            logger.warning("[LogRetention] delete %s failed: %s", label, e)
            counts[label] = -1

    _delete(TradeLog, "trade_logs", TradeLog.created_at)
    _delete(WebhookReceiveLog, "webhook_receive_logs", WebhookReceiveLog.created_at)
    _delete(WebhookIdempotencyKey, "webhook_idempotency_keys", WebhookIdempotencyKey.created_at)
    _delete(AdminAlert, "admin_alerts", AdminAlert.created_at)
    # Child rows first (no cascade guarantee on all DBs)
    _delete(SignalDispatchUserResult, "signal_dispatch_user_results", SignalDispatchUserResult.created_at)
    _delete(SignalDispatchLog, "signal_dispatch_logs", SignalDispatchLog.created_at)

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.exception("[LogRetention] commit failed: %s", e)
        counts["error"] = str(e)
        return counts

    total = sum(v for k, v in counts.items() if isinstance(v, int) and v > 0)
    if total:
        logger.info("[LogRetention] purged %s rows older than %s days: %s", total, retain_days, counts)
    return counts
