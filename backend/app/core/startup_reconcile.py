"""Unified VPS / deploy restart reconciliation — exchange-first, no blind re-place."""

from __future__ import annotations

import logging
import time
from typing import Any

from app.core.adverse_radar_guard import (
    ADVERSE_STOP_TOLERANCE,
    ADVERSE_VERIFY_RETRIES,
    ADVERSE_VERIFY_RETRY_DELAY_SEC,
    adverse_move_pct,
    is_floating_profit,
)
from app.core.position_exposure_guard import (
    audit_position_tp_exposure,
    format_exposure_summary,
    live_side_from_amt,
    resolve_booked_side,
)
from app.core.radar_trail import RADAR_STARTUP_PROFIT_PROGRESS, tp1_consumed
from app.core.symbol_precision import merge_tv_targets
from app.services.tv_signal_enrich import compute_tv_tps_from_regime

logger = logging.getLogger(__name__)

STARTUP_LIVE_SETTLE_SEC = 1.0


def recovery_section(ctx: dict | None, key: str) -> dict:
    """Safe nested recovery access — .get(key, {}) still returns None if value is null."""
    if not ctx:
        return {}
    val = ctx.get(key)
    return val if isinstance(val, dict) else {}


def extract_tv_sl_reference(*sources: dict | None) -> float:
    """First valid TV tv_sl from recovery sources (reference-only, not authoritative)."""
    for src in sources:
        if not src:
            continue
        sl = float(src.get("tv_sl") or 0)
        if sl > 0:
            return sl
    return 0.0


def apply_tv_sl_from_sources(target, *sources: dict | None) -> float:
    """Deprecated: sets tv_sl from TV reference. Use recompute_vps_hard_sl_on_recovery instead."""
    ref = extract_tv_sl_reference(*sources)
    if ref > 0 and hasattr(target, "tv_sl"):
        target.tv_sl = ref
    return ref if ref > 0 else float(getattr(target, "tv_sl", 0) or 0)


def recompute_vps_hard_sl_on_recovery(
    supervisor,
    *,
    entry_px: float | None = None,
    side: str | None = None,
    tv_sl_reference: float | None = None,
) -> dict:
    """Recovery: hard SL = TradingView tv_sl only (no VPS entry×regime fallback)."""
    if not hasattr(supervisor, "_recompute_vps_hard_sl"):
        return {}
    entry = float(
        entry_px
        or getattr(supervisor, "watched_entry", 0)
        or getattr(supervisor, "tv_price", 0)
        or 0
    )
    side_u = (
        (side or "").upper()
        or getattr(supervisor, "current_side", None)
        or getattr(supervisor, "last_tv_side", None)
    )
    if entry <= 0 or side_u not in ("LONG", "SHORT"):
        return {"error": "missing_entry_or_side", "entry": entry, "side": side_u}

    prev_sl = float(getattr(supervisor, "tv_sl", 0) or 0)
    ref = float(tv_sl_reference or 0)
    if ref <= 0:
        ref = float(getattr(supervisor, "_tv_hard_sl_price", 0) or 0)
    if ref <= 0:
        ref = extract_tv_sl_reference(
            getattr(supervisor, "last_tv_signal", None),
            {"tv_sl": getattr(supervisor, "tv_sl", 0)},
        )
    payload: dict = {
        "regime": int(getattr(supervisor, "regime", 3) or 3),
        "atr": float(getattr(supervisor, "current_atr", 0) or 30.0),
    }
    if ref > 0:
        payload["tv_sl"] = ref
        if hasattr(supervisor, "_tv_hard_sl_price"):
            supervisor._tv_hard_sl_price = ref
    meta = supervisor._recompute_vps_hard_sl(entry_px=entry, side=side_u, payload=payload)
    new_sl = float(meta.get("stop_price") or 0)
    if prev_sl > 0 and new_sl > 0:
        meta["prev_sl"] = prev_sl
        meta["sl_changed"] = abs(new_sl - prev_sl) > ADVERSE_STOP_TOLERANCE
    return meta


def live_matches_tv_direction(reconcile: dict | None, live_side: str | None) -> bool:
    """
    True when live position aligns with TV entry direction — manual adopt, not flatten.
    Used to avoid closing same-direction manual positions when latest TV is CLOSE.
    """
    live = (live_side or "").upper()
    if live not in ("LONG", "SHORT"):
        return False
    reconcile = reconcile or {}
    for key in (
        "state_last_tv_side",
        "latest_tv_action",
        "latest_entry_tv_action",
        "open_log_side",
        "last_tv_side",
    ):
        val = (reconcile.get(key) or "").upper()
        if val == live:
            return True
    return False


