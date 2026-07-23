"""Exchange REST/WS transient failures — must never be treated as flat/zero."""

from __future__ import annotations

import re
import time
from typing import Any


class ExchangeTransientError(RuntimeError):
    """API/network failure; caller must keep last-known state and pause auto-judgment."""

    def __init__(
        self,
        message: str,
        *,
        exchange: str | None = None,
        code: str | int | None = None,
        banned_until_ms: int | None = None,
        cause: BaseException | None = None,
    ):
        super().__init__(message)
        self.exchange = exchange
        self.code = code
        self.banned_until_ms = banned_until_ms
        self.__cause__ = cause

    @property
    def is_ip_ban(self) -> bool:
        return self.code in (-1003, "-1003", 1003, "1003") or bool(self.banned_until_ms)


_BAN_UNTIL_RE = re.compile(r"banned until\s+(\d+)", re.I)
_CODE_RE = re.compile(r"code(?:=|\s*)(-?\d+)", re.I)


def parse_binance_error(exc: BaseException | str) -> dict[str, Any]:
    text = str(exc)
    out: dict[str, Any] = {"raw": text[:500]}
    m = _BAN_UNTIL_RE.search(text)
    if m:
        out["banned_until_ms"] = int(m.group(1))
    c = _CODE_RE.search(text)
    if c:
        try:
            out["code"] = int(c.group(1))
        except ValueError:
            out["code"] = c.group(1)
    if " -1003" in text or "code=-1003" in text or "code\":-1003" in text:
        out["code"] = -1003
    return out


def raise_exchange_transient(
    exc: BaseException,
    *,
    exchange: str,
    op: str,
    user_id: int | str | None = None,
) -> None:
    meta = parse_binance_error(exc)
    code = meta.get("code")
    ban_ms = meta.get("banned_until_ms")
    # -1003 often has no "banned until" stamp — impose shared cool-down
    if code in (-1003, "-1003", 1003, "1003") or "Too many requests" in str(exc):
        try:
            from app.core.ip_rest_cooldown import note_rate_limit

            until = note_rate_limit(
                exchange=exchange,
                user_id=user_id,
                cool_sec=90.0,
                banned_until_ms=int(ban_ms) if ban_ms else None,
            )
            if not ban_ms:
                ban_ms = int(until * 1000)
        except Exception:
            if not ban_ms:
                ban_ms = int((time.time() + 90.0) * 1000)
    msg = f"{exchange} {op} failed: {exc}"
    raise ExchangeTransientError(
        msg,
        exchange=exchange,
        code=code,
        banned_until_ms=ban_ms,
        cause=exc,
    ) from exc
