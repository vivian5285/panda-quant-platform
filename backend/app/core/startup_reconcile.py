"""Unified VPS / deploy restart reconciliation — exchange-first, no blind re-place."""

from __future__ import annotations

import logging
import time
from typing import Any

from app.core.adverse_radar_guard import (
    ADVERSE_VERIFY_RETRIES,
    ADVERSE_VERIFY_RETRY_DELAY_SEC,
    adverse_hard_stop_price,
    adverse_move_pct,
    is_floating_profit,
)
logger = logging.getLogger(__name__)

STARTUP_LIVE_SETTLE_SEC = 1.0


def classify_startup_pnl_track(
    entry: float,
    curr_px: float,
    side: str | None,
    *,
    radar_progress: float = 0.0,
    radar_active: bool = False,
) -> str:
    """
    loss_shield — 浮亏/雷达未激活：保 TP123 + 10% 硬止损
    profit_radar — 朝 TP1 达激活比例或雷达已锁：撤硬止损，雷达接管
    """
    if radar_active or radar_progress >= 1.0:
        return "profit_radar"
    return "loss_shield"


def format_startup_defense_summary(audit: dict) -> str:
    parts = []
    track = audit.get("pnl_track")
    if track == "profit_radar":
        parts.append("浮盈/雷达轨")
    elif track == "loss_shield":
        parts.append("浮亏/防护轨")
    adv = audit.get("adverse_pct")
    if adv is not None:
        parts.append(f"浮亏{adv:.1f}%")
    tp_m = audit.get("tp_matched")
    tp_e = audit.get("tp_expected")
    if tp_e:
        consumed = audit.get("consumed_tp_levels") or []
        live_qty = audit.get("live_qty")
        initial = audit.get("initial_qty")
        if consumed:
            parts.append(f"已成交TP{''.join(str(x) for x in consumed)}")
        if initial and live_qty and float(initial) > float(live_qty):
            parts.append(f"初始{initial}→现仓{live_qty}")
        parts.append(f"TP{tp_m}/{tp_e}")
    shield = audit.get("shield")
    if isinstance(shield, dict):
        if shield.get("aligned") or shield.get("synced_armed"):
            parts.append("10%硬止损✓")
        elif shield.get("placed", 0):
            parts.append("10%硬止损补挂")
        elif audit.get("pnl_track") == "profit_radar":
            parts.append("硬止损已撤")
        elif audit.get("pnl_track") == "loss_shield":
            parts.append("硬止损待补挂")
    prog = audit.get("radar_progress")
    if prog is not None:
        parts.append(f"雷达进度{prog:.0%}")
    if audit.get("breakeven_active"):
        parts.append("保本雷达ON")
    if audit.get("defenses_skipped"):
        parts.append("未重复挂单")
    elif audit.get("defenses_rebuilt"):
        parts.append("增量补挂")
    return " | ".join(parts) if parts else "接管完成"


