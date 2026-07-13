"""Cancel TP limit orders made obsolete by radar SL advancement."""

from __future__ import annotations

from typing import Any

from app.core.tp_defense_reconcile import tp_price_matches


def tp_levels_obsolete_by_radar(
    radar_sl: float,
    side: str | None,
    tv_tps: list[float],
    *,
    consumed_levels: list[int] | None = None,
    max_level: int = 2,
) -> list[int]:
    """
    TP1/TP2 limits below radar protection are pointless (LONG: radar >= TP price).
    Only checks levels 1..max_level (default TP1+TP2).
    """
    radar_sl = float(radar_sl or 0)
    if radar_sl <= 0 or side not in ("LONG", "SHORT"):
        return []
    consumed = set(int(x) for x in (consumed_levels or []) if int(x) in (1, 2, 3))
    obsolete: list[int] = []
    for i, raw in enumerate(tv_tps or []):
        level = i + 1
        if level > max_level or level in consumed:
            continue
        px = float(raw or 0)
        if px <= 0:
            continue
        if side == "LONG" and radar_sl >= px:
            obsolete.append(level)
        elif side == "SHORT" and radar_sl <= px:
            obsolete.append(level)
    return obsolete


def format_obsolete_tp_detail(
    obsolete_levels: list[int],
    radar_sl: float,
    tv_tps: list[float],
    side: str | None,
) -> dict[str, Any]:
    prices = {}
    for lv in obsolete_levels:
        idx = lv - 1
        if 0 <= idx < len(tv_tps or []):
            prices[f"tp{lv}"] = float(tv_tps[idx] or 0)
    return {
        "obsolete_levels": obsolete_levels,
        "radar_sl": round(float(radar_sl or 0), 2),
        "side": side,
        "tp_prices": prices,
        "reason": "radar_sl_passed_tp",
    }
