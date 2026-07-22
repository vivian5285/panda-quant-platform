"""Offline verification: Binance 30m → VPS 90m timestamps + ATR/ADX vs TV-implied."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.market_engine import atr_mismatch_ratio, implied_atr_from_tv_stop  # noqa: E402
from app.core.market_indicators import (  # noqa: E402
    BAR_MS_90M,
    aggregate_30m_to_90m,
    utc_90m_bucket_ms,
    wilder_adx,
    wilder_atr_series,
)


def _load_klines(path: Path) -> list:
    text = path.read_text(encoding="utf-8").strip()
    if not text.startswith("["):
        i, j = text.find("["), text.rfind("]")
        text = text[i : j + 1]
    return json.loads(text)


def _ref_atr(cands: list[dict], period: int = 14) -> list[float]:
    if len(cands) < period + 1:
        return []
    trs = []
    for i in range(1, len(cands)):
        h, l, pc = cands[i]["high"], cands[i]["low"], cands[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = sum(trs[:period]) / period
    out = [atr]
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
        out.append(atr)
    return out


def main() -> None:
    src = Path(
        r"C:\Users\Administrator\.cursor\projects\c-Users-Administrator-Desktop-panda-quant-platform"
        r"\agent-tools\a3d29729-b6e6-4642-9d18-43cab6c40851.txt"
    )
    raw = _load_klines(src)
    now_ms = int(raw[-1][0]) + 30 * 60 * 1000
    bars90 = aggregate_30m_to_90m(raw, now_ms=now_ms)
    atr_s = wilder_atr_series(bars90, 14)
    cutoff = now_ms - 48 * 3600 * 1000
    recent = [b for b in bars90 if b["open_time"] >= cutoff]

    rows = []
    for b in recent:
        ot = int(b["open_time"])
        ct = ot + BAR_MS_90M
        tv_expected = utc_90m_bucket_ms(ot)
        rows.append({
            "vps_open_ms": ot,
            "vps_open_utc": datetime.fromtimestamp(ot / 1000, tz=timezone.utc).strftime(
                "%Y-%m-%d %H:%M"
            ),
            "vps_close_utc": datetime.fromtimestamp(ct / 1000, tz=timezone.utc).strftime(
                "%Y-%m-%d %H:%M"
            ),
            "tv_expected_open_ms": tv_expected,
            "open_match": ot == tv_expected,
            "o": round(b["open"], 2),
            "h": round(b["high"], 2),
            "l": round(b["low"], 2),
            "c": round(b["close"], 2),
        })

    adx_points = []
    for idx in range(14, len(bars90)):
        if bars90[idx]["open_time"] < cutoff:
            continue
        subset = bars90[: idx + 1]
        s = wilder_atr_series(subset, 14)
        atr = s[-1] if s else None
        adx = wilder_adx(subset, 14)
        adx_points.append({
            "open_utc": datetime.fromtimestamp(
                bars90[idx]["open_time"] / 1000, tz=timezone.utc
            ).strftime("%Y-%m-%d %H:%M"),
            "vps_atr": round(float(atr), 4) if atr else None,
            "vps_adx": round(float(adx), 4) if adx else None,
            "close": round(bars90[idx]["close"], 2),
        })

    ref = _ref_atr(bars90)
    max_self_err = 0.0
    for a, b in zip(atr_s, ref):
        if a > 0:
            max_self_err = max(max_self_err, abs(a - b) / a)

    incidents = [
        dict(label="2026-07-22 01:30 CST", entry=1930.49, stop=1915.6471582505, vps=14.8288),
        dict(label="2026-07-21 21:01 CST", entry=1901.54, stop=1901.54 - 10.74 * 1.5, vps=15.1935),
    ]
    inc_rows = []
    for inc in incidents:
        wrong = implied_atr_from_tv_stop(inc["entry"], inc["stop"], initial_sl_atr=1.5)
        right = implied_atr_from_tv_stop(inc["entry"], inc["stop"], initial_sl_atr=1.0)
        inc_rows.append({
            "label": inc["label"],
            "vps_atr": inc["vps"],
            "tv_implied_div_1_5": round(wrong, 4),
            "err_old_pct": round(atr_mismatch_ratio(inc["vps"], wrong) * 100, 2),
            "tv_implied_div_1_0": round(right, 4),
            "err_new_pct": round(atr_mismatch_ratio(inc["vps"], right) * 100, 2),
        })

    # 01:30 CST Jul 22 = 17:30 UTC Jul 21
    signal_ms = int(datetime(2026, 7, 21, 17, 30, tzinfo=timezone.utc).timestamp() * 1000)
    closed_before = [b for b in bars90 if b["open_time"] + BAR_MS_90M <= signal_ms]
    nearest = closed_before[-1] if closed_before else None
    near_atr = None
    if nearest:
        idx = bars90.index(nearest)
        s = wilder_atr_series(bars90[: idx + 1], 14)
        near_atr = s[-1] if s else None

    out = {
        "fetched_30m": len(raw),
        "closed_90m_total": len(bars90),
        "closed_90m_last_48h": len(recent),
        "all_48h_open_match_tv_epoch_formula": all(r["open_match"] for r in rows),
        "mismatched_opens": [r for r in rows if not r["open_match"]],
        "bars_48h": rows,
        "atr_adx_48h": adx_points,
        "wilder_self_check_max_err_pct": round(max_self_err * 100, 6),
        "incident_atr_compare": inc_rows,
        "nearest_bar_at_0130_cst": {
            "open_utc": (
                datetime.fromtimestamp(nearest["open_time"] / 1000, tz=timezone.utc).strftime(
                    "%Y-%m-%d %H:%M"
                )
                if nearest
                else None
            ),
            "vps_atr": round(near_atr, 4) if near_atr else None,
            "ohlc": (
                {k: round(nearest[k], 2) for k in ("open", "high", "low", "close")}
                if nearest
                else None
            ),
        },
        "latest_atr": round(atr_s[-1], 4) if atr_s else None,
        "latest_adx": round(wilder_adx(bars90, 14), 4),
    }
    out_path = ROOT / "data" / "_verify_90m_report.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", out_path)
    print("48h_bars", len(rows), "all_match", out["all_48h_open_match_tv_epoch_formula"])
    print("incident", json.dumps(inc_rows, ensure_ascii=False))
    print("near", out["nearest_bar_at_0130_cst"])
    print("latest_atr", out["latest_atr"], "adx", out["latest_adx"])
    print("self_err_pct", out["wilder_self_check_max_err_pct"])


if __name__ == "__main__":
    main()
