"""Pine v6.9.94 TP qty_percent alignment — all exchanges share regime_settings."""

from app.core.tp_regime_ratios import (
    PINE_TP_QTY_PERCENT,
    build_regime_settings,
    enrich_tp_alert_detail,
    format_tp_ratio_pct,
    pine_tp_ratios_frac,
)
from app.core.position_supervisor import PositionSupervisor
from app.core.position_supervisor_deepcoin import DeepcoinPositionSupervisor
from unittest.mock import MagicMock


def test_pine_tp_percent_table_matches_strategy():
    assert PINE_TP_QTY_PERCENT[1] == (25, 35, 40)
    assert PINE_TP_QTY_PERCENT[2] == (20, 35, 45)
    assert PINE_TP_QTY_PERCENT[3] == (18, 32, 50)
    assert PINE_TP_QTY_PERCENT[4] == (5, 20, 75)


def test_regime_ratios_frac_sum_to_one():
    for regime in (1, 2, 3, 4):
        ratios = pine_tp_ratios_frac(regime)
        assert len(ratios) == 3
        assert abs(sum(ratios) - 1.0) < 1e-9


def test_build_regime_settings_all_exchanges_same_ratios():
    settings = build_regime_settings()
    for regime in (1, 2, 3, 4):
        assert settings[regime]["ratios"] == pine_tp_ratios_frac(regime)


def test_supervisors_use_central_pine_ratios():
    client = MagicMock()
    client.trading_leverage = 20
    client.trading_symbol = "ETHUSDT"
    binance = PositionSupervisor(1, client)
    deepcoin = DeepcoinPositionSupervisor(2, client)
    for regime in (1, 2, 3, 4):
        assert binance.regime_settings[regime]["ratios"] == pine_tp_ratios_frac(regime)
        assert deepcoin.regime_settings[regime]["ratios"] == pine_tp_ratios_frac(regime)


def test_enrich_tp_alert_detail_for_dingtalk():
    detail = enrich_tp_alert_detail({"qty": 1.0}, regime=1)
    assert detail["tp_ratios_pct"] == "25/35/40"
    assert detail["regime"] == 1
    assert detail["tp_ratios"] == [0.25, 0.35, 0.40]


def test_format_tp_ratio_label():
    assert format_tp_ratio_pct(3) == "18/32/50"
