"""Unified VPS / deploy restart reconciliation — exchange-first, no blind re-place."""

from __future__ import annotations

import logging
import time
from typing import Any

from app.core.adverse_radar_guard import (
    ADVERSE_VERIFY_RETRIES,
    ADVERSE_VERIFY_RETRY_DELAY_SEC,
    adverse_move_pct,
    is_floating_profit,
)
logger = logging.getLogger(__name__)

STARTUP_LIVE_SETTLE_SEC = 1.0


def recovery_section(ctx: dict | None, key: str) -> dict:
    """Safe nested recovery access — .get(key, {}) still returns None if value is null."""
    if not ctx:
        return {}
    val = ctx.get(key)
    return val if isinstance(val, dict) else {}


def apply_tv_sl_from_sources(target, *sources: dict | None) -> float:
    """Apply first valid tv_sl from recovery sources (latest TV preferred for manual adopt)."""
    for src in sources:
        if not src:
            continue
        sl = float(src.get("tv_sl") or 0)
        if sl > 0:
            if hasattr(target, "tv_sl"):
                target.tv_sl = sl
            return sl
    return float(getattr(target, "tv_sl", 0) or 0)


def adopt_live_tv_side(
    supervisor,
    reconcile: dict | None = None,
    *,
    adopted_manual: bool = False,
) -> dict[str, Any]:
    """
    实盘有持仓时以交易所方向为准，避免人工/外部开仓被 stale last_tv_side 误杀。
    仅当最新 TV 为明确反向 OPEN 且非人工接管时才标记 conflict（不自动全平）。
    """
    live = getattr(supervisor, "current_side", None)
    result: dict[str, Any] = {
        "live_side": live,
        "previous_tv_side": getattr(supervisor, "last_tv_side", None),
        "realigned": False,
        "conflict": False,
        "adopted_manual": adopted_manual,
    }
    if not live:
        return result

    reconcile = reconcile or {}
    latest = (reconcile.get("latest_tv_action") or "").upper()
    prev = getattr(supervisor, "last_tv_side", None)

    if adopted_manual or latest not in ("LONG", "SHORT"):
        supervisor.last_tv_side = live
        result["realigned"] = prev != live
        result["reason"] = "trust_live_manual" if adopted_manual else "trust_live_no_tv_entry"
        return result

    if latest == live:
        supervisor.last_tv_side = live
        result["realigned"] = prev != live
        result["reason"] = "latest_tv_matches_live"
        return result

    # TV 最新为反向 OPEN：标记冲突，但默认仍信任实盘（人工可能先于 TV 成交）
    supervisor.last_tv_side = live
    result["realigned"] = True
    result["conflict"] = True
    result["reason"] = "tv_opposite_but_trust_live"
    return result


