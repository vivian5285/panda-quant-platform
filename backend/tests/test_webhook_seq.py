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
    assert not fp.startswith("seq:")
    assert len(fp) == 64


def test_seq_gate_orders_same_bar_close_then_open():
    gate = reset_seq_gate_for_tests()
    released: list[tuple[int, str]] = []

    def dispatch(payload, fingerprint):
        released.append((int(payload["seq"]), str(payload["action"])))

    # Out-of-order arrival: OPEN seq=2 first
    gate.submit(
        {"action": "LONG", "symbol": "ETHUSDT", "bar_index": 200, "seq": 2, "price": 1},
        "seq:ETHUSDT_200_2",
        dispatch=dispatch,
    )
    assert released == []
    assert gate.pending_depth() == 1

    gate.submit(
        {"action": "CLOSE_PROTECT", "symbol": "ETHUSDT", "bar_index": 200, "seq": 1},
        "seq:ETHUSDT_200_1",
        dispatch=dispatch,
    )
    assert released == [(1, "CLOSE_PROTECT"), (2, "LONG")]
    assert gate.pending_depth() == 0


def test_seq_gate_cross_bar_order():
    gate = reset_seq_gate_for_tests()
    released: list[tuple[int, int]] = []

    def dispatch(payload, fingerprint):
        released.append((int(payload["bar_index"]), int(payload["seq"])))

    gate.submit(
        {"action": "LONG", "symbol": "ETHUSDT", "bar_index": 301, "seq": 1},
        "a",
        dispatch=dispatch,
    )
    # 301 waits? Actually next expected for bar 301 is seq=1 and it's present —
    # but bar 300 isn't pending. Spec: process by bar_index ascending among pending.
    # Only 301 is pending → releases 301 immediately.
    assert released == [(301, 1)]

    gate = reset_seq_gate_for_tests()
    released.clear()

    def dispatch2(payload, fingerprint):
        released.append((int(payload["bar_index"]), int(payload["seq"])))

    # Both pending: 301 first arrival, then 300 → must process 300 then 301
    gate.submit(
        {"action": "LONG", "symbol": "ETHUSDT", "bar_index": 301, "seq": 1},
        "b",
        dispatch=dispatch2,
    )
    # With only 301, it flushes. Re-buffer both before flush by submitting 300 while
    # forcing wait: inject 301 then 300 with seq gap on 300? Better: submit 301 seq=2
    # first (buffers), then 300 seq=1 (lower bar releases first).
    gate = reset_seq_gate_for_tests()
    released.clear()

    def dispatch3(payload, fingerprint):
        released.append((int(payload["bar_index"]), int(payload["seq"])))

    gate.submit(
        {"action": "LONG", "symbol": "ETHUSDT", "bar_index": 301, "seq": 2},
        "c",
        dispatch=dispatch3,
    )
    assert released == []  # waiting for seq=1 on 301
    gate.submit(
        {"action": "CLOSE_PROTECT", "symbol": "ETHUSDT", "bar_index": 300, "seq": 1},
        "d",
        dispatch=dispatch3,
    )
    # bar 300 ready → release; bar 301 still gap
    assert released == [(300, 1)]
    gate.submit(
        {"action": "LONG", "symbol": "ETHUSDT", "bar_index": 301, "seq": 1},
        "e",
        dispatch=dispatch3,
    )
    assert released == [(300, 1), (301, 1), (301, 2)]


def test_seq_gate_cycle_1_2_1_releases_second_open():
    """V1.6.10: open→close→open on same bar (seq 1-2-1) must all release."""
    gate = reset_seq_gate_for_tests()
    released: list[tuple[int, str]] = []

    def dispatch(payload, fingerprint):
        released.append((int(payload["seq"]), str(payload["action"])))

    gate.submit(
        {"action": "LONG", "symbol": "ETHUSDT", "bar_index": 200, "seq": 1, "price": 3500},
        "fp-open-1",
        dispatch=dispatch,
    )
    gate.submit(
        {"action": "CLOSE_STOPLOSS", "symbol": "ETHUSDT", "bar_index": 200, "seq": 2},
        "fp-close-2",
        dispatch=dispatch,
    )
    gate.submit(
        {"action": "LONG", "symbol": "ETHUSDT", "bar_index": 200, "seq": 1, "price": 3488},
        "fp-open-1b",
        dispatch=dispatch,
    )
    assert released == [
        (1, "LONG"),
        (2, "CLOSE_STOPLOSS"),
        (1, "LONG"),
    ]
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
    # Reset batcher queue by flushing leftovers
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
