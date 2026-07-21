"""TP qty ratios — fixed 30/30/40 for all exchanges (checklist 简洁版)."""

from app.core.tp_regime_targets import (
    FIXED_TP_QTY_PERCENT,
    PINE_TP_QTY_PERCENT,
    PLACEABLE_TP_LEVELS,
    build_regime_settings,
    enrich_tp_alert_detail,
    format_tp_ratio_pct,
    pine_tp_ratios_frac,
    resolve_tp_ratios_from_payload,
)
from app.core.position_supervisor import PositionSupervisor
from app.core.position_supervisor_deepcoin import DeepcoinPositionSupervisor
from unittest.mock import MagicMock


def test_fixed_tp_percent_all_regimes():
    assert FIXED_TP_QTY_PERCENT == (30, 30, 40)
    assert PLACEABLE_TP_LEVELS == frozenset({1, 2, 3})
    for regime in (1, 2, 3, 4):
        assert PINE_TP_QTY_PERCENT[regime] == (30, 30, 40)


def test_regime_ratios_frac_sum_to_one():
    for regime in (1, 2, 3, 4):
        ratios = pine_tp_ratios_frac(regime)
        assert ratios == [0.3, 0.3, 0.4]
        assert abs(sum(ratios) - 1.0) < 1e-9


def test_tv_qty_ignored():
    r = resolve_tp_ratios_from_payload({"qty1": 1, "qty2": 2, "qty3": 7})
    assert r == [0.3, 0.3, 0.4]


def test_build_regime_settings_all_exchanges_same_ratios():
    settings = build_regime_settings()
    for regime in (1, 2, 3, 4):
        assert settings[regime]["ratios"] == [0.3, 0.3, 0.4]


def test_supervisors_use_central_pine_ratios():
    client = MagicMock()
    client.trading_leverage = 20
    client.trading_symbol = "ETHUSDT"
    client.exchange_id = "binance"
    binance = PositionSupervisor(1, client)
    deepcoin = DeepcoinPositionSupervisor(2, client)
    for regime in (1, 2, 3, 4):
        assert binance.regime_settings[regime]["ratios"] == [0.3, 0.3, 0.4]
        assert deepcoin.regime_settings[regime]["ratios"] == [0.3, 0.3, 0.4]


def test_enrich_tp_alert_detail_for_dingtalk():
    detail = enrich_tp_alert_detail({"qty": 1.0}, regime=1)
    assert detail["tp_ratios_pct"] == "30/30/40"
    assert detail["regime"] == 1
    assert detail["tp_ratios"] == [0.3, 0.3, 0.4]
    assert detail["tp3_limit_placed"] is True
    assert detail["tp_placeable_levels"] == [1, 2, 3]


def test_format_tp_ratio_label():
    assert format_tp_ratio_pct(3) == "30/30/40"
