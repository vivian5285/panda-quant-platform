"""initial_atr open-lock — write-guard for breathing engine.

After open lock, only flat-clear (→0), identical restore, or authorized
VPS 1h ATR upgrade (scenario 2→1) is accepted. Other overwrites are blocked.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class InitialAtrDescriptor:
    """Instance attribute `initial_atr` with lock-after-open semantics."""

    def __set_name__(self, owner, name):  # noqa: D401
        self.public_name = name
        self.private_name = "_initial_atr_value"
        self.lock_name = "_initial_atr_locked"
        self.blocked_name = "_initial_atr_blocked_writes"

    def __get__(self, obj, owner=None):
        if obj is None:
            return self
        return float(getattr(obj, self.private_name, 0.0) or 0.0)

    def __set__(self, obj, value) -> None:
        v = float(value or 0)
        locked = bool(getattr(obj, self.lock_name, False))
        cur = float(getattr(obj, self.private_name, 0.0) or 0.0)
        if v <= 0:
            setattr(obj, self.private_name, 0.0)
            setattr(obj, self.lock_name, False)
            return
        if locked and abs(v - cur) > 1e-9:
            n = int(getattr(obj, self.blocked_name, 0) or 0) + 1
            setattr(obj, self.blocked_name, n)
            logger.error(
                "[User %s] initial_atr locked=%.6f; reject overwrite %.6f (blocked#%s)",
                getattr(obj, "user_id", "?"),
                cur,
                v,
                n,
            )
            return
        setattr(obj, self.private_name, v)
        setattr(obj, self.lock_name, True)


def is_initial_atr_locked(obj: Any) -> bool:
    return bool(getattr(obj, "_initial_atr_locked", False))


def blocked_initial_atr_writes(obj: Any) -> int:
    return int(getattr(obj, "_initial_atr_blocked_writes", 0) or 0)


def rewrite_initial_atr_for_vps_upgrade(
    obj: Any,
    value: float,
    *,
    reason: str = "vps_1h_atr",
) -> bool:
    """Authorized unlock+rewrite when VPS real 1h ATR replaces TV fallback."""
    v = float(value or 0)
    if v <= 0:
        return False
    prev = float(getattr(obj, "_initial_atr_value", 0.0) or 0.0)
    obj._initial_atr_locked = False
    obj._initial_atr_value = v
    obj._initial_atr_locked = True
    logger.info(
        "[User %s] initial_atr VPS upgrade %.6f → %.6f (%s)",
        getattr(obj, "user_id", "?"),
        prev,
        v,
        reason,
    )
    return True


def force_set_initial_atr_for_tests(obj: Any, value: float, *, lock: bool = True) -> None:
    """Test helper — bypass guard by writing private fields directly."""
    obj._initial_atr_value = float(value or 0)
    obj._initial_atr_locked = bool(lock and float(value or 0) > 0)
    if float(value or 0) <= 0:
        obj._initial_atr_locked = False
