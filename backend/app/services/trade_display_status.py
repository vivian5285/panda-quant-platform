"""Resolve user-facing execution status — align with live book, not stray warning logs."""
from __future__ import annotations

# Non-fatal supervisor events that must not mark a successful open as「失败」
NON_FATAL_EVENT_TYPES = frozenset({
    "CAP_ALIGN",
    "CAP_ALIGN_BLOCKED",
    "CAP_ALIGN_FAIL",
    "CAP_ALIGN_OVERTRIM",
    "WARN",
    "DEFENSE",
    "DEFENSE_HEAL",
    "DEFENSE_HEAL_OK",
    "FLAT_UNCONFIRMED",
    "SIGNAL",
    "ADVERSE_SL",
    "ADVERSE_SL_REPAIR",
})

CAP_GUARD_ERROR_MARKERS = (
    "档位纠偏中止",
    "档位额度超标但减仓失败",
    "叠仓纠偏",
)


def _is_fatal_error_log(event_type: str | None, message: str | None) -> bool:
    et = (event_type or "").upper()
    if et != "ERROR":
        return False
    msg = message or ""
    if any(marker in msg for marker in CAP_GUARD_ERROR_MARKERS):
        return False
    return True


def resolve_trade_display_status(
    trade_status: str,
    logs: list[dict] | None = None,
) -> str:
    """
    Execution detail badge:
    - ``open`` trade → 持仓中 (wins over ancillary ERROR logs)
    - ``closed`` → 已平仓 unless only fatal errors without OPEN/CLOSE
    - fatal ERROR without successful open → 失败
    """
    status = (trade_status or "").lower()
    entries = logs or []
    has_open = any((l.get("event_type") or "").upper() == "OPEN" for l in entries)
    has_close = any((l.get("event_type") or "").upper() == "CLOSE" for l in entries)
    fatal_errors = [
        l for l in entries
        if _is_fatal_error_log(l.get("event_type"), l.get("message"))
    ]

    if status == "open":
        return "open"

    if any(
        (l.get("event_type") or "").upper() == "ADJUST"
        or "风控" in (l.get("message") or "")
        for l in entries
    ):
        return "risk"

    if status == "closed" or has_close:
        return "closed"

    if fatal_errors and not has_open:
        return "error"

    if has_open:
        return "open"

    return "closed" if status == "closed" else "error" if fatal_errors else "closed"
