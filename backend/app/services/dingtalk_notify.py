"""DingTalk notify with batching, retry, and optional WeCom fallback."""
from __future__ import annotations

import json
import logging
import time
import hmac
import hashlib
import base64
import urllib.parse
import threading
from dataclasses import dataclass

import requests

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _dingtalk_url() -> str:
    from app.services.dingtalk_secrets import get_dingtalk_webhook, get_dingtalk_secret

    webhook = get_dingtalk_webhook()
    secret = get_dingtalk_secret()
    if not webhook:
        return ""
    if not secret:
        return webhook
    ts = str(round(time.time() * 1000))
    sign_raw = f"{ts}\n{secret}".encode()
    sig = hmac.new(secret.encode(), sign_raw, hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(sig))
    sep = "&" if "?" in webhook else "?"
    return f"{webhook}{sep}timestamp={ts}&sign={sign}"


def _post_dingtalk(title: str, body: str) -> bool:
    url = _dingtalk_url()
    if not url:
        logger.warning("[DingTalk] 未配置 DINGTALK_WEBHOOK，告警仅写日志: %s", title)
        return False
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": title[:128],
            "text": f"### {title}\n\n{body}\n\n*双子星AI量化 · GEMINI AI · 管理员通知*",
        },
    }
    resp = requests.post(url, json=payload, timeout=6)
    if resp.status_code >= 400:
        logger.error("DingTalk HTTP %s: %s", resp.status_code, resp.text[:200])
        return False
    try:
        data = resp.json()
        if isinstance(data, dict) and data.get("errcode", 0) not in (0, None):
            logger.error("DingTalk API err: %s", data)
            return False
    except Exception:
        pass
    return True


def _post_wecom(title: str, body: str) -> bool:
    """Enterprise WeChat group bot fallback."""
    webhook = str(getattr(get_settings(), "WECOM_WEBHOOK", "") or "").strip()
    if not webhook:
        logger.error("[WeCom] 未配置 WECOM_WEBHOOK，备用渠道不可用: %s", title)
        return False
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "content": f"### {title}\n{body}\n\n> 双子星AI量化 · 钉钉备用通道",
        },
    }
    resp = requests.post(webhook, json=payload, timeout=6)
    if resp.status_code >= 400:
        logger.error("WeCom HTTP %s: %s", resp.status_code, resp.text[:200])
        return False
    return True


def _send_with_retry(title: str, body: str) -> bool:
    """Exponential backoff 1s/2s/4s after first fail; then WeCom fallback."""
    max_retry = max(1, int(getattr(get_settings(), "DINGTALK_RETRY_MAX", 3) or 3))
    delays = [0] + [2 ** i for i in range(max_retry)]  # 0,1,2,4 for max_retry=3
    last_err: Exception | None = None
    for attempt, delay in enumerate(delays):
        if delay:
            time.sleep(delay)
        try:
            if _post_dingtalk(title, body):
                if attempt:
                    logger.info("[DingTalk] retry success attempt=%s title=%s", attempt, title[:40])
                return True
        except Exception as e:
            last_err = e
            logger.error("DingTalk push failed attempt=%s: %s", attempt, e)
    logger.error(
        "[DingTalk] exhausted retries title=%s last_err=%s → WeCom fallback",
        title[:60], last_err,
    )
    try:
        return _post_wecom(title, body)
    except Exception as e:
        logger.error("WeCom fallback failed: %s", e)
        return False


@dataclass
class _QueuedAlert:
    title: str
    body: str
    enqueued_at: float


