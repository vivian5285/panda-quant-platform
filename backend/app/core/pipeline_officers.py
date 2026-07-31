"""Pipeline officers — role boundaries over the shared TradeLedger."""

from __future__ import annotations

import logging
import time
from typing import Any

from app.core.trade_ledger import (
    AuditorFinding,
    TradeLedger,
    TradePhase,
    ledger_for,
)

logger = logging.getLogger(__name__)

API_BUDGET_PER_MIN = 300  # increased from 40 to allow more REST calls per minute
TP_PLACEABLE_SUM_TOL = 0.04
HARD_STOP_PX_TOL_FRAC = 0.05  # 5% of expected distance
HARD_STOP_PX_TOL_ABS_FRAC = 0.002  # or 0.2% of entry

# Flat 后自动清 pause（今日卡死事故）— 审计/硬帽/脏盘/ATR 应急/方向类
FLAT_AUTO_CLEAR_REASONS = frozenset({
    "chief_auditor_fail",
    "open_orders_gt_5",
    "open_book_dirty",
})


def should_auto_unpause_on_flat(reason: str) -> bool:
    r = str(reason or "").strip()
    if not r:
        return False
    if r in FLAT_AUTO_CLEAR_REASONS:
        return True
    if "ATR应急" in r or "atr_emergency" in r.lower():
        return True
    if "方向" in r or "direction" in r.lower():
        return True
    if r.startswith("先平后开失败"):
        return True
    return False


def should_retry_open_despite_pause(reason: str) -> bool:
    """Next TV OPEN may retry force-flat even if still holding / book was dirty.

    Sticky ``先平后开失败·…`` while still in a position used to skip OPEN forever
    (reclaim requires flat). The OPEN path itself re-runs force_flat — allow it.
    """
    r = str(reason or "").strip()
    if not r:
        return False
    if r.startswith("先平后开失败"):
        return True
    if r in ("open_book_dirty", "flat_timeout"):
        return True
    if r.startswith("open_orders_gt_"):
        # Hard-cap pause: allow OPEN to mop+retry once flat path runs
        return True
    return False


class SignalOfficer:
    @staticmethod
    def receive(host: Any, payload: dict) -> TradeLedger:
        led = ledger_for(host)
        action = str(payload.get("action") or "").upper().strip()
        led.snap.signal_action = action
        led.snap.tier = str(payload.get("tier") or payload.get("regime") or "")
        if led.phase() in (TradePhase.IDLE, TradePhase.FLAT, TradePhase.FAILED, TradePhase.REPORTED):
            led.advance(TradePhase.SIGNAL_RECEIVED, reason=f"signal:{action}", force=True)
        else:
            led.note_event("SIGNAL_WHILE_BUSY", {"phase": led.phase().value, "action": action})
        led.persist()
        return led


class AdmissionOfficer:
    @staticmethod
    def admit(user: Any) -> tuple[bool, str]:
        if not user:
            return False, "no_user"
        if str(getattr(user, "api_status", "") or "").lower() != "active":
            return False, "api_inactive"
        if not getattr(user, "api_key_enc", None):
            return False, "api_unbound"
        return True, "ok"


class PositionAuditor:
    @staticmethod
    def request_clear(host: Any) -> TradeLedger:
        led = ledger_for(host)
        if led.phase() == TradePhase.SIGNAL_RECEIVED:
            led.advance(TradePhase.PENDING_CLEAR, reason="auditor")
        return led

    @staticmethod
    def needs_exchange_verify(host: Any) -> bool:
        led = ledger_for(host)
        if led.snap.book_suspect or led.snap.last_audit_ok is False:
            return True
        qty = float(getattr(host, "watched_qty", 0) or 0)
        mon = bool(getattr(host, "monitoring", False))
        return qty > 0 or mon

    @staticmethod
    def mark_cleared(host: Any, *, reason: str = "cleared") -> None:
        led = ledger_for(host)
        if led.phase() in (TradePhase.PENDING_CLEAR, TradePhase.SIGNAL_RECEIVED):
            led.advance(TradePhase.CLEARED, reason=reason, force=True)
        led.snap.book_suspect = False
        led.persist()


