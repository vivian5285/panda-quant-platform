"""Defense order-id persistence + log retention helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from app.core.adverse_radar_guard import AdverseRadarMixin
from app.services.trading_alerts import format_radar_arm_detail_cn
from app.services.webhook_symbol_coalesce import WebhookSymbolCoalesce


class _Stub(AdverseRadarMixin):
    def __init__(self):
        self._init_adverse_radar_fields()
        self._saved = False

    def _save_state(self):
        self._saved = True


def test_defense_order_id_remember_and_clear():
    s = _Stub()
    s._remember_defense_order_id("1", 111)
    s._remember_defense_order_id("tp2", "222")
    s._remember_defense_order_id("sl", 333)
    assert s._defense_order_id("1") == 111
    assert s._defense_order_id("2") == 222
    assert s._defense_order_id("sl") == 333
    s._mark_tp_placed(1, order_id=999)
    assert s._defense_order_id("1") == 999
    assert 1 in s._tp_placed_at
    s._clear_defense_order_ids("1")
    assert s._defense_order_id("1") is None
    assert s._defense_order_id("2") == 222
    s._clear_defense_order_ids()
    assert s._defense_order_ids == {}


def test_reset_adverse_clears_order_ids():
    s = _Stub()
    s._remember_defense_order_id("1", 1)
    s._remember_defense_order_id("sl", 2)
    s._reset_adverse_radar(keep_tv_sl=False)
    assert s._defense_order_ids == {}
    assert s._tp_placed_at == {}


def test_coalesce_default_window_is_one_sec(monkeypatch):
    monkeypatch.setattr(
        "app.services.webhook_symbol_coalesce.get_settings",
        lambda: MagicMock(WEBHOOK_COALESCE_SEC=1.0),
    )
    c = WebhookSymbolCoalesce()
    assert c.window_sec() == 1.0


def test_radar_arm_detail_includes_floating_pnl():
    text = format_radar_arm_detail_cn({
        "entry": 3300,
        "curr_px": 3310,
        "new_sl": 3300.01,
        "floating_pnl": 12.5,
        "exchange": "binance",
        "symbol": "ETHUSDT",
    })
    assert "当前浮盈" in text
    assert "+12.50" in text


def test_purge_old_logs_deletes_aged_rows(db_session=None):
    """Smoke: purge function runs against empty/mocked session without error."""
    from app.services.log_retention import purge_old_logs

    db = MagicMock()
    q = MagicMock()
    q.filter.return_value = q
    q.delete.return_value = 0
    db.query.return_value = q
    out = purge_old_logs(db, days=30)
    assert out["days"] == 30
    assert "trade_logs" in out
    db.commit.assert_called_once()
