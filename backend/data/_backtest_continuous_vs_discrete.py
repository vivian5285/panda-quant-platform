#!/usr/bin/env python3
"""Historical backtest: continuous trailDistanceMultiplier vs old discrete ladder.

Uses Binance public 1h klines. Simulates breathing-stop exits for both coef formulas
on the same entries, then compares PnL / DD / winrate / profit factor, with extra
focus near old discrete breakpoints (0.7 / 1.0 / 1.4 / 2.0).

No real funds. Writes JSON report under backend/data/.
"""

from __future__ import annotations

import json
import math
import sys
import time
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

# Allow running from repo root or backend/
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.breathing_profile import (  # noqa: E402
    ETH_PROFILE,
    XAU_PROFILE,
    trail_distance_multiplier,
)
from app.core.breathing_stop import (  # noqa: E402
    apply_breathing_tick,
    compute_initial_stop,
    init_breathing_state,
    stop_hit,
)
from app.core.market_indicators import normalize_candle, wilder_atr  # noqa: E402

ATR_PERIOD = 14
RATIO_SMOOTH_N = 3
# Sample breath coef every N bars (1h bars → ~5 min wall would be sub-bar;
# for 1h backtest we refresh every bar = conservative continuous update)
BARS_PER_SAMPLE = 1
LOOKBACK_BARS = 1500  # ~62 days of 1h
ENTRY_EVERY = 24  # open a synthetic long every N bars when flat
PHASE2_ATR = 3.0
TP1_ATR = 1.35
# Intentionally ABOVE phase2 gate so trailDistanceMultiplier is exercised.
# (Live TP2 fills reduce qty but residual can enter phase2; this isolates coef effect.)
TP_EXIT_ATR = 5.0


def discrete_coef(smooth_ratio: float, symbol: str) -> float:
    """Old deepseek discrete ladder (pre-aab2e41), including XAU trail_tighten=0.8."""
    r = float(smooth_ratio or 0)
    if symbol.upper().startswith("XAU"):
        if r <= 0:
            return 0.9 * 0.8
        if r < 0.7:
            c = 0.5
        elif r < 1.0:
            c = 0.7
        elif r < 1.4:
            c = 0.9
        elif r < 2.0:
            c = 1.0 + (r - 1.4) / 0.6 * 0.2
        else:
            c = 1.3
        return c * 0.8  # old trail_tighten
    # ETH
    if r <= 0:
        return 1.0
    if r < 0.7:
        return 0.7
    if r < 1.0:
        return 0.85
    if r < 1.4:
        return 1.0
    if r < 2.0:
        return 1.2 + (r - 1.4) / 0.6 * 0.2
    return 1.5


def continuous_coef(smooth_ratio: float, symbol: str) -> float:
    p = XAU_PROFILE if symbol.upper().startswith("XAU") else ETH_PROFILE
    r = float(smooth_ratio or 0)
    if r <= 0:
        r = 1.0
    return trail_distance_multiplier(r, p)


def fetch_klines(symbol: str, limit: int = LOOKBACK_BARS) -> list[list]:
    url = (
        "https://fapi.binance.com/fapi/v1/klines"
        f"?symbol={symbol}&interval=1h&limit={min(limit, 1500)}"
    )
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode())


def atr_series(klines: list) -> list[float]:
    candles = [normalize_candle(r) for r in klines]
    out: list[float] = [0.0] * len(candles)
    # rolling Wilder ATR ending at each bar
    for i in range(ATR_PERIOD + 1, len(candles)):
        window = candles[: i + 1]
        a = float(wilder_atr(window, period=ATR_PERIOD) or 0)
        out[i] = a if a > 0 else 0.0
    return out


@dataclass
class Trade:
    entry_i: int
    exit_i: int
    side: str
    entry: float
    exit: float
    initial_atr: float
    pnl_r: float  # PnL in ATR units (R)
    exit_reason: str
    near_breakpoints: list[str]
    coef_path_sample: list[float]
    smooth_path_sample: list[float]


def _near_bp(smooth: float) -> list[str]:
    tags = []
    for bp in (0.7, 1.0, 1.4, 2.0):
        if abs(smooth - bp) <= 0.08:
            tags.append(f"~{bp}")
    return tags