def live_matches_entry_direction(reconcile: dict | None, live_side: str | None) -> bool:
    """True when live matches entry/open-log/state direction — ignores stale latest TV OPEN/CLOSE."""
    live = (live_side or "").upper()
    if live not in ("LONG", "SHORT"):
        return False
    reconcile = reconcile or {}
    for key in ("state_last_tv_side", "latest_entry_tv_action", "open_log_side"):
        val = (reconcile.get(key) or "").upper()
        if val == live:
            return True
    return False


def should_skip_startup_tv_close_flatten(
    supervisor,
    reconcile: dict | None = None,
) -> tuple[bool, str]:
    """Never flatten on restart when live still matches the opening TV direction.

    Exception: latest TV is CLOSE_PROTECT / CLOSE_STOPLOSS / CLOSE_TP3 → always flatten.
    """
    reconcile = reconcile or {}
    latest = (reconcile.get("latest_tv_action") or "").upper().strip()
    if is_hard_tv_close_action(latest):
        return False, ""
    live_side = getattr(supervisor, "current_side", None)
    if live_side not in ("LONG", "SHORT"):
        return False, ""
    if live_matches_entry_direction(reconcile, live_side):
        return True, "live_matches_entry_direction"
    skip, reason = should_skip_tv_close_for_manual(supervisor, action=latest or None)
    if skip:
        return True, reason
    return False, ""


def finalize_recovery_tv_params(supervisor, report: dict, recovery: dict | None) -> None:
    """Merge TP123 / TV SL from all recovery sources; derive missing TPs from regime+ATR."""
    entry_tv = recovery_section(recovery, "latest_entry_tv")
    open_log = recovery_section(recovery, "open_log")
    latest_tv = recovery_section(recovery, "latest_tv")
    trade = recovery_section(recovery, "trade")

    tp_sources = []
    for src in (latest_tv, entry_tv, open_log, trade):
        if src and src.get("tv_tps"):
            tp_sources.append(src["tv_tps"])
    if getattr(supervisor, "tv_tps", None):
        tp_sources.append(supervisor.tv_tps)
    if tp_sources:
        supervisor.tv_tps = merge_tv_targets(*tp_sources)

    tv_sl_ref = extract_tv_sl_reference(latest_tv, entry_tv, open_log, trade)
    side = (
        getattr(supervisor, "current_side", None)
        or getattr(supervisor, "last_tv_side", None)
        or report.get("open_log_side")
        or (entry_tv or {}).get("action")
    )
    entry_px = float(
        report.get("open_log_entry")
        or getattr(supervisor, "watched_entry", 0)
        or getattr(supervisor, "tv_price", 0)
        or (entry_tv or {}).get("price")
        or (latest_tv or {}).get("price")
        or 0
    )
    sl_meta = recompute_vps_hard_sl_on_recovery(
        supervisor,
        entry_px=entry_px if entry_px > 0 else None,
        side=str(side or "").upper() or None,
        tv_sl_reference=tv_sl_ref if tv_sl_ref > 0 else None,
    )
    if sl_meta:
        report["vps_hard_sl_meta"] = sl_meta
    if tv_sl_ref > 0:
        report["tv_sl_reference"] = tv_sl_ref

    atr = float(getattr(supervisor, "current_atr", 0) or 0)
    regime = int(getattr(supervisor, "regime", 3) or 3)
    if sum(1 for t in supervisor.tv_tps if t > 0) < 3 and str(side or "").upper() in ("LONG", "SHORT"):
        if entry_px <= 0:
            entry_px = float(getattr(supervisor, "watched_entry", 0) or 0)
        if atr <= 0:
            atr = 30.0
            supervisor.current_atr = atr
        if entry_px > 0:
            derived = compute_tv_tps_from_regime(entry_px, atr, regime, str(side).upper())
            supervisor.tv_tps = merge_tv_targets(supervisor.tv_tps, derived)
            report.setdefault("warnings", []).append("tv_tps_derived_from_regime")

    if entry_tv:
        report["latest_entry_tv_action"] = entry_tv.get("action")
    report["tv_tps"] = list(supervisor.tv_tps)
    report["tv_sl"] = float(getattr(supervisor, "tv_sl", 0) or 0)


def prepare_manual_adopt(supervisor) -> None:
    """Reset anchor qty so false TP1 consumption does not drop TP123 on manual takeover."""
    qty = float(getattr(supervisor, "watched_qty", 0) or 0)
    if qty <= 0:
        return
    entry = float(getattr(supervisor, "watched_entry", 0) or 0)
    supervisor.initial_qty = qty
    if float(getattr(supervisor, "base_qty", 0) or 0) <= 0:
        supervisor.base_qty = qty
    supervisor.consumed_tp_levels = []
    supervisor.adopted_manual = True
    if entry > 0:
        supervisor.best_price = entry
    # 人工接管首挂仅 VPS 硬止损 + TP123；雷达待达 TP1 路径比例后再激活
    supervisor.current_sl = 0.0


