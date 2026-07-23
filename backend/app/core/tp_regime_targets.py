"""TP slice ratios — fixed 30/30/40; TP3 limit only in ATR scenario 2.

Scenario 1 (VPS real ATR): place TP1+TP2 only; TP3 remainder via breath trail.
Scenario 2 (TV atr fallback): also hang TP3 limit at TV price (40%).
"""

from __future__ import annotations

from typing import Any

from app.core.radar_trail import merge_regime_radar

FIXED_TP_QTY_PERCENT: tuple[int, int, int] = (30, 30, 40)
PLACEABLE_TP_LEVELS: frozenset[int] = frozenset({1, 2})
PLACEABLE_TP_LEVELS_WITH_TP3: frozenset[int] = frozenset({1, 2, 3})

PINE_TP_QTY_PERCENT: dict[int, tuple[int, int, int]] = {
    1: FIXED_TP_QTY_PERCENT,
    2: FIXED_TP_QTY_PERCENT,
    3: FIXED_TP_QTY_PERCENT,
    4: FIXED_TP_QTY_PERCENT,
}

REGIME_MARGIN_PCT: dict[int, float] = {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0}


def placeable_tp_levels(*, tp3_limit_active: bool = False) -> frozenset[int]:
    return PLACEABLE_TP_LEVELS_WITH_TP3 if tp3_limit_active else PLACEABLE_TP_LEVELS


def clamp_regime(regime: int) -> int:
    r = int(regime or 3)
    return r if r in PINE_TP_QTY_PERCENT else 3


def pine_tp_ratios_frac(regime: int = 3) -> list[float]:
    p1, p2, p3 = FIXED_TP_QTY_PERCENT
    return [p1 / 100.0, p2 / 100.0, p3 / 100.0]


def format_tp_ratio_pct(regime: int = 3) -> str:
    p1, p2, p3 = FIXED_TP_QTY_PERCENT
    return f"{p1}/{p2}/{p3}"


def build_regime_settings() -> dict[int, dict[str, Any]]:
    base = {
        r: {"margin": 0.0, "ratios": pine_tp_ratios_frac(r)}
        for r in PINE_TP_QTY_PERCENT
    }
    return merge_regime_radar(base)


def enrich_tp_alert_detail(
    detail: dict | None,
    *,
    regime: int = 3,
    tp3_limit_placed: bool | None = None,
) -> dict:
    out = dict(detail or {})
    out["regime"] = clamp_regime(regime)
    out["tp_ratios_pct"] = format_tp_ratio_pct()
    out["tp_ratios"] = pine_tp_ratios_frac()
    placed = bool(tp3_limit_placed) if tp3_limit_placed is not None else False
    out["tp3_limit_placed"] = placed
    out["tp_placeable_levels"] = sorted(placeable_tp_levels(tp3_limit_active=placed))
    return out


def resolve_tp_ratios_from_payload(payload: dict | None = None) -> list[float]:
    return pine_tp_ratios_frac()
