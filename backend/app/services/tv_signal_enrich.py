"""Enrich TradingView webhook payloads — v6.9.75 minimal JSON → full GEMINI dispatch."""

from __future__ import annotations

import logging
from typing import Any

from app.core.regime_utils import clamp_regime
from app.core.symbol_precision import normalize_tv_targets, round_price

logger = logging.getLogger(__name__)

# 万亿战神 v6.9.75 四档 ATR 止盈倍数（与 Pine raw_tp1/2/3_m 一致）
REGIME_TP_ATR_MULT: dict[int, tuple[float, float, float]] = {
    1: (0.75, 1.4, 2.0),
    2: (1.10, 2.0, 2.8),
    3: (1.30, 2.6, 3.8),
    4: (1.55, 3.0, 4.8),
}

CLOSE_ACTIONS = frozenset({
    "CLOSE", "CLOSE_PROTECT", "CLOSE_TP3", "CLOSE_STOPLOSS",
})
ENTRY_ACTIONS = frozenset({"LONG", "SHORT"})


def compute_tv_tps_from_regime(
    price: float,
    atr: float,
    regime: int,
    side: str,
) -> list[float]:
    """Derive TP1/2/3 from entry price + ATR + regime (Pine tv_tp*_l/s formula)."""
    px = float(price or 0)
    a = float(atr or 0)
    if px <= 0 or a <= 0:
        return [0.0, 0.0, 0.0]
    r = clamp_regime(regime)
    m1, m2, m3 = REGIME_TP_ATR_MULT.get(r, REGIME_TP_ATR_MULT[3])
    sign = 1.0 if str(side or "").upper() == "LONG" else -1.0
    return normalize_tv_targets([
        px + sign * a * m1,
        px + sign * a * m2,
        px + sign * a * m3,
    ])


def _has_tp_triplet(data: dict) -> bool:
    return all(float(data.get(k) or 0) > 0 for k in ("tv_tp1", "tv_tp2", "tv_tp3"))


def _estimate_atr_from_client(client, symbol: str) -> float:
    if client and hasattr(client, "estimate_atr"):
        try:
            val = float(client.estimate_atr(symbol) or 0)
            if val > 0:
                return val
        except Exception:
            pass
    return 0.0


def enrich_tv_signal(
    data: dict,
    *,
    fallback_regime: int | None = None,
    fallback_atr: float | None = None,
    client=None,
    symbol: str = "ETHUSDT",
) -> dict:
    """
    Fill missing regime / atr / tv_tp* for v6.9.75 minimal entry webhooks.
    Mutates a copy; records `_enriched_fields` for audit.
    """
    out = dict(data)
    action = str(out.get("action", "")).upper().strip()
    enriched: list[str] = []

    if action in CLOSE_ACTIONS or action.startswith("CLOSE"):
        if out.get("side") is not None:
            out["side"] = str(out["side"]).upper().strip()
        if action == "CLOSE_STOPLOSS" and not out.get("reason"):
            out["reason"] = "触碰硬止损或追踪保本线"
        out["_enriched_fields"] = enriched
        return out

    if action not in ENTRY_ACTIONS:
        out["_enriched_fields"] = enriched
        return out

    price = float(out.get("price") or 0)
    if price <= 0:
        out["_enriched_fields"] = enriched
        return out

    regime = out.get("regime")
    if regime is None or str(regime).strip() == "":
        out["regime"] = clamp_regime(fallback_regime or 3)
        enriched.append("regime")
    else:
        out["regime"] = clamp_regime(regime)

    atr = float(out.get("atr") or 0)
    if atr <= 0:
        atr = float(fallback_atr or 0)
    if atr <= 0:
        atr = _estimate_atr_from_client(client, symbol)
    if atr <= 0:
        atr = 30.0
    if float(out.get("atr") or 0) <= 0:
        enriched.append("atr")
    out["atr"] = round(float(atr), 4)

    out["price"] = round_price(price)

    if not _has_tp_triplet(out):
        tps = compute_tv_tps_from_regime(out["price"], out["atr"], out["regime"], action)
        out["tv_tp1"], out["tv_tp2"], out["tv_tp3"] = tps[0], tps[1], tps[2]
        enriched.append("tv_tps")

    out.setdefault("strategy_version", "v6.9.75")
    if out.get("risk_pct") is not None:
        out["strategy_version"] = "v6.9.85"
    out["_enriched_fields"] = enriched
    if enriched:
        logger.info(
            "[Webhook] enriched TV entry %s fields=%s regime=R%s atr=%s tps=%s,%s,%s",
            action, enriched, out["regime"], out["atr"],
            out.get("tv_tp1"), out.get("tv_tp2"), out.get("tv_tp3"),
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
    """Per-user enrich using supervisor memory when webhook omitted fields."""
    return enrich_tv_signal(
        payload,
        fallback_regime=regime,
        fallback_atr=atr if atr and atr > 0 else None,
    )