TV_CLOSE_ACTIONS = frozenset({
    "CLOSE_TP",
    "CLOSE_TRAIL",
    "CLOSE_SL_INITIAL",
    "CLOSE_SL_BREAKEVEN",
    "CLOSE_QUICK_EXIT",
    "CLOSE_RSI_EXIT",
})

# Only these force market flatten (radar cannot know multi-TF / RSI)
TV_HARD_CLOSE_ACTIONS = frozenset({"CLOSE_QUICK_EXIT", "CLOSE_RSI_EXIT"})


def _safe_float(val, default: float = 0.0) -> float:
    try:
        return float(val or 0)
    except (TypeError, ValueError):
        return default


def is_tv_close_action(action: str | None) -> bool:
    a = (action or "").upper().strip()
    return a in TV_CLOSE_ACTIONS or a.startswith("CLOSE")


def is_hard_tv_close_action(action: str | None) -> bool:
    """CLOSE_QUICK_EXIT / CLOSE_RSI_EXIT — must always flatten live qty."""
    a = (action or "").upper().strip()
    if not a:
        return False
    return a in TV_HARD_CLOSE_ACTIONS


# Bare TV CLOSE right after OPEN often is a regime/chart chase alert, not SL/TP.
OPEN_BARE_CLOSE_GRACE_SEC = 60.0


def should_ignore_bare_close_after_open(supervisor, action: str | None) -> tuple[bool, str]:
    """
    Ignore only bare action=CLOSE within grace after a factory OPEN.
    CLOSE_STOPLOSS / CLOSE_TP3 / CLOSE_PROTECT always pass through.
    """
    a = (action or "").upper().strip()
    if a != "CLOSE":
        return False, ""
    opened = float(getattr(supervisor, "trade_opened_at", 0) or 0)
    if opened <= 0:
        return False, ""
    age = time.time() - opened
    if age < 0 or age > OPEN_BARE_CLOSE_GRACE_SEC:
        return False, ""
    live_side, live_qty = resolve_supervisor_live_side(supervisor)
    if live_side not in ("LONG", "SHORT") or live_qty <= 0:
        return False, ""
    if bool(getattr(supervisor, "adopted_manual", False)):
        return False, ""
    if not getattr(supervisor, "current_trade_id", None):
        return False, ""
    return True, (
        f"开仓后 {OPEN_BARE_CLOSE_GRACE_SEC:.0f}s 内忽略裸 CLOSE"
        f"（已持仓 {age:.1f}s，防 TV 换防误杀；止损/TP3/保护仍放行）"
    )


def resolve_supervisor_live_side(supervisor) -> tuple[str | None, float]:
    """Exchange-first live side/qty for TV close skip decisions."""
    side = getattr(supervisor, "current_side", None)
    qty = _safe_float(getattr(supervisor, "watched_qty", 0))
    symbol = getattr(supervisor, "symbol", None)

    pm = getattr(supervisor, "position_manager", None)
    if pm and symbol:
        pos = pm.get_position(symbol)
        if pos and isinstance(pos, dict):
            amt = _safe_float(pos.get("positionAmt", 0))
            if amt != 0:
                return ("LONG" if amt > 0 else "SHORT"), abs(amt)

    get_pos = getattr(supervisor, "_get_active_position", None)
    if get_pos:
        pos = get_pos()
        if pos and isinstance(pos, dict):
            live_qty = _safe_float(pos.get("size", 0))
            if live_qty > 0:
                live_side = pos.get("side") or pos.get("posSide")
                if str(live_side or "").lower() in ("long", "buy"):
                    return "LONG", live_qty
                if str(live_side or "").lower() in ("short", "sell"):
                    return "SHORT", live_qty
                if side in ("LONG", "SHORT"):
                    return side, live_qty

    if side in ("LONG", "SHORT") and qty > 0:
        return side, qty
    return None, 0.0


def should_skip_tv_close_for_manual(supervisor, action: str | None = None) -> tuple[bool, str]:
    """
    Bare TV CLOSE must not flatten manual / external positions aligned with entry.

    CLOSE_PROTECT / CLOSE_STOPLOSS / CLOSE_TP3 are hard exits and always execute
    (same priority as open-grace: only bare CLOSE may be deferred).
    """
    if is_hard_tv_close_action(action):
        return False, ""

    live_side, live_qty = resolve_supervisor_live_side(supervisor)
    if live_side not in ("LONG", "SHORT") or live_qty <= 0:
        return False, ""

    adopted = bool(getattr(supervisor, "adopted_manual", False))
    trade_id = getattr(supervisor, "current_trade_id", None)
    if trade_id and not adopted:
        return False, ""

    # Only bare CLOSE (or unspecified action from startup helpers) can skip
    a = (action or "").upper().strip()
    if a and a != "CLOSE":
        return False, ""

    last_tv = (getattr(supervisor, "last_tv_side", None) or "").upper()
    if adopted or not trade_id:
        if not last_tv or last_tv == live_side:
            return True, "manual_same_direction_skip_tv_close"
        if is_opposite_tv_live(last_tv, live_side):
            return False, ""
        return True, "manual_external_skip_tv_close"
    return False, ""


