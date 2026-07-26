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

API_BUDGET_PER_MIN = 40
TP_PLACEABLE_SUM_TOL = 0.04


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
    def self_check_tp_slices(initial_qty: float, slices: list) -> tuple[bool, str]:
        iq = float(initial_qty or 0)
        if iq <= 0:
            return False, "zero_initial"
        used = sum(float(q) for lv, q, _ in slices if int(lv) in (1, 2))
        ratio = used / iq
        if abs(ratio - 0.30) > TP_PLACEABLE_SUM_TOL:
            return False, f"tp_sum_ratio={ratio:.4f} want≈0.30 (used={used} iq={iq})"
        if used + 1e-12 >= 0.95 * iq:
            return False, f"tp_eats_radar used={used} iq={iq}"
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
        if iq > 0 and tp_sum > 0:
            ratio = tp_sum / iq
            findings.append(AuditorFinding(
                abs(ratio - 0.30) <= TP_PLACEABLE_SUM_TOL and ratio < 0.95,
                "tp_slices_30pct",
                f"sum={tp_sum} iq={iq} ratio={ratio:.4f}",
            ))
        else:
            try:
                if hasattr(host, "_compute_tp_slices") and iq > 0:
                    slices = host._compute_tp_slices(iq, exclude_levels={3})
                    ok, detail = ExecutionOfficer.self_check_tp_slices(iq, slices)
                    findings.append(AuditorFinding(ok, "tp_slices_30pct", detail))
                else:
                    findings.append(AuditorFinding(True, "tp_slices_30pct", "deferred"))
            except Exception as e:
                findings.append(AuditorFinding(False, "tp_slices_30pct", str(e)[:120]))

        hard_px = float(s.hard_sl_price or 0)
        hung = bool(s.hard_sl_hung or s.hard_sl_order_id)
        if hard_px <= 0 and hasattr(host, "_frozen_hard_px"):
            try:
                hard_px = float(host._frozen_hard_px() or 0)
            except Exception:
                hard_px = 0.0
        findings.append(AuditorFinding(hard_px > 0 or hung, "hard_stop", f"px={hard_px} hung={hung}"))

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


class CommunicationsOfficer:
    GATED_TYPES = frozenset({"OPEN", "DEFENSE", "ENTRY", "PIPELINE_REPORT"})

    @staticmethod
    def allow_notify(host: Any, alert_type: str, severity: str) -> bool:
        at = str(alert_type or "").upper()
        sev = str(severity or "").lower()
        if sev in ("critical", "error"):
            return True
        if at not in CommunicationsOfficer.GATED_TYPES:
            return True
        led = ledger_for(host)
        ph = led.phase()
        if ph in (TradePhase.VERIFIED, TradePhase.REPORTED):
            return True
        if ph == TradePhase.ORDERS_PLACED and led.snap.last_audit_ok is True:
            return True
        led.note_event("NOTIFY_HELD", {"type": at, "phase": ph.value})
        return False

    @staticmethod
    def mark_reported(host: Any) -> None:
        led = ledger_for(host)
        if led.phase() == TradePhase.VERIFIED:
            led.advance(TradePhase.REPORTED, reason="comms")


def run_post_open_pipeline(host: Any, slices=None) -> bool:
    ExecutionOfficer.mark_orders_placed(host, slices)
    ok, _ = ChiefAuditor.run(host)
    if ok:
        CommunicationsOfficer.mark_reported(host)
    return ok