class StartupReconcileMixin:
    """Shared restart path: TV+持仓 → cap → TP123 → 硬止损/雷达 双轨."""

    def _startup_radar_progress(self, curr_px: float) -> float:
        if hasattr(self, "_radar_activation_progress"):
            return float(self._radar_activation_progress(curr_px) or 0.0)
        return 0.0

    def _startup_wait_live_book(self) -> None:
        """Brief settle after process restart before reading open orders."""
        time.sleep(STARTUP_LIVE_SETTLE_SEC)

    def _unified_startup_defense_reconcile(
        self,
        live_qty: float,
        entry: float,
        curr_px: float,
        *,
        cap_result: dict | None = None,
        reason: str = "重启接管",
    ) -> dict[str, Any]:
        """
        全域重启对账（VPS 关机 / git pull 重启均走此路径）：
        1. 实盘持仓数量
        2. 浮盈/浮亏 + 雷达进度 → 选轨
        3. TP123 交易所优先对账（齐全跳过）
        4. 浮亏轨：10% 硬止损核实/缺失补挂
        5. 浮盈轨：撤硬止损 + 雷达保本 SL（达比例时）
        """
        self._startup_wait_live_book()
        if hasattr(self, "_resolve_live_qty"):
            live_qty = float(self._resolve_live_qty(live_qty))
        elif hasattr(self, "_resolve_adverse_live_qty"):
            live_qty = float(self._resolve_adverse_live_qty(live_qty))

        if cap_result and cap_result.get("new_qty"):
            live_qty = float(cap_result["new_qty"])

        entry = float(entry or getattr(self, "watched_entry", 0) or 0)
        curr_px = float(curr_px or entry or 0)
        side = getattr(self, "current_side", None)

        if hasattr(self, "_refresh_radar_state_on_recover") and curr_px > 0:
            self._refresh_radar_state_on_recover(curr_px, entry)

        progress = self._startup_radar_progress(curr_px)
        radar_active = bool(hasattr(self, "_is_radar_active") and self._is_radar_active())
        pnl_track = classify_startup_pnl_track(
            entry, curr_px, side,
            radar_progress=progress,
            radar_active=radar_active,
        )
        adverse_pct = round(adverse_move_pct(entry, curr_px, side) * 100, 2)
        floating_profit = is_floating_profit(entry, curr_px, side)

        shield_audit: dict[str, Any] = {}
        sl_to_pass = None
        radar_handoff = False

        if pnl_track == "profit_radar":
            shield_audit = self._disarm_adverse_staged_stops(
                reason="startup_radar_track", notify=False,
            )
            sl_to_pass = (
                self._radar_sl_to_pass()
                if hasattr(self, "_radar_sl_to_pass")
                else (float(getattr(self, "current_sl", 0) or 0) or None)
            )
            if progress >= 1.0 or radar_active:
                radar_handoff = bool(self._handoff_shield_to_radar(live_qty, curr_px))
                if radar_handoff:
                    sl_to_pass = (
                        self._radar_sl_to_pass()
                        if hasattr(self, "_radar_sl_to_pass")
                        else sl_to_pass
                    )
        else:
            shield_audit = self._on_adverse_startup_reconcile(live_qty, curr_px)
            if not shield_audit.get("aligned"):
                arm = self._arm_adverse_shield_at_open(live_qty)
                shield_audit = {**shield_audit, **(arm or {})}
            sl_to_pass = None

        if cap_result and cap_result.get("trimmed", 0) > 0 and cap_result.get("defense"):
            tp_result = cap_result["defense"]
        elif hasattr(self, "_reconcile_tp_defenses_on_startup"):
            tp_result = self._reconcile_tp_defenses_on_startup(
                live_qty, entry, dynamic_sl=sl_to_pass,
            )
        else:
            tp_result = {"matched": 0, "expected": 0, "skipped": True, "audit": {}}

        if pnl_track == "loss_shield" and live_qty > 0:
            plan = shield_audit.get("plan") or self._compute_adverse_stop_plan(live_qty)
            post = self._sync_adverse_shield_with_retry(live_qty)
            shield_audit = {**shield_audit, **post}
            if not post.get("aligned") and self._can_repair_adverse_stops():
                repair = self._arm_adverse_shield_at_open(live_qty)
                shield_audit["post_tp_repair"] = repair
                shield_audit = {**shield_audit, **repair}
                if not repair.get("aligned") and repair.get("placed", 0) > 0:
                    post2 = self._sync_adverse_shield_with_retry(live_qty)
                    shield_audit = {**shield_audit, **post2}
            elif not post.get("aligned"):
                self._maybe_alert_shield_misalign(
                    post,
                    {
                        "live_qty": live_qty,
                        "placed": shield_audit.get("placed", 0),
                        "purged_duplicates": shield_audit.get("startup_purged", 0),
                        "force_alert": True,
                    },
                    context="startup",
                )

        stop_px = adverse_hard_stop_price(entry, str(side or "LONG"))

        result: dict[str, Any] = {
            "pnl_track": pnl_track,
            "floating_profit": floating_profit,
            "adverse_pct": adverse_pct,
            "radar_progress": round(progress, 3),
            "breakeven_active": radar_active,
            "radar_handoff": radar_handoff,
            "shield": shield_audit,
            "shield_stop_price": stop_px,
            "consumed_tp_levels": list(getattr(self, "consumed_tp_levels", []) or []),
            "initial_qty": float(getattr(self, "initial_qty", 0) or 0),
            "tp_matched": tp_result.get("matched"),
            "tp_expected": tp_result.get("expected"),
            "defenses_skipped": bool(tp_result.get("skipped")),
            "defenses_rebuilt": bool(tp_result.get("rebuilt") or tp_result.get("healed")),
            "defenses_aligned": bool(tp_result.get("aligned")),
            "defense_summary": tp_result.get("summary") or tp_result.get("after_summary"),
            "tp_defense": tp_result,
            "live_qty": live_qty,
            "entry": entry,
            "curr_px": curr_px,
            "reason": reason,
        }
        result["startup_summary"] = format_startup_defense_summary(result)

        uid = getattr(self, "user_id", "?")
        logger.info(
            "[User %s] 重启全域对账 | %s | %s",
            uid, reason, result["startup_summary"],
        )
        if hasattr(self, "_save_state"):
            self._save_state()
        return result
