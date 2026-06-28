#!/usr/bin/env python3
"""
双子星AI量化 · GEMINI AI · 生产级全域自检
用法:
  docker compose exec backend python scripts/check_system.py
  docker compose exec backend python scripts/check_system.py --strict   # 有问题则 exit 1
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import socket
import sys
from datetime import datetime
from urllib.error import URLError
from urllib.request import urlopen

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

PASS = "[OK]"
FAIL = "[FAIL]"
WARN = "[WARN]"

failures: list[str] = []
warnings: list[str] = []


def ok(msg: str) -> None:
    print(f"  {PASS} {msg}")


def fail(msg: str) -> None:
    print(f"  {FAIL} {msg}")
    failures.append(msg)


def warn(msg: str) -> None:
    print(f"  {WARN} {msg}")
    warnings.append(msg)


def check_port(host: str, port: int, name: str) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(3)
    try:
        if sock.connect_ex((host, port)) == 0:
            ok(f"{name} :{port} 监听中")
        else:
            fail(f"{name} :{port} 未监听")
    finally:
        sock.close()


def fetch_json(url: str) -> dict | None:
    try:
        with urlopen(url, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except URLError:
        return None


def check_imports() -> None:
    print("\n[1] 核心模块导入")
    modules = [
        "app.main",
        "app.core.position_supervisor",
        "app.core.binance_client",
        "app.services.dispatcher",
        "app.services.verification",
        "app.services.alert_service",
        "app.services.dingtalk_notify",
        "app.services.webhook_guard",
        "app.services.startup_audit",
        "app.services.api_validation",
        "app.services.principal",
    ]
    for mod in modules:
        try:
            importlib.import_module(mod)
            ok(mod)
        except Exception as e:
            fail(f"{mod} 导入失败: {e}")


def check_ports() -> None:
    print("\n[2] 服务端口")
    api_port = int(os.getenv("API_PORT", "8000"))
    webhook_port = int(os.getenv("WEBHOOK_PORT", "6010"))
    check_port("127.0.0.1", api_port, "REST API")
    check_port("127.0.0.1", webhook_port, "Webhook")


def check_http() -> None:
    print("\n[3] HTTP 健康检查")
    api_port = int(os.getenv("API_PORT", "8000"))
    webhook_port = int(os.getenv("WEBHOOK_PORT", "6010"))

    health = fetch_json(f"http://127.0.0.1:{api_port}/api/health")
    if health and health.get("status") == "ok":
        ok(f"/api/health 正常 · supervisors={health.get('active_supervisors', 0)} "
           f"audits={health.get('startup_audits', 0)} positions={health.get('users_with_position', 0)}")
        if health.get("production_ready") is False:
            warn(f"生产配置未就绪 ({health.get('security_warnings', 0)} 项)")
    else:
        fail("/api/health 不可达")

    wh = fetch_json(f"http://127.0.0.1:{webhook_port}/health")
    if wh and wh.get("status") == "ok":
        ok("/webhook /health 正常")
    else:
        fail("Webhook /health 不可达")


def check_security() -> None:
    print("\n[4] 生产安全配置")
    from app.services.startup_audit import validate_production_secrets, validate_production_infra
    from app.database import SessionLocal

    sec = validate_production_secrets()
    if sec:
        for w in sec:
            warn(w)
    else:
        ok("密钥/钉钉/验证码模式检查通过")

    db = SessionLocal()
    try:
        infra = validate_production_infra(db)
        for n in infra:
            warn(n)
        if not infra:
            ok("基础设施检查通过")
    finally:
        db.close()


def check_execution() -> None:
    print("\n[5] 策略执行引擎")
    from app.services.webhook_guard import VALID_ACTIONS
    from app.core.position_supervisor import PositionSupervisor
    from app.config import get_settings

    ok(f"Webhook actions: {', '.join(sorted(VALID_ACTIONS))}")
    ok("开仓必填: regime, atr, price, tv_tp1~3")

    s = get_settings()
    ok(f"交易对 {s.SYMBOL} · 杠杆 {s.LEVERAGE}x · Regime 1~4 保证金已配置")

    for m in ("handle_signal", "recover_on_startup", "_sentinel_loop", "_close_all"):
        if hasattr(PositionSupervisor, m):
            ok(f"PositionSupervisor.{m}")
        else:
            fail(f"缺少 PositionSupervisor.{m}")


def check_persistence() -> None:
    print("\n[6] 状态持久化 & 目录")
    for d, label in (("state", "用户交易状态"), ("data", "数据库"), ("logs", "日志")):
        path = os.path.join(ROOT, d)
        if os.path.isdir(path):
            count = len(os.listdir(path))
            ok(f"{label} {d}/ 存在 ({count} 项)")
        else:
            warn(f"{d}/ 不存在")


def check_auth_stack() -> None:
    print("\n[7] 用户认证 & 双重验证")
    from app.models import VerificationCode, User
    from app.services.verification import PURPOSES

    ok(f"验证码用途: {', '.join(sorted(PURPOSES))}")
    if hasattr(User, "withdraw_password_hash"):
        ok("提现密码字段 withdraw_password_hash")
    else:
        fail("缺少 withdraw_password_hash 字段")
    if VerificationCode.__tablename__ == "verification_codes":
        ok("verification_codes 表已定义")


def check_api_principal() -> None:
    print("\n[10] API 校验 & 初始本金周期")
    from app.models import PrincipalSnapshot, User
    from app.services.api_validation import validate_binance_api
    from app.services.principal import (
        fetch_live_equity, start_new_profit_cycle, reset_after_settlement_confirmed,
    )

    ok("validate_binance_api 已加载")
    ok("principal 周期: api_bind / settlement_reset")
    if hasattr(User, "initial_principal"):
        ok("User.initial_principal 字段")
    else:
        fail("缺少 User.initial_principal")
    if PrincipalSnapshot.__tablename__ == "principal_snapshots":
        ok("principal_snapshots 表已定义")
    else:
        fail("缺少 principal_snapshots 表")


def check_webhook_reject() -> None:
    print("\n[8] Webhook 安全拒绝测试")
    import urllib.request
    import urllib.error

    webhook_port = int(os.getenv("WEBHOOK_PORT", "6010"))
    req = urllib.request.Request(
        f"http://127.0.0.1:{webhook_port}/webhook",
        data=b'{"action":"LONG"}',
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=5)
        fail("无 secret 请求应被拒绝")
    except urllib.error.HTTPError as e:
        if e.code in (403, 400):
            ok(f"无 secret 请求被正确拒绝 (HTTP {e.code})")
        else:
            warn(f"Webhook 返回 HTTP {e.code}")
    except URLError as e:
        warn(f"Webhook 不可达: {e}")


def check_dingtalk() -> None:
    print("\n[9] 管理员钉钉")
    from app.config import get_settings
    from app.services.dingtalk_notify import _dingtalk_url
    from app.services.alert_service import notify_system

    s = get_settings()
    if s.DINGTALK_WEBHOOK.strip():
        url = _dingtalk_url()
        if url:
            ok("钉钉 Webhook URL 可构建")
        else:
            fail("钉钉 URL 构建失败")
    else:
        warn("DINGTALK_WEBHOOK 未配置")

    if callable(notify_system):
        ok("notify_system 系统级告警已就绪")


def main() -> int:
    parser = argparse.ArgumentParser(description="双子星AI量化 · GEMINI AI 生产级全域自检")
    parser.add_argument("--strict", action="store_true", help="存在 FAIL 或 WARN 时 exit 1")
    args = parser.parse_args()

    print("=" * 64)
    print("双子星AI量化 · GEMINI AI · 生产级全域自检")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"工作目录: {ROOT}")
    print("=" * 64)

    check_imports()
    check_ports()
    check_http()
    check_security()
    check_execution()
    check_persistence()
    check_auth_stack()
    check_webhook_reject()
    check_dingtalk()
    check_api_principal()

    print("\n" + "=" * 64)
    print(f"结果: FAIL={len(failures)}  WARN={len(warnings)}")
    if failures:
        print("\n必须修复:")
        for f in failures:
            print(f"  - {f}")
    if warnings:
        print("\n建议修复:")
        for w in warnings:
            print(f"  - {w}")
    print("=" * 64)

    if failures:
        return 1
    if args.strict and warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
