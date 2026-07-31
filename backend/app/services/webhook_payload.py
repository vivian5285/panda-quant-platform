"""Parse TradingView webhook JSON — Trillion_God / Gemini final.

Canonical fields: bot_id, secret, action, symbol, price, qty, qty1-3,
stop_loss, tp1, tp2, tp3 (+ optional atr).
Legacy aliases (token/tv_sl/tv_tp*) normalized for internal supervisors.
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
_BACKSLASH_ESCAPE = re.compile(r'\\([:,\s])')
_LEADING_SPACE_KEY = re.compile(r'{\s*"')
_TRAILING_SPACE_VALUE = re.compile(r'":\s*"')


def repair_shell_escaped_json(raw: str) -> str | None:
    """修复 SSH/Shell 双引号转义导致的畸形 JSON（如 secret\:\test\，action\:\LONG\）。

    症状：JSON key 被 \: 分割，如 ` secret\:\test\` 变成 `"secret":"test"` 的错误版本。
    也处理组合模式如 `\,\` -> `,`
    """
    if r'\:' not in raw and r'\,' not in raw and r'\ ' not in raw:
        return None
    fixed = _BACKSLASH_ESCAPE.sub(r'\1', raw)
    # 修复 leading space in first key: "{\" secret" -> "{\"secret"
    fixed = _LEADING_SPACE_KEY.sub(r'{"', fixed)
    try:
        json.loads(fixed)
        return fixed
    except json.JSONDecodeError:
        return None


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


def _coerce_int(out: dict, key: str, default: int = 0) -> None:
    """Coerce regime/side ordinals: 'strong'->3, 'moderate'->2, 'quiet'->1."""
    if key not in out or out[key] is None or out[key] == "":
        return
    val = out[key]
    if isinstance(val, int) and not isinstance(val, bool):
        return
    try:
        if isinstance(val, str):
            val = val.strip().lower()
            if val in ("strong", "3"):
                out[key] = 3
                return
            elif val in ("moderate", "2"):
                out[key] = 2
                return
            elif val in ("quiet", "1"):
                out[key] = 1
                return
            val = val.replace(",", "")
        out[key] = int(float(val))
    except (TypeError, ValueError):
        out[key] = default


def normalize_tv_payload(data: dict) -> dict:
    """Coerce v6.5.6 fields + legacy aliases into supervisor-ready shape."""
    out = dict(data)
    out["action"] = str(out.get("action", "")).upper().strip()

    # Auth: secret (canonical) ≡ token (legacy TV payloads)
    if out.get("secret") and not out.get("token"):
        out["token"] = str(out["secret"]).strip()
    elif out.get("token") and not out.get("secret"):
        out["secret"] = str(out["token"]).strip()

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

    # Regime: accept int (1-3), "strong"/"moderate"/"quiet", or numeric strings
    _coerce_int(out, "regime", 3)

    # Optional bar_time (ms); Pine `time` often = bar open — fine for monotonic order
    raw_bt = out.get("bar_time")
    if raw_bt is None or raw_bt == "":
        raw_bt = out.get("time")
    if raw_bt is not None and raw_bt != "":
        try:
            bt = float(raw_bt)
            if bt > 0 and bt < 1e11:
                bt *= 1000.0
            out["bar_time"] = int(bt) if bt > 0 else None
        except (TypeError, ValueError):
            out["bar_time"] = None

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
        # 尝试修复 Shell 转义导致的畸形 JSON（如 secret\:\test\）
        repaired = repair_shell_escaped_json(text)
        if repaired:
            try:
                data = json.loads(repaired)
                if isinstance(data, dict):
                    logger.warning(
                        "[Webhook] Repaired shell-escaped JSON (SSH double-quote escape artifact)"
                    )
                    data = normalize_tv_payload(data)
                    data = enrich_tv_signal(data)
                    return data, None
            except json.JSONDecodeError:
                pass

        # 尝试修复 Pine 侧/原因引号 bug 导致的畸形 JSON
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
