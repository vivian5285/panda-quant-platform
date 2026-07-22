"""OPEN 后短时间内忽略裸 CLOSE / 迟到 CLOSE_QUICK·RSI，防 TV 换防误杀。"""

import time
from unittest.mock import MagicMock

from app.core.startup_reconcile import (
    OPEN_BARE_CLOSE_GRACE_SEC,
    OPEN_FORCE_CLOSE_GRACE_SEC,
    should_ignore_bare_close_after_open,
    should_ignore_late_close_after_open,
)


class _Sup:
    def __init__(self, **kwargs):
        self.trade_opened_at = time.time() - 2
        self.current_trade_id = 101
        self.adopted_manual = False
        self.current_side = "LONG"
        self.watched_qty = 1.5
        self.symbol = "ETHUSDT"
        self.position_manager = MagicMock()
        self.position_manager.get_position.return_value = {
            "positionAmt": 1.5,
            "entryPrice": 1935.0,
        }
        for k, v in kwargs.items():
            setattr(self, k, v)


def test_bare_close_ignored_within_grace():
    skip, reason = should_ignore_bare_close_after_open(_Sup(), "CLOSE")
    assert skip is True
    assert "忽略裸 CLOSE" in reason


def test_stoploss_close_not_ignored():
    skip, _ = should_ignore_bare_close_after_open(_Sup(), "CLOSE_STOPLOSS")
    assert skip is False


def test_protect_and_tp3_not_ignored():
    for action in ("CLOSE_PROTECT", "CLOSE_TP3"):
        skip, _ = should_ignore_bare_close_after_open(_Sup(), action)
        assert skip is False


def test_grace_expires():
    sup = _Sup(trade_opened_at=time.time() - OPEN_BARE_CLOSE_GRACE_SEC - 1)
    skip, _ = should_ignore_bare_close_after_open(sup, "CLOSE")
    assert skip is False


def test_no_position_not_ignored():
    sup = _Sup(watched_qty=0, current_side=None)
    sup.position_manager.get_position.return_value = {"positionAmt": 0}
    skip, _ = should_ignore_bare_close_after_open(sup, "CLOSE")
    assert skip is False


def test_late_quick_exit_ignored_within_force_grace():
    skip, reason = should_ignore_late_close_after_open(_Sup(), "CLOSE_QUICK_EXIT")
    assert skip is True
    assert "忽略迟到平仓" in reason


def test_late_rsi_exit_ignored_within_force_grace():
    skip, _ = should_ignore_late_close_after_open(_Sup(), "CLOSE_RSI_EXIT")
    assert skip is True


def test_late_force_grace_expires():
    sup = _Sup(trade_opened_at=time.time() - OPEN_FORCE_CLOSE_GRACE_SEC - 0.5)
    skip, _ = should_ignore_late_close_after_open(sup, "CLOSE_QUICK_EXIT")
    assert skip is False


def test_force_grace_is_five_seconds():
    assert OPEN_FORCE_CLOSE_GRACE_SEC == 5.0
