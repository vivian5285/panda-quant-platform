"""Persist deposit monitor scan health for admin dashboards."""

from __future__ import annotations

from datetime import datetime, timezone

from app.config import get_settings
from app.services.deposit_secrets import is_deposit_mnemonic_configured
from app.services.platform_runtime import read_runtime_file, write_runtime_file

KEY = "deposit_monitor"
settings = get_settings()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def record_scan_result(stats: dict, error: str | None = None) -> dict:
    data = read_runtime_file()
    prev = data.get(KEY, {})
    consec = int(prev.get("consecutive_errors", 0))
    if error:
        consec += 1
    else:
        consec = 0

    matched_total = int(stats.get("matched_total", 0))
    entry = {
        "last_scan_at": _utc_now_iso(),
        "last_ok": error is None,
        "last_error": error,
        "last_stats": stats,
        "matched_total": matched_total,
        "consecutive_errors": consec,
        "scan_interval_sec": settings.DEPOSIT_SCAN_INTERVAL_SEC,
        "mnemonic_configured": is_deposit_mnemonic_configured(),
        "auto_confirm_enabled": settings.SETTLEMENT_AUTO_CONFIRM,
    }
    data[KEY] = entry
    write_runtime_file(data)
    return entry


def get_deposit_monitor_status() -> dict:
    data = read_runtime_file().get(KEY, {})
    interval = max(60, settings.DEPOSIT_SCAN_INTERVAL_SEC)
    mnemonic_ok = is_deposit_mnemonic_configured()
    last_scan_at = data.get("last_scan_at")
    last_ok = bool(data.get("last_ok", False))
    consec = int(data.get("consecutive_errors", 0))

    stale = False
    if last_scan_at:
        try:
            ts = datetime.fromisoformat(last_scan_at.replace("Z", "+00:00"))
            age_sec = (datetime.now(timezone.utc) - ts).total_seconds()
            stale = age_sec > interval * 2.5
        except Exception:
            stale = True

    if not mnemonic_ok:
        health = "not_configured"
    elif consec >= 2 or (last_scan_at and not last_ok):
        health = "error"
    elif stale:
        health = "stale"
    elif last_scan_at and last_ok:
        health = "healthy"
    else:
        health = "pending"

    return {
        "health": health,
        "last_scan_at": last_scan_at,
        "last_ok": last_ok,
        "last_error": data.get("last_error"),
        "last_stats": data.get("last_stats") or {},
        "matched_total": int(data.get("matched_total", 0)),
        "consecutive_errors": consec,
        "scan_interval_sec": interval,
        "mnemonic_configured": mnemonic_ok,
        "auto_confirm_enabled": settings.SETTLEMENT_AUTO_CONFIRM,
    }
