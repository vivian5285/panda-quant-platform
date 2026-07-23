#!/usr/bin/env python3
"""XAU minMult/maxMult sensitivity — continuous formula vs fixed discrete baseline."""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.breathing_profile import BreathingProfile, trail_distance_multiplier  # noqa: E402
from app.core.breathing_stop import apply_breathing_tick, init_breathing_state, stop_hit  # noqa: E402
from app.core.market_indicators import normalize_candle, wilder_atr  # noqa: E402

ATR_PERIOD = 14
RATIO_SMOOTH_N = 3
LOOKBACK = 1500
ENTRY_EVERY = 24
TP_EXIT_ATR = 5.0


def discrete_xau(r: float) -> float:
    r = float(r or 0)
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
    return c * 0.8


def fetch(symbol: str):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=1h&limit={LOOKBACK}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode())


def atrs_of(kl):
    candles = [normalize_candle(r) for r in kl]
    out = [0.0] * len(candles)
    for i in range(ATR_PERIOD + 1, len(candles)):
        a = float(wilder_atr(candles[: i + 1], period=ATR_PERIOD) or 0)
        out[i] = a if a > 0 else 0.0
    return out


def run(closes, highs, lows, atrs, coef_fn):
    trades = []
    i = ATR_PERIOD + 20
    n = len(closes)
    while i < n - 5:
        init_atr = atrs[i]
        if init_atr <= 0:
            i += 1
            continue
        entry = closes[i]
        state = init_breathing_state(entry, "LONG", atr=init_atr, symbol="XAUUSDT")
        ratios = []
        coef = coef_fn(1.0)
        state["breathing_coefficient"] = coef
        exit_i = exit_px = exit_reason = None
        j = i + 1
        while j < n:
            live = atrs[j]
            if live > 0:
                ratios.append(live / init_atr)
                ratios = ratios[-RATIO_SMOOTH_N:]
                smooth = sum(ratios) / len(ratios)
                coef = coef_fn(smooth)
                state["breathing_coefficient"] = coef
            hit = False
            for px in (lows[j], closes[j]):
                tick = apply_breathing_tick(
                    side="LONG",
                    price=px,
                    entry_price=float(state["entry_price"]),
                    initial_atr=float(state["initial_atr"]),
                    initial_stop=float(state["initial_stop"]),
                    current_stop=float(state["current_sl"]),
                    best_price=float(state["best_price"]),
                    breakeven_phase=bool(state["breakeven_phase"]),
                    breathing_coefficient=coef,
                    symbol="XAUUSDT",
                )
                state["current_sl"] = tick["current_sl"]
                state["best_price"] = tick["best_price"]
                state["breakeven_phase"] = tick["breakeven_phase"]
                if stop_hit("LONG", px, float(state["current_sl"])):
                    exit_i, exit_px, exit_reason = j, float(state["current_sl"]), "stop"
                    hit = True
                    break
            if hit:
                break
            if highs[j] >= entry + TP_EXIT_ATR * init_atr:
                exit_i, exit_px, exit_reason = j, entry + TP_EXIT_ATR * init_atr, "tp_far"
                break
            if j - i >= 96:
                exit_i, exit_px, exit_reason = j, closes[j], "time"
                break
            j += 1
        if exit_i is None:
            exit_i, exit_px, exit_reason = n - 1, closes[-1], "eod"
        pnl = (exit_px - entry) / init_atr
        trades.append(pnl)
        i = max(exit_i + 1, i + ENTRY_EVERY)
    wins = [p for p in trades if p > 0]
    losses = [p for p in trades if p <= 0]
    eq = peak = dd = 0.0
    for p in trades:
        eq += p
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    gw, gl = sum(wins), abs(sum(losses))
    pf = (gw / gl) if gl > 1e-12 else (999.0 if gw > 0 else 0.0)
    return {
        "n": len(trades),
        "total_pnl_R": round(sum(trades), 4),
        "winrate": round(len(wins) / len(trades), 4) if trades else 0,
        "profit_factor": round(pf, 4),
        "max_dd_R": round(dd, 4),
    }


def main():
    kl = fetch("XAUUSDT")
    closes = [float(r[4]) for r in kl]
    highs = [float(r[2]) for r in kl]
    lows = [float(r[3]) for r in kl]
    atrs = atrs_of(kl)
    disc = run(closes, highs, lows, atrs, discrete_xau)
    candidates = [
        (0.8, 1.8),  # current production (最终方案)
        (0.5, 1.2),  # ~ old effective tightness continuous
        (0.6, 1.4),
        (0.7, 1.5),
        (0.5, 1.0),
        (0.4, 1.04),  # literal old ends
    ]
    rows = [{"label": "discrete_old", **disc}]
    for mn, mx in candidates:
        p = BreathingProfile(symbol_tag="XAU", coef_min=mn, coef_max=mx, stop_order_buffer=0.5,
                             early_breakeven_atr=0.3, step_trigger_atr=0.4, step_advance_atr=0.35)

        def fn(r, _p=p):
            rr = float(r or 0) or 1.0
            return trail_distance_multiplier(rr, _p)

        m = run(closes, highs, lows, atrs, fn)
        rows.append({"label": f"cont_{mn}_{mx}", "min": mn, "max": mx, **m,
                     "delta_vs_disc": round(m["total_pnl_R"] - disc["total_pnl_R"], 4)})
    # pick best continuous by total pnl then pf
    cont_rows = [r for r in rows if r["label"].startswith("cont_")]
    best = max(cont_rows, key=lambda r: (r["total_pnl_R"], r["profit_factor"]))
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "discrete_baseline": disc,
        "candidates": rows,
        "recommended": best,
        "note": "Production currently uses 0.8/1.8 per 最终方案; sensitivity may recommend tighter band.",
    }
    out = ROOT / "data" / "_xau_min_max_sensitivity.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("RECOMMENDED", best["label"], best)


if __name__ == "__main__":
    main()
