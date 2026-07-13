"""VPS 开发清单（最终版）— 解析 / 执行 / 钉钉 / 雷达 / 交易工厂验收."""

import inspect

import pytest

from app.config import exchange_leverage, get_settings
from app.core.adverse_radar_guard import AdverseRadarMixin
from app.core.exchange_factory import SUPPORTED_EXCHANGES, create_supervisor
from app.core.position_supervisor import PositionSupervisor
from app.core.position_supervisor_deepcoin import DeepcoinPositionSupervisor
from app.core.startup_reconcile import StartupReconcileMixin
from app.core.tv_entry_sizing import (
    compute_vps_add_qty,
    compute_vps_open_qty,
    max_add_times_for_regime,
    parse_tv_entry_fields,
    regime_add_qty_ratio,
    resolve_vps_entry_qty_deepcoin,
    resolve_vps_entry_qty_eth,
)
from app.models import ExchangeType, User
from app.services.trading_alerts import should_push_trading_dingtalk
from app.services.webhook_payload import normalize_tv_payload
from unittest.mock import MagicMock, patch


CHECKLIST_OPEN_TABLE = [
    (1, 1.031, 0.0),
    (2, 1.406, 0.421),
    (3, 1.781, 0.891),
    (4, 2.5, 1.746),
]


@pytest.mark.parametrize("regime,open_qty,add_qty", CHECKLIST_OPEN_TABLE)
def test_checklist_open_and_add_table_1000u_2000(regime, open_qty, add_qty):
    """对照清单三：1000U 本金，价格=2000，25×交易所杠杆，保证金预算×5."""
    qty, meta = compute_vps_open_qty(
        live_balance=1000.0,
        initial_principal=1000.0,
        price=2000.0,
        tv_sl=1950.0,
        regime=regime,
        leverage=25,
        round_fn=lambda x: round(x, 3),
    )
    assert qty == pytest.approx(open_qty, rel=0.02)
    assert meta["margin_usd"] > 0
    assert meta["position_value"] == pytest.approx(meta["margin_usd"] * 25, rel=0.01)

    tv_ratio = regime_add_qty_ratio(regime)
    add, add_meta = compute_vps_add_qty(
        base_qty=qty,
        tv_qty_ratio=tv_ratio,
        round_fn=lambda x: round(x, 3),
    )
    assert add == pytest.approx(add_qty, rel=0.02)
    assert add_meta["add_qty_ratio"] == pytest.approx(tv_ratio)


def test_checklist_tv_fields_parsed_and_ignored():
    raw = {
        "action": "LONG",
        "entry_type": "OPEN",
        "regime": "3",
        "price": "2000",
        "tv_sl": "1950",
        "tv_tp1": 2100,
        "tv_tp2": 2200,
        "tv_tp3": 2300,
        "leverage": 10,
        "risk_pct": 9.9,
        "qty_ratio": 0.8,
    }
    norm = normalize_tv_payload(raw)
    assert norm["action"] == "LONG"
    assert norm["entry_type"] == "OPEN"
    assert norm["regime"] == 3
    assert norm["tv_sl"] == 1950.0

    fields = parse_tv_entry_fields(norm)
    assert fields["entry_type"] == "OPEN"
    assert fields["uses_vps_sizing"] is True
    assert fields["tv_qty_ratio_ignored"] is True


@pytest.mark.parametrize("exchange", ["binance", "okx", "gate", "deepcoin"])
def test_trading_factory_all_exchanges_25x_and_supervisor(exchange):
    settings = get_settings()
    assert exchange_leverage(exchange) == 25

    user = User(id=1, exchange=exchange)
    client = MagicMock()
    client.trading_leverage = 25
    client.trading_symbol = "ETHUSDT"

    if exchange == "deepcoin":
        with patch.object(DeepcoinPositionSupervisor, "_start_idle_flat_patrol"), patch.object(
            DeepcoinPositionSupervisor, "_start_signal_worker"
        ):
            sup = create_supervisor(user, client)
        assert isinstance(sup, DeepcoinPositionSupervisor)
        assert hasattr(sup, "_resolve_entry_qty")
        assert hasattr(sup, "recover_on_startup")
    else:
        sup = create_supervisor(user, client)
        assert isinstance(sup, PositionSupervisor)
        assert hasattr(sup, "_resolve_entry_qty")
        assert hasattr(sup, "recover_on_startup")

    assert exchange in SUPPORTED_EXCHANGES or exchange == ExchangeType.BINANCE.value


