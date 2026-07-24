"""Smart re-entry mixin — progressive radar tiers + limit re-open after radar BE."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)


class SmartReentryMixin:
    """Requires PositionSupervisor attrs: client, symbol, user_id, canonical_symbol, …"""

    def _init_smart_reentry_fields(self) -> None:
        from app.core.smart_reentry import reset_reentry_state

        sym = getattr(self, "canonical_symbol", None) or getattr(self, "symbol", None)
        st = reset_reentry_state(sym)
        for k, v in st.items():
            setattr(self, k, v)
        self._reentry_loop_stop = threading.Event()
        self._reentry_thread = None


    def _smart_reentry_state_dict(self) -> dict[str, Any]:
        return {
            "reentry_attempt": int(getattr(self, "reentry_attempt", 0) or 0),
            "reentry_arm_tp1_pct": float(getattr(self, "reentry_arm_tp1_pct", 0.5) or 0.5),
            "reentry_pending": bool(getattr(self, "reentry_pending", False)),
            "reentry_limit_oid": getattr(self, "reentry_limit_oid", None),
            "reentry_limit_deadline": float(getattr(self, "reentry_limit_deadline", 0) or 0),
            "reentry_tv_side": getattr(self, "reentry_tv_side", None),
            "reentry_tv_px": float(getattr(self, "reentry_tv_px", 0) or 0),
            "last_close_track": getattr(self, "last_close_track", None),
            "last_close_px": float(getattr(self, "last_close_px", 0) or 0),
            "active_early_be_atr": float(getattr(self, "active_early_be_atr", 0) or 0),
            "active_step_trigger_atr": float(getattr(self, "active_step_trigger_atr", 0) or 0),
            "active_step_advance_atr": float(getattr(self, "active_step_advance_atr", 0) or 0),
            "active_coef_min": float(getattr(self, "active_coef_min", 0) or 0),
            "active_coef_max": float(getattr(self, "active_coef_max", 0) or 0),
            "reentry_tier_label": getattr(self, "reentry_tier_label", None),
            "reentry_abort_reason": getattr(self, "reentry_abort_reason", None),
        }

    def _load_smart_reentry_state(self, s: dict[str, Any]) -> None:
        from app.core.smart_reentry import tier_for_attempt

        sym = getattr(self, "canonical_symbol", None) or getattr(self, "symbol", None)
        self.reentry_attempt = int(s.get("reentry_attempt", 0) or 0)
        self.reentry_arm_tp1_pct = float(s.get("reentry_arm_tp1_pct", 0.5) or 0.5)
        self.reentry_pending = bool(s.get("reentry_pending", False))
        self.reentry_limit_oid = s.get("reentry_limit_oid")
        self.reentry_limit_deadline = float(s.get("reentry_limit_deadline", 0) or 0)
        self.reentry_tv_side = s.get("reentry_tv_side")
        self.reentry_tv_px = float(s.get("reentry_tv_px", 0) or 0)
        self.last_close_track = s.get("last_close_track")
        self.last_close_px = float(s.get("last_close_px", 0) or 0)
        self.reentry_abort_reason = s.get("reentry_abort_reason")
        tier = tier_for_attempt(self.reentry_attempt, sym)
        self.active_early_be_atr = float(
            s.get("active_early_be_atr") or tier.early_breakeven_atr
        )
        self.active_step_trigger_atr = float(
            s.get("active_step_trigger_atr") or tier.step_trigger_atr
        )
        self.active_step_advance_atr = float(
            s.get("active_step_advance_atr") or tier.step_advance_atr
        )
        self.active_coef_min = float(s.get("active_coef_min") or tier.coef_min)
        self.active_coef_max = float(s.get("active_coef_max") or tier.coef_max)
        self.reentry_tier_label = s.get("reentry_tier_label") or tier.tier_label

    def _apply_radar_tier(self, attempt: int) -> None:
        from app.core.smart_reentry import apply_tier_to_state

        sym = getattr(self, "canonical_symbol", None) or getattr(self, "symbol", None)
        st = apply_tier_to_state(self._smart_reentry_state_dict(), attempt, sym)
        for k, v in st.items():
            setattr(self, k, v)
        if hasattr(self, "_save_state"):
            try:
                self._save_state()
            except Exception:
                pass

    def reset_reentry_state(self, *, reason: str = "tv_clear") -> None:
        from app.core.smart_reentry import reset_reentry_state

        self._stop_reentry_limit_loop()
        self._cancel_reentry_limit_order()
        sym = getattr(self, "canonical_symbol", None) or getattr(self, "symbol", None)
        st = reset_reentry_state(sym)
        for k, v in st.items():
            setattr(self, k, v)
        self.reentry_abort_reason = reason
        logger.info(
            "[User %s] reentry reset (%s) symbol=%s",
            getattr(self, "user_id", "?"), reason, sym,
        )
        if hasattr(self, "_log"):
            try:
                self._log("REENTRY_RESET", f"智能再入场状态已重置·{reason}", st)
            except Exception:
                pass
        if hasattr(self, "_save_state"):
            try:
                self._save_state()
            except Exception:
                pass

    def _breathing_tier_kwargs(self) -> dict[str, float | None]:
        """Pass active progressive tier into apply_breathing_tick."""
        arm = float(getattr(self, "reentry_arm_tp1_pct", 0.5) or 0.5)
        if arm <= 0:
            arm = 0.50
        st = float(getattr(self, "active_step_trigger_atr", 0) or 0)
        eb = float(getattr(self, "active_early_be_atr", 0) or 0)
        sa = float(getattr(self, "active_step_advance_atr", 0) or 0)
        cmin = float(getattr(self, "active_coef_min", 0) or 0)
        cmax = float(getattr(self, "active_coef_max", 0) or 0)
        return {
            "arm_tp1_pct": arm,
            "step_trigger_atr": st if st > 0 else None,
            "early_breakeven_atr": eb if eb > 0 else None,
            "step_advance_atr": sa if sa > 0 else None,
            "coef_min": cmin if cmin > 0 else None,
            "coef_max": cmax if cmax > 0 else None,
        }

    def _cancel_reentry_limit_order(self) -> None:
        oid = getattr(self, "reentry_limit_oid", None)
        if not oid:
            return
        client = getattr(self, "client", None)
        symbol = getattr(self, "symbol", None)
        if not client or not symbol:
            self.reentry_limit_oid = None
            return
        try:
            client.cancel_order(symbol, order_id=int(oid))
        except Exception as exc:
            logger.debug("cancel reentry limit %s: %s", oid, exc)
        self.reentry_limit_oid = None
        self.reentry_limit_deadline = 0.0

    def _stop_reentry_limit_loop(self) -> None:
        ev = getattr(self, "_reentry_loop_stop", None)
        if ev is not None:
            ev.set()
        self.reentry_pending = False

    def _seed_tier0_on_open(self, side: str, tv_px: float) -> None:
        """First market open — attempt 0 coefficients + arm 50%."""
        self._stop_reentry_limit_loop()
        self._cancel_reentry_limit_order()
        self._apply_radar_tier(0)
        self.reentry_pending = False
        self.reentry_tv_side = str(side or "").upper() or None
        self.reentry_tv_px = float(tv_px or getattr(self, "tv_price", 0) or 0)
        self.reentry_abort_reason = None
        self.last_close_track = None

    def _maybe_arm_smart_reentry(
        self,
        *,
        close_track: str,
        close_px: float,
        close_action: str | None = None,
    ) -> bool:
        """After flat: if radar BE/micro-profit in zone → start limit reentry."""
        from app.core.smart_reentry import (
            MAX_REENTRY,
            close_allows_reentry,
            smart_reentry_enabled_for,
        )

        sym = getattr(self, "canonical_symbol", None) or getattr(self, "symbol", None)
        if not smart_reentry_enabled_for(sym):
            self.reentry_abort_reason = "disabled"
            return False

        side = str(getattr(self, "current_side", None) or getattr(self, "reentry_tv_side", "") or "").upper()
        entry = float(getattr(self, "watched_entry", 0) or 0)
        atr = float(getattr(self, "initial_atr", 0) or getattr(self, "current_atr", 0) or 0)
        self.last_close_track = str(close_track or "")
        self.last_close_px = float(close_px or 0)

        ok, meta = close_allows_reentry(
            side=side,
            entry=entry,
            close_px=float(close_px or 0),
            atr=atr,
            symbol=sym,
            close_track=close_track,
        )
        if not ok:
            self.reentry_abort_reason = meta.get("reason")
            logger.info(
                "[User %s] reentry denied: %s",
                getattr(self, "user_id", "?"), meta.get("reason"),
            )
            if hasattr(self, "_log"):
                try:
                    self._log("REENTRY_SKIP", f"再入场跳过·{meta.get('reason')}", meta)
                except Exception:
                    pass
            return False

        cur = int(getattr(self, "reentry_attempt", 0) or 0)
        if cur >= MAX_REENTRY:
            self.reentry_abort_reason = "max_reentry_tier5"
            if hasattr(self, "_log"):
                try:
                    self._log(
                        "REENTRY_SKIP",
                        "再入场跳过·已达5.0档位后再扫出",
                        {"attempt": cur, "tier": getattr(self, "reentry_tier_label", None)},
                    )
                except Exception:
                    pass
            return False

        next_attempt = cur + 1
        prev_pct = float(getattr(self, "reentry_arm_tp1_pct", 0.5) or 0.5)
        self._apply_radar_tier(next_attempt)
        # Ladder is source of truth (50/65/80/90/95); ×1.3 is documented growth shape
        self.reentry_tv_side = side
        if float(getattr(self, "reentry_tv_px", 0) or 0) <= 0:
            self.reentry_tv_px = float(getattr(self, "tv_price", 0) or entry or 0)
        self.reentry_pending = True
        self.reentry_abort_reason = None
        qty = float(getattr(self, "watched_qty", 0) or getattr(self, "initial_qty", 0) or 0)
        if qty <= 0:
            self.reentry_abort_reason = "no_qty"
            self.reentry_pending = False
            return False

        if hasattr(self, "_log"):
            try:
                self._log(
                    "REENTRY_ARM",
                    f"雷达平仓·启动限价再入场 tier={self.reentry_tier_label} attempt={next_attempt}",
                    {
                        **meta,
                        "attempt": next_attempt,
                        "tier_label": self.reentry_tier_label,
                        "arm_tp1_pct": self.reentry_arm_tp1_pct,
                        "prev_arm_tp1_pct": prev_pct,
                        "tier": {
                            "early_be": self.active_early_be_atr,
                            "step_trigger": self.active_step_trigger_atr,
                            "step_advance": self.active_step_advance_atr,
                            "coef_min": self.active_coef_min,
                            "coef_max": self.active_coef_max,
                        },
                    },
                )
            except Exception:
                pass
        if hasattr(self, "_alert"):
            try:
                self._alert(
                    "info",
                    "SMART_REENTRY_ARM",
                    "智能再入场·限价挂单",
                    f"tier={self.reentry_tier_label} arm={self.reentry_arm_tp1_pct:.0%} "
                    f"early_be={self.active_early_be_atr} coef={self.active_coef_min}~{self.active_coef_max}",
                    {"attempt": next_attempt, "close_px": close_px},
                )
            except Exception:
                pass

        self._start_reentry_limit_loop(side=side, qty=qty)
        return True

    def _start_reentry_limit_loop(self, *, side: str, qty: float) -> None:
        self._stop_reentry_limit_loop()
        self._reentry_loop_stop = threading.Event()
        stop_ev = self._reentry_loop_stop

        def _run() -> None:
            try:
                self._reentry_limit_worker(side=side, qty=qty, stop_ev=stop_ev)
            except Exception as exc:
                logger.exception(
                    "[User %s] reentry worker crashed: %s",
                    getattr(self, "user_id", "?"), exc,
                )
                self.reentry_pending = False

        t = threading.Thread(target=_run, daemon=True, name=f"reentry-{getattr(self, 'user_id', 0)}")
        self._reentry_thread = t
        t.start()

    def _reentry_limit_worker(
        self, *, side: str, qty: float, stop_ev: threading.Event,
    ) -> None:
        from app.core.smart_reentry import (
            LIMIT_TTL_SEC,
            MAX_UNFILLED_CYCLES,
            compute_optimal_reentry_price,
        )

        client = getattr(self, "client", None)
        symbol = getattr(self, "symbol", None)
        if not client or not symbol:
            self.reentry_pending = False
            return

        open_side = "BUY" if str(side).upper() == "LONG" else "SELL"
        unfilled = 0

        while not stop_ev.is_set() and bool(getattr(self, "reentry_pending", False)):
            if unfilled >= MAX_UNFILLED_CYCLES:
                self.reentry_abort_reason = "max_unfilled_cycles"
                if hasattr(self, "_log"):
                    try:
                        self._log(
                            "REENTRY_ABORT",
                            f"再入场终止·连续{MAX_UNFILLED_CYCLES}次限价未成交",
                            {"unfilled": unfilled},
                        )
                    except Exception:
                        pass
                break

            # Flat check
            try:
                pos = client.get_position(symbol) if hasattr(client, "get_position") else None
                amt = float((pos or {}).get("positionAmt") or 0)
                if abs(amt) > 1e-12:
                    self.reentry_abort_reason = "already_in_position"
                    break
            except Exception as exc:
                logger.warning("reentry pos check: %s", exc)
                time.sleep(5)
                continue

            tv_px = float(getattr(self, "reentry_tv_px", 0) or getattr(self, "tv_price", 0) or 0)
            if tv_px <= 0:
                self.reentry_abort_reason = "no_tv_px"
                break

            # No same-direction open limit already
            try:
                oo = list(client.get_open_orders(symbol) or [])
                conflict = False
                for o in oo:
                    if str(o.get("side") or "").upper() != open_side:
                        continue
                    if str(o.get("type") or "").upper() != "LIMIT":
                        continue
                    if bool(o.get("reduceOnly")):
                        continue
                    conflict = True
                    break
                if conflict:
                    self.reentry_abort_reason = "existing_same_dir_limit"
                    break
            except Exception:
                pass

            k5 = k3 = None
            try:
                if hasattr(client, "fetch_klines"):
                    k5 = client.fetch_klines(symbol, interval="5m", limit=3) or []
                    k3 = client.fetch_klines(symbol, interval="3m", limit=3) or []
            except Exception as exc:
                logger.debug("reentry klines: %s", exc)

            limit_px, px_meta = compute_optimal_reentry_price(
                side=side, tv_px=tv_px, symbol=getattr(self, "canonical_symbol", None) or symbol,
                klines_5m=k5, klines_3m=k3,
            )
            if limit_px <= 0:
                self.reentry_abort_reason = px_meta.get("reason") or "not_better_than_tv"
                if hasattr(self, "_log"):
                    try:
                        self._log(
                            "REENTRY_ABORT",
                            f"再入场终止·价格无法优于TV ({self.reentry_abort_reason})",
                            px_meta,
                        )
                    except Exception:
                        pass
                break

            self._cancel_reentry_limit_order()
            try:
                res = client.place_limit_order(
                    open_side, qty, limit_px, symbol, reduce_only=False,
                )
            except Exception as exc:
                logger.warning("reentry place_limit failed: %s", exc)
                time.sleep(10)
                continue

            oid = None
            if isinstance(res, dict):
                oid = res.get("orderId") or res.get("order_id")
            self.reentry_limit_oid = oid
            self.reentry_limit_deadline = time.time() + float(LIMIT_TTL_SEC)
            if hasattr(self, "_save_state"):
                try:
                    self._save_state()
                except Exception:
                    pass
            if hasattr(self, "_log"):
                try:
                    self._log(
                        "REENTRY_LIMIT",
                        f"再入场限价 {open_side} {qty} @{limit_px} src={px_meta.get('source')}",
                        {"oid": oid, "ttl": LIMIT_TTL_SEC, **px_meta},
                    )
                except Exception:
                    pass

            filled = False
            deadline = float(self.reentry_limit_deadline)
            while time.time() < deadline and not stop_ev.is_set():
                try:
                    pos = client.get_position(symbol) if hasattr(client, "get_position") else None
                    amt = float((pos or {}).get("positionAmt") or 0)
                    if abs(amt) > 1e-12:
                        entry = float((pos or {}).get("entryPrice") or limit_px)
                        self._on_reentry_filled(side=side, qty=abs(amt), entry=entry)
                        return
                except Exception:
                    pass
                if oid and hasattr(client, "get_order"):
                    try:
                        od = client.get_order(symbol, order_id=int(oid))
                        st = str((od or {}).get("status") or "").upper()
                        if st in ("FILLED", "PARTIALLY_FILLED"):
                            pos = client.get_position(symbol) or {}
                            amt = abs(float(pos.get("positionAmt") or 0))
                            if amt > 0:
                                self._on_reentry_filled(
                                    side=side,
                                    qty=amt,
                                    entry=float(pos.get("entryPrice") or limit_px),
                                )
                                return
                            filled = True
                            break
                        if st in ("CANCELED", "CANCELLED", "EXPIRED", "REJECTED"):
                            break
                    except Exception:
                        pass
                time.sleep(3.0)

            self._cancel_reentry_limit_order()
            if filled:
                continue
            unfilled += 1
            time.sleep(0.5)

        self.reentry_pending = False
        self._cancel_reentry_limit_order()
        if hasattr(self, "_save_state"):
            try:
                self._save_state()
            except Exception:
                pass

    def _on_reentry_filled(self, *, side: str, qty: float, entry: float) -> None:
        """Limit filled — mount defenses with current progressive tier."""
        self.reentry_pending = False
        self._cancel_reentry_limit_order()
        self.watched_qty = float(qty)
        self.watched_entry = float(entry)
        self.current_side = str(side).upper()
        self.initial_qty = float(qty)
        self.monitoring = True
        if hasattr(self, "_log"):
            try:
                self._log(
                    "REENTRY_FILL",
                    f"再入场成交 {side} {qty} @{entry} attempt={self.reentry_attempt}",
                    self._smart_reentry_state_dict(),
                )
            except Exception:
                pass
        # Remount hard + radar + TP using existing protect path if available
        try:
            if hasattr(self, "_protect_and_monitor"):
                self._protect_and_monitor(float(qty), float(entry))
            elif hasattr(self, "_ensure_defenses"):
                self._ensure_defenses(float(qty), float(entry), None, force_rebuild=True)
        except Exception as exc:
            logger.error("reentry protect failed: %s", exc)
        if hasattr(self, "_save_state"):
            try:
                self._save_state()
            except Exception:
                pass
        # Restart sentinel if needed
        if self.monitoring and hasattr(self, "_sentinel_loop"):
            try:
                threading.Thread(target=self._sentinel_loop, daemon=True).start()
            except Exception:
                pass
