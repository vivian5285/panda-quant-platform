"""OPEN 铁律：TP123+硬止损一次挂齐；硬止损失败禁止裸奔且不推 OPEN 钉钉。"""

from unittest.mock import MagicMock, patch

from app.core.position_supervisor import PositionSupervisor


def _base_supervisor():
    client = MagicMock()
    client.exchange_id = "binance"
    client.trading_symbol = "ETHUSDT"
    client.trading_leverage = 25
    client.get_current_price.return_value = 2000.0
    client.get_open_orders.return_value = []
    client.cancel_all_open_orders.return_value = None
    client.place_market_order.return_value = {}
    client.set_leverage.return_value = None
    client.get_futures_account_summary.return_value = {
        "total_margin_balance": 1000.0,
        "available_balance": 800.0,
    }
    sup = PositionSupervisor(user_id=1, client=client, initial_principal=1000.0)
    sup.regime = 3
    sup.tv_price = 2000.0
    sup.tv_sl = 1950.0
    sup.tv_tps = [2100.0, 2200.0, 2300.0]
    sup.current_atr = 12.0
    sup.on_trade_open = MagicMock(return_value=42)
    sup._alert = MagicMock()
    sup._log = MagicMock()
    sup._save_state = MagicMock()
    return sup, client


def test_protect_returns_aborted_when_hard_sl_fails():
    sup, _ = _base_supervisor()
    sup.current_side = "LONG"
    sup._ensure_price_ws = MagicMock()
    sup._get_active_position = MagicMock(
        return_value={"size": 1.0, "entry_price": 2000.0, "side": "LONG"}
    )
    sup._smart_realign_defenses = MagicMock(
        return_value={
            "matched": 3,
            "expected": 3,
            "audit": {"matched_full": 3, "expected": 3, "levels": [], "issues": []},
            "summary": "3/3",
        }
    )
    sup._format_audit_summary = MagicMock(return_value="3/3")
    sup._sync_tv_hard_stop = MagicMock(
        return_value={"armed": False, "placed": 0, "reason": "place_failed"}
    )
    sup._close_all = MagicMock()
    with patch("threading.Thread"):
        out = sup._protect_and_monitor(1.0, 2000.0)
    assert out["aborted"] is True
    assert out["ok"] is False
    assert out["reason"] == "hard_sl_fail_abort"
    sup._close_all.assert_called_once()
    assert sup.monitoring is False


def test_open_skips_dingtalk_when_hard_sl_aborts():
    """硬止损挂失败撤仓后，禁止再推 OPEN 成功钉钉。"""
    sup, client = _base_supervisor()
    sup._apply_tv_entry_context({
        "entry_type": "OPEN",
        "regime": 3,
        "risk_pct": 2.0,
        "leverage": 25,
        "qty_ratio": 1.0,
    })
    sup._resolve_entry_qty = MagicMock(return_value=(1.0, {
        "sizing_mode": "equity20_lev5_notional",
        "order_amount": 2000,
        "sl_distance": 50,
        "sizing_source": "test",
    }))
    sup._resolve_entry_leverage = MagicMock(return_value=25)
    sup.position_manager.get_position = MagicMock(return_value={
        "positionAmt": "1.0",
        "entryPrice": "2000.0",
    })
    if hasattr(sup, "_cancel_binance_all_close_stops"):
        sup._cancel_binance_all_close_stops = MagicMock(return_value=0)

    def protect_and_set(qty, entry):
        out = {
            "ok": False,
            "aborted": True,
            "reason": "hard_sl_fail_abort",
            "defense": {},
            "shield": {},
        }
        sup._last_protect_result = out
        return out

    with patch.object(sup, "_protect_and_monitor", side_effect=protect_and_set):
        result = PositionSupervisor._open_position(sup, "LONG", 2000.0)

    assert result["status"] == "error"
    assert result["reason"] == "hard_sl_fail_abort"
    open_calls = [
        c for c in (sup._alert.call_args_list or [])
        if len(c.args) >= 2 and c.args[1] == "OPEN"
    ]
    assert open_calls == []


def test_nuclear_tp_only_never_cancel_all():
    """核武重挂只撤 TP 限价，禁止 cancel_all 误撤硬止损。"""
    from app.core.binance_smart_defense import BinanceSmartDefenseMixin

    class _T(BinanceSmartDefenseMixin):
        def __init__(self):
            self.user_id = 1
            self.symbol = "ETHUSDT"
            self.qty_unit = "ETH"
            self.client = MagicMock()
            self.current_side = "LONG"
            self.tv_tps = [2100.0, 2200.0, 2300.0]
            self.regime = 3
            self.consumed_tp_levels = []
            self.watched_qty = 1.0
            self.initial_qty = 1.0

        def _audit_tp_levels(self, live_qty, curr_px=None):
            return {
                "matched_full": 3,
                "expected": 3,
                "levels": [],
                "issues": [],
                "pending_prices": [],
            }

        def _def_log(self, *a, **k):
            pass

        def _format_audit_summary(self, audit):
            return "ok"

        def _cancel_all_tp_limit_orders(self, **kw):
            self._tp_cancelled = True
            return 3

        def _rebuild_tp_limit_orders(self, qty, entry, dynamic_sl=None):
            return 3

        def _defenses_fully_ok(self, *a, **k):
            return True

        def _ensure_radar_sl(self, *a, **k):
            return True

    t = _T()
    t._nuclear_realign_tp(1.0, 2000.0, dynamic_sl=None, rounds=1)
    assert getattr(t, "_tp_cancelled", False) is True
    t.client.cancel_all_open_orders.assert_not_called()
