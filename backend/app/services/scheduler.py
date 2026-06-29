"""Background schedulers: settlement cycle scan + deposit monitor."""
from __future__ import annotations

import logging
import threading
import time

from app.config import get_settings
from app.database import SessionLocal
from app.services.settlement import run_scheduled_settlements
from app.services.deposit_monitor import run_deposit_monitor_once

logger = logging.getLogger(__name__)
settings = get_settings()
_stop = threading.Event()


def _settlement_loop():
    interval = max(300, settings.SETTLEMENT_SCAN_INTERVAL_SEC)
    logger.info("[Scheduler] settlement scan every %ss", interval)
    while not _stop.is_set():
        db = SessionLocal()
        try:
            created = run_scheduled_settlements(db)
            if created:
                logger.info("[Scheduler] created %s settlement(s): %s", len(created), [s.id for s in created])
        except Exception as e:
            logger.exception("[Scheduler] settlement scan failed: %s", e)
        finally:
            db.close()
        _stop.wait(interval)


def _deposit_loop():
    interval = max(60, settings.DEPOSIT_SCAN_INTERVAL_SEC)
    logger.info("[Scheduler] deposit monitor every %ss", interval)
    while not _stop.is_set():
        try:
            stats = run_deposit_monitor_once()
            if any(v for k, v in stats.items() if k != "error" and v):
                logger.info("[Scheduler] deposit matches: %s", stats)
        except Exception as e:
            logger.exception("[Scheduler] deposit monitor failed: %s", e)
        _stop.wait(interval)


def start_background_schedulers():
    if not settings.ENABLE_BACKGROUND_SCHEDULERS:
        logger.info("[Scheduler] background schedulers disabled")
        return
    threading.Thread(target=_settlement_loop, daemon=True, name="settlement-scan").start()
    threading.Thread(target=_deposit_loop, daemon=True, name="deposit-monitor").start()


def stop_background_schedulers():
    _stop.set()
