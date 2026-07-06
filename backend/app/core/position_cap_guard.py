"""Regime cap guard: radar-authority trim when live position exceeds tier margin limit."""
from __future__ import annotations

import logging
import time
from typing import Any

from app.core.position_sizing import (
    compute_deepcoin_contracts,
    compute_eth_qty,
    read_contract_equity,
    resolve_cap_sizing_base,
)

logger = logging.getLogger(__name__)

CAP_TOLERANCE_ETH = 0.001
CAP_TRIM_MAX_ROUNDS = 4
CAP_TRIM_VERIFY_DELAY = 0.8
# Reject trim if computed target keeps less than this fraction of live qty (bad max_qty).
CAP_MIN_RETAIN_RATIO = 0.25


class PositionCapGuardMixin:
    """
    Highest-priority sizing alignment: if live qty exceeds regime cap (principal% × leverage),
    market-reduce excess then realign TP1/2/3 while preserving active radar trailing SL.
    """

    def _regime_margin_pct(self) -> float:
        return float(self.regime_settings[self.regime]["margin"]) * float(
            getattr(self, "risk_multiplier", 1.0) or 1.0
        )

    def _is_deepcoin_cap(self) -> bool:
        return getattr(self, "exchange_id", "") == "deepcoin"

    def _cap_tolerance(self) -> float:
        return 0.0 if self._is_deepcoin_cap() else CAP_TOLERANCE_ETH

    def _cap_qty_within_target(self, qty: float, target_qty: float) -> bool:
        """True when live qty is at or below regime cap (float-safe)."""
        return float(qty) <= float(target_qty) + self._cap_tolerance() + 1e-9

    def _cap_equity_balance(self) -> float:
        """Total contract equity for cap math — same anchor as open-order sizing."""
        return read_contract_equity(self.client)

    def _compute_regime_cap_target(self, price: float) -> tuple[float, dict[str, Any]]:
        equity = self._cap_equity_balance()
        principal = float(getattr(self, "initial_principal", 0) or 0)
        sizing_base, sizing_source = resolve_cap_sizing_base(equity, principal)
        margin_pct = self._regime_margin_pct()
        px = float(price or 0)
        if self._is_deepcoin_cap():
            # Reuse deepcoin helper but override sizing base in meta.
            _contracts, meta = compute_deepcoin_contracts(
                live_balance=sizing_base,
                initial_principal=principal,
                margin_pct=margin_pct,
                leverage=int(getattr(self, "leverage", 10) or 10),
                price=px,
                face_value=float(getattr(self, "face_value", 0.1) or 0.1),
            )
            # compute with forced principal anchor
            margin_usd = sizing_base * margin_pct
            notional = margin_usd * int(getattr(self, "leverage", 10) or 10)
            denom = px * float(getattr(self, "face_value", 0.1) or 0.1)
            contracts = max(int(notional / denom), 1) if denom > 0 else 1
            meta["sizing_base"] = round(sizing_base, 2)
            meta["sizing_source"] = sizing_source
            meta["equity_balance"] = round(equity, 2)
            meta["regime"] = self.regime
            return float(contracts), meta

        from app.core.symbol_precision import round_quantity

        margin_usd = sizing_base * margin_pct
        notional = margin_usd * int(getattr(self, "leverage", 10) or 10)
        qty = round_quantity(notional / px) if px > 0 else 0.0
        meta = {
            "sizing_base": round(sizing_base, 2),
            "sizing_source": sizing_source,
            "equity_balance": round(equity, 2),
            "margin_pct": round(margin_pct, 4),
            "margin_usd": round(margin_usd, 2),
            "notional_usd": round(notional, 2),
            "initial_principal": round(principal, 2),
            "leverage": int(getattr(self, "leverage", 10) or 10),
            "price": round(px, 2),
            "regime": self.regime,
        }
        return float(qty), meta

    def _cap_oversize_detail(self, live_qty: float, price: float) -> dict[str, Any]:
        max_qty, cap_meta = self._compute_regime_cap_target(price)
        tol = self._cap_tolerance()
        target_qty = max(0.0, float(max_qty))
        raw_gap = max(0.0, float(live_qty) - target_qty)
        oversized = raw_gap > tol + 1e-9
        excess = max(0.0, raw_gap - tol) if oversized else 0.0
        trim_qty = raw_gap if oversized else 0.0
        retain_ratio = (target_qty / float(live_qty)) if live_qty > 0 else 0.0
        return {
            **cap_meta,
            "max_qty": target_qty,
            "target_qty": target_qty,
            "trim_qty": trim_qty,
            "live_qty": float(live_qty),
            "excess": excess,
            "retain_ratio": round(retain_ratio, 4),
            "oversized": oversized,
            "tolerance": tol,
        }

    def _validate_cap_trim_plan(self, cap: dict[str, Any]) -> str | None:
        """Return error string if trim plan looks unsafe (would flatten instead of align)."""
        live = float(cap.get("live_qty", 0) or 0)
        target = float(cap.get("target_qty", 0) or 0)
        trim = float(cap.get("trim_qty", 0) or 0)
        if live <= 0 or target <= 0:
            return "invalid_qty"
        if trim <= 0:
            return None
        retain = target / live
        if retain < CAP_MIN_RETAIN_RATIO and live > target * 2:
            return (
                f"unsafe_retain_ratio={retain:.3f}: target {target:.4f} too small vs live {live:.4f} "
                f"(likely depleted balance skewed max_qty)"
            )
        if trim > live * 0.85 and target < live * 0.15:
            return (
                f"unsafe_trim_ratio: would cut {trim:.4f} of {live:.4f}, retaining only {target:.4f}"
            )
        if abs(trim - (live - target)) > max(live * 0.05, 0.01):
            return f"trim_mismatch: trim={trim:.4f} expected={live - target:.4f}"
        return None

    def _place_cap_trim_order(self, trim_qty: float) -> bool:
        if trim_qty <= 0:
            return False
        symbol = getattr(self, "symbol", None)
        if self._is_deepcoin_cap():
            pos = self._get_active_position()
            if not pos:
                return False
            close_side = "sell" if str(pos.get("posSide", "long")).lower() == "long" else "buy"
            pos_side = pos.get("posSide", "long")
            trim_int = max(int(trim_qty), 1)
            order = self.client.place_market_order(
                symbol, close_side, pos_side, trim_int, reduce_only=True,
            )
            return order is not None

        from app.core.symbol_precision import round_quantity

        qty = round_quantity(trim_qty)
        if qty <= 0:
            return False
        close_side = self._close_order_side()
        order = self.client.place_market_order(close_side, qty, symbol, reduce_only=True)
        return order is not None

    def _read_live_position_qty(self) -> tuple[float, float]:
        """Return (qty, entry_price)."""
        pos = self._get_active_position()
        if not pos:
            return 0.0, 0.0
        if self._is_deepcoin_cap():
            return float(self._safe_qty(pos.get("size", 0))), float(pos.get("entry_price", 0) or 0)
        return float(pos.get("size", 0)), float(pos.get("entry_price", 0) or 0)

    def _enforce_regime_cap_alignment(
        self,
        live_qty: float,
        entry: float,
        price: float,
        *,
        reason: str = "档位额度对齐",
    ) -> dict[str, Any]:
        """
        Radar-authority: trim excess over regime cap, then realign TP limits.
        Active radar SL (breakeven trail) is passed through and preserved.
        """
        cap = self._cap_oversize_detail(live_qty, price)
        result: dict[str, Any] = {
            "aligned": not cap["oversized"],
            "trimmed": 0.0,
            "cap_meta": cap,
            "reason": reason,
        }
        if cap.get("max_qty", 0) <= 0:
            logger.debug("[User %s] cap guard skipped: max_qty unavailable", self.user_id)
            return result
        if not cap["oversized"]:
            return result

        target_qty = float(cap["target_qty"])
        tol = self._cap_tolerance()
        if float(cap.get("trim_qty", 0) or 0) <= tol + 1e-9:
            logger.info(
                "[User %s] CAP_ALIGN within tolerance: live=%.4f target=%.4f tol=%.4f",
                self.user_id, live_qty, target_qty, tol,
            )
            result["aligned"] = True
            return result

        trim_plan_err = self._validate_cap_trim_plan(cap)
        if trim_plan_err:
            logger.error(
                "[User %s] CAP_ALIGN blocked unsafe trim: %s | cap=%s",
                self.user_id, trim_plan_err, cap,
            )
            self._log("ERROR", f"档位纠偏中止(安全校验): {trim_plan_err}", cap)
            self._alert(
                "critical",
                "CAP_ALIGN_BLOCKED",
                "叠仓超标 · 纠偏中止",
                f"实盘 {live_qty:.4f} 超上限 {target_qty:.4f}，但减仓计划异常已中止: {trim_plan_err}",
                {**cap, "error": trim_plan_err},
            )
            result["error"] = trim_plan_err
            return result

        logger.warning(
            "[User %s] CAP_ALIGN oversized: live=%.4f target=%.4f trim=%.4f regime=%s",
            self.user_id, live_qty, target_qty, cap["trim_qty"], self.regime,
        )

        trimmed_total = 0.0
        for round_i in range(CAP_TRIM_MAX_ROUNDS):
            current_qty, _ = self._read_live_position_qty()
            if current_qty <= 0:
                result["error"] = "trim_zero_position"
                return result
            if self._cap_qty_within_target(current_qty, target_qty):
                break

            slice_trim = max(0.0, current_qty - target_qty)
            from app.core.symbol_precision import round_quantity
            if not self._is_deepcoin_cap():
                slice_trim = round_quantity(slice_trim)
            if slice_trim <= 0:
                break

            if not self._place_cap_trim_order(slice_trim):
                self._log(
                    "ERROR",
                    f"档位额度超标但减仓失败: 实盘 {current_qty:.4f} > 目标 {target_qty:.4f}",
                    cap,
                )
                self._alert(
                    "critical",
                    "CAP_ALIGN_FAIL",
                    "叠仓超标 · 减仓失败",
                    f"实盘 {current_qty:.4f} 超档位{self.regime}上限 {target_qty:.4f}，请人工处理",
                    cap,
                )
                result["error"] = "trim_failed"
                return result

            time.sleep(CAP_TRIM_VERIFY_DELAY)
            after_qty, _ = self._read_live_position_qty()
            trimmed_total += max(0.0, current_qty - after_qty)
            if self._cap_qty_within_target(after_qty, target_qty):
                break
            if round_i == CAP_TRIM_MAX_ROUNDS - 1:
                logger.warning(
                    "[User %s] CAP_ALIGN trim rounds exhausted: want %.4f got %.4f",
                    self.user_id, target_qty, after_qty,
                )

        new_qty, new_entry = self._read_live_position_qty()
        if new_entry > 0:
            entry = new_entry
        if new_qty <= 0:
            result["error"] = "trim_zero_position"
            return result

        if new_qty < target_qty * 0.5 and live_qty > target_qty * 1.5:
            self._alert(
                "critical",
                "CAP_ALIGN_OVERTRIM",
                "叠仓纠偏 · 过度减仓",
                f"目标保留 {target_qty:.4f} ETH，实盘仅剩 {new_qty:.4f} ETH，请人工核查",
                {**cap, "new_qty": new_qty},
            )
            result["error"] = "over_trim"
            result["new_qty"] = new_qty
            return result

        trimmed = max(0.0, float(live_qty) - new_qty) if trimmed_total <= 0 else trimmed_total
        self.watched_qty = new_qty
        if float(getattr(self, "initial_qty", 0) or 0) > new_qty:
            self.initial_qty = new_qty

        sl_to_pass = self._radar_sl_to_pass()
        defense = self._smart_realign_defenses(
            new_qty,
            entry or float(getattr(self, "watched_entry", 0) or 0),
            dynamic_sl=sl_to_pass,
            reason=f"雷达强制减仓对齐档位额度 ({reason})",
        )

        detail = {
            **cap,
            "trimmed": trimmed,
            "new_qty": new_qty,
            "entry": entry,
            "regime": self.regime,
            "radar_sl_preserved": sl_to_pass,
            "defense": defense,
            "trigger": reason,
        }
        msg = (
            f"雷达强制减仓 {trimmed:.4f} ETH · 对齐档位{self.regime}目标 {target_qty:.4f} "
            f"(原 {live_qty:.4f} → 现 {new_qty:.4f}) | TP {defense.get('matched')}/{defense.get('expected')}"
        )
        self._log("CAP_ALIGN", msg, detail)
        self._alert(
            "critical",
            "CAP_ALIGN",
            "叠仓超标 · 雷达强制对齐",
            msg,
            detail,
        )
        if hasattr(self, "_save_state"):
            self._save_state()

        result.update({
            "aligned": True,
            "trimmed": trimmed,
            "new_qty": new_qty,
            "defense": defense,
        })
        return result
