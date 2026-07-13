"""Tests for radar-driven obsolete TP limit cancellation."""

from unittest.mock import MagicMock

import pytest

from app.core.tp_orphan_guard import (
    format_obsolete_tp_detail,
    tp_levels_obsolete_by_radar,
)
from app.core.binance_smart_defense import BinanceSmartDefenseMixin


class _OrphanHost(BinanceSmartDefenseMixin):
    def __init__(self):
        self.symbol = "ETHUSDT"
        self.current_side = "LONG"
        self.tv_tps = [1836.0, 1850.0, 1870.0]
        self.consumed_tp_levels = []
        self.client = MagicMock()
        self._log = MagicMock()
        self._alert = MagicMock()

    def _def_log(self, msg, level=None):
        pass

    def _collect_tp_limit_orders(self):
        return [
            {"orderId": 1, "price": 1836.0},
            {"orderId": 2, "price": 1850.0},
            {"orderId": 3, "price": 1870.0},
        ]


class TestTpLevelsObsoleteByRadar:
    def test_long_radar_above_tp1_marks_obsolete(self):
        levels = tp_levels_obsolete_by_radar(1840.0, "LONG", [1836.0, 1850.0, 1870.0])
        assert levels == [1]

    def test_long_radar_above_tp1_and_tp2(self):
        levels = tp_levels_obsolete_by_radar(1855.0, "LONG", [1836.0, 1850.0, 1870.0])
        assert levels == [1, 2]

    def test_long_radar_below_tp1_no_obsolete(self):
        levels = tp_levels_obsolete_by_radar(1830.0, "LONG", [1836.0, 1850.0, 1870.0])
        assert levels == []

    def test_short_radar_below_tp1_marks_obsolete(self):
        levels = tp_levels_obsolete_by_radar(1795.0, "SHORT", [1800.0, 1780.0, 1750.0])
        assert levels == [1]

    def test_skips_consumed_levels(self):
        levels = tp_levels_obsolete_by_radar(
            1855.0, "LONG", [1836.0, 1850.0, 1870.0], consumed_levels=[1],
        )
        assert levels == [2]

    def test_format_detail(self):
        detail = format_obsolete_tp_detail([1, 2], 1855.0, [1836.0, 1850.0, 1870.0], "LONG")
        assert detail["obsolete_levels"] == [1, 2]
        assert detail["tp_prices"]["tp1"] == 1836.0
        assert detail["reason"] == "radar_sl_passed_tp"


class TestCancelObsoleteTpMixin:
    def test_cancels_tp1_when_radar_passed(self):
        host = _OrphanHost()
        result = host._cancel_obsolete_tp_after_radar_move(1840.0)
        assert result["cancelled"] == 1
        host.client.cancel_order.assert_called_once_with("ETHUSDT", 1)
        host._alert.assert_called_once()
        assert host._alert.call_args[0][1] == "TP_ORPHAN_PURGE"

    def test_no_cancel_when_radar_below_tp1(self):
        host = _OrphanHost()
        result = host._cancel_obsolete_tp_after_radar_move(1820.0)
        assert result["cancelled"] == 0
        host.client.cancel_order.assert_not_called()