def is_manual_same_direction_position(supervisor, action: str | None) -> bool:
    """True when live position is manual/external and matches TV OPEN direction."""
    live_side, live_qty = resolve_supervisor_live_side(supervisor)
    if live_side not in ("LONG", "SHORT") or live_qty <= 0:
        return False
    if str(action or "").upper() != live_side:
        return False
    adopted = bool(getattr(supervisor, "adopted_manual", False))
    trade_id = getattr(supervisor, "current_trade_id", None)
    return adopted or not trade_id


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

    if live_matches_entry_direction(reconcile, live):
        supervisor.last_tv_side = live
        result["tv_side"] = live
        result["realigned"] = prev != live
        result["reason"] = "trust_live_entry_direction_over_latest_tv"
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
    activation: float | None = None,
) -> str:
    """
    loss_shield — 未达雷达激活：保 TP123 + TV tv_sl 硬止损（无 VPS 宽止损）
    profit_radar — TP1 已成交、雷达已锁、或路径进度 ≥ 档位激活比例（与实盘哨兵一致）
    """
    consumed = list(consumed_tp_levels or [])
    if tp1_consumed(consumed) or any(x in consumed for x in (2, 3)):
        return "profit_radar"
    if radar_active:
        return "profit_radar"
    act = float(activation if activation is not None else RADAR_STARTUP_PROFIT_PROGRESS)
    if float(radar_progress or 0) + 1e-9 >= act:
        return "profit_radar"
    _ = (entry, curr_px, side)
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
        on_conflict: str | None = None,
    ) -> dict[str, Any]:
        """TV 方向为准：方向不一致 → 强制市价全平 + 钉钉（重启与运行中同一逻辑）。

        ``on_conflict="pause"`` 仅作显式逃生阀（缺持久化 TP 等另路径仍用 ``_pause_trading``）。
        """
        sync = adopt_live_tv_side(self, reconcile, adopted_manual=adopted_manual)
        if not sync.get("force_close"):
            return sync

        mode = on_conflict or "force_close"
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
            "side": live,
            "price": entry,
            "on_conflict": mode,
        }

        if mode == "pause":
            msg = f"持仓方向与 TV 不一致：实盘{live} vs TV{tv} → 暂停交易"
            if hasattr(self, "_pause_trading"):
                self._pause_trading(msg, detail)
            elif hasattr(self, "_alert"):
                self._alert("critical", "TRADING_PAUSED", "交易已暂停", msg, detail)
            sync["paused"] = True
            sync["force_aligned"] = False
            sync["closed"] = False
            return sync

        msg = f"实盘{live} vs TV{tv} → 强制平仓对齐 TV"
        if hasattr(self, "_log"):
            self._log("SIGNAL", f"⚠️ FORCE_ALIGN: {msg}", detail)
        else:
            logger.warning("[User %s] FORCE_ALIGN: %s", getattr(self, "user_id", "?"), msg)

        if hasattr(self, "_alert"):
            self._alert(
                "critical",
                "FORCE_ALIGN",
                "方向不一致 · 强制平仓对齐 TV",
                f"{msg} | {qty} @ {entry:.2f}（{trigger}）",
                detail,
            )

        self._close_all(
            f"FORCE_ALIGN：{msg}（{trigger}）",
            close_trigger="force_align_opposite",
        )
        sync["closed"] = True
        sync["force_aligned"] = True
        sync["paused"] = False
        return sync

    def _sentinel_force_align_if_opposite(self, actual_side: str) -> bool:
        """哨兵巡检：仅当 TV 方向与实盘 OPEN 反向时强平（人工同向单不扫）."""
        adopted = bool(getattr(self, "adopted_manual", False))
        tv = getattr(self, "last_tv_side", None)
        if not is_opposite_tv_live(tv, actual_side):
            if not tv and actual_side in ("LONG", "SHORT"):
                self.last_tv_side = actual_side
                if hasattr(self, "_save_state"):
                    self._save_state()
            return False

        self.current_side = actual_side
        if adopted:
            sync = adopt_live_tv_side(
                self,
                {
                    "latest_tv_action": tv,
                    "state_last_tv_side": tv,
                    "open_log_side": getattr(self, "_open_log_side", None),
                },
                adopted_manual=True,
            )
            if not sync.get("force_close"):
                return False

        self._try_force_align_opposite_to_tv(
            {
                "latest_tv_action": tv,
                "state_last_tv_side": tv,
                "open_log_side": getattr(self, "_open_log_side", None),
            },
            adopted_manual=adopted,
            trigger="sentinel",
        )
        return True

    def _audit_live_exposure(
        self,
        live_qty: float,
        live_side: str | None,
        *,
        position_amt: float | None = None,
        curr_px: float | None = None,
    ) -> dict[str, Any]:
        """实盘头寸 vs 挂单止盈合计 — 检测超挂/方向背离."""
        amt = position_amt
        if amt is None and hasattr(self, "position_manager"):
            pos = self.position_manager.get_position(getattr(self, "symbol", ""))
            if pos:
                amt = float(pos.get("positionAmt", 0) or 0)
        side = live_side or live_side_from_amt(amt or 0)
        qty = abs(float(live_qty or 0))
        if qty <= 0 and amt:
            qty = abs(float(amt))

        tp_orders: list[dict] = []
        expected: list[dict] = []
        if hasattr(self, "_collect_tp_limit_orders"):
            tp_orders = self._collect_tp_limit_orders() or []
        if hasattr(self, "_expected_tp_levels") and qty > 0:
            expected = self._expected_tp_levels(qty, curr_px) or []

        booked = resolve_booked_side(
            current_side=getattr(self, "current_side", None),
            last_tv_side=getattr(self, "last_tv_side", None),
        )
        is_contracts = bool(getattr(self, "face_value", None))
        audit = audit_position_tp_exposure(
            live_qty=qty,
            live_side=side,
            tp_orders=tp_orders,
            expected_levels=expected,
            booked_side=booked,
            is_contracts=is_contracts,
        )
        audit["summary"] = format_exposure_summary(audit)
        audit["exchange"] = getattr(self, "exchange_id", None)
        return audit

    def _remediate_exposure_anomaly(
        self,
        exposure: dict[str, Any],
        entry: float,
        *,
        trigger: str = "sentinel",
        curr_px: float | None = None,
    ) -> dict[str, Any]:
        """超挂止盈或方向背离 → 撤单重挂 / 强平对齐 TV."""
        result: dict[str, Any] = {"trigger": trigger, "exposure": exposure, "remediated": False}
        live_qty = float(exposure.get("live_qty") or 0)
        live_side = exposure.get("live_side")
        summary = exposure.get("summary") or format_exposure_summary(exposure)

        if exposure.get("side_flip"):
            tv = getattr(self, "last_tv_side", None)
            self.current_side = live_side
            self.watched_qty = live_qty
            if entry > 0:
                self.watched_entry = entry
            detail = {
                **exposure,
                "trigger": trigger,
                "tv_side": tv,
                "live_side": live_side,
                "qty": live_qty,
                "entry": entry,
            }
            msg = f"实盘方向背离 TV：{live_side} {live_qty} vs TV {tv} | {summary}"
            if hasattr(self, "_log"):
                self._log("SIGNAL", f"⚠️ POSITION_SIDE_FLIP: {msg}", detail)
            if hasattr(self, "_alert"):
                self._alert(
                    "critical",
                    "POSITION_SIDE_FLIP",
                    "逆势蚂蚁仓 · 强平对齐 TV",
                    msg,
                    detail,
                )
            sync = self._try_force_align_opposite_to_tv(
                {
                    "latest_tv_action": tv,
                    "state_last_tv_side": tv,
                    "open_log_side": getattr(self, "_open_log_side", None),
                },
                adopted_manual=bool(getattr(self, "adopted_manual", False)),
                trigger=trigger,
            )
            result.update(sync)
            result["remediated"] = bool(sync.get("closed"))
            return result

        if exposure.get("over_committed") and live_qty > 0 and entry > 0:
            msg = f"止盈挂单超挂 → 核武重挂 | {summary}"
            if hasattr(self, "_log"):
                self._log("DEFENSE_HEAL", msg, exposure)
            if hasattr(self, "_alert"):
                self._alert(
                    "warning",
                    "TP_OVER_COMMIT",
                    "止盈超挂纠偏",
                    msg,
                    exposure,
                )
            if hasattr(self, "_cancel_all_tp_limit_orders"):
                self._cancel_all_tp_limit_orders()
                time.sleep(0.5)
            defense: dict[str, Any] = {}
            if hasattr(self, "_nuclear_realign_tp"):
                sl = self._radar_sl_to_pass() if hasattr(self, "_radar_sl_to_pass") else None
                defense = self._nuclear_realign_tp(
                    live_qty, entry, dynamic_sl=sl, rounds=3,
                )
            elif hasattr(self, "_smart_realign_defenses"):
                sl = self._radar_sl_to_pass() if hasattr(self, "_radar_sl_to_pass") else None
                defense = self._smart_realign_defenses(
                    live_qty, entry, dynamic_sl=sl, reason="止盈超挂纠偏",
                )
            post = self._audit_live_exposure(live_qty, live_side, curr_px=curr_px)
            result["defense"] = defense
            result["post_exposure"] = post
            result["remediated"] = not post.get("over_committed")
            return result

        return result

    def _sentinel_exposure_patrol(
        self,
        actual_qty: float,
        actual_side: str,
        entry: float,
        curr_px: float,
        *,
        trigger: str = "sentinel",
    ) -> bool:
        """巡检：头寸与止盈合计是否匹配；异常则实盘核实后纠偏."""
        exposure = self._audit_live_exposure(
            actual_qty, actual_side, curr_px=curr_px,
        )
        if not exposure.get("needs_remediate"):
            return False
        self._remediate_exposure_anomaly(
            exposure, entry, trigger=trigger, curr_px=curr_px,
        )
        return True

    def _preserve_manual_on_tv_close(
        self,
        raw_action: str,
        *,
        skip_reason: str,
        tv_reason: str | None = None,
    ) -> dict[str, Any]:
        """Ignore TV CLOSE for manual same-direction positions; refresh TP123/雷达."""
        import threading

        was_monitoring = bool(getattr(self, "monitoring", False))
        live_side, live_qty = resolve_supervisor_live_side(self)
        if live_side:
            self.current_side = live_side
            self.last_tv_side = live_side
        self.adopted_manual = True
        self.monitoring = True
        self.watched_qty = live_qty

        entry = float(getattr(self, "watched_entry", 0) or 0)
        pm = getattr(self, "position_manager", None)
        if pm and getattr(self, "symbol", None):
            pos = pm.get_position(self.symbol)
            if pos:
                entry = float(pos.get("entryPrice") or entry or 0)
                self.watched_entry = entry
        elif hasattr(self, "_get_active_position"):
            pos = self._get_active_position()
            if pos:
                entry = float(pos.get("entry_price", 0) or entry or 0)
                self.watched_entry = entry

        curr_px = entry
        if hasattr(self.client, "get_current_price"):
            curr_px = float(self.client.get_current_price(self.symbol) or 0) or entry

        detail: dict[str, Any] = {
            "tv_action": raw_action,
            "skip_reason": skip_reason,
            "side": live_side,
            "qty": live_qty,
            "entry": entry,
            "tv_reason": tv_reason,
            "adopted_manual": True,
        }
        msg = (
            f"收到 TV {raw_action}，人工同向持仓 {live_side} {live_qty} "
            f"继续 TP123/雷达管理（未强平）"
        )
        if hasattr(self, "_log"):
            self._log("SIGNAL", f"⏭️ {msg}", detail)
        if hasattr(self, "_alert"):
            self._alert(
                "info",
                "TV_CLOSE_SKIPPED",
                "TV平仓信号已忽略 · 人工同向持仓",
                msg,
                detail,
            )

        if live_qty > 0 and entry > 0:
            try:
                if hasattr(self, "_unified_startup_defense_reconcile"):
                    unified = self._unified_startup_defense_reconcile(
                        live_qty, entry, curr_px, reason="TV_CLOSE忽略后补挂",
                    )
                    detail["startup_summary"] = unified.get("startup_summary")
                elif hasattr(self, "_smart_realign_defenses"):
                    detail["tp_realign"] = self._smart_realign_defenses(
                        live_qty, entry, dynamic_sl=None,
                    )
                    if hasattr(self, "_sync_tv_hard_stop"):
                        detail["shield"] = self._sync_tv_hard_stop(live_qty)
            except Exception as exc:
                logger.warning(
                    "[User %s] defense refresh after TV close skip: %s",
                    getattr(self, "user_id", "?"), exc,
                )
                detail["refresh_error"] = str(exc)

        if hasattr(self, "_save_state"):
            self._save_state()
        if hasattr(self, "_ensure_price_ws"):
            self._ensure_price_ws()

        if not was_monitoring:
            target = getattr(self, "_sentinel_loop", None)
            if target:
                threading.Thread(target=target, daemon=True).start()

        return {"status": "skipped", "reason": skip_reason, "action": raw_action, "detail": detail}

    def _preserve_manual_on_tv_open_reopen(self, action: str, curr_px: float) -> dict[str, Any]:
        """Same-direction TV OPEN must not 先平后开 manual positions."""
        live_side, live_qty = resolve_supervisor_live_side(self)
        entry = float(getattr(self, "watched_entry", 0) or 0)
        pm = getattr(self, "position_manager", None)
        if pm and getattr(self, "symbol", None):
            pos = pm.get_position(self.symbol)
            if pos:
                entry = float(pos.get("entryPrice") or entry or 0)
        self.adopted_manual = True
        self.monitoring = True
        self.current_side = action
        self.last_tv_side = action
        self.watched_qty = live_qty
        self.watched_entry = entry

        detail = {"side": action, "qty": live_qty, "entry": entry, "tv_price": curr_px}
        msg = "人工同向持仓：忽略 TV OPEN 先平后开，刷新 TP123/雷达"
        if hasattr(self, "_log"):
            self._log("SIGNAL", msg, detail)
        if hasattr(self, "_alert"):
            self._alert("info", "TV_OPEN_SKIPPED", "TV开仓信号 · 保留人工持仓", msg, detail)

        if live_qty > 0 and hasattr(self, "_unified_startup_defense_reconcile"):
            unified = self._unified_startup_defense_reconcile(
                live_qty, entry, curr_px, reason="TV_OPEN忽略先平后开",
            )
            detail["startup_summary"] = unified.get("startup_summary")
        if hasattr(self, "_save_state"):
            self._save_state()
        return {"status": "skipped", "reason": "manual_skip_tv_open_reopen", "action": action, "detail": detail}

    def _purge_defense_orders_on_flat(self, trigger: str = "flat", *, notify: bool = True) -> dict:
        """Immediately tear down TP123 + STOP/algo/conditional when exchange position is flat."""
        sym = getattr(self, "symbol", None)
        detail: dict[str, Any] = {
            "trigger": trigger,
            "prev_side": getattr(self, "current_side", None),
            "prev_watched_qty": float(getattr(self, "watched_qty", 0) or 0),
            "cancelled_tp": 0,
            "cancelled_stops": 0,
            "cancelled_all": False,
            "disarmed_stops": 0,
        }
        if not sym:
            return detail

        if detail["prev_side"] in ("LONG", "SHORT"):
            self._flat_purge_side = detail["prev_side"]

        tp_fn = getattr(self, "_cancel_all_tp_limit_orders", None)
        if tp_fn:
            try:
                detail["cancelled_tp"] = int(tp_fn(flat_purge=True))
            except TypeError:
                detail["cancelled_tp"] = int(tp_fn())

        consumed_fn = getattr(self, "_cancel_tp_orders_for_consumed_levels", None)
        if consumed_fn:
            detail["cancelled_tp"] += int(consumed_fn() or 0)

        stop_fn = getattr(self, "_cancel_binance_all_close_stops", None)
        if stop_fn:
            detail["cancelled_stops"] = int(stop_fn() or 0)
        elif hasattr(self, "_cancel_stop_orders"):
            detail["cancelled_stops"] = int(self._cancel_stop_orders() or 0)
        elif hasattr(self, "_cancel_radar_stop_orders"):
            detail["cancelled_stops"] = int(self._cancel_radar_stop_orders() or 0)

        if hasattr(self, "_disarm_adverse_staged_stops"):
            disarm = self._disarm_adverse_staged_stops(reason=trigger, notify=False)
            detail["disarmed_stops"] = int(disarm.get("cancelled", 0) or 0)
            detail["cancelled_stops"] += detail["disarmed_stops"]

        if hasattr(self.client, "cancel_all_open_orders"):
            self.client.cancel_all_open_orders(sym)
            detail["cancelled_all"] = True

        if hasattr(self, "_flat_purge_side"):
            delattr(self, "_flat_purge_side")

        total_cancelled = (
            detail["cancelled_tp"]
            + detail["cancelled_stops"]
            + (1 if detail["cancelled_all"] else 0)
        )
        if notify and total_cancelled > 0:
            prev_s = detail["prev_side"] or "?"
            prev_q = detail["prev_watched_qty"]
            parts = []
            if detail["cancelled_tp"] > 0:
                parts.append(f"TP×{detail['cancelled_tp']}")
            if detail["cancelled_stops"] > 0:
                parts.append(f"止损×{detail['cancelled_stops']}")
            if detail["cancelled_all"]:
                parts.append("全撤")
            cancel_desc = " ".join(parts) or "挂单"
            if hasattr(self, "_log"):
                self._log(
                    "FLAT_PURGE",
                    f"平仓撤单: {prev_s} {prev_q} → {cancel_desc}",
                    detail,
                )
            if hasattr(self, "_alert"):
                self._alert(
                    "warning" if detail["cancelled_tp"] > 0 or detail["cancelled_stops"] > 0 else "info",
                    "MANUAL_FLAT_TP_PURGE",
                    "平仓后撤销残留挂单",
                    f"实盘已平 {prev_s} {prev_q}，已撤 {cancel_desc}",
                    detail,
                )
        return detail

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
        detail = self._purge_defense_orders_on_flat("idle_patrol", notify=False)
        detail["orphan_orders"] = len(orders)
        if hasattr(self, "_log"):
            self._log("IDLE_WATCH", f"空仓巡检：清理 {len(orders)} 个孤儿挂单", detail)
        if hasattr(self, "_alert"):
            self._alert(
                "info",
                "IDLE_WATCH",
                "空仓巡检 · 清理孤儿挂单",
                f"实盘空仓但仍有 {len(orders)} 个挂单，已撤 TP×{detail.get('cancelled_tp', 0)}",
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
            trade = recovery_section(ctx, "trade")
            factory_open = bool(trade and trade.get("id"))
            entry_tv = recovery_section(ctx, "latest_entry_tv")
            if entry_tv:
                reconcile["latest_entry_tv_action"] = entry_tv.get("action")
            # Hard exits always flatten (ETH/XAU · all exchanges), even if adopted_manual
            hard_exit = is_hard_tv_close_action(tv_action)
            same_side = (trade.get("side") or "").upper() == (side or "").upper() if trade else False
            if hard_exit or (factory_open and same_side):
                self._close_all(
                    f"空仓巡检: TV已发{tv_action}，"
                    + ("硬平仓清场" if hard_exit else "工厂持仓清场"),
                    close_trigger="idle_patrol_tv_close",
                    close_action=tv_action if hard_exit else None,
                )
                return
            if side in ("LONG", "SHORT"):
                if hasattr(self, "_log"):
                    self._log(
                        "IDLE_WATCH",
                        f"TV已发{tv_action}，实盘{side}同向 → 接管补挂 TP123/雷达（人工不强平）",
                        {"trigger": "idle_patrol", "latest_tv": tv_action, "side": side},
                    )
            else:
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
        if hasattr(self, "_radar_activation_reached") and not self._radar_activation_reached(curr_px):
            audit["deferred"] = "await_tp1_or_activation_ratio"
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

    def _ensure_tv_shield_on_startup(self, live_qty: float, shield_audit: dict) -> dict:
        """TV 硬止损：重启/人工接管时不论盈亏轨，缺失则补挂."""
        tv_sl = float(getattr(self, "tv_sl", 0) or 0)
        if tv_sl <= 0 or live_qty <= 0:
            return shield_audit
        if shield_audit.get("aligned"):
            return shield_audit

        if hasattr(self, "_uses_dual_stop_track") and self._uses_dual_stop_track():
            if not shield_audit.get("aligned"):
                arm = self._arm_adverse_shield_at_open(live_qty)
                return {**shield_audit, **(arm or {})}
            return shield_audit

        if hasattr(self, "_sync_binance_merged_stop"):
            merged = self._sync_binance_merged_stop(live_qty)
            shield_audit = {**shield_audit, **merged}

        post = self._sync_adverse_shield_with_retry(live_qty)
        shield_audit = {**shield_audit, **post}
        if not post.get("aligned") and self._can_repair_adverse_stops():
            repair = self._arm_adverse_shield_at_open(live_qty)
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
        return shield_audit

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

        if live_qty > 0 and entry > 0 and side in ("LONG", "SHORT"):
            sl_meta = recompute_vps_hard_sl_on_recovery(
                self, entry_px=entry, side=side,
            )
            if sl_meta.get("sl_changed"):
                logger.info(
                    "[User %s] 重启重算 VPS 硬止损: %.2f → %.2f (%s R%s)",
                    getattr(self, "user_id", "?"),
                    sl_meta.get("prev_sl", 0),
                    sl_meta.get("stop_price", 0),
                    side,
                    sl_meta.get("regime", "?"),
                )

        if hasattr(self, "_refresh_radar_state_on_recover") and curr_px > 0:
            self._refresh_radar_state_on_recover(curr_px, entry)

        progress = self._startup_radar_progress(curr_px)
        consumed = list(getattr(self, "consumed_tp_levels", []) or [])
        radar_active = bool(
            getattr(self, "radar_latched", False)
            or (hasattr(self, "_is_radar_active") and self._is_radar_active())
        )
        pnl_track = classify_startup_pnl_track(
            entry, curr_px, side,
            radar_progress=progress,
            radar_active=radar_active,
            consumed_tp_levels=consumed,
        )
        radar_permitted = (
            self._radar_activation_reached(curr_px)
            if hasattr(self, "_radar_activation_reached")
            else False
        )
        adopted_manual = bool(getattr(self, "adopted_manual", False))
        if adopted_manual and not radar_permitted:
            pnl_track = "loss_shield"
            radar_handoff = False
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
            if radar_active or consumed:
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
        elif live_qty > 0 and float(getattr(self, "tv_sl", 0) or 0) > 0:
            shield_audit = self._ensure_tv_shield_on_startup(live_qty, shield_audit)

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
            "radar_permitted": radar_permitted,
            "adopted_manual": adopted_manual,
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
