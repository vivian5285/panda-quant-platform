"""Background schedulers: settlement cycle scan + deposit monitor."""
from __future__ import annotations

import logging
import threading
import time

from app.config import get_settings
from app.database import SessionLocal
from app.services.settlement import run_scheduled_settlements, run_awaiting_flat_settlements
from app.services.deposit_monitor import run_deposit_monitor_once
from app.services.deposit_sweep import run_deposit_sweep_once
from app.services.settlement_reminder import send_daily_settlement_reminders

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


def _sweep_loop():
    interval = max(600, getattr(settings, "DEPOSIT_SWEEP_INTERVAL_SEC", 3600))
    logger.info("[Scheduler] deposit sweep every %ss", interval)
    while not _stop.is_set():
        try:
            stats = run_deposit_sweep_once()
            if stats.get("swept") or stats.get("failed"):
                logger.info("[Scheduler] deposit sweep: %s", stats)
        except Exception as e:
            logger.exception("[Scheduler] deposit sweep failed: %s", e)
        _stop.wait(interval)


def _awaiting_flat_loop():
    interval = max(120, getattr(settings, "SETTLEMENT_AWAITING_FLAT_SCAN_SEC", 300))
    logger.info("[Scheduler] awaiting-flat settlement scan every %ss", interval)
    while not _stop.is_set():
        db = SessionLocal()
        try:
            created = run_awaiting_flat_settlements(db)
            if created:
                logger.info("[Scheduler] awaiting-flat billed %s settlement(s)", len(created))
        except Exception as e:
            logger.exception("[Scheduler] awaiting-flat scan failed: %s", e)
        finally:
            db.close()
        _stop.wait(interval)


def _settlement_reminder_loop():
    interval = max(3600, getattr(settings, "SETTLEMENT_REMINDER_INTERVAL_SEC", 86400))
    logger.info("[Scheduler] settlement reminder every %ss", interval)
    while not _stop.is_set():
        db = SessionLocal()
        try:
            stats = send_daily_settlement_reminders(db)
            if stats.get("notified"):
                logger.info("[Scheduler] settlement reminders: %s", stats)
        except Exception as e:
            logger.exception("[Scheduler] settlement reminder failed: %s", e)
        finally:
            db.close()
        _stop.wait(interval)


def _log_retention_loop():
    interval = max(3600, int(getattr(settings, "LOG_RETENTION_INTERVAL_SEC", 86400) or 86400))
    logger.info("[Scheduler] log retention every %ss (keep %sd)", interval, getattr(settings, "LOG_RETENTION_DAYS", 30))
    # First run shortly after boot so ops see effect without waiting a day
    _stop.wait(120)
    while not _stop.is_set():
        db = SessionLocal()
        try:
            from app.services.log_retention import purge_old_logs

            stats = purge_old_logs(db)
            if any(isinstance(v, int) and v > 0 for v in stats.values()):
                logger.info("[Scheduler] log retention: %s", stats)
        except Exception as e:
            logger.exception("[Scheduler] log retention failed: %s", e)
        finally:
            db.close()
        _stop.wait(interval)


def start_background_schedulers():
    if not settings.ENABLE_BACKGROUND_SCHEDULERS:
        logger.info("[Scheduler] background schedulers disabled")
        return
    threading.Thread(target=_settlement_loop, daemon=True, name="settlement-scan").start()
    threading.Thread(target=_awaiting_flat_loop, daemon=True, name="awaiting-flat-scan").start()
    threading.Thread(target=_settlement_reminder_loop, daemon=True, name="settlement-reminder").start()
    threading.Thread(target=_deposit_loop, daemon=True, name="deposit-monitor").start()
    threading.Thread(target=_sweep_loop, daemon=True, name="deposit-sweep").start()
    threading.Thread(target=_log_retention_loop, daemon=True, name="log-retention").start()


def stop_background_schedulers():
    _stop.set()