def classify_startup_pnl_track(
    entry: float,
    curr_px: float,
    side: str | None,
    *,
    radar_progress: float = 0.0,
    radar_active: bool = False,
    consumed_tp_levels: list | None = None,
) -> str:
    """
    loss_shield — 浮亏/雷达未激活：保 TP123 + TV 硬止损
    profit_radar — 朝 TP1 达激活比例或雷达已锁 / TP 已部分成交：撤硬止损，雷达接管
    """
    if consumed_tp_levels:
        return "profit_radar"
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
            parts.append("TV硬止损✓")
        elif shield.get("placed", 0):
            parts.append("TV硬止损补挂")
        elif audit.get("pnl_track") == "profit_radar":
            parts.append("硬止损已撤")
        elif audit.get("pnl_track") == "loss_shield":
            parts.append("硬止损待补挂")
    prog = audit.get("radar_progress")
    if prog is not None:
        parts.append(f"雷达进度{prog:.0%}")
    radar_sl = audit.get("radar_sl") or {}
    if track == "profit_radar" and radar_sl.get("expected_sl"):
        if radar_sl.get("live"):
            parts.append(f"保本雷达ON@{radar_sl['expected_sl']:.2f}✓")
        else:
            parts.append(f"保本雷达缺失@{radar_sl['expected_sl']:.2f}")
    elif audit.get("breakeven_active"):
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

    def _startup_has_radar_sl_on_book(self, sl_price: float, tolerance: float = 2.0) -> bool:
        if sl_price <= 0:
            return False
        if hasattr(self, "_has_stop_sl_near"):
            return bool(self._has_stop_sl_near(sl_price, tolerance))
        if hasattr(self, "_has_trigger_sl_near"):
            return bool(self._has_trigger_sl_near(sl_price, tolerance))
        return False

    def _startup_ensure_radar_sl(self, sl_price: float, live_qty: float) -> bool:
        if sl_price <= 0 or live_qty <= 0:
            return False
        if getattr(self, "exchange_id", "") == "deepcoin":
            fn = getattr(self, "_ensure_radar_sl", None)
            return bool(fn(live_qty, sl_price)) if fn else False
        fn = getattr(self, "_ensure_radar_sl", None)
        return bool(fn(sl_price, live_qty)) if fn else False

    def _finalize_startup_radar_sl(
        self,
        live_qty: float,
        entry: float,
        curr_px: float,
        pnl_track: str,
    ) -> dict[str, Any]:
        """
        重启最后一关：内存 radar 状态必须对应交易所实盘 STOP。
        TP1 已成交后只剩 TP23 时，仍须补挂移动保本止损。
        """
        audit: dict[str, Any] = {"expected_sl": 0.0, "live": False, "placed": False}
        if pnl_track != "profit_radar" or live_qty <= 0:
            return audit

        if hasattr(self, "_refresh_radar_state_on_recover") and curr_px > 0 and entry > 0:
            self._refresh_radar_state_on_recover(curr_px, entry)

        sl_px = float(getattr(self, "current_sl", 0) or 0)
        audit["expected_sl"] = sl_px
        if sl_px <= 0:
            return audit

        if self._startup_has_radar_sl_on_book(sl_px):
            audit["live"] = True
            return audit

        for attempt in range(3):
            audit["placed"] = self._startup_ensure_radar_sl(sl_px, live_qty)
            time.sleep(0.5 + attempt * 0.25)
            audit["live"] = self._startup_has_radar_sl_on_book(sl_px)
            if audit["live"]:
                break

        if not audit["live"] and hasattr(self, "_realign_radar_defenses"):
            audit["realign"] = bool(self._realign_radar_defenses(live_qty, entry, sl_px))
            time.sleep(0.6)
            audit["live"] = self._startup_has_radar_sl_on_book(sl_px)

        uid = getattr(self, "user_id", "?")
        if audit["live"]:
            logger.info("[User %s] 重启雷达止损实盘核实 ✓ @ %.2f", uid, sl_px)
        else:
            logger.warning(
                "[User %s] 重启雷达止损缺失，补挂仍失败 @ %.2f | placed=%s realign=%s",
                uid, sl_px, audit.get("placed"), audit.get("realign"),
            )
            if hasattr(self, "_alert"):
                self._alert(
                    "warning",
                    "STARTUP_RADAR_SL",
                    "重启接管 · 雷达保本止损未挂上",
                    f"期望 SL @ {sl_px:.2f}，实盘无 STOP 单，请人工核查",
                    audit,
                )
        return audit

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
        4. 浮亏轨：TV 硬止损核实/缺失补挂
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
        consumed = list(getattr(self, "consumed_tp_levels", []) or [])
        radar_active = bool(hasattr(self, "_is_radar_active") and self._is_radar_active())
        pnl_track = classify_startup_pnl_track(
            entry, curr_px, side,
            radar_progress=progress,
            radar_active=radar_active,
            consumed_tp_levels=consumed,
        )
        adverse_pct = round(adverse_move_pct(entry, curr_px, side) * 100, 2)
        floating_profit = is_floating_profit(entry, curr_px, side)

        shield_audit: dict[str, Any] = {}
        radar_handoff = False

        if pnl_track == "profit_radar":
            if self._uses_dual_stop_track():
                shield_audit = self._on_adverse_startup_reconcile(live_qty, curr_px)
            elif hasattr(self, "_sync_binance_merged_stop"):
                shield_audit = self._sync_binance_merged_stop(live_qty)
            else:
                shield_audit = {}
            if progress >= 1.0 or radar_active or consumed:
                radar_handoff = bool(self._handoff_shield_to_radar(live_qty, curr_px))
        else:
            shield_audit = self._on_adverse_startup_reconcile(live_qty, curr_px)
            if not shield_audit.get("aligned"):
                arm = self._arm_adverse_shield_at_open(live_qty)
                shield_audit = {**shield_audit, **(arm or {})}

        if cap_result and cap_result.get("trimmed", 0) > 0 and cap_result.get("defense"):
            tp_result = cap_result["defense"]
        elif hasattr(self, "_reconcile_tp_defenses_on_startup"):
            # TP123 与雷达保本 STOP 分轨：止盈对账不携带 dynamic_sl，避免与 reduceOnly 份额冲突
            tp_result = self._reconcile_tp_defenses_on_startup(
                live_qty, entry, dynamic_sl=None,
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

        stop_px = float(getattr(self, "tv_sl", 0) or 0)

        radar_sl_audit = self._finalize_startup_radar_sl(
            live_qty, entry, curr_px, pnl_track,
        )
        breakeven_live = bool(radar_sl_audit.get("live"))

        result: dict[str, Any] = {
            "pnl_track": pnl_track,
            "floating_profit": floating_profit,
            "adverse_pct": adverse_pct,
            "radar_progress": round(progress, 3),
            "breakeven_active": breakeven_live,
            "radar_sl": radar_sl_audit,
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
