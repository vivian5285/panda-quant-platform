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
    compute_tv_entry_qty,
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


# Spec table @1000U ETH 1892.43 — risk/stop → open; add = open × regime_add_ratio
CHECKLIST_OPEN_TABLE = [
    # regime, risk_pct, stop_dist, open_qty, add_ratio
    (1, 0.81, 12.08, 0.67, 0.0),
    (2, 1.35, 14.09, 0.96, 0.3),
    (3, 2.03, 14.02, 1.45, 0.5),
    (4, 2.70, 15.94, 1.69, 0.7),
]


@pytest.mark.parametrize("regime,risk_pct,stop_dist,open_qty,add_ratio", CHECKLIST_OPEN_TABLE)
def test_checklist_open_and_add_table_1000u(regime, risk_pct, stop_dist, open_qty, add_ratio):
    """对照用户仓位表：1000U · ETH@1892.43 · TV risk 公式."""
    price = 1892.43
    tv_sl = price - stop_dist
    qty, meta = compute_tv_entry_qty(
        live_balance=1000.0,
        initial_principal=1000.0,
        price=price,
        tv_sl=tv_sl,
        risk_pct=risk_pct,
        leverage=25,
        qty_ratio=1.0,
        regime=regime,
        symbol="ETHUSDT",
    )
    assert qty == pytest.approx(open_qty, abs=0.01)
    assert meta["sizing_mode"] == "tv_risk_formula"

    add, add_meta = compute_tv_entry_qty(
        live_balance=1000.0,
        initial_principal=1000.0,
        price=price,
        tv_sl=tv_sl,
        risk_pct=risk_pct,
        leverage=25,
        qty_ratio=add_ratio if add_ratio > 0 else 0.0,
        entry_type="PYRAMID",
        regime=regime,
        symbol="ETHUSDT",
    )
    if add_ratio <= 0:
        assert add == 0.0
    else:
        assert add == pytest.approx(open_qty * add_ratio, abs=0.02)
        assert add_meta["qty_ratio"] == pytest.approx(add_ratio)


def test_checklist_tv_fields_parsed_as_authoritative():
    raw = {
        "action": "LONG",
        "entry_type": "OPEN",
        "regime": "3",
        "price": "1892.43",
        "tv_sl": "1878.41",
        "tv_tp1": 2100,
        "tv_tp2": 2200,
        "tv_tp3": 2300,
        "leverage": 25,
        "risk_pct": 2.03,
        "qty_ratio": 1.0,
    }
    norm = normalize_tv_payload(raw)
    assert norm["action"] == "LONG"
    assert norm["entry_type"] == "OPEN"
    assert norm["regime"] == 3
    assert norm["tv_sl"] == 1878.41

    fields = parse_tv_entry_fields(norm)
    assert fields["entry_type"] == "OPEN"
    assert fields["uses_tv_sizing"] is True
    assert fields["tv_qty_ratio_ignored"] is False
    assert fields["risk_pct"] == pytest.approx(2.03)
    assert fields["leverage"] == 25
    assert fields["qty_ratio"] == pytest.approx(1.0)


@pytest.mark.parametrize("exchange", ["binance", "okx", "gate", "deepcoin"])
def test_trading_factory_all_exchanges_25x_and_supervisor(exchange):
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
        assert hasattr(sup, "_resolve_entry_qty")
        assert hasattr(sup, "recover_on_startup")
    else:
        with patch.object(PositionSupervisor, "_start_idle_flat_patrol"):
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
    assert should_push_trading_dingtalk("TRAIL", "info") is True


def test_config_matches_checklist_defaults():
    s = get_settings()
    assert s.ADD_QTY_RATIO == pytest.approx(0.5)
    assert s.MAX_ADD_TIMES == 2
    assert s.ADD_RATIO_REG4 == pytest.approx(0.7)
    assert max_add_times_for_regime(4) == 3
    assert s.LEVERAGE == 25
    assert s.DEEPCOIN_LEVERAGE == 25
    assert s.OKX_LEVERAGE == 25
    assert s.GATE_LEVERAGE == 25
    assert s.MAX_COMBINED_NOTIONAL_MULT == pytest.approx(13.0)


def test_r4_tv_formula_matches_user_table():
    """R4 @1000U · risk 2.70% · stop 15.94 → ~1.69 ETH."""
    price = 1892.43
    qty, meta = compute_tv_entry_qty(
        live_balance=1000.0,
        initial_principal=1000.0,
        price=price,
        tv_sl=price - 15.94,
        risk_pct=2.70,
        leverage=25,
        qty_ratio=1.0,
        regime=4,
        symbol="ETHUSDT",
    )
    assert qty == pytest.approx(1.69, abs=0.01)
    assert meta["sizing_mode"] == "tv_risk_formula"
    assert meta["binding"] == "theoretical"


def test_resolve_entry_qty_eth_requires_tv_sl():
    qty, meta = resolve_vps_entry_qty_eth(
        live_balance=1000.0,
        initial_principal=1000.0,
        entry_type="OPEN",
        base_qty=0,
        price=1892.43,
        tv_sl=0,
        regime=4,
        exchange_leverage=25,
        round_fn=lambda x: x,
        risk_pct=2.70,
    )
    assert qty == 0
    assert meta.get("error") == "missing_tv_sl"


def test_resolve_entry_qty_deepcoin_add():
    price = 1892.43
    qty, meta = resolve_vps_entry_qty_deepcoin(
        live_balance=1000.0,
        initial_principal=1000.0,
        entry_type="PYRAMID",
        base_qty=15,
        price=price,
        tv_sl=price - 14.02,
        regime=3,
        exchange_leverage=25,
        face_value=0.1,
        tv_qty_ratio=0.5,
        risk_pct=2.03,
        symbol="ETHUSDT",
    )
    assert qty > 0
    assert meta["sizing_mode"] == "tv_risk_formula"
    # ~0.72 ETH / 0.1 face → 7 contracts
    assert qty == 7
