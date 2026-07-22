"""Emergency ATR fallback — temporary degrade only, never silent.

VPS ATR/ADX remains the primary source. This path activates only when VPS ATR is
unusable or repeatedly diverges from TV-implied ATR, then:
  - one open may proceed using TV-implied ATR
  - breathing-stop multipliers stay unchanged (still 1.5× / 0.75× / …)
  - critical DingTalk alert
  - symbol auto-open paused until manual resume
"""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.core.market_engine import atr_mismatch_ratio, implied_atr_from_tv_stop
from app.core.market_indicators import evaluate_atr_sanity


def tv_implied_atr(
    entry: float,
    stop_loss: float,
    *,
    tv_stop_atr_mult: float | None = None,
) -> float:
    settings = get_settings()
    mult = float(
        tv_stop_atr_mult
        if tv_stop_atr_mult is not None
        else (getattr(settings, "TV_STOP_ATR_MULT", 1.0) or 1.0)
    )
    return implied_atr_from_tv_stop(
        float(entry or 0), float(stop_loss or 0), initial_sl_atr=mult,
    )


def evaluate_emergency_atr_fallback(
    *,
    vps_atr: float,
    atr_series: list[float] | None,
    entry: float,
    tv_stop_loss: float | None,
    mismatch_streak: int = 0,
) -> dict[str, Any]:
    """Decide whether this open must degrade to TV-implied ATR.

    Returns meta with keys:
      need_fallback, reason, tv_implied_atr, vps_atr, mismatch_pct,
      mismatch_streak_next, pause_after_open
    """
    settings = get_settings()
    lookback = int(getattr(settings, "ATR_MEDIAN_LOOKBACK", 50) or 50)
    floor_ratio = float(getattr(settings, "ATR_MEDIAN_FLOOR_RATIO", 0.30) or 0.30)
    warn_pct = float(
        getattr(settings, "ATR_FALLBACK_MISMATCH_PCT", None)
        or getattr(settings, "ATR_COMPARE_WARN_PCT", 0.20)
        or 0.20
    )
    streak_need = int(getattr(settings, "ATR_FALLBACK_STREAK", 3) or 3)

    vps = float(vps_atr or 0)
    implied = tv_implied_atr(float(entry or 0), float(tv_stop_loss or 0))
    sanity = evaluate_atr_sanity(
        vps, atr_series, lookback=lookback, floor_ratio=floor_ratio,
    )
    ratio = atr_mismatch_ratio(vps, implied) if (vps > 0 and implied > 0) else 0.0

    streak = int(mismatch_streak or 0)
    if vps > 0 and implied > 0 and ratio >= warn_pct:
        streak_next = streak + 1
    elif vps > 0 and implied > 0:
        streak_next = 0
    else:
        streak_next = streak

    reason = None
    if vps <= 0 or sanity.get("error") == "atr_invalid":
        reason = "vps_atr_invalid_or_missing"
    elif sanity.get("error") == "atr_anomaly":
        reason = "vps_atr_below_median_floor"
    elif implied > 0 and streak_next >= streak_need and ratio >= warn_pct:
        reason = f"atr_mismatch_streak_{streak_next}"

    need = bool(reason) and implied > 0
    return {
        "need_fallback": need,
        "reason": reason,
        "vps_atr": round(vps, 6),
        "tv_implied_atr": round(implied, 6) if implied > 0 else 0.0,
        "mismatch_pct": round(ratio * 100, 2),
        "warn_pct": warn_pct * 100,
        "mismatch_streak": streak,
        "mismatch_streak_next": streak_next if need or (implied > 0) else streak,
        "pause_after_open": need,
        "sanity": sanity,
        "tv_stop_loss": float(tv_stop_loss or 0) or None,
        "entry": float(entry or 0) or None,
        # Multipliers intentionally unchanged — only ATR value source swaps.
        "note": "fallback_replaces_atr_value_only; breathing multipliers unchanged",
    }


def apply_fallback_atr(decision: dict[str, Any]) -> float:
    """Return ATR to use for this open (TV-implied). 0 if not applicable."""
    if not decision.get("need_fallback"):
        return 0.0
    return float(decision.get("tv_implied_atr") or 0)
