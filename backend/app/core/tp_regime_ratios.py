"""Compat re-export — canonical TP module is ``tp_regime_targets``.

Checklist 简洁版: fixed 30/30/40, place TP1+TP2+TP3 limits @ TV prices,
ignore TV qty1/qty2/qty3. Prefer importing from ``tp_regime_targets`` in new code.
"""

from __future__ import annotations

from app.core.tp_regime_targets import (  # noqa: F401
    FIXED_TP_QTY_PERCENT,
    PINE_TP_QTY_PERCENT,
    PLACEABLE_TP_LEVELS,
    REGIME_MARGIN_PCT,
    build_regime_settings,
    clamp_regime,
    enrich_tp_alert_detail,
    format_tp_ratio_pct,
    pine_tp_ratios_frac,
    resolve_tp_ratios_from_payload,
)

__all__ = [
    "FIXED_TP_QTY_PERCENT",
    "PINE_TP_QTY_PERCENT",
    "PLACEABLE_TP_LEVELS",
    "REGIME_MARGIN_PCT",
    "build_regime_settings",
    "clamp_regime",
    "enrich_tp_alert_detail",
    "format_tp_ratio_pct",
    "pine_tp_ratios_frac",
    "resolve_tp_ratios_from_payload",
]
