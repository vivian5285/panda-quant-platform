"""Dual-symbol smart re-entry after radar stop — progressive arm + radar tiers.

ETH 90m / XAU 45m share the same arm TP1%% ladder; coefficient tables differ.
Hard-stop / loss closes never re-enter. Limit re-entry improves on TV px by 0.3%%.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.core.breathing_profile import ETH_PROFILE, profile_for_symbol
from app.core.symbol_registry import CANONICAL_ETH, CANONICAL_XAU, normalize_canonical_symbol

ARM_TP1_PCTS: tuple[float, ...] = (0.50, 0.65, 0.80, 0.95)
ARM_PCT_GROWTH = 1.3
ARM_PCT_CAP = 0.95
LIMIT_IMPROVE_PCT = 0.003  # fallback when klines unavailable
MAX_REENTRY = 3  # re-entries after first open (attempts 1..3)
LIMIT_TTL_SEC = 300
MAX_UNFILLED_CYCLES = 5  # consecutive TTL cycles without fill → abort
MAX_DEV_FROM_TV_PCT = 0.01
# Favorable close zone (entry → entry ± zone×ATR) for BE / micro-profit
REENTRY_ZONE_ATR = {
    CANONICAL_ETH: 0.5,
    CANONICAL_XAU: 0.3,
}


@dataclass(frozen=True)
class RadarTier:
    """Radar coefficient tier for open attempt index (0=first, 1..3=reentry)."""

    attempt: int
    early_breakeven_atr: float
    step_trigger_atr: float
    step_advance_atr: float
    arm_tp1_pct: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# attempt -> (early_be, step_trigger, step_advance)
_ETH_TIERS: tuple[tuple[float, float, float], ...] = (
    (0.50, 0.75, 0.40),
    (0.65, 0.90, 0.45),
    (0.80, 1.05, 0.50),
    (1.00, 1.20, 0.55),
)
_XAU_TIERS: tuple[tuple[float, float, float], ...] = (
    (0.65, 0.70, 0.45),
    (0.80, 0.85, 0.50),
    (1.00, 1.00, 0.55),
    (1.20, 1.15, 0.60),
)


def _canon(symbol: str | None) -> str:
    return normalize_canonical_symbol(symbol) or CANONICAL_ETH


def arm_tp1_pct_for_attempt(attempt: int) -> float:
    """Fixed ladder 50/65/80/95; clamp attempt into range."""
    idx = max(0, min(int(attempt), len(ARM_TP1_PCTS) - 1))
    return float(ARM_TP1_PCTS[idx])


def next_attempt_arm_pct(prev_pct: float) -> float:
    """×1.3 growth capped at 0.95×TP1 (scheme step 5)."""
    try:
        p = float(prev_pct)
    except (TypeError, ValueError):
        p = ARM_TP1_PCTS[0]
    if p <= 0:
        p = ARM_TP1_PCTS[0]
    return min(float(ARM_PCT_CAP), p * float(ARM_PCT_GROWTH))


def tier_for_attempt(attempt: int, symbol: str | None = None) -> RadarTier:
    can = _canon(symbol)
    table = _XAU_TIERS if can == CANONICAL_XAU else _ETH_TIERS
    idx = max(0, min(int(attempt), len(table) - 1))
    early, trigger, advance = table[idx]
    return RadarTier(
        attempt=idx,
        early_breakeven_atr=float(early),
        step_trigger_atr=float(trigger),
        step_advance_atr=float(advance),
        arm_tp1_pct=arm_tp1_pct_for_attempt(idx),
    )


def reentry_zone_atr(symbol: str | None = None) -> float:
    can = _canon(symbol)
    return float(REENTRY_ZONE_ATR.get(can, REENTRY_ZONE_ATR[CANONICAL_ETH]))


def arm_distance(
    atr: float,
    attempt: int,
    symbol: str | None = None,
    *,
    arm_tp1_pct: float | None = None,
    step_trigger_atr: float | None = None,
) -> float:
    """arm_dist = max(TP1×pct, step_trigger×ATR)."""
    p = profile_for_symbol(symbol)
    a = float(atr or 0)
    if a <= 0:
        return 0.0
    tier = tier_for_attempt(attempt, symbol)
    pct = float(arm_tp1_pct if arm_tp1_pct is not None else tier.arm_tp1_pct)
    trig = float(step_trigger_atr if step_trigger_atr is not None else tier.step_trigger_atr)
    tp1_arm = float(p.tp1_atr) * a * pct
    trigger_arm = trig * a
    return max(tp1_arm, trigger_arm)


def limit_reentry_price(side: str, tv_px: float) -> float:
    """Fallback only: LONG TV×0.997 / SHORT TV×1.003."""
    px = float(tv_px or 0)
    if px <= 0:
        return 0.0
    side_u = str(side or "").upper()
    if side_u == "LONG":
        return px * (1.0 - LIMIT_IMPROVE_PCT)
    if side_u == "SHORT":
        return px * (1.0 + LIMIT_IMPROVE_PCT)
    return 0.0


def _price_tick(symbol: str | None) -> float:
    try:
        from app.core.symbol_registry import symbol_meta

        meta = symbol_meta(symbol) or {}
        tick = float(meta.get("price_tick") or 0.01)
        return tick if tick > 0 else 0.01
    except Exception:
        return 0.01


def _kline_high_low(rows: list | None) -> tuple[float, float]:
    """Binance kline row: [ot, o, h, l, c, ...]. Use last closed-ish bar."""
    if not rows:
        return 0.0, 0.0
    row = rows[-1]
    try:
        hi = float(row[2])
        lo = float(row[3])
        if hi > 0 and lo > 0 and hi >= lo:
            return hi, lo
    except (TypeError, ValueError, IndexError):
        pass
    return 0.0, 0.0


def reentry_price_better_than_tv(side: str, limit_px: float, tv_px: float) -> bool:
    """LONG must be < TV; SHORT must be > TV."""
    lim = float(limit_px or 0)
    tv = float(tv_px or 0)
    if lim <= 0 or tv <= 0:
        return False
    side_u = str(side or "").upper()
    if side_u == "LONG":
        return lim < tv - 1e-12
    if side_u == "SHORT":
        return lim > tv + 1e-12
    return False


def compute_optimal_reentry_price(
    *,
    side: str,
    tv_px: float,
    symbol: str | None = None,
    klines_5m: list | None = None,
    klines_3m: list | None = None,
) -> tuple[float, dict[str, Any]]:
    """Ultimate plan: LONG = 5m low + 1 tick; SHORT = 5m high − 1 tick.

    Fallback 3m, then TV×0.997/1.003. Returns (price, meta); price=0 if not better than TV.
    """
    side_u = str(side or "").upper()
    tv = float(tv_px or 0)
    tick = _price_tick(symbol)
    meta: dict[str, Any] = {
        "side": side_u,
        "tv_px": tv,
        "tick": tick,
        "source": None,
    }
    if side_u not in ("LONG", "SHORT") or tv <= 0:
        meta["reason"] = "bad_inputs"
        return 0.0, meta

    hi5, lo5 = _kline_high_low(klines_5m)
    hi3, lo3 = _kline_high_low(klines_3m)
    candidate = 0.0
    if hi5 > 0 and lo5 > 0:
        candidate = (lo5 + tick) if side_u == "LONG" else (hi5 - tick)
        meta["source"] = "kline_5m"
        meta["kline_high"] = hi5
        meta["kline_low"] = lo5
    elif hi3 > 0 and lo3 > 0:
        candidate = (lo3 + tick) if side_u == "LONG" else (hi3 - tick)
        meta["source"] = "kline_3m"
        meta["kline_high"] = hi3
        meta["kline_low"] = lo3
    else:
        candidate = limit_reentry_price(side_u, tv)
        meta["source"] = "tv_pct_fallback"

    if candidate <= 0:
        meta["reason"] = "no_candidate"
        return 0.0, meta
    if not reentry_price_better_than_tv(side_u, candidate, tv):
        meta["reason"] = "not_better_than_tv"
        meta["candidate"] = candidate
        return 0.0, meta
    meta["reason"] = "ok"
    meta["limit_px"] = candidate
    return float(candidate), meta


def tv_deviation_ok(mark: float, tv_px: float, *, max_pct: float = MAX_DEV_FROM_TV_PCT) -> bool:
    m = float(mark or 0)
    t = float(tv_px or 0)
    if m <= 0 or t <= 0:
        return False
    return abs(m - t) / t <= float(max_pct)


def close_allows_reentry(
    *,
    side: str,
    entry: float,
    close_px: float,
    atr: float,
    symbol: str | None,
    close_track: str,
) -> tuple[bool, dict[str, Any]]:
    """Radar BE/micro-profit in zone only; hard/loss/unknown → reject."""
    meta: dict[str, Any] = {
        "side": str(side or "").upper(),
        "entry": float(entry or 0),
        "close_px": float(close_px or 0),
        "atr": float(atr or 0),
        "symbol": _canon(symbol),
        "close_track": str(close_track or "").lower(),
        "zone_atr": reentry_zone_atr(symbol),
    }
    track = meta["close_track"]
    if track == "hard":
        meta["reason"] = "hard_stop_no_reentry"
        return False, meta
    if track not in ("radar",):
        meta["reason"] = "not_radar_close"
        return False, meta

    entry_px = float(entry or 0)
    exit_px = float(close_px or 0)
    atr_v = float(atr or 0)
    side_u = meta["side"]
    if entry_px <= 0 or exit_px <= 0 or atr_v <= 0 or side_u not in ("LONG", "SHORT"):
        meta["reason"] = "bad_inputs"
        return False, meta

    zone = reentry_zone_atr(symbol) * atr_v
    # Loss: exit worse than entry
    if side_u == "LONG" and exit_px < entry_px - 1e-12:
        meta["reason"] = "loss_no_reentry"
        return False, meta
    if side_u == "SHORT" and exit_px > entry_px + 1e-12:
        meta["reason"] = "loss_no_reentry"
        return False, meta

    # Zone: BE or micro-profit within entry..entry±zone
    if side_u == "LONG":
        lo, hi = entry_px, entry_px + zone
        in_zone = lo - 1e-9 <= exit_px <= hi + 1e-9
    else:
        lo, hi = entry_px - zone, entry_px
        in_zone = lo - 1e-9 <= exit_px <= hi + 1e-9
    meta["zone_lo"] = lo
    meta["zone_hi"] = hi
    if not in_zone:
        meta["reason"] = "outside_reentry_zone"
        return False, meta

    meta["reason"] = "ok"
    return True, meta


def classify_stop_track(
    *,
    close_action: str | None = None,
    close_trigger: str | None = None,
    fill_px: float = 0.0,
    frozen_hard_px: float = 0.0,
    radar_sl_px: float = 0.0,
    side: str | None = None,
    near_pct: float = 0.0025,
) -> str:
    """Return hard | radar | unknown from soft tags and fill proximity."""
    action = str(close_action or "").upper()
    trigger = str(close_trigger or "").lower()
    if "BREATH" in action or trigger in ("breathing_stop_hit", "radar_stop", "close_breath_stop"):
        return "radar"
    if "HARD" in action or trigger in ("hard_stop_hit", "adverse_hard"):
        return "hard"

    fill = float(fill_px or 0)
    hard = float(frozen_hard_px or 0)
    radar = float(radar_sl_px or 0)
    if fill <= 0:
        return "unknown"

    def _near(a: float, b: float) -> bool:
        if a <= 0 or b <= 0:
            return False
        return abs(a - b) / max(a, b) <= float(near_pct)

    near_hard = _near(fill, hard)
    near_radar = _near(fill, radar)
    if near_hard and not near_radar:
        return "hard"
    if near_radar and not near_hard:
        return "radar"
    if near_hard and near_radar:
        # Prefer hard if fill is further into adverse region than radar
        side_u = str(side or "").upper()
        if side_u == "LONG" and hard > 0 and radar > 0:
            return "hard" if fill <= hard + 1e-9 and hard <= radar else "radar"
        if side_u == "SHORT" and hard > 0 and radar > 0:
            return "hard" if fill >= hard - 1e-9 and hard >= radar else "radar"
        return "unknown"
    return "unknown"


def default_reentry_state() -> dict[str, Any]:
    """Fresh state after new TV clear / first open seed."""
    t0 = tier_for_attempt(0, CANONICAL_ETH)
    return {
        "reentry_attempt": 0,
        "reentry_arm_tp1_pct": float(ARM_TP1_PCTS[0]),
        "reentry_pending": False,
        "reentry_limit_oid": None,
        "reentry_limit_deadline": 0.0,
        "reentry_tv_side": None,
        "reentry_tv_px": 0.0,
        "last_close_track": None,
        "last_close_px": 0.0,
        "active_early_be_atr": float(t0.early_breakeven_atr),
        "active_step_trigger_atr": float(t0.step_trigger_atr),
        "active_step_advance_atr": float(t0.step_advance_atr),
        "reentry_abort_reason": None,
    }


def apply_tier_to_state(state: dict[str, Any], attempt: int, symbol: str | None) -> dict[str, Any]:
    tier = tier_for_attempt(attempt, symbol)
    out = dict(state or {})
    out["reentry_attempt"] = int(tier.attempt)
    out["reentry_arm_tp1_pct"] = float(tier.arm_tp1_pct)
    out["active_early_be_atr"] = float(tier.early_breakeven_atr)
    out["active_step_trigger_atr"] = float(tier.step_trigger_atr)
    out["active_step_advance_atr"] = float(tier.step_advance_atr)
    return out


def reset_reentry_state(symbol: str | None = None) -> dict[str, Any]:
    """Clear pending + reset to tier0 for symbol."""
    base = default_reentry_state()
    return apply_tier_to_state(base, 0, symbol)