class ExecutionOfficer:
    @staticmethod
    def mark_entry_submitted(host: Any) -> None:
        led = ledger_for(host)
        if led.phase() in (TradePhase.CLEARED, TradePhase.PENDING_CLEAR, TradePhase.SIGNAL_RECEIVED):
            led.advance(TradePhase.ENTRY_SUBMITTED, reason="order_sent", force=True)

    @staticmethod
    def mark_entry_confirmed(host: Any, *, qty: float, entry: float, side: str) -> None:
        led = ledger_for(host)
        led.snap.qty = float(qty)
        if float(led.snap.initial_qty or 0) <= 0:
            led.snap.initial_qty = float(qty)
        led.snap.entry_price = float(entry)
        led.snap.side = str(side or "").upper()
        led.snap.opened_at = led.snap.opened_at or time.time()
        led.advance(TradePhase.ENTRY_CONFIRMED, reason="fill", force=True)
        led.persist()

    @staticmethod
    def self_check_tp_slices(
        initial_qty: float,
        slices: list,
        *,
        relax_for_min_lot: bool = False,
    ) -> tuple[bool, str]:
        iq = float(initial_qty or 0)
        if iq <= 0:
            return False, "zero_initial"
        used = sum(float(q) for lv, q, _ in slices if int(lv) in (1, 2))
        ratio = used / iq
        if used + 1e-12 >= 0.95 * iq:
            return False, f"tp_eats_radar used={used} iq={iq}"
        if abs(ratio - 0.30) > TP_PLACEABLE_SUM_TOL:
            # DeepCoin/contract min lot (1 张) + small XAU/ETH min_notional folds:
            # integer/step rounding can leave TP1+TP2 off ~30%; still OK if radar
            # residual remains (placeable ≤ ~35%).
            if relax_for_min_lot and used > 0 and ratio <= 0.35 + TP_PLACEABLE_SUM_TOL:
                return True, f"ok_relaxed_min_lot ratio={ratio:.4f}"
            return False, f"tp_sum_ratio={ratio:.4f} want≈0.30 (used={used} iq={iq})"
        return True, "ok"

    @staticmethod
    def mark_orders_placed(host: Any, slices=None) -> None:
        led = ledger_for(host)
        if slices:
            led.set_tp_slices(slices)
        led.sync_from_supervisor(host)
        led.advance(TradePhase.ORDERS_PLACED, reason="defenses_hung", force=True)