def test_all_supervisors_share_radar_and_startup_mixins():
    for cls in (PositionSupervisor, DeepcoinPositionSupervisor):
        mro_names = {c.__name__ for c in cls.__mro__}
        assert AdverseRadarMixin.__name__ in mro_names or "AdverseRadarMixin" in str(mro_names)
        assert StartupReconcileMixin.__name__ in mro_names or "StartupReconcileMixin" in str(mro_names)


def test_eth_and_deepcoin_use_same_vps_resolver_entry_points():
    assert "resolve_vps_entry_qty_eth" in inspect.getsource(PositionSupervisor._resolve_entry_qty)
    assert "resolve_vps_entry_qty_deepcoin" in inspect.getsource(
        DeepcoinPositionSupervisor._resolve_entry_qty
    )


def test_dingtalk_push_open_startup_radar_alerts():
    assert should_push_trading_dingtalk("OPEN", "info") is True
    assert should_push_trading_dingtalk("STARTUP", "info") is True
    assert should_push_trading_dingtalk("PYRAMID", "info") is True
    assert should_push_trading_dingtalk("UPDATE_SL", "info") is True
    assert should_push_trading_dingtalk("FORCE_ALIGN", "critical") is True
    assert should_push_trading_dingtalk("IDLE_WATCH", "info") is True
    assert should_push_trading_dingtalk("TRAIL", "info") is False


def test_config_matches_checklist_defaults():
    s = get_settings()
    assert s.VPS_RISK_PCT == pytest.approx(3.0)
    assert s.ADD_QTY_RATIO == pytest.approx(0.5)
    assert s.MAX_ADD_TIMES == 2
    assert s.ADD_RATIO_REG4 == pytest.approx(0.7)
    assert max_add_times_for_regime(4) == 3
    assert s.REGIME_SCALE_1 == pytest.approx(0.55)
    assert s.REGIME_SCALE_4 == pytest.approx(1.33)
    assert s.SIZING_MARGIN_LEVERAGE == 5
    assert s.LEVERAGE == 25
    assert s.DEEPCOIN_LEVERAGE == 25
    assert s.OKX_LEVERAGE == 25
    assert s.GATE_LEVERAGE == 25


def test_r4_strongest_open_200u_margin_5000u_position_at_25x():
    """R4 最强趋势：1000U 本金 ≈200U 保证金 ×25 杠杆 ≈5000U 头寸."""
    qty, meta = compute_vps_open_qty(
        live_balance=1000.0,
        initial_principal=1000.0,
        price=2000.0,
        tv_sl=1950.0,
        regime=4,
        leverage=25,
        round_fn=lambda x: round(x, 3),
    )
    assert meta["margin_usd"] == pytest.approx(199.5, rel=0.02)
    assert meta["position_value"] == pytest.approx(4987.5, rel=0.02)
    assert qty == pytest.approx(2.494, rel=0.02)


def test_resolve_entry_qty_eth_open_uses_price_not_sl_distance():
    qty, meta = resolve_vps_entry_qty_eth(
        live_balance=1000.0,
        initial_principal=1000.0,
        entry_type="OPEN",
        base_qty=0,
        price=2000.0,
        tv_sl=0,
        regime=4,
        exchange_leverage=25,
        round_fn=lambda x: round(x, 3),
    )
    assert qty == pytest.approx(2.494, rel=0.02)
    assert meta.get("error") is None
    assert "margin_usd" in meta


def test_resolve_entry_qty_deepcoin_add():
    qty, meta = resolve_vps_entry_qty_deepcoin(
        live_balance=1000.0,
        initial_principal=1000.0,
        entry_type="PYRAMID",
        base_qty=4,
        price=2000.0,
        tv_sl=1950.0,
        regime=3,
        exchange_leverage=15,
        face_value=0.1,
        tv_qty_ratio=0.5,
    )
    assert qty == 2
    assert meta["add_qty"] == 2