class _DingTalkBatcher:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._queue: list[_QueuedAlert] = []
        self._timer: threading.Timer | None = None
        self._sent_ok = 0
        self._sent_fail = 0

    def enqueue(self, title: str, body: str) -> None:
        with self._lock:
            self._queue.append(_QueuedAlert(title=title, body=body, enqueued_at=time.time()))
            max_n = max(1, int(getattr(get_settings(), "DINGTALK_BATCH_MAX", 8) or 8))
            if len(self._queue) >= max_n:
                self._flush_locked()
            else:
                self._arm_timer_locked()

    def flush_now(self) -> None:
        with self._lock:
            self._flush_locked()

    def stats(self) -> dict:
        with self._lock:
            return {
                "pending": len(self._queue),
                "sent_ok": self._sent_ok,
                "sent_fail": self._sent_fail,
            }

    def _flush_sec(self) -> float:
        return max(1.0, float(getattr(get_settings(), "DINGTALK_BATCH_FLUSH_SEC", 6.0) or 6.0))

    def _arm_timer_locked(self) -> None:
        if not self._queue:
            if self._timer:
                self._timer.cancel()
                self._timer = None
            return
        if self._timer:
            return
        t = threading.Timer(self._flush_sec(), self._on_timer)
        t.daemon = True
        self._timer = t
        t.start()

    def _on_timer(self) -> None:
        with self._lock:
            self._timer = None
            self._flush_locked()

    def _flush_locked(self) -> None:
        if self._timer:
            self._timer.cancel()
            self._timer = None
        if not self._queue:
            return
        items = list(self._queue)
        self._queue.clear()
        # Send off lock to avoid blocking enqueue
        threading.Thread(
            target=self._send_batch,
            args=(items,),
            daemon=True,
            name="dingtalk-batch-send",
        ).start()

    def _send_batch(self, items: list[_QueuedAlert]) -> None:
        if len(items) == 1:
            ok = _send_with_retry(items[0].title, items[0].body)
        else:
            lines = [f"**共 {len(items)} 条通知**（攒批防限流）\n"]
            for i, it in enumerate(items, 1):
                lines.append(f"---\n**[{i}] {it.title}**\n\n{it.body}\n")
            title = f"GEMINI 通知汇总 ({len(items)}条)"
            ok = _send_with_retry(title, "\n".join(lines))
        with self._lock:
            if ok:
                self._sent_ok += 1
            else:
                self._sent_fail += 1
            logger.info(
                "[DingTalk] batch size=%s ok=%s pending=%s success_rate≈%s/%s",
                len(items),
                ok,
                len(self._queue),
                self._sent_ok,
                self._sent_ok + self._sent_fail,
            )


_batcher = _DingTalkBatcher()


def push_dingtalk(title: str, body: str, *, immediate: bool = False) -> None:
    """
    管理员钉钉推送。默认攒批（条数/秒数阈值），immediate=True 立即发送（带重试）。
    """
    if immediate:
        _send_with_retry(title, body)
        return
    _batcher.enqueue(title, body)


def flush_dingtalk_batch() -> None:
    """Force flush (tests / shutdown)."""
    _batcher.flush_now()


def dingtalk_batch_stats() -> dict:
    return _batcher.stats()


def push_system_alert(
    alert_type: str,
    severity: str,
    title: str,
    message: str,
    detail: dict | None = None,
) -> None:
    """平台级告警（系统重启 / 系统异常），仅推送管理员钉钉。"""
    sev_label = {"critical": "🚨", "warning": "⚠️", "info": "ℹ️"}.get(severity, "📢")
    body = (
        f"{sev_label} **类型**: {alert_type}\n\n"
        f"**说明**: {message}\n\n"
    )
    if detail:
        body += f"```\n{json.dumps(detail, ensure_ascii=False, indent=2)}\n```"
    # critical system alerts go out immediately
    push_dingtalk(
        f"{sev_label} {title}",
        body,
        immediate=severity == "critical",
    )


def push_trading_alert(
    user_id: int,
    uid: str,
    display: str,
    alert_type: str,
    severity: str,
    title: str,
    message: str,
    detail: dict | None = None,
) -> None:
    sev_label = {"critical": "🚨", "warning": "⚠️", "info": "ℹ️"}.get(severity, "📢")
    body = (
        f"{sev_label} **类型**: {alert_type}\n\n"
        f"**用户**: {display} (UID {uid} / id {user_id})\n\n"
        f"**说明**: {message}\n\n"
    )
    if detail:
        body += f"```\n{json.dumps(detail, ensure_ascii=False, indent=2)}\n```"
    push_dingtalk(f"{sev_label} {title}", body)


def push_sweep_alert(
    *,
    success: bool,
    user_id: int,
    user_uid: str,
    chain: str,
    amount: float,
    from_address: str,
    to_address: str,
    sweep_tx_hash: str | None = None,
    gas_tx_hash: str | None = None,
    error_message: str | None = None,
) -> None:
    """USDT 子地址归集结果通知（管理员钉钉）。"""
    if success:
        sev_label = "✅"
        title = "USDT 归集成功"
        message = f"已将 ${amount:.2f} USDT 从子地址转至冷钱包"
    else:
        sev_label = "❌"
        title = "USDT 归集失败"
        message = error_message or "链上归集失败，请查看管理后台归集记录"

    body = (
        f"{sev_label} **链**: {chain}\n\n"
        f"**用户**: {user_uid or f'id {user_id}'} (id {user_id})\n\n"
        f"**金额**: ${amount:.2f} USDT\n\n"
        f"**子地址**: `{from_address}`\n\n"
        f"**冷钱包**: `{to_address}`\n\n"
        f"**说明**: {message}\n\n"
    )
    if sweep_tx_hash:
        body += f"**归集 Tx**: `{sweep_tx_hash}`\n\n"
    if gas_tx_hash:
        body += f"**Gas Tx**: `{gas_tx_hash}`\n\n"
    push_dingtalk(f"{sev_label} {title}", body, immediate=not success)
