import json
import logging
import threading

from flask import Flask, request, jsonify

from app.config import get_settings
from app.services.webhook_guard import check_webhook_access, validate_signal_payload, _client_ip

logger = logging.getLogger(__name__)
settings = get_settings()

webhook_app = Flask(__name__)


def _persist_webhook_log(**kwargs) -> int | None:
    from app.database import SessionLocal
    from app.services.webhook_receive_log import create_webhook_log

    db = SessionLocal()
    try:
        row = create_webhook_log(db, client_ip=_client_ip(), **kwargs)
        return row.id
    except Exception as e:
        logger.warning("[Webhook] failed to persist receive log: %s", e)
        return None
    finally:
        db.close()


def _update_webhook_log(log_id: int | None, **kwargs) -> None:
    if not log_id:
        return
    from app.database import SessionLocal
    from app.services.webhook_receive_log import update_webhook_log

    db = SessionLocal()
    try:
        update_webhook_log(db, log_id, **kwargs)
    except Exception as e:
        logger.warning("[Webhook] failed to update receive log %s: %s", log_id, e)
    finally:
        db.close()


def _run_dispatch_async(data: dict, fingerprint: str, webhook_log_id: int | None) -> None:
    from app.database import SessionLocal
    from app.services.signal_admin import record_webhook_hit, run_signal_dispatch
    from app.services.webhook_idempotency import finalize
    from app.services.webhook_receive_log import WebhookLogTimer

    timer = WebhookLogTimer()
    action = str(data.get("action", "UNKNOWN")).upper()
    record_webhook_hit(action)
    _update_webhook_log(webhook_log_id, event_status="processing", response_status="processing")

    db = SessionLocal()
    try:
        row, _result = run_signal_dispatch(db, data, source="webhook")
        finalize(db, fingerprint, row.id)
        _update_webhook_log(
            webhook_log_id,
            event_status="dispatched",
            response_status="success",
            dispatch_log_id=row.id,
            latency_ms=timer.elapsed_ms(),
        )
    except Exception as e:
        logger.exception("Webhook dispatch persistence failed: %s", e)
        _update_webhook_log(
            webhook_log_id,
            event_status="failed",
            response_status="error",
            error_message=str(e),
            latency_ms=timer.elapsed_ms(),
        )
    finally:
        db.close()


@webhook_app.route("/webhook", methods=["POST"])
def webhook():
    ok, msg, status = check_webhook_access()
    if not ok:
        _persist_webhook_log(
            payload={},
            event_status="rejected",
            http_status=status,
            error_message=msg,
            response_status="error",
        )
        return jsonify({"status": "error", "message": msg}), status

    raw_text = request.get_data(as_text=True) or ""
    try:
        data = request.get_json(silent=True) or json.loads(raw_text or "{}")
    except Exception:
        _persist_webhook_log(
            payload={"raw": raw_text[:2000]},
            event_status="rejected",
            http_status=400,
            error_message="Invalid JSON",
            response_status="error",
        )
        return jsonify({"status": "error", "message": "Invalid JSON"}), 400

    if not data:
        _persist_webhook_log(
            payload={},
            event_status="rejected",
            http_status=400,
            error_message="Empty payload",
            response_status="error",
        )
        return jsonify({"status": "error", "message": "Empty payload"}), 400

    secret = str(data.get("secret", "")).strip()
    if secret != settings.WEBHOOK_SECRET:
        _persist_webhook_log(
            payload=data,
            event_status="rejected",
            http_status=403,
            error_message="Invalid secret",
            response_status="error",
        )
        return jsonify({"status": "error", "message": "Invalid secret"}), 403

    valid, err = validate_signal_payload(data)
    if not valid:
        _persist_webhook_log(
            payload=data,
            event_status="rejected",
            http_status=400,
            error_message=err,
            response_status="error",
        )
        return jsonify({"status": "error", "message": err}), 400

    from app.services.trading_control import is_globally_paused
    if is_globally_paused():
        _persist_webhook_log(
            payload=data,
            event_status="rejected",
            http_status=503,
            error_message="Platform trading globally paused",
            response_status="error",
        )
        return jsonify({"status": "error", "message": "Platform trading globally paused"}), 503

    from app.database import SessionLocal
    from app.services.webhook_idempotency import compute_fingerprint, try_acquire

    fingerprint = compute_fingerprint(data)
    db = SessionLocal()
    try:
        acquired, existing_dispatch_id = try_acquire(db, fingerprint)
    finally:
        db.close()

    if not acquired:
        logger.info("[Webhook] Duplicate signal fingerprint=%s dispatch_id=%s", fingerprint[:16], existing_dispatch_id)
        _persist_webhook_log(
            payload=data,
            fingerprint=fingerprint,
            event_status="duplicate",
            http_status=200,
            dispatch_log_id=existing_dispatch_id,
            response_status="duplicate",
            error_message="Signal already processed (idempotent)",
        )
        return jsonify({
            "status": "duplicate",
            "message": "Signal already processed (idempotent)",
            "dispatch_id": existing_dispatch_id,
            "action": str(data.get("action", "")).upper(),
        }), 200

    action = str(data.get("action", "UNKNOWN")).upper()
    reason = data.get("reason", "")
    if "CLOSE_PROTECT" in action:
        logger.info("[Webhook] CLOSE_PROTECT | reason=%s regime=%s", reason, data.get("regime"))
    else:
        logger.info("[Webhook] action=%s regime=%s atr=%s", action, data.get("regime"), data.get("atr"))

    webhook_log_id = _persist_webhook_log(
        payload=data,
        fingerprint=fingerprint,
        event_status="accepted",
        http_status=200,
        response_status="success",
    )

    threading.Thread(
        target=_run_dispatch_async,
        args=(data, fingerprint, webhook_log_id),
        daemon=True,
        name=f"webhook-dispatch-{action}",
    ).start()

    return jsonify({
        "status": "success",
        "message": "Signal received, dispatching to all users",
        "action": action,
        "webhook_log_id": webhook_log_id,
    }), 200


@webhook_app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200
