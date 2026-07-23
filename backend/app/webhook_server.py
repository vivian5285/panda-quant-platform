import logging
import queue
import threading
import time

from flask import Flask, request, jsonify

from app.services.webhook_secrets import get_webhook_secret
from app.services.webhook_guard import check_webhook_access, validate_signal_payload, _client_ip
from app.services.webhook_payload import parse_webhook_payload

logger = logging.getLogger(__name__)

webhook_app = Flask(__name__)

# Per-symbol serial dispatch: seq gate always releases CLOSE before OPEN on the
# same bar (even when TV sends OPEN seq=1 and CLOSE seq=2). One worker per
# symbol runs _run_dispatch_async to completion before the next signal.
_symbol_dispatch_queues: dict[str, queue.Queue] = {}
_symbol_dispatch_lock = threading.Lock()


def _symbol_dispatch_worker(symbol: str, q: "queue.Queue") -> None:
    while True:
        item = q.get()
        try:
            if item is None:
                return
            data, fingerprint = item
            action = str(data.get("action", "?")).upper()
            logger.info(
                "[WebhookDispatch] serial start symbol=%s action=%s bar=%s seq=%s qsize=%s",
                symbol, action, data.get("bar_index"), data.get("seq"), q.qsize(),
            )
            _run_dispatch_async(data, fingerprint, None)
            logger.info(
                "[WebhookDispatch] serial done symbol=%s action=%s bar=%s seq=%s",
                symbol, action, data.get("bar_index"), data.get("seq"),
            )
        except Exception:
            logger.exception("[WebhookDispatch] serial worker failed symbol=%s", symbol)
        finally:
            q.task_done()


def _enqueue_symbol_dispatch(data: dict, fingerprint: str) -> None:
    from app.core.symbol_registry import extract_payload_symbol

    symbol = extract_payload_symbol(data, require=False) or "UNKNOWN"
    with _symbol_dispatch_lock:
        q = _symbol_dispatch_queues.get(symbol)
        if q is None:
            q = queue.Queue()
            _symbol_dispatch_queues[symbol] = q
            t = threading.Thread(
                target=_symbol_dispatch_worker,
                args=(symbol, q),
                daemon=True,
                name=f"webhook-serial-{symbol}",
            )
            t.start()
        q.put((data, fingerprint))


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


def _log_reject_async(**kwargs) -> None:
    """Audit rejected webhooks without blocking TV HTTP response."""
    threading.Thread(
        target=_persist_webhook_log,
        kwargs=kwargs,
        daemon=True,
        name="webhook-log-reject",
    ).start()


def _run_dispatch_async(data: dict, fingerprint: str, webhook_log_id: int | None) -> None:
    from app.database import SessionLocal
    from app.services.signal_admin import record_webhook_hit, run_signal_dispatch
    from app.services.webhook_idempotency import finalize
    from app.services.webhook_receive_log import WebhookLogTimer

    if webhook_log_id is None:
        webhook_log_id = _persist_webhook_log(
            payload=data,
            fingerprint=fingerprint,
            event_status="accepted",
            http_status=200,
            response_status="success",
        )

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


def _spawn_dispatch(data: dict, fingerprint: str) -> None:
    """Enqueue ordered per-symbol dispatch (called after seq gate releases)."""
    _enqueue_symbol_dispatch(data, fingerprint)


