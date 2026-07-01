"""Parse TradingView webhook JSON bodies (with optional repair for common Pine quoting bugs)."""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

# Pine v6.9.30 bug: missing closing quote after side/reason
# Broken:  "side":"LONG,"reason":"xxx,"pnl_pct":
# Fixed:    "side":"LONG","reason":"xxx","pnl_pct":
_PINE_CLOSE_PROTECT_SIDE_REASON = re.compile(
    r'"side":"(LONG|SHORT|NONE),("reason":")([^"]*?)(,"pnl_pct":)'
)


def repair_pine_close_protect_json(raw: str) -> str | None:
    """Repair known malformed CLOSE_PROTECT JSON from 万亿战神 v6.9.30."""
    if "CLOSE_PROTECT" not in raw:
        return None
    fixed, n = _PINE_CLOSE_PROTECT_SIDE_REASON.subn(
        r'"side":"\1","reason":"\3"\4',
        raw,
        count=1,
    )
    return fixed if n else None


def normalize_tv_payload(data: dict) -> dict:
    """Coerce TradingView alert fields — TV may send numbers as strings."""
    out = dict(data)
    out["action"] = str(out.get("action", "")).upper().strip()
    if out.get("regime") is not None:
        try:
            out["regime"] = int(out["regime"])
        except (TypeError, ValueError):
            pass
    for key in ("atr", "price", "tv_tp1", "tv_tp2", "tv_tp3", "pnl_pct"):
        if key in out and out[key] is not None and out[key] != "":
            try:
                val = out[key]
                out[key] = float(str(val).strip()) if isinstance(val, str) else float(val)
            except (TypeError, ValueError):
                pass
    if out.get("side") is not None:
        out["side"] = str(out["side"]).upper().strip()
    if out.get("reason") is not None:
        out["reason"] = str(out["reason"])[:500]
    return out


def parse_webhook_payload(raw_text: str) -> tuple[dict | None, str | None]:
    """
    Parse webhook body. Returns (data, error_message).
    On success error_message is None.
    """
    text = (raw_text or "").strip()
    if not text:
        return None, "Empty payload"

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return normalize_tv_payload(data), None
        return None, "JSON root must be an object"
    except json.JSONDecodeError as first_err:
        repaired = repair_pine_close_protect_json(text)
        if repaired:
            try:
                data = json.loads(repaired)
                if isinstance(data, dict):
                    logger.warning(
                        "[Webhook] Repaired malformed CLOSE_PROTECT JSON (Pine side/reason quote bug)"
                    )
                    return normalize_tv_payload(data), None
            except json.JSONDecodeError:
                pass
        return None, f"Invalid JSON: {first_err.msg}"