class ChiefAuditor:
    @staticmethod
    def _count_live_tp_limits(host: Any) -> int:
        """How many reduce-only TP limits are on the exchange book right now."""
        try:
            if hasattr(host, "_collect_tp_limit_orders"):
                return len(list(host._collect_tp_limit_orders() or []))
            if hasattr(host, "_open_tp_prices_on_book"):
                return len([p for p in (host._open_tp_prices_on_book() or []) if float(p or 0) > 0])
            client = getattr(host, "client", None)
            sym = getattr(host, "symbol", None)
            if client and sym and hasattr(client, "get_open_orders"):
                n = 0
                for o in client.get_open_orders(sym) or []:
                    if str(o.get("type") or "").upper() == "LIMIT":
                        n += 1
                return n
        except Exception:
            return -1
        return 0

    @staticmethod
    def _check_hard_stop(host: Any, s) -> AuditorFinding:
        hard_px = float(s.hard_sl_price or 0)
        hung = bool(s.hard_sl_hung or s.hard_sl_order_id)
        if hard_px <= 0 and hasattr(host, "_frozen_hard_px"):
            try:
                hard_px = float(host._frozen_hard_px() or 0)
            except Exception:
                hard_px = 0.0
        if hard_px <= 0 and not hung:
            return AuditorFinding(False, "hard_stop", "missing")

        entry = float(s.entry_price or getattr(host, "watched_entry", 0) or 0)
        tv_sl = float(
            getattr(host, "tv_sl", 0)
            or getattr(host, "_tv_stop_loss_ref", 0)
            or getattr(host, "tv_hard_sl_price", 0)
            or 0
        )
        tv_e = float(getattr(host, "tv_price", 0) or entry or 0)
        side = str(s.side or getattr(host, "current_side", "") or "").upper()
        can = str(getattr(host, "canonical_symbol", None) or getattr(host, "symbol", "") or "")

        if hard_px > 0 and entry > 0 and tv_sl > 0 and side in ("LONG", "SHORT"):
            try:
                from app.core.breathing_stop import compute_hard_stop_distance

                meta = compute_hard_stop_distance(
                    fill_entry=entry,
                    tv_stop_loss=tv_sl,
                    tv_entry=tv_e,
                    symbol=can or None,
                )
                want_dist = float(meta.get("final_dist") or 0)
                if want_dist > 0:
                    expect = entry - want_dist if side == "LONG" else entry + want_dist
                    tol = max(entry * HARD_STOP_PX_TOL_ABS_FRAC, want_dist * HARD_STOP_PX_TOL_FRAC)
                    ok = abs(hard_px - expect) <= tol
                    return AuditorFinding(
                        ok or hung,
                        "hard_stop",
                        f"px={hard_px} expect≈{expect:.4f} tol={tol:.4f} hung={hung}",
                    )
            except Exception as e:
                return AuditorFinding(
                    hard_px > 0 or hung,
                    "hard_stop",
                    f"px={hard_px} hung={hung} formula_err={str(e)[:60]}",
                )
        return AuditorFinding(hard_px > 0 or hung, "hard_stop", f"px={hard_px} hung={hung}")

    @staticmethod
    def run(host: Any, *, api_budget: int = API_BUDGET_PER_MIN):
        led = ledger_for(host)
        led.sync_from_supervisor(host)
        s = led.snap
        findings: list[AuditorFinding] = []

        sig = str(s.signal_action or "").upper()
        side = str(s.side or getattr(host, "current_side", "") or "").upper()
        if sig in ("LONG", "SHORT") and side in ("LONG", "SHORT"):
            findings.append(AuditorFinding(sig == side, "tv_direction", f"signal={sig} side={side}"))
        else:
            findings.append(AuditorFinding(bool(side), "tv_direction", f"signal={sig} side={side}"))

        meta = getattr(host, "_last_open_sizing_meta", None) or {}
        if meta.get("margin_pct_frac") is not None:
            want = float(s.margin_pct_frac or 0.2)
            got = float(meta.get("margin_pct_frac") or want)
            findings.append(AuditorFinding(abs(got - want) <= 0.02, "margin_weight", f"want={want} got={got}"))
        else:
            findings.append(AuditorFinding(True, "margin_weight", "no_meta_skip"))

        lev = int(s.leverage or getattr(host, "leverage", 5) or 5)
        findings.append(AuditorFinding(1 <= lev <= 125, "leverage", f"lev={lev}"))

        can = str(getattr(host, "canonical_symbol", None) or getattr(host, "symbol", "") or "")
        findings.append(AuditorFinding(bool(can), "symbol", f"ledger={s.symbol} host={can}"))

        iq = float(s.initial_qty or getattr(host, "initial_qty", 0) or 0)
        tp_sum = float(s.tp1_qty or 0) + float(s.tp2_qty or 0)
        relax = str(getattr(host, "exchange_id", "") or "").lower() == "deepcoin"
        if iq > 0 and tp_sum > 0:
            ratio = tp_sum / iq
            ok_ratio = ratio < 0.95 and (
                abs(ratio - 0.30) <= TP_PLACEABLE_SUM_TOL or relax
            )
            findings.append(AuditorFinding(
                ok_ratio,
                "tp_slices_30pct",
                f"sum={tp_sum} iq={iq} ratio={ratio:.4f}",
            ))
        else:
            # Ledger empty: plan slices, then require them on the live book.
            # Small XAU used to plan [] → pause with naked position; after top-up,
            # plan may be OK while place still failed — remount once before fail.
            try:
                slices = []
                detail = "deferred"
                ok = True
                if hasattr(host, "_compute_tp_slices") and iq > 0:
                    slices = host._compute_tp_slices(iq, exclude_levels={3}) or []
                    ok, detail = ExecutionOfficer.self_check_tp_slices(
                        iq, slices, relax_for_min_lot=True,
                    )
                live_q = float(getattr(host, "watched_qty", 0) or s.qty or 0)
                book_n = -1
                if ok and slices and live_q > 0:
                    book_n = ChiefAuditor._count_live_tp_limits(host)
                    if book_n == 0 and hasattr(host, "_rebuild_tp_limit_orders"):
                        try:
                            entry = float(
                                getattr(host, "watched_entry", 0)
                                or getattr(host, "entry_price", 0)
                                or s.entry_price
                                or 0
                            )
                            host._rebuild_tp_limit_orders(live_q, entry, dynamic_sl=None)
                        except Exception as e:
                            detail = f"{detail}; remount_err={str(e)[:80]}"
                        book_n = ChiefAuditor._count_live_tp_limits(host)
                    if book_n == 0:
                        ok = False
                        detail = f"tp_book_empty after_plan ({detail})"
                    elif book_n > 0:
                        detail = f"{detail}; book_limits={book_n}"
                findings.append(AuditorFinding(ok, "tp_slices_30pct", detail))
            except Exception as e:
                findings.append(AuditorFinding(False, "tp_slices_30pct", str(e)[:120]))

        findings.append(ChiefAuditor._check_hard_stop(host, s))

        # Radar: ledger qty vs host watched (shadow drift)
        wq = float(getattr(host, "watched_qty", 0) or 0)
        if wq > 0:
            findings.append(AuditorFinding(
                abs(float(s.qty or 0) - wq) / max(wq, 1e-12) <= 0.15 or float(s.qty or 0) <= 0,
                "radar_qty_sync",
                f"ledger_qty={s.qty} watched={wq}",
            ))
        else:
            findings.append(AuditorFinding(True, "radar_state", f"activated={bool(s.radar_activated)}"))

        n = led.api_calls_last_min()
        findings.append(AuditorFinding(n <= api_budget, "api_frequency", f"calls_1m={n} budget={api_budget}"))

        ok = led.mark_audit(findings)
        if ok:
            led.advance(TradePhase.VERIFIED, reason="chief_auditor", force=True)
        else:
            led.snap.book_suspect = True
            led.advance(TradePhase.FAILED, reason="audit_fail", force=True)
            if hasattr(host, "_pause_trading"):
                try:
                    host._pause_trading("chief_auditor_fail", {"failures": list(led.snap.last_audit_failures)})
                except Exception:
                    pass
            if hasattr(host, "_alert"):
                try:
                    host._alert(
                        "critical",
                        "CHIEF_AUDITOR_FAIL",
                        "督察官复查未通过·已暂停新开仓",
                        "; ".join(led.snap.last_audit_failures)[:400],
                        {"failures": list(led.snap.last_audit_failures)},
                    )
                except Exception:
                    pass
        return ok, findings

    @staticmethod
    def recheck_live(host: Any, *, reason: str = "hold") -> bool:
        """Mid-trade re-audit (TP fill / radar / stall). Throttled; fail → pause."""
        now = time.time()
        last = float(getattr(host, "_chief_recheck_at", 0) or 0)
        if now - last < 25.0 and reason not in ("tp_fill", "flat", "stall"):
            return True
        host._chief_recheck_at = now
        led = ledger_for(host)
        led.sync_from_supervisor(host)
        s = led.snap
        findings = [
            ChiefAuditor._check_hard_stop(host, s),
        ]
        wq = float(getattr(host, "watched_qty", 0) or 0)
        iq = float(s.initial_qty or getattr(host, "initial_qty", 0) or 0)
        if iq > 0 and wq > 0 and wq > iq * 1.05:
            findings.append(AuditorFinding(False, "qty_inflate", f"watched={wq} initial={iq}"))
        if iq > 0 and float(getattr(host, "initial_qty", 0) or 0) + 1e-12 < iq * 0.95:
            findings.append(AuditorFinding(
                False, "initial_qty_compressed",
                f"host_iq={getattr(host, 'initial_qty', 0)} ledger_iq={iq}",
            ))
        # Placeable residual: after both TP filled, live should be ~70%
        consumed = {int(x) for x in (getattr(host, "consumed_tp_levels", None) or [])}
        if 1 in consumed and 2 in consumed and iq > 0 and wq > 0:
            ratio = wq / iq
            findings.append(AuditorFinding(
                0.55 <= ratio <= 0.85,
                "radar_residual_70pct",
                f"live/iq={ratio:.3f} want≈0.70",
            ))
        ok = all(f.ok for f in findings)
        led.mark_audit(findings)
        if not ok:
            led.snap.book_suspect = True
            led.persist()
            if hasattr(host, "_pause_trading"):
                try:
                    host._pause_trading(
                        "chief_auditor_fail",
                        {"reason": reason, "failures": [f"{f.item}:{f.detail}" for f in findings if not f.ok]},
                    )
                except Exception:
                    pass
            if hasattr(host, "_alert"):
                try:
                    host._alert(
                        "critical",
                        "CHIEF_AUDITOR_FAIL",
                        f"持仓中督察失败·{reason}",
                        "; ".join(f"{f.item}:{f.detail}" for f in findings if not f.ok)[:400],
                        {"reason": reason},
                    )
                except Exception:
                    pass
        else:
            led.note_event("LIVE_AUDIT_OK", {"reason": reason})
            led.persist()
        return ok


