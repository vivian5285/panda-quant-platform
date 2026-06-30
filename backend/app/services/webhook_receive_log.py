"""Persist TradingView webhook HTTP events for admin audit."""

from __future__ import annotations

import json
import time
from typing import Any

from sqlalchemy.orm import Session

from app.models.platform import WebhookReceiveLog, SignalDispatchLog
from app.services.dispatch_persistence import list_dispatch_user_results

TV_SUMMARY_KEYS = (
    "action", "regime", "atr", "price", "tv_tp1", "tv_tp2", "tv_tp3",
    "reason", "strategy_id", "symbol", "interval", "close", "open", "volume",
)


def sanitize_payload(data: dict | None) -> dict:
    if not data:
        return {}
    out = dict(data)
    if "secret" in out:
        out["secret"] = "***"
    return out


def extract_tv_summary(data: dict | None) -> dict:
    if not data:
        return {}
    summary: dict[str, Any] = {}
    for key in TV_SUMMARY_KEYS:
        if key in data and data[key] is not None:
            summary[key] = data[key]
    return summary


def create_webhook_log(
    db: Session,
    *,
    client_ip: str,
    payload: dict | None = None,
    fingerprint: str | None = None,
    event_status: str = "received",
    http_status: int = 200,
    error_message: str | None = None,
    response_status: str | None = None,
    dispatch_log_id: int | None = None,
    latency_ms: int | None = None,
) -> WebhookReceiveLog:
    safe = sanitize_payload(payload or {})
    action = str(safe.get("action", "") or "").upper() or None
    row = WebhookReceiveLog(
        event_status=event_status,
        http_status=http_status,
        client_ip=(client_ip or "")[:64],
        fingerprint=fingerprint,
        action=action,
        tv_summary_json=json.dumps(extract_tv_summary(payload or {}), ensure_ascii=False),
        payload_json=json.dumps(safe, ensure_ascii=False),
        dispatch_log_id=dispatch_log_id,
        error_message=(error_message or "")[:500] if error_message else None,
        response_status=response_status,
        latency_ms=latency_ms,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_webhook_log(
    db: Session,
    log_id: int,
    *,
    event_status: str | None = None,
    http_status: int | None = None,
    error_message: str | None = None,
    response_status: str | None = None,
    dispatch_log_id: int | None = None,
    latency_ms: int | None = None,
) -> WebhookReceiveLog | None:
    row = db.query(WebhookReceiveLog).filter(WebhookReceiveLog.id == log_id).first()
    if not row:
        return None
    if event_status is not None:
        row.event_status = event_status
    if http_status is not None:
        row.http_status = http_status
    if error_message is not None:
        row.error_message = error_message[:500]
    if response_status is not None:
        row.response_status = response_status
    if dispatch_log_id is not None:
        row.dispatch_log_id = dispatch_log_id
    if latency_ms is not None:
        row.latency_ms = latency_ms
    db.commit()
    db.refresh(row)
    return row


def webhook_log_to_dict(row: WebhookReceiveLog, *, include_payload: bool = True) -> dict:
    try:
        tv_summary = json.loads(row.tv_summary_json or "{}")
    except json.JSONDecodeError:
        tv_summary = {}
    try:
        payload = json.loads(row.payload_json or "{}") if include_payload else {}
    except json.JSONDecodeError:
        payload = {}

    dispatch = None
    if row.dispatch_log:
        d = row.dispatch_log
        dispatch = {
            "id": d.id,
            "status": d.status,
            "source": d.source,
            "dispatched_count": d.dispatched_count,
            "error_count": d.error_count,
            "skipped_count": getattr(d, "skipped_count", 0) or 0,
        }

    return {
        "id": row.id,
        "event_status": row.event_status,
        "http_status": row.http_status,
        "client_ip": row.client_ip,
        "fingerprint": row.fingerprint,
        "action": row.action,
        "tv_summary": tv_summary,
        "payload": payload if include_payload else None,
        "dispatch_log_id": row.dispatch_log_id,
        "dispatch": dispatch,
        "error_message": row.error_message,
        "response_status": row.response_status,
        "latency_ms": row.latency_ms,
        "created_at": row.created_at,
    }


def get_webhook_log_detail(db: Session, log_id: int) -> dict | None:
    row = (
        db.query(WebhookReceiveLog)
        .filter(WebhookReceiveLog.id == log_id)
        .first()
    )
    if not row:
        return None
    out = webhook_log_to_dict(row, include_payload=True)
    if row.dispatch_log_id:
        out["user_results"] = list_dispatch_user_results(db, row.dispatch_log_id)
        disp = db.query(SignalDispatchLog).filter(SignalDispatchLog.id == row.dispatch_log_id).first()
        if disp:
            try:
                out["dispatch_payload"] = json.loads(disp.payload_json or "{}")
            except json.JSONDecodeError:
                out["dispatch_payload"] = {}
    else:
        out["user_results"] = []
        out["dispatch_payload"] = None
    return out


class WebhookLogTimer:
    def __init__(self) -> None:
        self._start = time.perf_counter()

    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self._start) * 1000)
