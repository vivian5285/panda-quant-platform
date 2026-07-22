"""User/symbol isolation — concurrent dual-user + same-user ETH/XAU.

Pool key is (user_id, canonical_symbol). Breathing state lives on each
supervisor instance; clients carry that user's API key only.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import MagicMock

import pytest

from app.core.position_supervisor import PositionSupervisor
from app.core.symbol_registry import CANONICAL_ETH, CANONICAL_XAU
from app.core.tv_entry_sizing import compute_tv_entry_qty
from app.services.dispatcher import UserSupervisorPool, _pool_key


def _seed_breathing(sup: PositionSupervisor, *, entry: float, sl: float, qty: float, side="LONG"):
    sup.monitoring = True
    sup.current_side = side
    sup.watched_entry = entry
    sup.watched_qty = qty
    sup.initial_qty = qty
    sup.current_sl = sl
    sup.tv_sl = sl
    sup.initial_stop = sl
    sup.initial_atr = 14.0
    sup.best_price = entry
    sup.breakeven_phase = False
    sup.remaining_qty_pct = 1.0


def test_pool_key_isolates_user_and_symbol():
    assert _pool_key(1, "ETHUSDT") == (1, CANONICAL_ETH)
    assert _pool_key(1, "ethusdt") == (1, CANONICAL_ETH)
    assert _pool_key(1, "XAUUSDT") != _pool_key(1, "ETHUSDT")
    assert _pool_key(1, "ETHUSDT") != _pool_key(2, "ETHUSDT")


def test_same_user_eth_xau_breathing_state_not_cross_contaminated(tmp_path, monkeypatch):
    """Realistic single-user dual-symbol: mutate ETH stop must not touch XAU book."""
    monkeypatch.chdir(tmp_path)
    eth_client = MagicMock(api_key="KEY_U1", exchange_id="binance")
    xau_client = MagicMock(api_key="KEY_U1", exchange_id="binance")
    eth = PositionSupervisor(user_id=6, client=eth_client, initial_principal=1000.0)
    xau = PositionSupervisor(user_id=6, client=xau_client, initial_principal=1000.0)
    eth.canonical_symbol = CANONICAL_ETH
    eth.symbol = "ETHUSDT"
    xau.canonical_symbol = CANONICAL_XAU
    xau.symbol = "XAUUSDT"

    _seed_breathing(eth, entry=1918.0, sl=1895.79, qty=0.033)
    _seed_breathing(xau, entry=4020.5, sl=3980.0, qty=1.25)

    pool = UserSupervisorPool()
    with pool._lock:
        pool._supervisors[_pool_key(6, CANONICAL_ETH)] = eth
        pool._supervisors[_pool_key(6, CANONICAL_XAU)] = xau

    # Concurrent "ticks": ETH trail improve vs XAU untouched
    eth.current_sl = 1905.0
    eth.best_price = 1930.0
    eth.breakeven_phase = True

    got_eth = pool.get(6, CANONICAL_ETH)
    got_xau = pool.get(6, CANONICAL_XAU)
    assert got_eth is eth and got_xau is xau
    assert got_eth is not got_xau

    assert float(got_xau.watched_entry) == pytest.approx(4020.5)
    assert float(got_xau.current_sl) == pytest.approx(3980.0)
    assert float(got_xau.watched_qty) == pytest.approx(1.25)
    assert got_xau.breakeven_phase is False
    assert float(got_eth.current_sl) == pytest.approx(1905.0)
    assert got_eth.breakeven_phase is True

    # Flat-clear ETH must not wipe XAU
    eth._clear_position_local_state()
    assert float(got_xau.watched_entry) == pytest.approx(4020.5)
    assert got_xau.current_side == "LONG"
    assert float(got_eth.watched_entry) == 0.0
    assert got_eth.current_side is None


def test_two_users_same_symbol_concurrent_long_do_not_cross_state(tmp_path, monkeypatch):
    """Two users almost-simultaneous LONG on ETHUSDT — independent books + keys."""
    monkeypatch.chdir(tmp_path)
    c_a = MagicMock(api_key="USER_A_KEY", api_secret="SEC_A", exchange_id="binance")
    c_b = MagicMock(api_key="USER_B_KEY", api_secret="SEC_B", exchange_id="binance")
    a = PositionSupervisor(user_id=11, client=c_a, initial_principal=2000.0)
    b = PositionSupervisor(user_id=22, client=c_b, initial_principal=500.0)
    a.canonical_symbol = CANONICAL_ETH
    b.canonical_symbol = CANONICAL_ETH
    a.symbol = b.symbol = "ETHUSDT"

    pool = UserSupervisorPool()
    with pool._lock:
        pool._supervisors[_pool_key(11, CANONICAL_ETH)] = a
        pool._supervisors[_pool_key(22, CANONICAL_ETH)] = b

    barrier = threading.Barrier(2)
    errors: list[str] = []

    def _open_sim(sup: PositionSupervisor, entry: float, sl: float, qty: float):
        try:
            barrier.wait(timeout=5)
            # Simulate post-open breathing seed (what open path writes onto self)
            _seed_breathing(sup, entry=entry, sl=sl, qty=qty)
            time.sleep(0.01)
            # Second write wave — catch races if any shared state existed
            sup.best_price = entry + 5.0
            sup.current_sl = sl + 1.0
        except Exception as exc:
            errors.append(f"uid={sup.user_id}: {exc}")

    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = [
            ex.submit(_open_sim, a, 1910.0, 1880.0, 0.05),
            ex.submit(_open_sim, b, 1925.0, 1899.0, 0.02),
        ]
        for f in as_completed(futs):
            f.result()

    assert errors == []
    assert a.client.api_key == "USER_A_KEY"
    assert b.client.api_key == "USER_B_KEY"
    assert a.client.api_key != b.client.api_key

    assert float(a.watched_entry) == pytest.approx(1910.0)
    assert float(a.current_sl) == pytest.approx(1881.0)
    assert float(a.watched_qty) == pytest.approx(0.05)
    assert float(b.watched_entry) == pytest.approx(1925.0)
    assert float(b.current_sl) == pytest.approx(1900.0)
    assert float(b.watched_qty) == pytest.approx(0.02)
    assert a.watched_entry != b.watched_entry
    assert a.current_sl != b.current_sl

    # Dispatch-style filter: same signal symbol → both, but still distinct instances
    targets = [
        s for (uid, can), s in pool._supervisors.items()
        if can == CANONICAL_ETH
    ]
    assert len(targets) == 2
    assert {id(targets[0]), id(targets[1])} == {id(a), id(b)}


def test_concurrent_sizing_equity_binds_to_calling_user():
    """compute_tv_entry_qty is pure — concurrent calls with different equity stay correct."""
    barrier = threading.Barrier(2)
    results: dict[str, tuple] = {}

    def _size(tag: str, equity: float, tv_qty: float):
        barrier.wait(timeout=5)
        qty, meta = compute_tv_entry_qty(
            live_balance=equity,
            initial_principal=equity,
            price=2000.0,
            tv_sl=1900.0,
            tv_stop_loss=1900.0,
            tv_qty=tv_qty,
            symbol=CANONICAL_ETH,
        )
        results[tag] = (qty, float(meta.get("equity_balance") or 0), float(meta.get("equity") or 0))

    with ThreadPoolExecutor(max_workers=2) as ex:
        list(as_completed([
            ex.submit(_size, "rich", 5000.0, 2.0),
            ex.submit(_size, "poor", 500.0, 2.0),
        ]))

    q_rich, bal_rich, eq_rich = results["rich"]
    q_poor, bal_poor, eq_poor = results["poor"]
    assert bal_rich == 5000.0 and bal_poor == 500.0
    assert eq_rich == 5000.0 and eq_poor == 500.0
    assert q_rich > q_poor
    # Poor account must not accidentally receive rich sizing
    assert q_poor < q_rich
