"""Dual-symbol registry, sizing, and notional cap."""

from app.core.symbol_precision import round_price, round_quantity
from app.core.symbol_registry import (
    CANONICAL_ETH,
    CANONICAL_XAU,
    extract_payload_symbol,
    exchange_native_symbol,
    normalize_canonical_symbol,
)
from app.core.tv_entry_sizing import compute_vps_open_qty, regime_margin_coeff
import pytest


def test_normalize_xau_aliases():
    assert normalize_canonical_symbol("XAUUSD") == CANONICAL_XAU
    assert normalize_canonical_symbol("XAU-USDT-SWAP") == CANONICAL_XAU
    assert normalize_canonical_symbol("GOLD") == CANONICAL_XAU
    assert normalize_canonical_symbol("ETH-USDT-SWAP") == CANONICAL_ETH


def test_extract_payload_symbol():
    assert extract_payload_symbol({"symbol": "XAUUSDT", "action": "LONG"}) == CANONICAL_XAU
    assert extract_payload_symbol({"ticker": "BINANCE:ETHUSDT"}) == CANONICAL_ETH
    assert extract_payload_symbol({"symbol": "ETHUSDT.P"}) == CANONICAL_ETH
    assert extract_payload_symbol({"symbol": "XAUUSDT.P"}) == CANONICAL_XAU
    # require=True (default): missing symbol must reject — never silent ETH fallback on OPEN
    assert extract_payload_symbol({"action": "CLOSE"}) is None
    assert extract_payload_symbol({"action": "CLOSE"}, require=False) == CANONICAL_ETH
    assert extract_payload_symbol({"symbol": "BTCUSDT"}) is None


def test_close_protect_payload_routes_eth_not_xau():
    """TV dual-alert ETHUSDT.P CLOSE_PROTECT must route only to ETH supervisor."""
    from app.services.webhook_guard import validate_signal_payload

    payload = {
        "symbol": "ETHUSDT.P",
        "action": "CLOSE_PROTECT",
        "secret": "528586",
        "regime": 4,
        "price": 1882.85,
        "atr": 13.1372332303,
        "side": "SHORT",
        "reason": "常规防守：大级别转多或动能衰竭",
        "pnl_pct": 0.26,
    }
    ok, err = validate_signal_payload(payload)
    assert ok, err
    assert extract_payload_symbol(payload) == CANONICAL_ETH
    xau = {
        **payload,
        "symbol": "XAUUSDT.P",
        "price": 4020.5,
    }
    assert extract_payload_symbol(xau) == CANONICAL_XAU
    ok2, err2 = validate_signal_payload(xau)
    assert ok2, err2


def test_exchange_native_symbols():
    assert exchange_native_symbol("binance", CANONICAL_XAU) == "XAUUSDT"
    assert exchange_native_symbol("okx", CANONICAL_XAU) == "XAU-USDT-SWAP"
    assert exchange_native_symbol("gate", CANONICAL_XAU) == "XAU_USDT"
    assert exchange_native_symbol("deepcoin", CANONICAL_ETH) == "ETH-USDT-SWAP"


def test_margin_coeff_and_open_qty_matches_spec():
    # Spec: equity 1000, R4 26%, ETH @ 1800 → qty ≈ 3.611 (6500/1800)
    assert abs(regime_margin_coeff(1) - 0.08) < 1e-9
    assert abs(regime_margin_coeff(4) - 0.26) < 1e-9
    qty, meta = compute_vps_open_qty(
        live_balance=1000,
        initial_principal=1000,
        price=1800,
        tv_sl=1700,
        regime=4,
        leverage=25,
        round_fn=lambda x: round(x, 3),
        symbol=CANONICAL_ETH,
    )
    assert abs(qty - round(6500 / 1800, 3)) < 1e-9
    assert abs(meta["margin_usd"] - 260) < 1e-6
    assert abs(meta["notional_usd"] - 6500) < 1e-6

    # Spec: XAU @ 2500 → qty 2.6
    qty_x, meta_x = compute_vps_open_qty(
        live_balance=1000,
        initial_principal=1000,
        price=2500,
        tv_sl=2300,
        regime=4,
        leverage=25,
        round_fn=lambda x: round(x, 2),
        symbol=CANONICAL_XAU,
    )
    assert abs(qty_x - 2.6) < 1e-6
    assert abs(meta_x["notional_usd"] - 6500) < 1e-6


def test_hard_sl_uses_tv_sl():
    from app.core.vps_hard_sl import compute_vps_hard_sl

    # Without tv_sl → no placement (no VPS fallback)
    bare = compute_vps_hard_sl(entry=1800, side="LONG", regime=4)
    assert float(bare.get("stop_price") or 0) == 0.0
    assert bare.get("error") == "no_tv_sl"
    # With TV tv_sl → hang exactly that price
    meta = compute_vps_hard_sl(entry=1800, side="LONG", regime=4, tv_sl_reference=1650.0)
    assert float(meta.get("stop_price") or 0) == pytest.approx(1650.0)
    assert meta.get("source") == "tv_sl"
    xau = compute_vps_hard_sl(
        entry=4004.27, side="SHORT", atr=15.16, regime=3, tv_sl_reference=4226.91,
    )
    assert float(xau["stop_price"]) == pytest.approx(4226.91)


def test_xau_qty_precision():
    assert round_quantity(1.234, CANONICAL_XAU) == 1.23
    assert round_quantity(2.5678, CANONICAL_ETH) == 2.567
    assert round_price(2500.126, CANONICAL_XAU) == 2500.13


def test_combined_notional_cap(monkeypatch):
    from app.core import combined_notional as cn

    class FakeSup:
        def __init__(self, can, qty, entry):
            self.canonical_symbol = can
            self.watched_qty = qty
            self.watched_entry = entry
            self.best_price = entry
            self.user_id = 1

    class FakePool:
        def get_all_for_user(self, user_id):
            return [FakeSup(CANONICAL_ETH, 6500 / 1800, 1800)]  # 6500 notional

    import app.services.dispatcher as disp

    monkeypatch.setattr(disp, "supervisor_pool", FakePool())
    # Peer ETH 6500 + new XAU 6500 = 13000 == 13×1000 → allow
    ok, meta = cn.check_combined_notional_cap(
        user_id=1,
        canonical=CANONICAL_XAU,
        equity=1000,
        new_notional=6500,
    )
    assert ok is True
    assert abs(meta["proposed_notional"] - 13000) < 1e-6
    assert abs(meta["max_mult"] - 13.0) < 1e-9

    # +1 over → reject
    ok2, meta2 = cn.check_combined_notional_cap(
        user_id=1,
        canonical=CANONICAL_XAU,
        equity=1000,
        new_notional=6501,
    )
    assert ok2 is False
    assert meta2.get("error") == "combined_notional_exceeded"
