"""DingTalk once-per-event / cooldown gate (all exchanges).

Prevents monitor-loop spam: same important action must not re-broadcast every tick.
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

# Lifetime events: push at most once per fingerprint (TTL)
ONCE_TTL_SEC = 6 * 3600

# User rule: same behavior → at most once per 20s (default)
DEFAULT_COOLDOWN_SEC = 20.0

# Longer cooldowns for noisy heal/check types
COOLDOWN_SEC: dict[str, float] = {
    "POSITION_RECONCILE": 180.0,
    "DEFENSE_HEAL_FAIL": 120.0,
    "CLOSE_FAIL": 60.0,
    "POSITION_QTY_CHANGE": 60.0,
    "MANUAL_ADJUST": 60.0,
    "ADJUST": 60.0,
    "TRAIL": 90.0,
    "UPDATE_SL": 60.0,
    "UPDATE_TP": 60.0,
    "ADVERSE_SL_MISALIGN": 90.0,
    "IDLE_WATCH": 300.0,
    "CAP_ALIGN": 120.0,
    "CAP_ALIGN_BLOCKED": 120.0,
    "CAP_ALIGN_FAIL": 60.0,
    "FALSE_FLAT": 90.0,
    "FLIP_CLEAN": 20.0,
    "TP_ORPHAN_PURGE": 90.0,
    "MANUAL_FLAT_TP_PURGE": 90.0,
    "DEFENSE": 60.0,
    # Rate-limit / -1003 flaps must not DingTalk-spam
    "EXCHANGE_QUERY_FAIL": 900.0,
    "EXCHANGE_QUERY_OK": 900.0,
}

# Always once-per-fingerprint (no re-push until TTL)
ONCE_TYPES = frozenset({
    "OPEN",
    "CLOSE",
    "CLOSE_TP3",
    "CLOSE_PROTECT",
    "CLOSE_STOPLOSS",
    "CLOSE_ATTRIBUTION",
    "TP_FILLED",
    "TP_FILL",
    "TP_SKIP_REHANG",
    "RADAR_ARM",
    "RADAR_REVOKE",
    "ADVERSE_SL",
    "ADVERSE_SL_DISARM",
    "ADVERSE_SL_HIT",
    "SAME_DIR_TP_REFRESH",
    "SAME_DIR_REOPEN",
    "PYRAMID",
    "PROFIT_ADD",
    "STARTUP",
    "STARTUP_FAIL",
    "FORCE_ALIGN",
    "POSITION_SIDE_FLIP",
    "NOTIONAL_CAP",
    "INSUFFICIENT_BALANCE",
})

_lock = threading.RLock()
# fingerprint -> last_sent_ts
_sent: dict[str, float] = {}


def reset_dingtalk_dedupe_for_tests() -> None:
    with _lock:
        _sent.clear()


def _round_num(v: Any, nd: int = 4) -> str:
    try:
        return f"{float(v):.{nd}f}"
    except (TypeError, ValueError):
        return str(v)


def build_alert_fingerprint(
    user_id: int,
    alert_type: str,
    title: str,
    message: str,
    detail: dict | None,
) -> str:
    d = detail or {}
    at = str(alert_type or "").upper()
    parts = [
        str(user_id),
        str(d.get("exchange") or d.get("exchange_id") or ""),
        str(d.get("canonical_symbol") or d.get("symbol") or ""),
        at,
        str(title or "")[:80],
    ]
    for key in (
        "level",
        "side",
        "change_type",
        "reason",
        "skip_reason",
        "entry_type",
        "stage",
    ):
        if d.get(key) is not None and d.get(key) != "":
            parts.append(f"{key}={d.get(key)}")
    if d.get("old_qty") is not None:
        parts.append(f"oq={_round_num(d.get('old_qty'))}")
    if d.get("new_qty") is not None:
        parts.append(f"nq={_round_num(d.get('new_qty'))}")
    if d.get("entry") is not None:
        parts.append(f"entry={_round_num(d.get('entry'), 2)}")
    if d.get("qty") is not None and at in ("OPEN", "PYRAMID", "PROFIT_ADD"):
        parts.append(f"qty={_round_num(d.get('qty'))}")
    # Ban/error text changes every tick — do not fingerprint it for query flaps
    if at not in ("EXCHANGE_QUERY_FAIL", "EXCHANGE_QUERY_OK"):
        msg_bit = hashlib.sha1(str(message or "").encode("utf-8", errors="ignore")).hexdigest()[:10]
        parts.append(msg_bit)
    raw = "|".join(parts)
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()


def allow_trading_dingtalk(
    user_id: int,
    alert_type: str,
    title: str,
    message: str,
    detail: dict | None = None,
) -> bool:
    """
    Return True if this trading alert may be pushed to DingTalk.
    Important actions: once per fingerprint. Others: default 20s cooldown.
    """
    at = str(alert_type or "").upper()
    fp = build_alert_fingerprint(user_id, at, title, message, detail)
    now = time.time()
    ttl = ONCE_TTL_SEC if at in ONCE_TYPES else float(COOLDOWN_SEC.get(at, DEFAULT_COOLDOWN_SEC))

    with _lock:
        if len(_sent) > 4000:
            cutoff = now - ONCE_TTL_SEC
            stale = [k for k, ts in _sent.items() if ts < cutoff]
            for k in stale:
                _sent.pop(k, None)

        last = _sent.get(fp)
        if last is not None and (now - last) < ttl:
            logger.info(
                "[DingTalkDedupe] suppress type=%s user=%s age=%.1fs ttl=%.0fs",
                at, user_id, now - last, ttl,
            )
            return False
        _sent[fp] = now
        return True