def run_mode(
    symbol: str,
    closes: list[float],
    highs: list[float],
    lows: list[float],
    atrs: list[float],
    mode: str,
) -> dict[str, Any]:
    coef_fn = continuous_coef if mode == "continuous" else discrete_coef
    trades: list[Trade] = []
    i = ATR_PERIOD + 20
    n = len(closes)
    while i < n - 5:
        init_atr = atrs[i]
        if init_atr <= 0:
            i += 1
            continue
        # synthetic entry: long at close
        side = "LONG"
        entry = closes[i]
        state = init_breathing_state(entry, side, atr=init_atr, symbol=symbol)
        ratios: list[float] = []
        coef = coef_fn(1.0, symbol)  # cold start
        state["breathing_coefficient"] = coef
        near: list[str] = []
        coef_samples: list[float] = [coef]
        smooth_samples: list[float] = [1.0]
        exit_i = None
        exit_px = None
        exit_reason = None
        j = i + 1
        while j < n:
            # refresh ratio each bar from live ATR / initial
            live = atrs[j]
            if live > 0 and init_atr > 0:
                ratios.append(live / init_atr)
                if len(ratios) > RATIO_SMOOTH_N:
                    ratios = ratios[-RATIO_SMOOTH_N:]
                smooth = sum(ratios) / len(ratios)
                coef = coef_fn(smooth, symbol)
                state["breathing_coefficient"] = coef
                near.extend(_near_bp(smooth))
                if j % 6 == 0:
                    coef_samples.append(round(coef, 4))
                    smooth_samples.append(round(smooth, 4))

            # intrabar stop check: adverse extreme first, then close tick
            px_path = [lows[j], closes[j]] if side == "LONG" else [highs[j], closes[j]]
            hit = False
            for px in px_path:
                tick = apply_breathing_tick(
                    side=side,
                    price=px,
                    entry_price=float(state["entry_price"]),
                    initial_atr=float(state["initial_atr"]),
                    initial_stop=float(state["initial_stop"]),
                    current_stop=float(state["current_sl"]),
                    best_price=float(state["best_price"]),
                    breakeven_phase=bool(state["breakeven_phase"]),
                    breathing_coefficient=coef,
                    symbol=symbol,
                )
                state["current_sl"] = tick["current_sl"]
                state["best_price"] = tick["best_price"]
                state["breakeven_phase"] = tick["breakeven_phase"]
                state["breathing_coefficient"] = tick["breathing_coefficient"]
                if stop_hit(side, px, float(state.get("current_sl") or 0)):
                    exit_i = j
                    exit_px = float(state["current_sl"])
                    exit_reason = "stop"
                    hit = True
                    break
            if hit:
                break
            # soft far TP (above phase2) — same for both modes; residual path exercises trail
            if side == "LONG" and highs[j] >= entry + TP_EXIT_ATR * init_atr:
                exit_i = j
                exit_px = entry + TP_EXIT_ATR * init_atr
                exit_reason = "tp_far"
                break
            # time stop: 96h — allow phase2 trails to matter
            if j - i >= 96:
                exit_i = j
                exit_px = closes[j]
                exit_reason = "time"
                break
            j += 1
        if exit_i is None:
            exit_i = n - 1
            exit_px = closes[-1]
            exit_reason = "eod"
        pnl = (exit_px - entry) / init_atr if side == "LONG" else (entry - exit_px) / init_atr
        reached_p2 = bool(state.get("breakeven_phase"))
        trades.append(
            Trade(
                entry_i=i,
                exit_i=exit_i,
                side=side,
                entry=entry,
                exit=float(exit_px),
                initial_atr=init_atr,
                pnl_r=pnl,
                exit_reason=("phase2_" + (exit_reason or "?")) if reached_p2 else (exit_reason or "?"),
                near_breakpoints=sorted(set(near)),
                coef_path_sample=coef_samples[:12],
                smooth_path_sample=smooth_samples[:12],
            )
        )
        i = max(exit_i + 1, i + ENTRY_EVERY)

    pnls = [t.pnl_r for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    gross_win = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0
    pf = (gross_win / gross_loss) if gross_loss > 1e-12 else (999.0 if gross_win > 0 else 0.0)
    near_trades = [t for t in trades if t.near_breakpoints]
    p2_trades = [t for t in trades if str(t.exit_reason).startswith("phase2_")]
    stop_exits = sum(1 for t in trades if "stop" in str(t.exit_reason))
    return {
        "mode": mode,
        "symbol": symbol,
        "n_trades": len(trades),
        "total_pnl_R": round(sum(pnls), 4),
        "winrate": round(len(wins) / len(pnls), 4) if pnls else 0.0,
        "profit_factor": round(pf, 4),
        "max_drawdown_R": round(max_dd, 4),
        "avg_pnl_R": round(sum(pnls) / len(pnls), 4) if pnls else 0.0,
        "stop_exit_pct": round(stop_exits / len(trades), 4) if trades else 0.0,
        "phase2_trade_pct": round(len(p2_trades) / len(trades), 4) if trades else 0.0,
        "phase2_avg_pnl_R": round(sum(t.pnl_r for t in p2_trades) / len(p2_trades), 4) if p2_trades else None,
        "near_breakpoint_trades": len(near_trades),
        "near_breakpoint_avg_pnl_R": round(
            sum(t.pnl_r for t in near_trades) / len(near_trades), 4
        )
        if near_trades
        else None,
        "exit_reasons": {
            k: sum(1 for t in trades if t.exit_reason == k)
            for k in (
                "stop", "tp_far", "time", "eod",
                "phase2_stop", "phase2_tp_far", "phase2_time", "phase2_eod",
            )
        },
        "sample_near_trades": [
            {
                "pnl_R": round(t.pnl_r, 4),
                "exit_reason": t.exit_reason,
                "near": t.near_breakpoints,
                "coef_path": t.coef_path_sample,
                "smooth_path": t.smooth_path_sample,
                "entry": t.entry,
                "exit": t.exit,
            }
            for t in near_trades[:8]
        ],
        "sample_phase2_trades": [
            {
                "pnl_R": round(t.pnl_r, 4),
                "exit_reason": t.exit_reason,
                "coef_path": t.coef_path_sample,
                "smooth_path": t.smooth_path_sample,
            }
            for t in p2_trades[:8]
        ],
    }


def jump_analysis(symbol: str) -> dict[str, Any]:
    """Uniform 0.01 ratio grid — continuous must have smaller max step than discrete."""
    rows = []
    rs = [round(x * 0.01, 2) for x in range(50, 231)]  # 0.50 .. 2.30
    for r in rs:
        rows.append(
            {
                "ratio": r,
                "continuous": round(continuous_coef(r, symbol), 6),
                "discrete": round(discrete_coef(r, symbol), 6),
                "delta": round(continuous_coef(r, symbol) - discrete_coef(r, symbol), 6),
                "cont_jump_vs_prev": None,
                "disc_jump_vs_prev": None,
            }
        )
    for i in range(1, len(rows)):
        rows[i]["cont_jump_vs_prev"] = round(rows[i]["continuous"] - rows[i - 1]["continuous"], 6)
        rows[i]["disc_jump_vs_prev"] = round(rows[i]["discrete"] - rows[i - 1]["discrete"], 6)
    max_disc_jump = max(abs(x["disc_jump_vs_prev"] or 0) for x in rows)
    max_cont_jump = max(abs(x["cont_jump_vs_prev"] or 0) for x in rows)
    # spotlight old breakpoints
    spotlight = [x for x in rows if x["ratio"] in (0.69, 0.70, 0.71, 0.99, 1.00, 1.01, 1.39, 1.40, 1.41, 1.99, 2.00, 2.01)]
    return {
        "symbol": symbol,
        "max_abs_discrete_step": max_disc_jump,
        "max_abs_continuous_step": max_cont_jump,
        "continuous_smoother": max_cont_jump <= max_disc_jump + 1e-12,
        "breakpoint_spotlight": spotlight,
        "grid_head": rows[:5],
        "grid_tail": rows[-5:],
    }


def main() -> int:
    report: dict[str, Any] = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "head_note": "continuous = aab2e41 trailDistanceMultiplier; discrete = pre-aab2e41 ladder",
        "params": {
            "lookback_bars": LOOKBACK_BARS,
            "entry_every": ENTRY_EVERY,
            "tp_exit_atr": TP_EXIT_ATR,
            "time_stop_bars": 96,
        },
        "symbols": {},
        "breakpoint_continuity": {},
    }
    for symbol in ("ETHUSDT", "XAUUSDT"):
        print(f"fetch {symbol} ...")
        kl = fetch_klines(symbol, LOOKBACK_BARS)
        closes = [float(r[4]) for r in kl]
        highs = [float(r[2]) for r in kl]
        lows = [float(r[3]) for r in kl]
        atrs = atr_series(kl)
        cont = run_mode(symbol, closes, highs, lows, atrs, "continuous")
        disc = run_mode(symbol, closes, highs, lows, atrs, "discrete")
        report["symbols"][symbol] = {
            "continuous": cont,
            "discrete": disc,
            "delta_total_pnl_R": round(cont["total_pnl_R"] - disc["total_pnl_R"], 4),
            "delta_max_dd_R": round(cont["max_drawdown_R"] - disc["max_drawdown_R"], 4),
            "delta_winrate": round(cont["winrate"] - disc["winrate"], 4),
            "delta_pf": round(cont["profit_factor"] - disc["profit_factor"], 4),
            "continuous_not_worse_overall": (
                cont["total_pnl_R"] >= disc["total_pnl_R"] * 0.85
                or cont["max_drawdown_R"] <= disc["max_drawdown_R"] * 1.15
            ),
        }
        report["breakpoint_continuity"][symbol] = jump_analysis(symbol)
        print(
            symbol,
            "CONT",
            cont["total_pnl_R"],
            "WR",
            cont["winrate"],
            "PF",
            cont["profit_factor"],
            "DD",
            cont["max_drawdown_R"],
            "| DISC",
            disc["total_pnl_R"],
            disc["winrate"],
            disc["profit_factor"],
            disc["max_drawdown_R"],
        )

    out = ROOT / "data" / "_continuous_vs_discrete_backtest_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("WROTE", out)
    # verdict
    ok = True
    for sym, block in report["symbols"].items():
        if not report["breakpoint_continuity"][sym]["continuous_smoother"]:
            ok = False
            print("WARN smoother fail", sym)
        print(
            "SUMMARY",
            sym,
            "pnl_delta",
            block["delta_total_pnl_R"],
            "dd_delta",
            block["delta_max_dd_R"],
            "okish",
            block["continuous_not_worse_overall"],
        )
    report["verdict_pass"] = ok and all(
        b["continuous_not_worse_overall"] for b in report["symbols"].values()
    )
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("VERDICT", "PASS" if report["verdict_pass"] else "REVIEW_PARAMS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
