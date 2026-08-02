"""Open-time ATR — TV webhook ``atr`` only (Gemini multi-user spec §7 / §14.12).

VPS no longer fetches/computes exchange ATR for radar. Scenario labels kept as
compat aliases so persisted state / logs do not break; LIVE path is always TV.
"""

from __future__ import annotations

from typing import Any

from app.core.tp_regime_targets import placeable_tp_levels

# Compat labels (no longer switched at runtime)
ATR_SCENARIO_VPS = "vps_real"  # LEGACY — unused for LIVE decisions
ATR_SCENARIO_TV = "tv_webhook"
ATR_SCENARIO_PENDING = "pending"


def fetch_vps_1h_atr_fresh(*, client: Any = None, symbol: str | None = None) -> tuple[float, bool]:
    """LEGACY_PURGED — VPS ATR fetch disabled (§14.12). Always (0, False)."""
    _ = (client, symbol)
    return 0.0, False


def resolve_open_atr(
    *,
    client: Any = None,
    symbol: str | None = None,
    tv_atr: float = 0.0,
) -> dict[str, Any]:
    """Always use TV webhook atr. TP3 limit never active."""
    _ = (client, symbol)
    tv = float(tv_atr or 0)
    return {
        "scenario": ATR_SCENARIO_TV,
        "initial_atr": tv,
        "atr_1h": 0.0,
        "tv_atr": tv,
        "atr_source": "tv_webhook",
    }


def apply_vps_atr_upgrade(
    supervisor: Any,
    atr_1h: float,
    *,
    live_qty: float = 0.0,
) -> dict[str, Any]:
    """LEGACY_PURGED — no VPS ATR upgrade path."""
    _ = (supervisor, atr_1h, live_qty)
    return {"upgraded": False, "reason": "vps_atr_fetch_purged_use_tv_only"}


def maybe_retry_vps_atr_on_tick(supervisor: Any, live_qty: float = 0.0) -> dict[str, Any]:
    """LEGACY_PURGED — no tick-time VPS ATR retry."""
    _ = (supervisor, live_qty)
    return {"upgraded": False, "reason": "vps_atr_fetch_purged_use_tv_only"}


def supervisor_placeable_levels(supervisor: Any = None) -> frozenset[int]:
    """TP1+TP2 only (TP3 radar-managed)."""
    _ = supervisor
    return placeable_tp_levels()