@webhook_app.route("/webhook", methods=["POST"])
def webhook():
    t0 = time.perf_counter()
    ok, msg, status = check_webhook_access()
    if not ok:
        _log_reject_async(
            payload={},
            event_status="rejected",
            http_status=status,
            error_message=msg,
            response_status="error",
        )
        return jsonify({"status": "error", "message": msg}), status

    raw_text = request.get_data(as_text=True) or ""
    data, parse_err = parse_webhook_payload(raw_text)
    if parse_err:
        _log_reject_async(
            payload={"raw": raw_text[:2000]},
            event_status="rejected",
            http_status=400,
            error_message=parse_err,
            response_status="error",
        )
        logger.warning("[Webhook] JSON parse failed: %s | raw=%s", parse_err, raw_text[:300])
        return jsonify({"status": "error", "message": parse_err}), 400

    if not data:
        _log_reject_async(
            payload={},
            event_status="rejected",
            http_status=400,
            error_message="Empty payload",
            response_status="error",
        )
        return jsonify({"status": "error", "message": "Empty payload"}), 400

    # Canonical auth field is `secret`; legacy `token` still accepted.
    # Deprecation: remove `token` fallback after all TV alerts are confirmed on
    # `secret` for ≥14 consecutive days with zero Invalid-secret rejects from token-only payloads
    # (track via webhook auth logs). Target remove window: post-stabilization cutover.
    secret = str(data.get("secret") or data.get("token") or "").strip()
    if secret != get_webhook_secret():
        _log_reject_async(
            payload=data,
            event_status="rejected",
            http_status=403,
            error_message="Invalid secret",
            response_status="error",
        )
        return jsonify({"status": "error", "message": "Invalid secret"}), 403

    valid, err = validate_signal_payload(data)
    if not valid:
        # Legacy CLOSE_TP/TRAIL/SL_* → soft-ignore (TV should stop sending; VPS monitors fills)
        if str(err).startswith("legacy_ignored:"):
            logger.info("[Webhook] ignore legacy TV reconcile: %s", err)
            return jsonify({
                "status": "ignored",
                "reason": "legacy_tv_reconcile",
                "message": "TP/SL fills are monitored by VPS; TV CLOSE_TP/TRAIL/SL_* ignored",
                "action": str(data.get("action") or "").upper(),
            }), 200
        _log_reject_async(
            payload=data,
            event_status="rejected",
            http_status=400,
            error_message=err,
            response_status="error",
        )
        # ATR rejects are a funds-safety floor — always DingTalk
        err_l = str(err).lower()
        if "atr" in err_l:
            try:
                from app.services.dingtalk_notify import push_system_alert
                from app.core.symbol_registry import extract_payload_symbol, normalize_canonical_symbol
                can = extract_payload_symbol(data, require=False) or normalize_canonical_symbol(
                    data.get("symbol") or data.get("ticker")
                )
                tag = "[XAU]" if can and "XAU" in str(can) else "[ETH]"
                push_system_alert(
                    "critical",
                    "ATR_INVALID",
                    f"{tag} 开仓拒绝·ATR无效",
                    f"{tag} Webhook拒绝开仓: {err} | action={data.get('action')} "
                    f"symbol={data.get('symbol')} atr={data.get('atr')!r} price={data.get('price')}",
                )
            except Exception as exc:
                logger.warning("[Webhook] ATR reject DingTalk failed: %s", exc)
        return jsonify({"status": "error", "message": err}), 400

    from app.services.trading_control import is_globally_paused
    from app.services.webhook_guard import is_close_signal

    action = str(data.get("action", "UNKNOWN")).upper()
    is_close = is_close_signal(action)

    if is_globally_paused() and not is_close:
        _log_reject_async(
            payload=data,
            event_status="rejected",
            http_status=503,
            error_message="Platform trading globally paused",
            response_status="error",
        )
        return jsonify({"status": "error", "message": "Platform trading globally paused"}), 503

    from app.services.webhook_bar_time import check_and_accept_bar_time

    # CLOSE 永不因 bar_time 过期被丢弃（反转保护优先）；仅 OPEN 做乱序丢弃
    if not is_close:
        bt_ok, bt_reason, bt_meta = check_and_accept_bar_time(
            symbol=data.get("symbol") or data.get("ticker"),
            bar_time=data.get("bar_time"),
        )
        if not bt_ok:
            logger.info(
                "[Webhook] stale_bar_time reject symbol=%s bar_time=%s last=%s",
                bt_meta.get("symbol"),
                bt_meta.get("bar_time"),
                bt_meta.get("last_bar_time"),
            )
            _log_reject_async(
                payload=data,
                event_status="rejected",
                http_status=200,
                error_message=f"stale_bar_time:{bt_reason}",
                response_status="ignored",
            )
            return jsonify({
                "status": "ignored",
                "reason": "stale_bar_time",
                "message": "bar_time older than last processed for symbol — no trade",
                "bar_time": bt_meta.get("bar_time"),
                "last_bar_time": bt_meta.get("last_bar_time"),
            }), 200
    else:
        # CLOSE：永不因 bar_time 丢弃；仅向前推进水位
        from app.services.webhook_bar_time import note_bar_time_watermark
        note_bar_time_watermark(
            symbol=data.get("symbol") or data.get("ticker"),
            bar_time=data.get("bar_time"),
        )

    from app.database import SessionLocal
    from app.services.webhook_idempotency import compute_fingerprint, try_acquire
    from app.services.webhook_symbol_coalesce import get_coalesce

    fingerprint = compute_fingerprint(data)
    db = SessionLocal()
    try:
        acquired, existing_dispatch_id = try_acquire(db, fingerprint)
    finally:
        db.close()

    bar_index = data.get("bar_index")
    seq = data.get("seq")
    logger.info(
        "[Webhook] recv action=%s symbol=%s bar_index=%s seq=%s regime=%s atr=%s fp=%s",
        action,
        data.get("symbol") or data.get("ticker"),
        bar_index,
        seq,
        data.get("regime"),
        data.get("atr"),
        fingerprint[:48],
    )

    if not acquired:
        logger.info(
            "[Webhook] Duplicate fingerprint=%s bar_index=%s seq=%s dispatch_id=%s",
            fingerprint[:48], bar_index, seq, existing_dispatch_id,
        )
        _log_reject_async(
            payload=data,
            fingerprint=fingerprint,
            event_status="duplicate",
            http_status=200,
            dispatch_log_id=existing_dispatch_id,
            response_status="duplicate",
            error_message="Signal already processed (idempotent)",
        )
        resp = jsonify({
            "status": "duplicate",
            "message": "Signal already processed (idempotent)",
            "dispatch_id": existing_dispatch_id,
            "action": action,
            "bar_index": bar_index,
            "seq": seq,
        })
        resp.headers["X-Webhook-Latency-Ms"] = str(max(1, int((time.perf_counter() - t0) * 1000)))
        return resp, 200

    reason = data.get("reason", "")
    if "CLOSE_PROTECT" in action:
        logger.info(
            "[Webhook] CLOSE_PROTECT | reason=%s regime=%s side=%s bar_index=%s seq=%s",
            reason, data.get("regime"), data.get("side"), bar_index, seq,
        )

    # 15s per-symbol coalesce: 先平后开；OPEN 后 CLOSE 丢弃（白皮书时序铁律）
    coalesce = get_coalesce()
    coalesce.set_dispatch(_spawn_dispatch)
    disposition = coalesce.submit(data, fingerprint, dispatch=_spawn_dispatch)
    depth = coalesce.pending_depth()
    logger.info(
        "[Webhook] coalesce disposition=%s depth=%s action=%s bar_index=%s seq=%s",
        disposition, depth, action, bar_index, seq,
    )

    resp = jsonify({
        "status": "success",
        "message": "Signal received, dispatching to all users",
        "action": action,
        "bar_index": bar_index,
        "seq": seq,
        "coalesce": disposition,
    })
    resp.headers["X-Webhook-Latency-Ms"] = str(max(1, int((time.perf_counter() - t0) * 1000)))
    return resp, 200


@webhook_app.route("/health", methods=["GET"])
def health():
    from app.services.webhook_symbol_coalesce import get_coalesce

    return jsonify({
        "status": "ok",
        "coalesce_pending": get_coalesce().pending_depth(),
    }), 200
