"""Regime cap guard: radar-authority trim when live position exceeds tier margin limit."""
from __future__ import annotations

import logging
import time
from typing import Any

from app.core.position_sizing import compute_deepcoin_contracts, compute_eth_qty

logger = logging.getLogger(__name__)

CAP_TOLERANCE_ETH = 0.001


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

    def _compute_regime_cap_target(self, price: float) -> tuple[float, dict[str, Any]]:
        balance = float(self.client.get_available_balance() or 0)
        margin_pct = self._regime_margin_pct()
        px = float(price or 0)
        if self._is_deepcoin_cap():
            contracts, meta = compute_deepcoin_contracts(
                live_balance=balance,
                initial_principal=float(getattr(self, "initial_principal", 0) or 0),
                margin_pct=margin_pct,
                leverage=int(getattr(self, "leverage", 10) or 10),
                price=px,
                face_value=float(getattr(self, "face_value", 0.1) or 0.1),
            )
            meta["regime"] = self.regime
            return float(contracts), meta

        from app.core.symbol_precision import round_quantity

        qty, meta = compute_eth_qty(
            live_balance=balance,
            initial_principal=float(getattr(self, "initial_principal", 0) or 0),
            margin_pct=margin_pct,
            leverage=int(getattr(self, "leverage", 10) or 10),
            price=px,
            round_fn=round_quantity,
        )
        meta["regime"] = self.regime
        return float(qty), meta

    def _cap_oversize_detail(self, live_qty: float, price: float) -> dict[str, Any]:
        max_qty, cap_meta = self._compute_regime_cap_target(price)
        tol = self._cap_tolerance()
        excess = max(0.0, float(live_qty) - max_qty - tol)
        return {
            **cap_meta,
            "max_qty": max_qty,
            "live_qty": float(live_qty),
            "excess": excess,
            "oversized": excess > 0,
            "tolerance": tol,
        }

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

        excess = cap["excess"]
        max_qty = cap["max_qty"]
        logger.warning(
            "[User %s] CAP_ALIGN oversized: live=%.4f max=%.4f excess=%.4f regime=%s",
            self.user_id, live_qty, max_qty, excess, self.regime,
        )

        if not self._place_cap_trim_order(excess):
            self._log(
                "ERROR",
                f"档位额度超标但减仓失败: 实盘 {live_qty} > 上限 {max_qty}",
                cap,
            )
            self._alert(
                "critical",
                "CAP_ALIGN_FAIL",
                "叠仓超标 · 减仓失败",
                f"实盘 {live_qty} 超档位{self.regime}上限 {max_qty}，请人工处理",
                cap,
            )
            result["error"] = "trim_failed"
            return result

        time.sleep(1.2)
        new_qty, new_entry = self._read_live_position_qty()
        if new_entry > 0:
            entry = new_entry
        if new_qty <= 0:
            result["error"] = "trim_zero_position"
            return result

        trimmed = max(0.0, float(live_qty) - new_qty)
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
            f"雷达强制减仓 {trimmed:.4f} → 对齐档位{self.regime}上限 {max_qty:.4f} "
            f"(原 {live_qty:.4f}) | TP {defense.get('matched')}/{defense.get('expected')}"
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
