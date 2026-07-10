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
    TV 方向为权威：实盘与 TV 同为 LONG/SHORT 时对齐；反向则标记 force_close（由调用方强平）。
    最新 TV 非 OPEN（如 CLOSE）时仍信任实盘方向。
    """
    live = getattr(supervisor, "current_side", None)
    result: dict[str, Any] = {
        "live_side": live,
        "previous_tv_side": getattr(supervisor, "last_tv_side", None),
        "realigned": False,
        "conflict": False,
        "force_close": False,
        "adopted_manual": adopted_manual,
    }
    if not live:
        return result

    reconcile = reconcile or {}
    latest = (reconcile.get("latest_tv_action") or "").upper()
    prev = getattr(supervisor, "last_tv_side", None)
    state_tv = (reconcile.get("state_last_tv_side") or prev or "").upper()

    if adopted_manual and live in ("LONG", "SHORT"):
        if state_tv == live:
            supervisor.last_tv_side = live
            result["tv_side"] = live
            result["realigned"] = prev != live
            result["reason"] = "manual_adopt_matches_state_tv"
            return result
        if latest in ("LONG", "SHORT") and latest == live:
            supervisor.last_tv_side = live
            result["tv_side"] = live
            result["realigned"] = prev != live
            result["reason"] = "manual_adopt_matches_user_tv"
            return result
        open_log_side = (reconcile.get("open_log_side") or "").upper()
        if open_log_side == live:
            supervisor.last_tv_side = live
            result["tv_side"] = live
            result["realigned"] = prev != live
            result["reason"] = "manual_adopt_matches_open_log"
            return result

    if latest not in ("LONG", "SHORT"):
        supervisor.last_tv_side = live
        result["tv_side"] = live
        result["realigned"] = prev != live
        result["reason"] = "trust_live_no_tv_entry"
        return result

    tv_side = latest
    result["tv_side"] = tv_side
    supervisor.last_tv_side = tv_side

    if live == tv_side:
        result["realigned"] = prev != tv_side
        result["reason"] = "trust_live_manual" if adopted_manual else "latest_tv_matches_live"
        return result

    result["conflict"] = True
    result["force_close"] = True
    result["reason"] = "tv_opposite_force_flat"
    return result


def is_opposite_tv_live(tv_side: str | None, live_side: str | None) -> bool:
    return (
        tv_side in ("LONG", "SHORT")
        and live_side in ("LONG", "SHORT")
        and tv_side != live_side
    )


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

    def _try_force_align_opposite_to_tv(
        self,
        reconcile: dict | None,
        *,
        adopted_manual: bool = False,
        trigger: str = "startup",
    ) -> dict[str, Any]:
        """实盘与 TV 反向 OPEN → 强平并保留 TV 方向（重启 / 哨兵共用）."""
        sync = adopt_live_tv_side(self, reconcile, adopted_manual=adopted_manual)
        if not sync.get("force_close"):
            return sync

        live = sync.get("live_side")
        tv = sync.get("tv_side")
        qty = float(getattr(self, "watched_qty", 0) or 0)
        entry = float(getattr(self, "watched_entry", 0) or 0)
        detail: dict[str, Any] = {
            **sync,
            "trigger": trigger,
            "qty": qty,
            "entry": entry,
            "exchange": getattr(self, "exchange_id", None),
            "watched_qty": qty,
        }
        msg = f"逆势人工持仓 · 实盘{live} vs TV{tv} → 强平对齐 TV"
        if hasattr(self, "_log"):
            self._log("SIGNAL", f"⚠️ FORCE_ALIGN: {msg}", detail)
        else:
            logger.warning("[User %s] FORCE_ALIGN: %s", getattr(self, "user_id", "?"), msg)

        if hasattr(self, "_alert"):
            self._alert(
                "critical",
                "FORCE_ALIGN",
                "逆势人工持仓 · 强制对齐 TV",
                f"{msg} | {qty} @ {entry:.2f}",
                detail,
            )

        self._close_all(
            f"FORCE_ALIGN：{msg}（{trigger}）",
            close_trigger="force_align_opposite",
        )
        sync["closed"] = True
        sync["force_aligned"] = True
        return sync

    def _sentinel_force_align_if_opposite(self, actual_side: str) -> bool:
        """哨兵巡检：发现与 TV 反向持仓则强平。返回 True 表示已强平并应退出哨兵."""
        tv = getattr(self, "last_tv_side", None)
        if not is_opposite_tv_live(tv, actual_side):
            if not tv and actual_side in ("LONG", "SHORT"):
                self.last_tv_side = actual_side
                if hasattr(self, "_save_state"):
                    self._save_state()
            return False

        self.current_side = actual_side
        self._try_force_align_opposite_to_tv(
            {"latest_tv_action": tv},
            trigger="sentinel",
        )
        return True

    def _idle_book_is_flat(self) -> bool:
        wq = float(getattr(self, "watched_qty", 0) or 0)
        side = getattr(self, "current_side", None)
        init = float(getattr(self, "initial_qty", 0) or 0)
        return wq <= 0 and init <= 0 and side not in ("LONG", "SHORT")

    def _load_idle_recovery_context(self) -> dict:
        """DB 最新 TV + 开仓日志；失败时回退到 supervisor 内存状态."""
        uid = getattr(self, "user_id", None)
        try:
            from app.database import SessionLocal
            from app.services.radar_context import build_radar_recovery_context

            db = SessionLocal()
            try:
                ctx = build_radar_recovery_context(db, uid)
            finally:
                db.close()
            if ctx.get("latest_tv") or ctx.get("trade") or ctx.get("open_log"):
                return ctx
        except Exception as exc:
            logger.debug("[User %s] idle recovery DB context: %s", uid, exc)

        latest_tv = None
        lts = getattr(self, "last_tv_side", None)
        if lts in ("LONG", "SHORT"):
            latest_tv = {
                "action": lts,
                "regime": int(getattr(self, "regime", 3) or 3),
                "atr": float(getattr(self, "current_atr", 30) or 30),
                "price": float(getattr(self, "tv_price", 0) or 0),
                "tv_tps": list(getattr(self, "tv_tps", []) or []),
                "tv_sl": float(getattr(self, "tv_sl", 0) or 0),
            }
        else:
            sig = getattr(self, "last_tv_signal", None)
            if isinstance(sig, dict):
                action = (sig.get("action") or "").upper()
                if action in ("LONG", "SHORT"):
                    latest_tv = {
                        "action": action,
                        "regime": int(sig.get("regime", 3) or 3),
                        "atr": float(sig.get("atr", 30) or 30),
                        "price": float(sig.get("price", 0) or 0),
                        "tv_tps": list(sig.get("tv_tps") or []),
                    }
        return {"trade": None, "open_log": None, "latest_tv": latest_tv, "checks": []}

    def _idle_reconcile_stale_book_flat(self) -> bool:
        fn = getattr(self, "_recover_missed_flat_on_startup", None)
        if fn:
            return bool(fn(was_monitoring=False))
        if hasattr(self, "_handle_detected_flat"):
            return bool(self._handle_detected_flat("idle_patrol"))
        if hasattr(self, "_handle_manual_flat_detected"):
            self._handle_manual_flat_detected("空仓巡检：账本有仓但实盘已平")
            return True
        return False

    def _idle_cancel_orphan_orders_when_flat(self) -> bool:
        sym = getattr(self, "symbol", None)
        if not sym or not hasattr(self.client, "get_open_orders"):
            return False
        try:
            orders = self.client.get_open_orders(sym) or []
        except Exception as exc:
            logger.debug("[User %s] idle orphan order scan: %s", getattr(self, "user_id", "?"), exc)
            return False
        if not orders:
            return False
        self.client.cancel_all_open_orders(sym)
        detail = {"trigger": "idle_patrol", "orphan_orders": len(orders)}
        if hasattr(self, "_log"):
            self._log("IDLE_WATCH", f"空仓巡检：清理 {len(orders)} 个孤儿挂单", detail)
        if hasattr(self, "_alert"):
            self._alert(
                "info",
                "IDLE_WATCH",
                "空仓巡检 · 清理孤儿挂单",
                f"实盘空仓但仍有 {len(orders)} 个挂单，已撤单",
                detail,
            )
        return True

    def _run_idle_live_watch(self) -> None:
        """VPS 账本空仓时仍核对交易所：残量扫尾 / 人工平仓收口 / 同向持仓接管."""
        if getattr(self, "monitoring", False):
            return

        get_pos = getattr(self, "_get_active_position", None)
        if not get_pos:
            return
        pos = get_pos()
        live_qty = float(pos.get("size", 0) or 0) if pos else 0.0

        if live_qty <= 0:
            if not self._idle_book_is_flat():
                prev = float(getattr(self, "watched_qty", 0) or 0)
                if self._idle_reconcile_stale_book_flat():
                    if hasattr(self, "_alert"):
                        self._alert(
                            "warning",
                            "MANUAL_ADJUST",
                            "空仓巡检 · 人工全平收口",
                            f"账本 {prev} → 实盘已空，状态已更新",
                            {"trigger": "idle_patrol", "prev_watched": prev},
                        )
            else:
                self._idle_cancel_orphan_orders_when_flat()
            return

        is_dust = getattr(self, "_is_dust_qty", None)
        if is_dust and is_dust(live_qty):
            if pos and not getattr(self, "current_side", None):
                self.current_side = pos.get("side")
            self._sweep_dust_and_finalize("空闲巡检：盘口蚂蚁仓自动扫平")
            return

        finalize = getattr(self, "_should_finalize_tp_victory", None)
        if finalize and finalize(live_qty):
            if pos and not getattr(self, "current_side", None):
                self.current_side = pos.get("side")
            self._sweep_dust_and_finalize("空闲巡检：止盈残量扫尾")
            return

        side = (pos or {}).get("side") or getattr(self, "current_side", None)
        entry = float((pos or {}).get("entry_price", 0) or 0)
        self.current_side = side
        self.watched_qty = live_qty
        self.watched_entry = entry

        ctx = self._load_idle_recovery_context()
        saved_state_tv_side = getattr(self, "last_tv_side", None)
        reconcile = (
            self._reconcile_radar_context(ctx)
            if hasattr(self, "_reconcile_radar_context")
            else ctx
        )
        if isinstance(reconcile, dict):
            reconcile["state_last_tv_side"] = saved_state_tv_side
        tv_action = (reconcile.get("latest_tv_action") or "").upper()
        if not tv_action:
            lt = recovery_section(ctx, "latest_tv")
            tv_action = (lt.get("action") or "").upper()

        if tv_action in ("LONG", "SHORT") and side != tv_action:
            self._try_force_align_opposite_to_tv(
                reconcile,
                adopted_manual=True,
                trigger="idle_patrol",
            )
            return

        if tv_action.startswith("CLOSE"):
            self._close_all(
                f"空仓巡检: TV已发{tv_action}，执行清场",
                close_trigger="idle_patrol_tv_close",
            )
            return

        from app.config import get_settings

        settings = get_settings()
        cooldown_until = float(getattr(self, "_idle_adopt_cooldown_until", 0) or 0)
        if time.time() < cooldown_until:
            return

        detail = {
            "side": side,
            "qty": live_qty,
            "entry": entry,
            "tv_side": tv_action or getattr(self, "last_tv_side", None),
            "trigger": "idle_patrol",
        }
        if hasattr(self, "_log"):
            self._log(
                "IDLE_WATCH",
                f"空仓巡检发现同向持仓 {side} {live_qty} @ {entry:.2f} → 接管补挂 TP123/雷达",
                detail,
            )
        recover = getattr(self, "recover_on_startup", None)
        if not recover:
            return
        try:
            audit = recover(recovery_context=ctx)
            if audit.get("force_aligned"):
                return
            if audit.get("has_position") and audit.get("monitoring"):
                if hasattr(self, "_alert"):
                    self._alert(
                        "info",
                        "IDLE_WATCH",
                        "空仓巡检 · 同向持仓接管",
                        f"{side} {live_qty} @ {entry:.2f} | "
                        f"{audit.get('startup_summary', 'TP123/雷达已补挂')}",
                        {**audit, **detail},
                    )
            elif audit.get("error"):
                self._idle_adopt_cooldown_until = (
                    time.time() + float(settings.IDLE_ADOPT_RETRY_COOLDOWN_SEC or 45)
                )
        except Exception as exc:
            logger.error(
                "[User %s] idle adopt failed: %s",
                getattr(self, "user_id", "?"),
                exc,
            )
            self._idle_adopt_cooldown_until = (
                time.time() + float(settings.IDLE_ADOPT_RETRY_COOLDOWN_SEC or 45)
            )

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