class CommunicationsOfficer:
    GATED_TYPES = frozenset({
        "OPEN", "DEFENSE", "ENTRY", "PIPELINE_REPORT",
        "TP_FILLED", "TRAIL", "BREATH_TRAIL",
    })
    HOLD_PHASES = frozenset({
        TradePhase.ORDERS_PLACED,
        TradePhase.VERIFIED,
        TradePhase.REPORTED,
    })
    TRAIL_TYPES = frozenset({"TRAIL", "BREATH_TRAIL"})
    TRAIL_MIN_INTERVAL_SEC = 90.0

    @staticmethod
    def allow_notify(host: Any, alert_type: str, severity: str, *, stash: dict | None = None) -> bool:
        at = str(alert_type or "").upper()
        sev = str(severity or "").lower()
        if sev in ("critical", "error"):
            return True
        if at not in CommunicationsOfficer.GATED_TYPES:
            return True
        led = ledger_for(host)
        ph = led.phase()

        # OPEN/DEFENSE/ENTRY — only after chief verify (or held until flush)
        if at in ("OPEN", "DEFENSE", "ENTRY", "PIPELINE_REPORT"):
            if ph in (TradePhase.VERIFIED, TradePhase.REPORTED):
                return True
            if ph == TradePhase.ORDERS_PLACED and led.snap.last_audit_ok is True:
                return True
            led.note_event("NOTIFY_HELD", {"type": at, "phase": ph.value})
            if stash is not None:
                held = getattr(host, "_held_pipeline_notifies", None)
                if not isinstance(held, list):
                    held = []
                    host._held_pipeline_notifies = held
                held.append(dict(stash))
                if len(held) > 8:
                    host._held_pipeline_notifies = held[-8:]
            return False

        # TP fill — only while holding (never during pre-open scramble)
        if at == "TP_FILLED":
            if ph in CommunicationsOfficer.HOLD_PHASES or bool(getattr(host, "monitoring", False)):
                return True
            led.note_event("NOTIFY_HELD", {"type": at, "phase": ph.value})
            return False

        # Trail / breath trail — CommunicationsOfficer owns rate limit (anti-spam)
        if at in CommunicationsOfficer.TRAIL_TYPES:
            if ph not in CommunicationsOfficer.HOLD_PHASES and not bool(getattr(host, "monitoring", False)):
                led.note_event("NOTIFY_HELD", {"type": at, "phase": ph.value})
                return False
            now = time.time()
            last = float(getattr(host, "_comms_last_trail_at", 0) or 0)
            if now - last < CommunicationsOfficer.TRAIL_MIN_INTERVAL_SEC:
                led.note_event("NOTIFY_THROTTLED", {"type": at, "since": round(now - last, 1)})
                return False
            host._comms_last_trail_at = now
            return True

        return True

    @staticmethod
    def mark_reported(host: Any) -> None:
        led = ledger_for(host)
        if led.phase() == TradePhase.VERIFIED:
            led.advance(TradePhase.REPORTED, reason="comms")
        CommunicationsOfficer.flush_held(host)

    @staticmethod
    def flush_held(host: Any) -> None:
        held = list(getattr(host, "_held_pipeline_notifies", None) or [])
        if not held:
            return
        host._held_pipeline_notifies = []
        for item in held:
            try:
                if hasattr(host, "_alert"):
                    host._alert(
                        item.get("severity") or "info",
                        item.get("alert_type") or "OPEN",
                        item.get("title") or "GEMINI开仓",
                        item.get("message") or "",
                        item.get("detail"),
                    )
            except Exception as e:
                logger.warning("flush held notify failed: %s", e)


def check_phase_stall(host: Any) -> bool:
    """Return True if stalled and alerted (at most once per phase entry)."""
    led = ledger_for(host)
    if not led.is_stalled():
        return False
    ph = led.phase()
    key = f"_stall_alerted_{ph.value}"
    if getattr(host, key, False):
        return True
    setattr(host, key, True)
    led.note_event("PHASE_STALL", {"phase": ph.value, "sec": round(led.stall_seconds(), 1)})
    led.persist()
    if hasattr(host, "_alert"):
        try:
            host._alert(
                "critical",
                "PIPELINE_STALL",
                f"流水线卡住·{ph.value}",
                f"阶段 {ph.value} 已停留 {led.stall_seconds():.0f}s 超阈",
                {"phase": ph.value, "stall_sec": led.stall_seconds()},
            )
        except Exception:
            pass
    return True


def run_post_open_pipeline(host: Any, slices=None) -> bool:
    ExecutionOfficer.mark_orders_placed(host, slices)
    ok, _ = ChiefAuditor.run(host)
    if ok:
        CommunicationsOfficer.mark_reported(host)
    return ok
