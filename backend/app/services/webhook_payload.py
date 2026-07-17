"""Parse TradingView webhook JSON bodies (with optional repair for common Pine quoting bugs)."""

from __future__ import annotations

import json
import logging
import re

from app.services.tv_signal_enrich import enrich_tv_signal

logger = logging.getLogger(__name__)

# Pine v6.9.30 bug: missing closing quote after side/reason
# Broken:  "side":"LONG,"reason":"xxx,"pnl_pct":
# Fixed:    "side":"LONG","reason":"xxx","pnl_pct":
_PINE_CLOSE_PROTECT_SIDE_REASON = re.compile(
    r'"side":"(LONG|SHORT|NONE),("reason":")([^"]*?)(,"pnl_pct":)'
)
# v6.9.x: missing quote before reason key on CLOSE_STOPLOSS
_PINE_CLOSE_SIDE_REASON_GENERIC = re.compile(
    r'"side":"(LONG|SHORT|NONE),("reason":")([^"]*?)(,"(?:pnl_pct|price)":)'
)
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")


def repair_pine_close_protect_json(raw: str) -> str | None:
    """Repair known malformed CLOSE_* JSON from 万亿战神 v6.9.30–v6.9.75."""
    if not any(x in raw for x in ("CLOSE_PROTECT", "CLOSE_TP3", "CLOSE_STOPLOSS", "CLOSE")):
        return None
    fixed = raw
    n_total = 0
    for pattern in (_PINE_CLOSE_PROTECT_SIDE_REASON, _PINE_CLOSE_SIDE_REASON_GENERIC):
        fixed, n = pattern.subn(r'"side":"\1","reason":"\3"\4', fixed, count=1)
        n_total += n
    fixed, n = _TRAILING_COMMA.subn(r"\1", fixed)
    n_total += n
    return fixed if n_total else None


def normalize_tv_payload(data: dict) -> dict:
    """Coerce TradingView alert fields — TV may send numbers as strings."""
    out = dict(data)
    out["action"] = str(out.get("action", "")).upper().strip()
    if out.get("regime") is not None:
        try:
            out["regime"] = int(out["regime"])
        except (TypeError, ValueError):
            pass
    for key in ("atr", "price", "tv_tp1", "tv_tp2", "tv_tp3", "tv_sl", "pnl_pct", "risk_pct", "qty_ratio", "leverage"):
        if key in out and out[key] is not None and out[key] != "":
            try:
                val = out[key]
                if isinstance(val, str):
                    val = val.strip().replace(",", "")
                out[key] = float(val)
            except (TypeError, ValueError):
                pass
    if out.get("side") is not None:
        out["side"] = str(out["side"]).upper().strip()
    if out.get("reason") is not None:
        out["reason"] = str(out["reason"])[:500]
    if out.get("entry_type") is not None:
        out["entry_type"] = str(out["entry_type"]).upper().strip()
    for key in ("bar_index", "seq"):
        if key in out and out[key] is not None and out[key] != "":
            try:
                out[key] = int(float(str(out[key]).strip()))
            except (TypeError, ValueError):
                pass
    return out


def parse_webhook_payload(raw_text: str) -> tuple[dict | None, str | None]:
    """
    Parse webhook body. Returns (data, error_message).
    On success error_message is None.
    """
    text = (raw_text or "").strip()
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")
    if not text:
        return None, "Empty payload"

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            data = normalize_tv_payload(data)
            data = enrich_tv_signal(data)
            return data, None
        return None, "JSON root must be an object"
    except json.JSONDecodeError as first_err:
        repaired = repair_pine_close_protect_json(text)
        if repaired:
            try:
                data = json.loads(repaired)
                if isinstance(data, dict):
                    logger.warning(
                        "[Webhook] Repaired malformed CLOSE JSON (Pine side/reason quote bug)"
                    )
                    data = normalize_tv_payload(data)
                    data = enrich_tv_signal(data)
                    return data, None
            except json.JSONDecodeError:
                pass
        return None, f"Invalid JSON: {first_err.msg}"
