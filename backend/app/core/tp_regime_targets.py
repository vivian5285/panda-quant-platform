"""TP slice ratios — fixed 10/20/70; only TP1/TP2 hang as limits.

Gemini multi-user spec §7 (final): TP3 (70%) never hangs a limit — radar-only.
ATR always from TV webhook ``atr`` (no VPS fetch / scenario gate on TP3).
"""

from __future__ import annotations

from typing import Any

from app.core.radar_trail import merge_regime_radar

# Defaults; overridden by Settings TP1_QTY_PCT / TP2_QTY_PCT when available
FIXED_TP_QTY_PERCENT: tuple[int, int, int] = (10, 20, 70)
# Spec §7: TP3 never placed as limit
PLACEABLE_TP_LEVELS: frozenset[int] = frozenset({1, 2})

PINE_TP_QTY_PERCENT: dict[int, tuple[int, int, int]] = {
    1: FIXED_TP_QTY_PERCENT,
    2: FIXED_TP_QTY_PERCENT,
    3: FIXED_TP_QTY_PERCENT,
    4: FIXED_TP_QTY_PERCENT,
}

REGIME_MARGIN_PCT: dict[int, float] = {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0}


def _ratios_from_settings() -> tuple[int, int, int]:
    try:
        from app.config import get_settings

        s = get_settings()
        p1 = float(getattr(s, "TP1_QTY_PCT", 0.10) or 0.10)
        p2 = float(getattr(s, "TP2_QTY_PCT", 0.20) or 0.20)
        if p1 <= 0 or p2 <= 0 or p1 + p2 >= 1.0:
            return FIXED_TP_QTY_PERCENT
        p3 = 1.0 - p1 - p2
        return (int(round(p1 * 100)), int(round(p2 * 100)), int(round(p3 * 100)))
    except Exception:
        return FIXED_TP_QTY_PERCENT


def placeable_tp_levels() -> frozenset[int]:
    """TP1+TP2 only. TP3 never hung as limit (Spec §7)."""
    return PLACEABLE_TP_LEVELS


def clamp_regime(regime: int) -> int:
    r = int(regime or 3)
    return r if r in PINE_TP_QTY_PERCENT else 3


def pine_tp_ratios_frac(regime: int = 3) -> list[float]:
    p1, p2, p3 = _ratios_from_settings()
    return [p1 / 100.0, p2 / 100.0, p3 / 100.0]


def format_tp_ratio_pct(regime: int = 3) -> str:
    p1, p2, p3 = _ratios_from_settings()
    return f"{p1}/{p2}/{p3}"


def remaining_qty_pct_from_consumed(consumed: list | None) -> float:
    """Residual after TP1/TP2 fills (10/20/70 → 0.9 / 0.7). Level-3 consume → 0."""
    levels = {int(x) for x in (consumed or []) if int(x) in (1, 2, 3)}
    ratios = pine_tp_ratios_frac()
    rem = 1.0
    for lv in (1, 2, 3):
        if lv in levels:
            rem -= float(ratios[lv - 1])
    return max(0.0, rem)


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
) -> dict:
    out = dict(detail or {})
    out["regime"] = clamp_regime(regime)
    out["tp_ratios_pct"] = format_tp_ratio_pct()
    out["tp_ratios"] = pine_tp_ratios_frac()
    out["tp3_limit_placed"] = False  # Spec §7: TP3 never hung
    out["tp_placeable_levels"] = sorted(PLACEABLE_TP_LEVELS)
    return out


def resolve_tp_ratios_from_payload(payload: dict | None = None) -> list[float]:
    return pine_tp_ratios_frac()
