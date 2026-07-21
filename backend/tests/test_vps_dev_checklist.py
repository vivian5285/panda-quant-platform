"""VPS 开发清单（最终版）— 四交易所统一验收."""

import inspect

import pytest

from app.config import exchange_leverage, get_settings
from app.core.adverse_radar_guard import AdverseRadarMixin
from app.core.exchange_factory import SUPPORTED_EXCHANGES, create_supervisor
from app.core.position_supervisor import PositionSupervisor
from app.core.position_supervisor_deepcoin import DeepcoinPositionSupervisor
from app.core.startup_reconcile import StartupReconcileMixin
from app.core.tv_entry_sizing import (
    MAX_LEVERAGE,
    RISK_PCT,
    compute_tv_entry_qty,
    resolve_vps_entry_qty_deepcoin,
    resolve_vps_entry_qty_eth,
)
from app.core.tp_regime_ratios import PLACEABLE_TP_LEVELS
from app.core.ws_reconnect import ws_reconnect_delay
from app.models import ExchangeType, User
from app.services.trading_alerts import should_push_trading_dingtalk
from app.services.webhook_guard import VALID_ACTIONS
from app.services.webhook_payload import normalize_tv_payload
from unittest.mock import MagicMock, patch


def test_checklist_risk20_cap5x_sizing():
    """清单§四：风险资金=权益×20%；名义上限=权益×5；取 min 并受 TV.qty 封顶。"""
    assert RISK_PCT == 0.20 and MAX_LEVERAGE == 5
    qty, meta = compute_tv_entry_qty(
        live_balance=1000, initial_principal=1000, price=2000, tv_sl=1900,
    )
    # risk=200 / stop=100 → 2.0; notional=5000/2000=2.5 → qty=2.0
    assert abs(qty - 2.0) < 1e-9
    assert "risk20" in str(meta.get("sizing_mode") or meta.get("binding") or "")
    qty2, m2 = compute_tv_entry_qty(
        live_balance=1000, initial_principal=1000, price=2000, tv_sl=1900, tv_qty=0.5,
    )
    assert abs(qty2 - 0.5) < 1e-9


def test_checklist_tv_fields_parsed():
    raw = {
        "action": "LONG",
        "token": "528586",
        "symbol": "ETHUSDT",
        "price": "3300.5",
        "qty": 12,
        "qty1": 3,
        "qty2": 3,
        "qty3": 6,
        "stop_loss": 3200.5,
        "tp1": 3350,
        "tp2": 3480,
        "tp3": 3560,
    }
    norm = normalize_tv_payload(raw)
    assert norm["action"] == "LONG"
    assert float(norm.get("stop_loss") or norm.get("tv_sl") or 0) == 3200.5
    assert PLACEABLE_TP_LEVELS == frozenset({1, 2})
    assert VALID_ACTIONS == frozenset({
        "LONG", "SHORT", "CLOSE_QUICK_EXIT", "CLOSE_RSI_EXIT",
    })


@pytest.mark.parametrize("exchange", ["binance", "okx", "gate", "deepcoin"])
def test_trading_factory_all_exchanges_supervisor(exchange):
    settings = get_settings()
    assert exchange_leverage(exchange) == 25

    user = User(id=1, exchange=exchange)
    client = MagicMock()
    client.exchange_id = exchange
    client.canonical_symbol = "ETHUSDT"
    client.trading_leverage = 25
    client.trading_symbol = "ETHUSDT"

    if exchange == "deepcoin":
        with patch.object(DeepcoinPositionSupervisor, "_start_idle_flat_patrol"), patch.object(
            DeepcoinPositionSupervisor, "_start_signal_worker"
        ):
            sup = create_supervisor(user, client)
        assert isinstance(sup, DeepcoinPositionSupervisor)
        assert hasattr(sup, "_place_limit_with_retry")
        assert hasattr(sup, "recover_on_startup")
    else:
        with patch.object(PositionSupervisor, "_start_idle_flat_patrol"):
            sup = create_supervisor(user, client)
        assert isinstance(sup, PositionSupervisor)
        assert hasattr(sup, "_place_limit_with_retry")
        assert hasattr(sup, "recover_on_startup")

    assert exchange in SUPPORTED_EXCHANGES or exchange == ExchangeType.BINANCE.value


def test_all_supervisors_share_radar_and_startup_mixins():
    for cls in (PositionSupervisor, DeepcoinPositionSupervisor):
        mro_names = {c.__name__ for c in cls.__mro__}
        assert AdverseRadarMixin.__name__ in mro_names
        assert StartupReconcileMixin.__name__ in mro_names


def test_eth_and_deepcoin_use_same_vps_resolver_entry_points():
    assert "resolve_vps_entry_qty_eth" in inspect.getsource(PositionSupervisor._resolve_entry_qty)
    assert "resolve_vps_entry_qty_deepcoin" in inspect.getsource(
        DeepcoinPositionSupervisor._resolve_entry_qty
    )


def test_dingtalk_push_checklist_events():
    assert should_push_trading_dingtalk("OPEN", "info") is True
    assert should_push_trading_dingtalk("STARTUP", "info") is True
    assert should_push_trading_dingtalk("RADAR_ARM", "info") is True
    assert should_push_trading_dingtalk("TP_FILLED", "info") is True
    assert should_push_trading_dingtalk("FORCE_ALIGN", "critical") is True
    assert should_push_trading_dingtalk("TRAIL", "info") is True
    assert should_push_trading_dingtalk("CLOSE_QUICK_EXIT", "info") is True


def test_config_leverage_and_webhook_defaults():
    s = get_settings()
    assert s.WEBHOOK_SECRET == "528586" or len(str(s.WEBHOOK_SECRET)) > 0
    assert s.LEVERAGE == 25
    assert s.DEEPCOIN_LEVERAGE == 25
    assert s.OKX_LEVERAGE == 25
    assert s.GATE_LEVERAGE == 25


def test_ws_reconnect_exponential_all_exchanges():
    assert ws_reconnect_delay(0) == 1.0
    assert ws_reconnect_delay(1) == 2.0
    assert ws_reconnect_delay(2) == 4.0


def test_resolve_entry_qty_eth_requires_stop():
    qty, meta = resolve_vps_entry_qty_eth(
        live_balance=1000.0,
        initial_principal=1000.0,
        entry_type="OPEN",
        base_qty=0,
        price=1892.43,
        tv_sl=0,
        regime=3,
        exchange_leverage=25,
        round_fn=lambda x: x,
    )
    assert qty == 0
    err = str(meta.get("error") or "")
    assert "missing" in err and "stop" in err or "sl" in err


def test_resolve_entry_qty_deepcoin_open_contracts():
    price = 2000.0
    qty, meta = resolve_vps_entry_qty_deepcoin(
        live_balance=1000.0,
        initial_principal=1000.0,
        entry_type="OPEN",
        base_qty=0,
        price=price,
        tv_sl=1900.0,
        regime=3,
        exchange_leverage=25,
        face_value=0.1,
        tv_qty=12,
        symbol="ETHUSDT",
    )
    assert qty > 0
    assert meta.get("sizing_mode") or meta.get("binding")
