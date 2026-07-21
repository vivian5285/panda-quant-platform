"""Enrich TradingView webhook payloads — v6.5.6 (no regime TP invent)."""

from __future__ import annotations

import logging
from typing import Any

from app.core.symbol_precision import round_price

logger = logging.getLogger(__name__)

CLOSE_ACTIONS = frozenset({
    "CLOSE_QUICK_EXIT",
    "CLOSE_RSI_EXIT",
})
ENTRY_ACTIONS = frozenset({"LONG", "SHORT"})


def enrich_tv_signal(
    data: dict,
    *,
    fallback_regime: int | None = None,
    fallback_atr: float | None = None,
    client=None,
    symbol: str = "ETHUSDT",
) -> dict:
    """
    v6.5.6: map aliases already done in normalize_tv_payload.
    ATR/ADX are computed by VPS market engine — do NOT invent atr for decisions.
    NEVER invent tp1-3 from regime.
    """
    out = dict(data)
    action = str(out.get("action", "")).upper().strip()
    enriched: list[str] = []

    if action in CLOSE_ACTIONS or action.startswith("CLOSE"):
        if out.get("side") is not None:
            out["side"] = str(out["side"]).upper().strip()
        out["_enriched_fields"] = enriched
        return out

    if action not in ENTRY_ACTIONS:
        out["_enriched_fields"] = enriched
        return out

    price = float(out.get("price") or 0)
    if price <= 0:
        out["_enriched_fields"] = enriched
        return out

    out["price"] = round_price(price)

    # regime inert (compat for old state keys) — fixed ladder does not use it
    if out.get("regime") is None:
        out["regime"] = 3
        enriched.append("regime_default")

    # Keep atr/adx on payload only if TV sent them (debug / ATR_MISMATCH compare).
    # Do not fill defaults — breathing stop uses market_engine exclusively.
    if fallback_atr is not None and float(out.get("atr") or 0) <= 0:
        # retained for logging only; supervisors ignore webhook atr
        pass

    # Ensure tv_* mirrors for supervisors
    if float(out.get("stop_loss") or 0) > 0:
        out["tv_sl"] = float(out["stop_loss"])
    if float(out.get("tp1") or 0) > 0:
        out["tv_tp1"] = float(out["tp1"])
    if float(out.get("tp2") or 0) > 0:
        out["tv_tp2"] = float(out["tp2"])
    if float(out.get("tp3") or 0) > 0:
        out["tv_tp3"] = float(out["tp3"])

    out["strategy_version"] = "v6.5.6"
    out["entry_type"] = "OPEN"
    out["_enriched_fields"] = enriched
    if enriched:
        logger.info(
            "[Webhook] enriched v6.5.6 entry %s fields=%s tps=%s,%s,%s sl=%s",
            action, enriched,
            out.get("tv_tp1"), out.get("tv_tp2"), out.get("tv_tp3"), out.get("tv_sl"),
        )
    return out


def format_enrich_note(data: dict) -> str:
    fields = data.get("_enriched_fields") or []
    if not fields:
        return ""
    return f"网关补全: {','.join(fields)}"


def merge_supervisor_fallbacks(
    payload: dict,
    *,
    regime: int,
    atr: float,
    tv_tps: list | None = None,
) -> dict:
    return enrich_tv_signal(
        payload,
        fallback_regime=regime,
        fallback_atr=atr,
    )


# Removed: compute_tv_tps_from_regime / REGIME_TP_ATR_MULT (old logic deleted)
def compute_tv_tps_from_regime(*args, **kwargs) -> list[float]:
    return [0.0, 0.0, 0.0]
