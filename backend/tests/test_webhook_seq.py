"""bar_index + seq fingerprint, reorder gate, DingTalk batch helpers."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from app.services.webhook_idempotency import compute_fingerprint, _ttl_seconds
from app.services.webhook_payload import parse_webhook_payload, normalize_tv_payload
from app.services.webhook_seq_gate import reset_seq_gate_for_tests


def test_normalize_bar_index_seq():
    out = normalize_tv_payload({"action": "LONG", "bar_index": "200", "seq": "2"})
    assert out["bar_index"] == 200
    assert out["seq"] == 2


def test_parse_preserves_bar_seq():
    raw = (
        '{"action":"CLOSE_PROTECT","secret":"528586","symbol":"ETHUSDT.P",'
        '"bar_index":200,"seq":1,"side":"SHORT","reason":"test"}'
    )
    data, err = parse_webhook_payload(raw)
    assert err is None
    assert data["bar_index"] == 200
    assert data["seq"] == 1


def test_fingerprint_prefers_seq_key():
    fp = compute_fingerprint({
        "action": "LONG",
        "symbol": "ETHUSDT.P",
        "bar_index": 200,
        "seq": 2,
        "price": 3500,
    })
    assert fp.startswith("seq:")
    assert "200_2" in fp
    assert "OPEN_LONG" in fp
    assert _ttl_seconds(fp) >= 3600


def test_fingerprint_1_2_1_second_open_not_duplicate():
    """Same bar seq recycle: second LONG must not collide with first."""
    first = compute_fingerprint({
        "action": "LONG",
        "symbol": "ETHUSDT",
        "bar_index": 100,
        "seq": 1,
        "price": 3500,
        "tv_tp1": 3510,
        "tv_tp2": 3520,
        "tv_tp3": 3530,
    })
    close_fp = compute_fingerprint({
        "action": "CLOSE_STOPLOSS",
        "symbol": "ETHUSDT",
        "bar_index": 100,
        "seq": 2,
        "price": 3490,
        "reason": "防回吐保本",
    })
    second = compute_fingerprint({
        "action": "LONG",
        "symbol": "ETHUSDT",
        "bar_index": 100,
        "seq": 1,
        "price": 3488,
        "tv_tp1": 3498,
        "tv_tp2": 3508,
        "tv_tp3": 3518,
    })
    assert first != close_fp
    assert first != second
    assert "CLOSE_STOPLOSS" in close_fp


def test_fingerprint_legacy_without_seq():
    fp = compute_fingerprint({
        "action": "LONG",
        "symbol": "ETHUSDT",
        "price": 3500,
        "regime": 3,
    })
    assert fp.startswith("h:")
    assert len(fp) == 34  # "h:" + sha256[:32]
    # price is part of key
    fp2 = compute_fingerprint({
        "action": "LONG",
        "symbol": "ETHUSDT",
        "price": 3501,
        "regime": 3,
    })
    assert fp != fp2


def test_seq_gate_orders_same_bar_close_then_open():
    gate = reset_seq_gate_for_tests()
    released: list[tuple[int, str]] = []

    def dispatch(payload, fingerprint):
        released.append((int(payload["seq"]), str(payload["action"])))

    # Out-of-order arrival: OPEN seq=2 first (TV refresh: close seq < open seq)
    gate.submit(
        {"action": "LONG", "symbol": "ETHUSDT", "bar_index": 200, "seq": 2, "price": 1},
        "seq:ETHUSDT_200_2",
        dispatch=dispatch,
    )
    assert released == []  # lone OPEN holds for CLOSE companion
    assert gate.pending_depth() == 1

    gate.submit(
        {"action": "CLOSE_PROTECT", "symbol": "ETHUSDT", "bar_index": 200, "seq": 1},
        "seq:ETHUSDT_200_1",
        dispatch=dispatch,
    )
    assert released == [(1, "CLOSE_PROTECT"), (2, "LONG")]
    assert gate.pending_depth() == 0


def test_seq_gate_v1610_open_seq1_close_seq2_final_open():
    """Live bug: V1.6.10 emits OPEN seq=1 + CLOSE_PROTECT seq=2 same second.

    Must NEVER open-then-flat. Always CLOSE first, OPEN last → position exists.
    """
    gate = reset_seq_gate_for_tests()
    released: list[tuple[int, str]] = []

    def dispatch(payload, fingerprint):
        released.append((int(payload["seq"]), str(payload["action"])))

    # Arrival order matches TV webhook log (OPEN first, then CLOSE)
    gate.submit(
        {
            "action": "LONG",
            "entry_type": "OPEN",
            "symbol": "ETHUSDT.P",
            "bar_index": 27096,
            "seq": 1,
            "price": 1867.93,
        },
        "fp-open-1",
        dispatch=dispatch,
    )
    assert released == []
    assert gate.pending_depth() == 1

    gate.submit(
        {
            "action": "CLOSE_PROTECT",
            "symbol": "ETHUSDT.P",
            "bar_index": 27096,
            "seq": 2,
            "side": "LONG",
            "reason": "保护性全平-清算模块确认",
        },
        "fp-close-2",
        dispatch=dispatch,
    )
    assert released == [(2, "CLOSE_PROTECT"), (1, "LONG")]
    assert released[-1][1] == "LONG"
    assert gate.pending_depth() == 0


def test_seq_gate_close_then_open_natural_order():
    """Canonical TV refresh: CLOSE seq=1 then OPEN seq=2 (open may arrive first)."""
    gate = reset_seq_gate_for_tests()
    released: list[str] = []

    def dispatch(payload, fingerprint):
        released.append(str(payload["action"]))

    gate.submit(
        {"action": "LONG", "symbol": "ETHUSDT", "bar_index": 91, "seq": 2, "price": 1},
        "fp-open2",
        dispatch=dispatch,
    )
    assert released == []
    gate.submit(
        {"action": "CLOSE_STOPLOSS", "symbol": "ETHUSDT", "bar_index": 91, "seq": 1},
        "fp-close1",
        dispatch=dispatch,
    )
    assert released == ["CLOSE_STOPLOSS", "LONG"]


def test_seq_gate_same_seq_close_then_open_companion():
    """Safety: equal seq still CLOSE→OPEN (OPEN after CLOSE with same seq)."""
    gate = reset_seq_gate_for_tests()
    released: list[str] = []

    def dispatch(payload, fingerprint):
        released.append(str(payload["action"]))

    gate.submit(
        {"action": "CLOSE_PROTECT", "symbol": "ETHUSDT", "bar_index": 92, "seq": 1},
        "fp-c",
        dispatch=dispatch,
    )
    assert released == ["CLOSE_PROTECT"]
    gate.submit(
        {"action": "LONG", "symbol": "ETHUSDT", "bar_index": 92, "seq": 1, "price": 2},
        "fp-o",
        dispatch=dispatch,
    )
    assert released == ["CLOSE_PROTECT", "LONG"]


def test_seq_gate_lone_open_holds_then_releases_on_timeout(monkeypatch):
    monkeypatch.setattr(
        "app.services.webhook_seq_gate.get_settings",
        lambda: MagicMock(WEBHOOK_SEQ_WAIT_SEC=0.05),
    )
    gate = reset_seq_gate_for_tests()
    released: list[str] = []

    def dispatch(payload, fingerprint):
        released.append(str(payload["action"]))

    gate.submit(
        {"action": "LONG", "symbol": "ETHUSDT", "bar_index": 88, "seq": 1, "price": 1},
        "fp-lone-open",
        dispatch=dispatch,
    )
    assert released == []
    time.sleep(0.2)
    gate.flush_now()
    assert released == ["LONG"]


def test_seq_gate_cross_bar_order(monkeypatch):
    monkeypatch.setattr(
        "app.services.webhook_seq_gate.get_settings",
        lambda: MagicMock(WEBHOOK_SEQ_WAIT_SEC=0.05),
    )
    gate = reset_seq_gate_for_tests()
    released: list[tuple[int, int]] = []

    def dispatch3(payload, fingerprint):
        released.append((int(payload["bar_index"]), int(payload["seq"])))

    gate.submit(
        {"action": "LONG", "symbol": "ETHUSDT", "bar_index": 301, "seq": 2},
        "c",
        dispatch=dispatch3,
    )
    assert released == []  # lone OPEN / gap holds
    gate.submit(
        {"action": "CLOSE_PROTECT", "symbol": "ETHUSDT", "bar_index": 300, "seq": 1},
        "d",
        dispatch=dispatch3,
    )
    # bar 300 CLOSE ready → release; bar 301 still holding
    assert released == [(300, 1)]
    gate.submit(
        {"action": "LONG", "symbol": "ETHUSDT", "bar_index": 301, "seq": 1},
        "e",
        dispatch=dispatch3,
    )
    # bar 301 now has two OPENs only → still hold until timeout
    assert (301, 1) not in released or released == [(300, 1)]
    time.sleep(0.2)
    gate.flush_now()
    assert released[0] == (300, 1)
    assert set(released[1:]) == {(301, 1), (301, 2)}
    assert released[-1][0] == 301


def test_seq_gate_cycle_1_2_1_releases_second_open():
    """V1.6.10: open+close+open on same bar — CLOSE runs before OPENs; final=OPEN."""
    gate = reset_seq_gate_for_tests()
    released: list[tuple[int, str]] = []

    def dispatch(payload, fingerprint):
        released.append((int(payload["seq"]), str(payload["action"])))

    gate.submit(
        {"action": "LONG", "symbol": "ETHUSDT", "bar_index": 200, "seq": 1, "price": 3500},
        "fp-open-1",
        dispatch=dispatch,
    )
    assert released == []  # hold for CLOSE
    gate.submit(
        {"action": "CLOSE_STOPLOSS", "symbol": "ETHUSDT", "bar_index": 200, "seq": 2},
        "fp-close-2",
        dispatch=dispatch,
    )
    # Unit flush: CLOSE then first OPEN
    assert released == [(2, "CLOSE_STOPLOSS"), (1, "LONG")]
    gate.submit(
        {"action": "LONG", "symbol": "ETHUSDT", "bar_index": 200, "seq": 1, "price": 3488},
        "fp-open-1b",
        dispatch=dispatch,
    )
    assert released == [
        (2, "CLOSE_STOPLOSS"),
        (1, "LONG"),
        (1, "LONG"),
    ]
    assert released[-1][1] == "LONG"
    assert gate.pending_depth() == 0


def test_seq_gate_timeout_force_release(monkeypatch):
    monkeypatch.setattr("app.services.webhook_seq_gate.get_settings", lambda: MagicMock(WEBHOOK_SEQ_WAIT_SEC=0.05))
    gate = reset_seq_gate_for_tests()
    released: list[int] = []

    def dispatch(payload, fingerprint):
        released.append(int(payload["seq"]))

    with patch.object(gate, "_alert_seq_gap"):
        gate.submit(
            {"action": "LONG", "symbol": "ETHUSDT", "bar_index": 50, "seq": 2},
            "f",
            dispatch=dispatch,
        )
        time.sleep(0.2)
        gate.flush_now()
    assert released == [2]


def test_dingtalk_batch_merges(monkeypatch):
    from app.services import dingtalk_notify as dn

    sent: list[tuple[str, str]] = []

    monkeypatch.setattr(dn, "_send_with_retry", lambda title, body: sent.append((title, body)) or True)
    monkeypatch.setattr(dn, "get_settings", lambda: MagicMock(
        DINGTALK_BATCH_MAX=3,
        DINGTALK_BATCH_FLUSH_SEC=60,
        DINGTALK_RETRY_MAX=3,
        WECOM_WEBHOOK="",
    ))
    # Reset batcher queue by flushing leftovers; cancel any seq-gate timers first
    reset_seq_gate_for_tests()
    dn.flush_dingtalk_batch()
    time.sleep(0.05)
    sent.clear()

    dn.push_dingtalk("t1", "b1")
    dn.push_dingtalk("t2", "b2")
    assert sent == []
    dn.push_dingtalk("t3", "b3")  # hits max=3
    time.sleep(0.15)
    assert len(sent) == 1
    assert "汇总" in sent[0][0]
    assert "t1" in sent[0][1] and "t3" in sent[0][1]
