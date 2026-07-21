"""Parse TradingView webhook JSON — v6.5.6 Trillion_God final.

Canonical fields: bot_id, token, action, symbol, price, qty, qty1-3,
stop_loss, tp1, tp2, tp3 (+ optional atr).
Legacy aliases (secret/tv_sl/tv_tp*) normalized for internal supervisors.
"""

from __future__ import annotations

import json
import logging
import re

from app.services.tv_signal_enrich import enrich_tv_signal

logger = logging.getLogger(__name__)

_PINE_CLOSE_PROTECT_SIDE_REASON = re.compile(
    r'"side":"(LONG|SHORT|NONE),("reason":")([^"]*?)(,"pnl_pct":)'
)
_PINE_CLOSE_SIDE_REASON_GENERIC = re.compile(
    r'"side":"(LONG|SHORT|NONE),("reason":")([^"]*?)(,"(?:pnl_pct|price)":)'
)
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")


def repair_pine_close_protect_json(raw: str) -> str | None:
    if not any(
        x in raw
        for x in (
            "CLOSE_PROTECT",
            "CLOSE_TP3",
            "CLOSE_STOPLOSS",
            "CLOSE_QUICK_EXIT",
            "CLOSE_RSI_EXIT",
            "CLOSE",
        )
    ):
        return None
    fixed = raw
    n_total = 0
    for pattern in (_PINE_CLOSE_PROTECT_SIDE_REASON, _PINE_CLOSE_SIDE_REASON_GENERIC):
        fixed, n = pattern.subn(r'"side":"\1","reason":"\3"\4', fixed, count=1)
        n_total += n
    fixed, n = _TRAILING_COMMA.subn(r"\1", fixed)
    n_total += n
    return fixed if n_total else None


def _coerce_float(out: dict, key: str) -> None:
    if key not in out or out[key] is None or out[key] == "":
        return
    try:
        val = out[key]
        if isinstance(val, str):
            val = val.strip().replace(",", "")
        out[key] = float(val)
    except (TypeError, ValueError):
        pass


def normalize_tv_payload(data: dict) -> dict:
    """Coerce v6.5.6 fields + legacy aliases into supervisor-ready shape."""
    out = dict(data)
    out["action"] = str(out.get("action", "")).upper().strip()

    # Auth: token (v6.5.6) ≡ secret (platform)
    if out.get("token") and not out.get("secret"):
        out["secret"] = str(out["token"]).strip()
    elif out.get("secret") and not out.get("token"):
        out["token"] = str(out["secret"]).strip()

    # Price aliases → internal tv_*
    if out.get("stop_loss") is not None and not out.get("tv_sl"):
        out["tv_sl"] = out["stop_loss"]
    if out.get("tv_sl") is not None and not out.get("stop_loss"):
        out["stop_loss"] = out["tv_sl"]

    for src, dst in (("tp1", "tv_tp1"), ("tp2", "tv_tp2"), ("tp3", "tv_tp3")):
        if out.get(src) is not None and not out.get(dst):
            out[dst] = out[src]
        if out.get(dst) is not None and not out.get(src):
            out[src] = out[dst]

    float_keys = (
        "atr", "adx", "price", "tv_tp1", "tv_tp2", "tv_tp3", "tv_sl",
        "tp1", "tp2", "tp3", "stop_loss",
        "qty", "qty1", "qty2", "qty3", "pnl_pct",
    )
    for key in float_keys:
        _coerce_float(out, key)

    if out.get("side") is not None:
        out["side"] = str(out["side"]).upper().strip()
    if out.get("reason") is not None:
        out["reason"] = str(out["reason"])[:500]
    if out.get("bot_id") is not None:
        out["bot_id"] = str(out["bot_id"]).strip()
    if out.get("leg") is not None:
        out["leg"] = str(out["leg"]).strip()

    for key in ("bar_index", "seq"):
        if key in out and out[key] is not None and out[key] != "":
            try:
                out[key] = int(float(str(out[key]).strip()))
            except (TypeError, ValueError):
                pass

    out.setdefault("strategy_version", "v6.5.6")
    return out


def parse_webhook_payload(raw_text: str) -> tuple[dict | None, str | None]:
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
