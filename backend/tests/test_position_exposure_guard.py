"""Position vs TP book exposure audit."""

import pytest

from app.core.position_exposure_guard import (
    audit_position_tp_exposure,
    live_side_from_amt,
    resolve_booked_side,
    sum_reduce_only_tp_qty,
)


def test_sum_reduce_only_tp_qty():
    orders = [{"qty": 0.019}, {"origQty": 0.027}, {"quantity": 0.031}]
    assert sum_reduce_only_tp_qty(orders) == pytest.approx(0.077)


def test_over_commit_detected():
    audit = audit_position_tp_exposure(
        live_qty=0.077,
        live_side="LONG",
        tp_orders=[{"qty": 0.04}, {"qty": 0.04}, {"qty": 0.03}],
        expected_levels=[
            {"level": 1, "qty": 0.019, "price": 2100.0},
            {"level": 2, "qty": 0.027, "price": 2200.0},
            {"level": 3, "qty": 0.031, "price": 2300.0},
        ],
        booked_side="LONG",
    )
    assert audit["over_committed"] is True
    assert audit["excess_tp_qty"] > 0
    assert audit["needs_remediate"] is True


def test_side_flip_detected():
    audit = audit_position_tp_exposure(
        live_qty=0.094,
        live_side="SHORT",
        tp_orders=[],
        booked_side="LONG",
    )
    assert audit["side_flip"] is True
    assert audit["needs_remediate"] is True
    assert "方向背离" in audit["issues"][0]


def test_aligned_book_ok():
    audit = audit_position_tp_exposure(
        live_qty=0.077,
        live_side="LONG",
        tp_orders=[{"qty": 0.019}, {"qty": 0.027}, {"qty": 0.031}],
        expected_levels=[
            {"level": 1, "qty": 0.019, "price": 2100.0},
            {"level": 2, "qty": 0.027, "price": 2200.0},
            {"level": 3, "qty": 0.031, "price": 2300.0},
        ],
        booked_side="LONG",
    )
    assert audit["over_committed"] is False
    assert audit["side_flip"] is False
    assert audit["needs_remediate"] is False


def test_live_side_from_amt():
    assert live_side_from_amt(0.077) == "LONG"
    assert live_side_from_amt(-0.094) == "SHORT"
    assert live_side_from_amt(0) is None


def test_resolve_booked_side_prefers_tv():
    assert resolve_booked_side(current_side="SHORT", last_tv_side="LONG") == "LONG"
