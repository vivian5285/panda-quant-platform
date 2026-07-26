"""Smart re-entry mixin — whitepaper v3.0 ADX-tier radar + max-1 reentry.

Closed loop (TV window):
  flat(BE/micro within window) → purge → dual-insurance limit → fill
  → hard+TP+radar(arm=1.00, trail +1 tier)
  hard/loss/window-expired → never reenter
  local pending-tag: NEVER place if tag inflight even when book query empty
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)


class SmartReentryMixin:
    """Requires PositionSupervisor attrs: client, symbol, user_id, canonical_symbol, …"""

    def _init_smart_reentry_fields(self) -> None:
        from app.core.order_place_guard import PendingOrderRegistry
        from app.core.smart_reentry import reset_reentry_state

        sym = getattr(self, "canonical_symbol", None) or getattr(self, "symbol", None)
        st = reset_reentry_state(sym)
        for k, v in st.items():
            setattr(self, k, v)
        self._reentry_loop_stop = threading.Event()
        self._reentry_thread = None
        self._reentry_deferred_plan: dict[str, Any] | None = None
        self._reentry_protect_lock = threading.Lock()
        self.reentry_qty_snapshot = 0.0
        self.reentry_tv_sl_ref = 0.0
        self.reentry_atr_ref = 0.0
        self.reentry_limit_tag = None
        self.reentry_client_order_id = None
        if not isinstance(getattr(self, "_pending_order_registry", None), PendingOrderRegistry):
            self._pending_order_registry = PendingOrderRegistry()
        if not hasattr(self, "radar_tp1_distance"):
            self.radar_tp1_distance = 0.0
        if not hasattr(self, "radar_tv_entry"):
            self.radar_tv_entry = 0.0

    def _pending_orders(self):
        from app.core.order_place_guard import PendingOrderRegistry

        reg = getattr(self, "_pending_order_registry", None)
        if not isinstance(reg, PendingOrderRegistry):
            self._pending_order_registry = PendingOrderRegistry()
        return self._pending_order_registry

    def _resolve_trend_tier(self) -> int:
        from app.core.trend_tier_params import clamp_tier, resolve_tier_from_payload

        stored = getattr(self, "trend_tier", None)
        if stored is not None:
            try:
                return clamp_tier(int(stored))
            except (TypeError, ValueError):
                pass
        payload = getattr(self, "_last_tv_payload", None) or getattr(self, "_tv_entry_fields", None)
        if isinstance(payload, dict):
            tv_sl = float(getattr(self, "reentry_tv_sl_ref", 0) or 0)
            tv_px = float(getattr(self, "tv_price", 0) or 0)
            atr = float(getattr(self, "initial_atr", 0) or getattr(self, "_tv_atr_ref", 0) or 0)
            dist = abs(tv_px - tv_sl) if tv_px > 0 and tv_sl > 0 else None
            return resolve_tier_from_payload(
                payload,
                adx=getattr(self, "current_adx", None),
                tv_stop_distance=dist,
                atr=atr,
            )
        from app.core.trend_tier_params import adx_to_tier

        return adx_to_tier(getattr(self, "current_adx", None))

    def _smart_reentry_state_dict(self) -> dict[str, Any]:
        return {
            "reentry_attempt": int(getattr(self, "reentry_attempt", 0) or 0),
            "reentry_arm_tp1_pct": float(getattr(self, "reentry_arm_tp1_pct", 0.85) or 0.85),
            "reentry_pending": bool(getattr(self, "reentry_pending", False)),
            "reentry_limit_oid": getattr(self, "reentry_limit_oid", None),
            "reentry_limit_deadline": float(getattr(self, "reentry_limit_deadline", 0) or 0),
            "reentry_tv_side": getattr(self, "reentry_tv_side", None),
            "reentry_tv_px": float(getattr(self, "reentry_tv_px", 0) or 0),
            "reentry_qty_snapshot": float(getattr(self, "reentry_qty_snapshot", 0) or 0),
            "reentry_tv_sl_ref": float(getattr(self, "reentry_tv_sl_ref", 0) or 0),
            "reentry_atr_ref": float(getattr(self, "reentry_atr_ref", 0) or 0),
            "reentry_limit_tag": getattr(self, "reentry_limit_tag", None),
            "reentry_client_order_id": getattr(self, "reentry_client_order_id", None),
            "last_close_track": getattr(self, "last_close_track", None),
            "last_close_px": float(getattr(self, "last_close_px", 0) or 0),
            "radar_flat_ts": float(getattr(self, "radar_flat_ts", 0) or 0),
            "trend_tier": int(self._resolve_trend_tier()),
            "radar_tier_boost": int(getattr(self, "radar_tier_boost", 0) or 0),
            "active_early_be_atr": float(getattr(self, "active_early_be_atr", 0) or 0),
            "active_step_trigger_atr": float(getattr(self, "active_step_trigger_atr", 0) or 0),
            "active_step_advance_atr": float(getattr(self, "active_step_advance_atr", 0) or 0),
            "active_coef_min": float(getattr(self, "active_coef_min", 0) or 0),
            "active_coef_max": float(getattr(self, "active_coef_max", 0) or 0),
            "active_breath_tp1_tp2_atr": float(getattr(self, "active_breath_tp1_tp2_atr", 0) or 0),
            "active_breath_tp2_tp3_atr": float(getattr(self, "active_breath_tp2_tp3_atr", 0) or 0),
            "active_hard_buffer": float(getattr(self, "active_hard_buffer", 0) or 0),
            "reentry_tier_label": getattr(self, "reentry_tier_label", None),
            "reentry_abort_reason": getattr(self, "reentry_abort_reason", None),
            "radar_tp1_distance": float(getattr(self, "radar_tp1_distance", 0) or 0),
            "radar_tv_entry": float(getattr(self, "radar_tv_entry", 0) or 0),
        }

    def _load_smart_reentry_state(self, s: dict[str, Any]) -> None:
        from app.core.smart_reentry import tier_for_attempt
        from app.core.trend_tier_params import clamp_tier

        sym = getattr(self, "canonical_symbol", None) or getattr(self, "symbol", None)
        self.reentry_attempt = int(s.get("reentry_attempt", 0) or 0)
        self.reentry_arm_tp1_pct = float(s.get("reentry_arm_tp1_pct", 0.85) or 0.85)
        self.reentry_pending = bool(s.get("reentry_pending", False))
        self.reentry_limit_oid = s.get("reentry_limit_oid")
        self.reentry_limit_deadline = float(s.get("reentry_limit_deadline", 0) or 0)
        self.reentry_tv_side = s.get("reentry_tv_side")
        self.reentry_tv_px = float(s.get("reentry_tv_px", 0) or 0)
        self.reentry_qty_snapshot = float(s.get("reentry_qty_snapshot", 0) or 0)
        self.reentry_tv_sl_ref = float(s.get("reentry_tv_sl_ref", 0) or 0)
        self.reentry_atr_ref = float(s.get("reentry_atr_ref", 0) or 0)
        self.reentry_limit_tag = s.get("reentry_limit_tag")
        self.reentry_client_order_id = s.get("reentry_client_order_id")
        self.last_close_track = s.get("last_close_track")
        self.last_close_px = float(s.get("last_close_px", 0) or 0)
        self.radar_flat_ts = float(s.get("radar_flat_ts", 0) or 0)
        self.trend_tier = clamp_tier(s.get("trend_tier", self._resolve_trend_tier()))
        self.radar_tier_boost = int(s.get("radar_tier_boost", 0) or 0)
        self.reentry_abort_reason = s.get("reentry_abort_reason")
        self.radar_tp1_distance = float(s.get("radar_tp1_distance", 0) or 0)
        self.radar_tv_entry = float(s.get("radar_tv_entry", 0) or 0)
        tier = tier_for_attempt(self.reentry_attempt, sym, adx_tier=self.trend_tier)
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
        self.active_breath_tp1_tp2_atr = float(
            s.get("active_breath_tp1_tp2_atr") or tier.breath_tp1_tp2_atr
        )
        self.active_breath_tp2_tp3_atr = float(
            s.get("active_breath_tp2_tp3_atr") or tier.breath_tp2_tp3_atr
        )
        self.active_hard_buffer = float(s.get("active_hard_buffer") or tier.hard_buffer)
        self.reentry_tier_label = s.get("reentry_tier_label") or tier.tier_label
        # Re-sync arm ratio from attempt (v3: 0.85 vs 1.00)
        self.reentry_arm_tp1_pct = float(
            s.get("reentry_arm_tp1_pct") or tier.arm_tp1_pct
        )
    def _apply_radar_tier(self, attempt: int) -> None:
        from app.core.smart_reentry import apply_tier_to_state

        sym = getattr(self, "canonical_symbol", None) or getattr(self, "symbol", None)
        st = apply_tier_to_state(
            self._smart_reentry_state_dict(),
            attempt,
            sym,
            adx_tier=self._resolve_trend_tier(),
        )
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
        self._pending_orders().clear_all(reason=reason)
        self._reentry_deferred_plan = None
        sym = getattr(self, "canonical_symbol", None) or getattr(self, "symbol", None)
        st = reset_reentry_state(sym, adx_tier=self._resolve_trend_tier())
        for k, v in st.items():
            setattr(self, k, v)
        self.reentry_qty_snapshot = 0.0
        self.reentry_tv_sl_ref = 0.0
        self.reentry_atr_ref = 0.0
        self.reentry_limit_tag = None
        self.reentry_client_order_id = None
        self.radar_flat_ts = 0.0
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

    def _breathing_tier_kwargs(self) -> dict[str, Any]:
        from app.core.trend_tier_params import RADAR_ARM_TP1_PCT

        arm = float(getattr(self, "reentry_arm_tp1_pct", 0) or 0)
        if arm <= 0:
            arm = float(RADAR_ARM_TP1_PCT)
        st = float(getattr(self, "active_step_trigger_atr", 0) or 0)
        eb = float(getattr(self, "active_early_be_atr", 0) or 0)
        sa = float(getattr(self, "active_step_advance_atr", 0) or 0)
        cmin = float(getattr(self, "active_coef_min", 0) or 0)
        cmax = float(getattr(self, "active_coef_max", 0) or 0)
        b12 = float(getattr(self, "active_breath_tp1_tp2_atr", 0) or 0)
        b23 = float(getattr(self, "active_breath_tp2_tp3_atr", 0) or 0)
        attempt = int(getattr(self, "reentry_attempt", 0) or 0)
        kw: dict[str, Any] = {
            "arm_tp1_pct": arm,
            "step_trigger_atr": st if st > 0 else None,
            "early_breakeven_atr": eb if eb > 0 else None,
            "step_advance_atr": sa if sa > 0 else None,
            "coef_min": cmin if cmin > 0 else None,
            "coef_max": cmax if cmax > 0 else None,
            "breath_tp1_tp2_atr": b12 if b12 > 0 else None,
            "breath_tp2_tp3_atr": b23 if b23 > 0 else None,
            "radar_activated": bool(getattr(self, "radar_activated", False)),
            "is_reentry": attempt >= 1,
            "reentry_attempt": attempt,
        }
        tv_e = float(getattr(self, "radar_tv_entry", 0) or getattr(self, "tv_price", 0) or 0)
        if tv_e > 0:
            kw["tv_entry"] = tv_e
        tp1_d = float(getattr(self, "radar_tp1_distance", 0) or 0)
        if tp1_d > 0:
            kw["tp1_dist"] = tp1_d
            kw["radar_tp1_distance"] = tp1_d
        for key, attr in (
            ("tp1_price", "tp1_price"),
            ("tp2_price", "tp2_price"),
            ("tp3_price", "tp3_price"),
        ):
            try:
                v = float(getattr(self, attr, 0) or 0)
            except (TypeError, ValueError):
                v = 0.0
            if v > 0:
                kw[key] = v
        # Fallback: tv_tps[0/1/2]
        if "tp1_price" not in kw or not kw.get("tp1_price"):
            tps = list(getattr(self, "tv_tps", None) or [])
            for i, key in enumerate(("tp1_price", "tp2_price", "tp3_price")):
                if key in kw and float(kw.get(key) or 0) > 0:
                    continue
                if i < len(tps):
                    try:
                        v = float(tps[i] or 0)
                    except (TypeError, ValueError):
                        v = 0.0
                    if v > 0:
                        kw[key] = v
        return kw

    def _seed_radar_tp1_distance(self, *, tv_px: float | None = None, tp1: float | None = None) -> float:
        """Persist |TV.tp1 − TV.price| for arm formula across reentry fills."""
        from app.core.trend_tier_params import tp1_distance

        e = float(tv_px if tv_px is not None else (getattr(self, "tv_price", 0) or 0))
        t1 = float(tp1 or 0)
        if t1 <= 0:
            t1 = float(getattr(self, "tp1_price", 0) or 0)
        if t1 <= 0:
            tps = list(getattr(self, "tv_tps", None) or [])
            if tps:
                try:
                    t1 = float(tps[0] or 0)
                except (TypeError, ValueError, IndexError):
                    t1 = 0.0
        dist = tp1_distance(e, t1)
        if dist > 0:
            self.radar_tp1_distance = dist
            self.radar_tv_entry = e
        return float(getattr(self, "radar_tp1_distance", 0) or 0)
    def _cancel_reentry_limit_order(self) -> None:
        oid = getattr(self, "reentry_limit_oid", None)
        tag = getattr(self, "reentry_limit_tag", None)
        client = getattr(self, "client", None)
        symbol = getattr(self, "symbol", None)
        if oid and client and symbol:
            try:
                client.cancel_order(symbol, order_id=int(oid))
            except Exception as exc:
                logger.debug("cancel reentry limit %s: %s", oid, exc)
        self.reentry_limit_oid = None
        self.reentry_limit_deadline = 0.0
        if tag:
            self._pending_orders().release(str(tag), reason="cancel")
        self.reentry_limit_tag = None
        self.reentry_client_order_id = None

    def _stop_reentry_limit_loop(self) -> None:
        ev = getattr(self, "_reentry_loop_stop", None)
        if ev is not None:
            ev.set()
        self.reentry_pending = False

    def _seed_tier0_on_open(self, side: str, tv_px: float) -> None:
        """First market open — attempt 0, arm=0.85 of tp1_distance; trail at ADX tier."""
        from app.core.trend_tier_params import resolve_tier_from_payload

        self._stop_reentry_limit_loop()
        self._cancel_reentry_limit_order()
        payload = getattr(self, "_last_tv_payload", None) or getattr(self, "_tv_entry_fields", None)
        tv_sl = 0.0
        if hasattr(self, "_pine_stop_loss_ref"):
            tv_sl = float(self._pine_stop_loss_ref() or 0)
        atr = float(getattr(self, "initial_atr", 0) or getattr(self, "_tv_atr_ref", 0) or 0)
        px = float(tv_px or getattr(self, "tv_price", 0) or 0)
        dist = abs(px - tv_sl) if px > 0 and tv_sl > 0 else None
        self.trend_tier = resolve_tier_from_payload(
            payload if isinstance(payload, dict) else None,
            adx=getattr(self, "current_adx", None),
            tv_stop_distance=dist,
            atr=atr,
        )
        self._apply_radar_tier(0)
        self.reentry_pending = False
        self.reentry_tv_side = str(side or "").upper() or None
        self.reentry_tv_px = px
        self.reentry_abort_reason = None
        self.last_close_track = None
        self.radar_flat_ts = 0.0
        self._seed_radar_tp1_distance(tv_px=px)
        # Snapshot Pine SL / ATR for any later reentry hard-stop distance
        if hasattr(self, "_pine_stop_loss_ref"):
            self.reentry_tv_sl_ref = float(self._pine_stop_loss_ref() or 0)
        else:
            self.reentry_tv_sl_ref = float(getattr(self, "_tv_stop_loss_ref", 0) or 0)
        self.reentry_atr_ref = float(
            getattr(self, "initial_atr", 0)
            or getattr(self, "_tv_atr_ref", 0)
            or 0
        )

    def _plan_smart_reentry(
        self,
        *,
        close_track: str,
        close_px: float,
        close_action: str | None = None,
    ) -> dict[str, Any] | None:
        """Decide reentry WITHOUT starting the worker (call after flat purge)."""
        from app.core.smart_reentry import (
            MAX_REENTRY,
            close_allows_reentry,
            smart_reentry_enabled_for,
        )

        sym = getattr(self, "canonical_symbol", None) or getattr(self, "symbol", None)
        if not smart_reentry_enabled_for(sym):
            self.reentry_abort_reason = "disabled"
            return None

        side = str(
            getattr(self, "current_side", None)
            or getattr(self, "reentry_tv_side", "")
            or ""
        ).upper()
        entry = float(getattr(self, "watched_entry", 0) or 0)
        atr = float(getattr(self, "initial_atr", 0) or getattr(self, "current_atr", 0) or 0)
        self.last_close_track = str(close_track or "")
        self.last_close_px = float(close_px or 0)
        flat_ts = float(getattr(self, "radar_flat_ts", 0) or 0)
        if flat_ts <= 0:
            flat_ts = time.time()
            self.radar_flat_ts = flat_ts
        trend_tier = self._resolve_trend_tier()
        cur = int(getattr(self, "reentry_attempt", 0) or 0)
        consumed = list(getattr(self, "consumed_tp_levels", None) or [])
        try:
            from app.core.vps_radar_stages import tp1_filled_from_consumed

            tp1_filled = bool(tp1_filled_from_consumed(consumed))
        except Exception:
            tp1_filled = any(int(x) == 1 for x in consumed if str(x).isdigit() or isinstance(x, int))

        ok, meta = close_allows_reentry(
            side=side,
            entry=entry,
            close_px=float(close_px or 0),
            atr=atr,
            symbol=sym,
            close_track=close_track,
            flat_ts=flat_ts,
            adx_tier=trend_tier,
            reentry_attempt=cur,
            tp1_filled=tp1_filled,
            require_strong_tier=True,
        )
        if not ok:
            self.reentry_abort_reason = meta.get("reason")
            self._reentry_deferred_plan = None
            logger.info(
                "[User %s] reentry denied: %s",
                getattr(self, "user_id", "?"), meta.get("reason"),
            )
            if hasattr(self, "_log"):
                try:
                    self._log("REENTRY_SKIP", f"再入场跳过·{meta.get('reason')}", meta)
                except Exception:
                    pass
            if hasattr(self, "_alert"):
                try:
                    self._alert(
                        "info",
                        "REENTRY_ABORT",
                        "重入放弃",
                        f"原因={meta.get('reason')} 档位={getattr(self, 'reentry_tier_label', '')}",
                        meta,
                    )
                except Exception:
                    pass
            return None

        if cur >= MAX_REENTRY:
            self.reentry_abort_reason = "max_reentry_once"
            if hasattr(self, "_log"):
                try:
                    self._log(
                        "REENTRY_SKIP",
                        "再入场跳过·已重入过一次",
                        {"attempt": cur},
                    )
                except Exception:
                    pass
            return None

        qty = float(getattr(self, "watched_qty", 0) or getattr(self, "initial_qty", 0) or 0)
        if qty <= 0:
            self.reentry_abort_reason = "no_qty"
            return None

        tv_sl = 0.0
        if hasattr(self, "_pine_stop_loss_ref"):
            tv_sl = float(self._pine_stop_loss_ref() or 0)
        if tv_sl <= 0:
            tv_sl = float(getattr(self, "_tv_stop_loss_ref", 0) or 0)
        atr_ref = float(
            atr
            or getattr(self, "_tv_atr_ref", 0)
            or 0
        )
        tv_px = float(
            getattr(self, "reentry_tv_px", 0)
            or getattr(self, "tv_price", 0)
            or entry
            or 0
        )
        next_attempt = cur + 1
        plan = {
            "side": side,
            "qty": qty,
            "next_attempt": next_attempt,
            "tv_px": tv_px,
            "tv_sl": tv_sl,
            "atr_ref": atr_ref,
            "close_px": float(close_px or 0),
            "last_entry": entry,
            "flat_ts": flat_ts,
            "trend_tier": trend_tier,
            "meta": meta,
            "prev_arm_tp1_pct": float(getattr(self, "reentry_arm_tp1_pct", 0.85) or 0.85),
        }
        self._reentry_deferred_plan = plan
        return plan

    def _commit_deferred_reentry(self) -> bool:
        """After flat purge confirmed — apply tier and start limit worker."""
        plan = getattr(self, "_reentry_deferred_plan", None)
        self._reentry_deferred_plan = None
        if not plan:
            return False
        next_attempt = int(plan["next_attempt"])
        side = str(plan["side"]).upper()
        qty = float(plan["qty"])
        if plan.get("trend_tier") is not None:
            self.trend_tier = int(plan["trend_tier"])
        self._apply_radar_tier(next_attempt)
        self.reentry_tv_side = side
        self.reentry_tv_px = float(plan.get("tv_px") or 0)
        self.reentry_qty_snapshot = qty
        self.reentry_tv_sl_ref = float(plan.get("tv_sl") or 0)
        self.reentry_atr_ref = float(plan.get("atr_ref") or 0)
        self.radar_flat_ts = float(plan.get("flat_ts") or getattr(self, "radar_flat_ts", 0) or 0)
        self.reentry_pending = True
        self.reentry_abort_reason = None
        # Restore Pine SL / ATR so hard stop on fill uses TV distance + fill slip
        if self.reentry_tv_sl_ref > 0:
            self._tv_stop_loss_ref = float(self.reentry_tv_sl_ref)
            self._pending_open_tv_sl = float(self.reentry_tv_sl_ref)
        if self.reentry_atr_ref > 0:
            self._tv_atr_ref = float(self.reentry_atr_ref)
            self.initial_atr = float(self.reentry_atr_ref)
        if self.reentry_tv_px > 0:
            self.tv_price = float(self.reentry_tv_px)

        if hasattr(self, "_log"):
            try:
                self._log(
                    "REENTRY_ARM",
                    f"雷达平仓·启动限价再入场 tier={self.reentry_tier_label} attempt={next_attempt}",
                    {
                        **(plan.get("meta") or {}),
                        "attempt": next_attempt,
                        "tier_label": self.reentry_tier_label,
                        "arm_tp1_pct": self.reentry_arm_tp1_pct,
                        "qty": qty,
                        "tv_px": self.reentry_tv_px,
                        "tv_sl": self.reentry_tv_sl_ref,
                        "atr_ref": self.reentry_atr_ref,
                        "tier": {
                            "early_be": self.active_early_be_atr,
                            "step_trigger": self.active_step_trigger_atr,
                            "step_advance": self.active_step_advance_atr,
                            "coef_min": self.active_coef_min,
                            "coef_max": self.active_coef_max,
                            "hard_buffer": getattr(self, "active_hard_buffer", None),
                        },
                    },
                )
            except Exception:
                pass
        if hasattr(self, "_alert"):
            try:
                rem = ""
                meta = plan.get("meta") or {}
                if meta.get("remaining_sec") is not None:
                    rem = f" 窗口剩余={float(meta['remaining_sec']):.0f}s"
                self._alert(
                    "info",
                    "SMART_REENTRY_ARM",
                    "重入尝试",
                    f"档位={self.reentry_tier_label} "
                    f"arm=1.00(重入)/trail+1档 "
                    f"qty={qty} tv={self.reentry_tv_px}{rem}",
                    {
                        "attempt": next_attempt,
                        "close_px": plan.get("close_px"),
                        "arm_tp1_pct": self.reentry_arm_tp1_pct,
                        "arm_kind": "reentry",
                        **meta,
                    },
                )
            except Exception:
                pass

        self._start_reentry_limit_loop(
            side=side,
            qty=qty,
            last_entry=float(plan.get("last_entry") or 0),
        )
        return True

    def _maybe_arm_smart_reentry(
        self,
        *,
        close_track: str,
        close_px: float,
        close_action: str | None = None,
        defer: bool = True,
    ) -> bool:
        """Plan reentry. Default defer=True — start only after flat purge via commit."""
        plan = self._plan_smart_reentry(
            close_track=close_track,
            close_px=close_px,
            close_action=close_action,
        )
        if not plan:
            return False
        if defer:
            return True
        return self._commit_deferred_reentry()

    def _start_reentry_limit_loop(
        self, *, side: str, qty: float, last_entry: float = 0.0,
    ) -> None:
        self._stop_reentry_limit_loop()
        self.reentry_pending = True
        self._reentry_loop_stop = threading.Event()
        stop_ev = self._reentry_loop_stop
        entry_snap = float(last_entry or 0)

        def _run() -> None:
            try:
                self._reentry_limit_worker(
                    side=side, qty=qty, stop_ev=stop_ev, last_entry=entry_snap,
                )
            except Exception as exc:
                logger.exception(
                    "[User %s] reentry worker crashed: %s",
                    getattr(self, "user_id", "?"), exc,
                )
                self.reentry_pending = False
                tag = getattr(self, "reentry_limit_tag", None)
                if tag:
                    self._pending_orders().release(str(tag), reason="crash")

        t = threading.Thread(
            target=_run, daemon=True, name=f"reentry-{getattr(self, 'user_id', 0)}"
        )
        self._reentry_thread = t
        t.start()

    def _reentry_confirm_flat_clean(self, *, max_rounds: int = 3) -> tuple[bool, dict]:
        """Confirm position=0 and open orders empty; purge retries. Fail-closed."""
        client = getattr(self, "client", None)
        symbol = getattr(self, "symbol", None)
        detail: dict[str, Any] = {"rounds": 0, "orders_left": -1, "pos_amt": None}
        if not client or not symbol:
            detail["reason"] = "no_client"
            return False, detail

        for i in range(1, max_rounds + 1):
            detail["rounds"] = i
            # Position
            try:
                pos = client.get_position(symbol) if hasattr(client, "get_position") else None
                amt = float((pos or {}).get("positionAmt") or 0)
                detail["pos_amt"] = amt
                if abs(amt) > 1e-12:
                    detail["reason"] = "still_in_position"
                    return False, detail
            except Exception as exc:
                detail["reason"] = "pos_query_fail"
                detail["error"] = str(exc)[:200]
                time.sleep(1.0)
                continue

            # Purge leftovers (TP/stop/limits) — never place while dirty
            if hasattr(self, "_purge_defense_orders_on_flat"):
                try:
                    self._purge_defense_orders_on_flat(
                        f"reentry_preflight_{i}", notify=False,
                    )
                except Exception as exc:
                    logger.warning("reentry purge: %s", exc)
            elif hasattr(client, "cancel_all_open_orders"):
                try:
                    client.cancel_all_open_orders(symbol)
                except Exception:
                    pass
            time.sleep(0.4)

            # Book must be readable AND empty
            try:
                if hasattr(client, "_invalidate_book_cache"):
                    try:
                        client._invalidate_book_cache("reentry_preflight")
                    except Exception:
                        pass
                oo = client.get_open_orders(symbol)
                if oo is None:
                    detail["reason"] = "book_unreadable"
                    time.sleep(1.0)
                    continue
                n = len(list(oo or []))
                detail["orders_left"] = n
                if n == 0:
                    detail["reason"] = "ok"
                    return True, detail
            except Exception as exc:
                detail["reason"] = "book_query_fail"
                detail["error"] = str(exc)[:200]
                time.sleep(1.0)
                continue

        if detail.get("reason") != "ok":
            detail.setdefault("reason", "clean_failed")
        return False, detail

    def _reentry_limit_worker(
        self,
        *,
        side: str,
        qty: float,
        stop_ev: threading.Event,
        last_entry: float = 0.0,
    ) -> None:
        from app.core.order_place_guard import (
            REENTRY_TAG_TTL_SEC,
            make_client_order_id,
            reentry_tag,
        )
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
        reg = self._pending_orders()

        # Checkpoint 1: flat + empty book before any place
        clean_ok, clean_meta = self._reentry_confirm_flat_clean()
        if not clean_ok:
            self.reentry_abort_reason = clean_meta.get("reason") or "preflight_dirty"
            if hasattr(self, "_log"):
                try:
                    self._log(
                        "REENTRY_ABORT",
                        f"再入场中止·清场未通过 ({self.reentry_abort_reason})",
                        clean_meta,
                    )
                except Exception:
                    pass
            if hasattr(self, "_alert"):
                try:
                    self._alert(
                        "critical",
                        "REENTRY_PREFLIGHT_FAIL",
                        "再入场清场失败·拒挂限价",
                        f"{symbol} {self.reentry_abort_reason} | {clean_meta}",
                        clean_meta,
                    )
                except Exception:
                    pass
            self.reentry_pending = False
            return

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

            # Local tag already inflight → wait, NEVER second place
            existing = reg.active_by_kind("reentry", symbol=symbol)
            if existing is not None:
                logger.warning(
                    "[User %s] reentry refuse place — local tag inflight %s oid=%s",
                    getattr(self, "user_id", "?"), existing.tag, existing.oid,
                )
                # Wait for fill/timeout of existing cycle
                deadline = float(getattr(self, "reentry_limit_deadline", 0) or 0)
                if deadline <= 0:
                    deadline = time.time() + 30
                while time.time() < deadline and not stop_ev.is_set():
                    try:
                        pos = client.get_position(symbol)
                        amt = float((pos or {}).get("positionAmt") or 0)
                        if abs(amt) > 1e-12:
                            self._on_reentry_filled(
                                side=side, qty=abs(amt),
                                entry=float((pos or {}).get("entryPrice") or 0),
                            )
                            return
                    except Exception:
                        pass
                    time.sleep(2.0)
                self._cancel_reentry_limit_order()
                unfilled += 1
                continue

            # Flat check (fail-closed on query error)
            try:
                pos = client.get_position(symbol) if hasattr(client, "get_position") else None
                amt = float((pos or {}).get("positionAmt") or 0)
                if abs(amt) > 1e-12:
                    self.reentry_abort_reason = "already_in_position"
                    break
            except Exception as exc:
                logger.warning("reentry pos check fail-closed: %s", exc)
                time.sleep(5)
                continue

            tv_px = float(getattr(self, "reentry_tv_px", 0) or getattr(self, "tv_price", 0) or 0)
            if tv_px <= 0:
                self.reentry_abort_reason = "no_tv_px"
                break

            # Exchange book check — FAIL CLOSED on error / None (never treat as empty)
            try:
                oo = client.get_open_orders(symbol)
                if oo is None:
                    logger.warning("reentry book unreadable — refuse place")
                    time.sleep(5)
                    continue
                oo_list = list(oo or [])
                conflict = False
                for o in oo_list:
                    if str(o.get("side") or "").upper() != open_side:
                        continue
                    if str(o.get("type") or "").upper() != "LIMIT":
                        continue
                    if bool(o.get("reduceOnly")):
                        continue
                    conflict = True
                    break
                if conflict:
                    # Already have same-dir open limit — do NOT place another
                    logger.warning(
                        "[User %s] reentry same-dir limit on book — wait/abort place",
                        getattr(self, "user_id", "?"),
                    )
                    time.sleep(5)
                    unfilled += 1
                    continue
                if oo_list:
                    # Leftover TP/stop — purge again before open limit
                    clean_ok, clean_meta = self._reentry_confirm_flat_clean(max_rounds=2)
                    if not clean_ok:
                        time.sleep(3)
                        continue
            except Exception as exc:
                logger.warning("reentry open_orders fail-closed: %s", exc)
                time.sleep(5)
                continue

            k5 = k3 = None
            try:
                if hasattr(client, "fetch_klines"):
                    k5 = client.fetch_klines(symbol, interval="5m", limit=3) or []
                    k3 = client.fetch_klines(symbol, interval="3m", limit=3) or []
            except Exception as exc:
                logger.debug("reentry klines: %s", exc)

            limit_px, px_meta = compute_optimal_reentry_price(
                side=side,
                tv_px=tv_px,
                symbol=getattr(self, "canonical_symbol", None) or symbol,
                klines_5m=k5,
                klines_3m=k3,
                last_entry=float(
                    last_entry
                    or getattr(self, "watched_entry", 0)
                    or 0
                ),
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

            attempt = int(getattr(self, "reentry_attempt", 0) or 0)
            tag = reentry_tag(
                getattr(self, "user_id", 0),
                symbol,
                attempt,
                exchange=getattr(self, "exchange_id", None),
            )
            cid = make_client_order_id("sr", getattr(self, "user_id", 0), attempt, unfilled)
            ok_acq, acq_reason = reg.try_acquire(
                tag,
                kind="reentry",
                symbol=symbol,
                ttl_sec=REENTRY_TAG_TTL_SEC,
                client_order_id=cid,
                meta={"limit_px": limit_px, "side": open_side},
            )
            if not ok_acq:
                logger.warning(
                    "[User %s] reentry local-tag refuse: %s tag=%s",
                    getattr(self, "user_id", "?"), acq_reason, tag,
                )
                if hasattr(self, "_alert"):
                    try:
                        self._alert(
                            "critical",
                            "REENTRY_DUP_BLOCK",
                            "再入场重复挂单已拦截",
                            f"local_tag {acq_reason} · 禁止盲挂",
                            {"tag": tag, "reason": acq_reason},
                        )
                    except Exception:
                        pass
                time.sleep(5)
                continue

            self.reentry_limit_tag = tag
            self.reentry_client_order_id = cid
            # Cancel only OUR previous oid (tag already exclusive)
            old_oid = getattr(self, "reentry_limit_oid", None)
            if old_oid:
                try:
                    client.cancel_order(symbol, order_id=int(old_oid))
                except Exception:
                    pass
                self.reentry_limit_oid = None

            try:
                place_kw: dict[str, Any] = {
                    "reduce_only": False,
                }
                # Prefer clientOrderId when exchange supports it
                try:
                    res = client.place_limit_order(
                        open_side, qty, limit_px, symbol,
                        reduce_only=False,
                        client_order_id=cid,
                    )
                except TypeError:
                    res = client.place_limit_order(
                        open_side, qty, limit_px, symbol, reduce_only=False,
                    )
            except Exception as exc:
                logger.warning("reentry place_limit failed: %s", exc)
                reg.release(tag, reason="place_exc")
                self.reentry_limit_tag = None
                time.sleep(10)
                continue

            oid = None
            if isinstance(res, dict):
                oid = res.get("orderId") or res.get("order_id")
            if not res:
                # Timeout / None — keep tag until verify; do NOT immediately re-place
                logger.warning(
                    "[User %s] reentry place returned None — hold tag, verify book",
                    getattr(self, "user_id", "?"),
                )
                time.sleep(2)
                try:
                    oo = list(client.get_open_orders(symbol) or [])
                    for o in oo:
                        if str(o.get("clientOrderId") or "") == cid:
                            oid = o.get("orderId")
                            break
                        if (
                            str(o.get("side") or "").upper() == open_side
                            and str(o.get("type") or "").upper() == "LIMIT"
                            and not bool(o.get("reduceOnly"))
                            and abs(float(o.get("price") or 0) - float(limit_px)) / max(limit_px, 1) < 0.0005
                        ):
                            oid = o.get("orderId")
                            break
                except Exception:
                    pass
                if not oid:
                    # Still unknown — release after short hold? Keep tag for TTL to block storm
                    self.reentry_limit_deadline = time.time() + min(60.0, float(LIMIT_TTL_SEC))
                    time.sleep(5)
                    # If still no oid and no fill, release and count unfilled
                    try:
                        pos = client.get_position(symbol)
                        if abs(float((pos or {}).get("positionAmt") or 0)) > 1e-12:
                            self._on_reentry_filled(
                                side=side,
                                qty=abs(float(pos.get("positionAmt") or 0)),
                                entry=float(pos.get("entryPrice") or limit_px),
                            )
                            return
                    except Exception:
                        pass
                    reg.release(tag, reason="place_none_unverified")
                    self.reentry_limit_tag = None
                    unfilled += 1
                    continue

            reg.mark_oid(tag, oid)
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
                        f"再入场限价 {open_side} {qty} @{limit_px} src={px_meta.get('source')} cid={cid}",
                        {"oid": oid, "tag": tag, "ttl": LIMIT_TTL_SEC, **px_meta},
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

            # Timeout: cancel oid, release tag, then next cycle may place
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
        """Limit filled — mount hard (fill+TV dist+slip) + TP12 + radar. Single-flight."""
        lock = getattr(self, "_reentry_protect_lock", None)
        if lock is None:
            self._reentry_protect_lock = threading.Lock()
            lock = self._reentry_protect_lock
        if not lock.acquire(blocking=False):
            logger.warning("reentry protect already in flight — skip duplicate")
            return
        try:
            self.reentry_pending = False
            tag = getattr(self, "reentry_limit_tag", None)
            self._cancel_reentry_limit_order()
            if tag:
                self._pending_orders().release(str(tag), reason="filled")
            # Release exclusive reentry/hard/radar tags so protect can place
            self._pending_orders().release_kind("reentry", symbol=getattr(self, "symbol", None))

            self.watched_qty = float(qty)
            self.watched_entry = float(entry)
            self.current_side = str(side).upper()
            self.initial_qty = float(qty)
            self.monitoring = True
            # Restore TV refs for hard-stop distance (fill may deviate from TV)
            if float(getattr(self, "reentry_tv_px", 0) or 0) > 0:
                self.tv_price = float(self.reentry_tv_px)
            if float(getattr(self, "reentry_tv_sl_ref", 0) or 0) > 0:
                self._tv_stop_loss_ref = float(self.reentry_tv_sl_ref)
                self._pending_open_tv_sl = float(self.reentry_tv_sl_ref)
            if float(getattr(self, "reentry_atr_ref", 0) or 0) > 0:
                self._tv_atr_ref = float(self.reentry_atr_ref)
                if float(getattr(self, "initial_atr", 0) or 0) <= 0:
                    self.initial_atr = float(self.reentry_atr_ref)

            if hasattr(self, "_log"):
                try:
                    self._log(
                        "REENTRY_FILL",
                        f"再入场成交 {side} {qty} @{entry} attempt={self.reentry_attempt}",
                        {
                            **self._smart_reentry_state_dict(),
                            "hard_uses_fill_plus_slip": True,
                            "tv_px": getattr(self, "tv_price", 0),
                            "tv_sl": getattr(self, "_tv_stop_loss_ref", 0),
                        },
                    )
                except Exception:
                    pass

            protect_out: dict[str, Any] = {}
            try:
                if hasattr(self, "_protect_and_monitor"):
                    protect_out = self._protect_and_monitor(float(qty), float(entry)) or {}
                elif hasattr(self, "_ensure_defenses"):
                    protect_out = self._ensure_defenses(
                        float(qty), float(entry), None, force_rebuild=True,
                    ) or {}
            except Exception as exc:
                logger.error("reentry protect failed: %s", exc)
                protect_out = {"ok": False, "error": str(exc)[:200]}

            # DingTalk live verify checkpoint
            hard_px = float(
                getattr(self, "_frozen_hard_stop_px", 0)
                or getattr(self, "_tv_hard_sl_price", 0)
                or 0
            )
            radar_px = float(getattr(self, "current_sl", 0) or getattr(self, "initial_stop", 0) or 0)
            chk = {
                "side": side,
                "qty": qty,
                "fill": entry,
                "tv_px": float(getattr(self, "tv_price", 0) or 0),
                "hard_px": hard_px,
                "radar_px": radar_px,
                "tier": getattr(self, "reentry_tier_label", None),
                "attempt": getattr(self, "reentry_attempt", 0),
                "protect_ok": bool(protect_out.get("ok", True)) and not protect_out.get("aborted"),
                "pending_tags": self._pending_orders().snapshot(),
                "slip_vs_tv": abs(float(entry) - float(getattr(self, "tv_price", 0) or entry)),
            }
            if hasattr(self, "_alert"):
                try:
                    sev = "info" if chk["protect_ok"] else "critical"
                    self._alert(
                        sev,
                        "SMART_REENTRY_PROTECTED",
                        "再入场成交·防线核查",
                        f"{side} {qty}@{entry} hard={hard_px} radar={radar_px} "
                        f"tier={chk['tier']} slip={chk['slip_vs_tv']:.4f}",
                        chk,
                    )
                except Exception:
                    pass
            if hasattr(self, "_log"):
                try:
                    self._log("REENTRY_PROTECTED", "再入场成交后防线", chk)
                except Exception:
                    pass

            if hasattr(self, "_save_state"):
                try:
                    self._save_state()
                except Exception:
                    pass
            if self.monitoring and hasattr(self, "_sentinel_loop"):
                try:
                    threading.Thread(target=self._sentinel_loop, daemon=True).start()
                except Exception:
                    pass
        finally:
            lock.release()
