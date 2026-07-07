"""Exchange-first TP defense reconciliation helpers (restart / audit)."""

from __future__ import annotations

from app.core.position_qty_tolerance import qty_drift_tolerance
from app.core.symbol_precision import PRICE_TICK, round_price

# Two price ticks — avoids grouping unrelated limit orders (e.g. adverse stops).
TP_PRICE_MATCH_TOL = float(PRICE_TICK) * 2
STARTUP_ORDER_FETCH_RETRIES = 4
STARTUP_ORDER_FETCH_DELAY = 0.75


def tp_price_matches(a: float, b: float, tol: float = TP_PRICE_MATCH_TOL) -> bool:
    return abs(round_price(a) - round_price(b)) <= float(tol) + 1e-9


def tp_qty_tolerance(
    expected: float,
    anchor: float,
    *,
    is_contracts: bool = False,
) -> float:
    return qty_drift_tolerance(expected, anchor, is_contracts=is_contracts)


def tp_qty_matches(
    expected: float,
    actual: float,
    anchor: float,
    *,
    is_contracts: bool = False,
) -> bool:
    tol = tp_qty_tolerance(expected, anchor, is_contracts=is_contracts)
    if is_contracts:
        return abs(int(round(float(actual))) - int(round(float(expected)))) <= tol + 1e-9
    return abs(float(actual) - float(expected)) <= tol + 1e-9


def pick_best_tp_order(
    orders: list[dict],
    expected_qty: float,
    *,
    qty_key: str = "qty",
) -> dict | None:
    if not orders:
        return None
    if len(orders) == 1:
        return orders[0]

    def score(o: dict) -> float:
        return abs(float(o.get(qty_key, 0) or 0) - float(expected_qty))

    return min(orders, key=score)


def dedupe_orders_by_id(orders: list[dict]) -> list[dict]:
    seen: set = set()
    out: list[dict] = []
    for o in orders:
        oid = o.get("orderId") or o.get("order_id") or o.get("ordId")
        if oid is not None:
            key = str(oid)
            if key in seen:
                continue
            seen.add(key)
        out.append(o)
    return out
