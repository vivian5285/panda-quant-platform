"""TP retry + live order audit for PositionSupervisor."""

from unittest.mock import MagicMock

import pytest

from app.core.position_supervisor import PositionSupervisor, TP_RETRY_MAX


def _open_orders_side_effect(*responses):
    """Mock get_open_orders: each response once, then []."""
    it = iter(responses)

    def _fn(_symbol):
        try:
            return next(it)
        except StopIteration:
            return []

    return _fn


@pytest.fixture
def supervisor(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = MagicMock()
    client.get_current_price.return_value = 3500.0
    client.cancel_all_open_orders.return_value = None
    sup = PositionSupervisor(user_id=7, client=client)
    sup.current_side = "LONG"
    sup.regime = 3
    sup.tv_tps = [3600.0, 3700.0, 3800.0]
    return sup


def test_place_limit_with_retry_succeeds_on_second_attempt(supervisor, monkeypatch):
    calls = {"n": 0}

    def fake_place(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return {"orderId": 12345}

    monkeypatch.setattr(supervisor.client, "place_limit_order", fake_place)
    monkeypatch.setattr("app.core.position_supervisor.time.sleep", lambda *_: None)

    result = supervisor._place_limit_with_retry("SHORT", 0.5, 3600.0, "TP1")

    assert result["ok"] is True
    assert result["attempt"] == 2
    assert result["order_id"] == 12345
    assert calls["n"] == 2


def test_place_limit_with_retry_fails_after_max(supervisor, monkeypatch):
    supervisor.client.place_limit_order.return_value = None
    monkeypatch.setattr("app.core.position_supervisor.time.sleep", lambda *_: None)

    result = supervisor._place_limit_with_retry("SHORT", 0.5, 3600.0, "TP1")

    assert result["ok"] is False
    assert result["attempts"] == TP_RETRY_MAX
    assert supervisor.client.place_limit_order.call_count == TP_RETRY_MAX


def test_scan_open_defenses_detects_missing_tp(supervisor):
    supervisor.client.get_open_orders.return_value = [
        {
            "orderId": 1,
            "type": "LIMIT",
            "side": "SELL",
            "price": "3600.00",
            "origQty": "0.180",
        },
    ]
    slices = supervisor._compute_tp_slices(1.0)

    scan = supervisor._scan_open_defenses(slices)

    assert len(scan["matched_tps"]) == 1
    assert len(scan["missing_tps"]) == 2
    assert scan["aligned"] is False


def test_verify_and_repair_defenses_repairs_missing(supervisor, monkeypatch):
    supervisor.client.get_open_orders.side_effect = _open_orders_side_effect([], [])
    supervisor.client.place_limit_order.return_value = {"orderId": 99}
    monkeypatch.setattr("app.core.position_supervisor.time.sleep", lambda *_: None)

    detail = supervisor._verify_and_repair_defenses(1.0, 3500.0)

    assert supervisor.client.place_limit_order.call_count >= 1
    assert detail.get("healed") or detail.get("placed") or detail.get("aligned")


def test_ensure_defenses_skips_when_already_aligned(supervisor, monkeypatch):
    """VPS 重启：TP1/2/3 已在实盘且比例正确 → 不重复挂单。"""
    slices = supervisor._compute_tp_slices(1.0)
    orders = []
    for level, qty, price in slices:
        if qty <= 0 or price <= 0:
            continue
        orders.append(_tp_limit(level, price, qty, reduce_only=True))
    supervisor.client.get_open_orders.return_value = orders
    monkeypatch.setattr("app.core.position_supervisor.time.sleep", lambda *_: None)

    result = supervisor._ensure_defenses(1.0, 3500.0, force_rebuild=False)

    assert result["skipped"] is True
    assert result["aligned"] is True
    supervisor.client.place_limit_order.assert_not_called()
    supervisor.client.cancel_all_open_orders.assert_not_called()


def test_ensure_defenses_only_places_missing(supervisor, monkeypatch):
    partial = [
        {"orderId": 1, "type": "LIMIT", "side": "SELL", "price": "3600.00", "origQty": "0.180"},
    ]
    supervisor.client.get_open_orders.side_effect = _open_orders_side_effect(
        [], partial, partial, [],
    )
    supervisor.client.place_limit_order.return_value = {"orderId": 99}
    monkeypatch.setattr("app.core.position_supervisor.time.sleep", lambda *_: None)

    result = supervisor._ensure_defenses(1.0, 3500.0, force_rebuild=False)

    assert result.get("healed") is True
    supervisor.client.cancel_all_open_orders.assert_called()
    assert supervisor.client.place_limit_order.call_count >= 2


def _tp_limit(oid, price, qty, reduce_only=True):
    return {
        "orderId": oid,
        "type": "LIMIT",
        "side": "SELL",
        "price": f"{price:.2f}",
        "origQty": f"{qty:.3f}",
        "reduceOnly": reduce_only,
    }


def test_aggressive_heal_on_duplicate_tp(supervisor, monkeypatch):
    dup_orders = [
        _tp_limit(i, 3600.0, 0.073) for i in range(1, 7)
    ]
    live: list = []

    def _get_orders(_symbol):
        return list(live)

    def _cancel(_symbol, oid):
        nonlocal live
        live = [o for o in live if o["orderId"] != oid]
        return True

    live[:] = dup_orders
    supervisor.client.get_open_orders.side_effect = _get_orders
    supervisor.client.cancel_order.side_effect = _cancel
    supervisor.client.place_limit_order.return_value = {"orderId": 100}
    monkeypatch.setattr("app.core.position_supervisor.time.sleep", lambda *_: None)
    alerts = []
    supervisor.on_alert = lambda *a, **k: alerts.append(a)

    result = supervisor._ensure_defenses(0.406, 1562.01, force_rebuild=False)

    assert result.get("healed") is True
    assert supervisor.client.cancel_order.call_count >= 5
    assert any("DEFENSE_HEAL" in str(a) for a in alerts)


def test_rebuild_defenses_force_cancels_then_places(supervisor, monkeypatch):
    partial = [
        {"orderId": 9, "type": "LIMIT", "side": "SELL", "price": "3600.00", "origQty": "0.050"},
    ]
    supervisor.client.get_open_orders.side_effect = _open_orders_side_effect(
        [], partial, partial, [],
    )
    supervisor.client.place_limit_order.return_value = {"orderId": 1}
    monkeypatch.setattr("app.core.position_supervisor.time.sleep", lambda *_: None)

    result = supervisor._rebuild_defenses(1.0, 3500.0)

    assert result.get("healed") is True
    supervisor.client.cancel_all_open_orders.assert_called()
    assert supervisor.client.place_limit_order.call_count >= 3


def test_scan_detects_duplicate_tp(supervisor):
    supervisor.client.get_open_orders.return_value = [
        _tp_limit(1, 3600.0, 0.180),
        _tp_limit(2, 3600.0, 0.180),
    ]
    slices = supervisor._compute_tp_slices(1.0)
    scan = supervisor._scan_open_defenses(slices)

    assert len(scan["duplicate_tps"]) == 1
    assert scan["needs_rebuild"] is True


def test_rebuild_defenses_logs_alignment(supervisor, monkeypatch):
    aligned_orders = [
        {"orderId": 1, "type": "LIMIT", "side": "SELL", "price": "3600.00", "origQty": "0.180"},
        {"orderId": 2, "type": "LIMIT", "side": "SELL", "price": "3700.00", "origQty": "0.320"},
        {"orderId": 3, "type": "LIMIT", "side": "SELL", "price": "3800.00", "origQty": "0.500"},
    ]
    supervisor.client.get_open_orders.return_value = aligned_orders
    monkeypatch.setattr("app.core.position_supervisor.time.sleep", lambda *_: None)
    logs = []
    supervisor.on_log = lambda uid, et, msg, detail, tid: logs.append((et, msg))

    result = supervisor._ensure_defenses(1.0, 3500.0, force_rebuild=False)

    assert result.get("skipped") is True
    assert result.get("aligned") is True
    assert any(et == "DEFENSE" for et, _ in logs)
    supervisor.client.cancel_all_open_orders.assert_not_called()
