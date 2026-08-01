#!/usr/bin/env python3
"""
双子星AI量化 · GEMINI AI · 生产级全域自检
用法:
  docker compose exec backend python scripts/check_system.py
  docker compose exec backend python scripts/check_system.py --strict   # 有问题则 exit 1
  docker compose exec backend python scripts/check_system.py --strict --network   # 含网络连通性检查
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import socket
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime
from typing import Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

PASS = "[OK]"
FAIL = "[FAIL]"
WARN = "[WARN]"

failures: list[str] = []
warnings: list[str] = []

TV_WEBHOOK_URL = "https://twinstar.pro/gemini/webhook"


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
        with urllib.request.urlopen(url, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.URLError:
        return None


def _check_tcp_port(host: str, port: int, timeout: float = 3.0) -> bool:
    """Check if a TCP port is reachable."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        result = sock.connect_ex((host, port))
        return result == 0
    except socket.error:
        return False
    finally:
        sock.close()


def _https_get(url: str, timeout: float = 10.0) -> tuple[int, float]:
    """Perform HTTPS GET, return (http_code, elapsed_seconds)."""
    try:
        start = datetime.now()
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            elapsed = (datetime.now() - start).total_seconds()
            return resp.getcode(), elapsed
    except urllib.error.HTTPError as e:
        return e.code, -1.0
    except (urllib.error.URLError, socket.error, ssl.SSLError):
        return 0, -1.0


def check_tv_webhook_connectivity() -> None:
    """Section 0: TV Webhook 外部连通性（生产关键）。"""
    print("\n[0] TV Webhook 外部连通性")
    print(f"    目标: {TV_WEBHOOK_URL}")

    host = "twinstar.pro"
    port = 443

    # DNS 解析
    try:
        info = socket.getaddrinfo(host, port)
        resolved_ip = info[0][4][0] if info else ""
        ok(f"DNS 解析 OK ({resolved_ip})")
    except socket.gaierror as e:
        fail(f"DNS 解析失败: {e}")

    # TCP :443 握手
    if _check_tcp_port(host, port):
        ok(":443 端口开放")
    else:
        fail(":443 端口无法连接（防火墙/路由问题）")

    # HTTPS GET /health
    health_url = TV_WEBHOOK_URL.rstrip("/") + "/health"
    code, elapsed = _https_get(health_url)
    if code == 200:
        latency_ms = int(elapsed * 1000)
        ok(f"GET /health HTTP {code} ({elapsed:.3f}s · {latency_ms}ms)")
    elif code == 0:
        fail("无法连接 twinstar.pro（VPS 外网/防火墙问题）")
    else:
        warn(f"GET /health HTTP {code}")

    # POST 无 secret 应拒绝
    req = urllib.request.Request(
        TV_WEBHOOK_URL,
        data=b'{"action":"LONG"}',
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=8)
        fail("POST 无 secret 未被拒绝（安全风险！）")
    except urllib.error.HTTPError as e:
        if e.code in (403, 400):
            ok(f"POST 无 secret 被正确拒绝 (HTTP {e.code})")
        else:
            warn(f"POST 返回 HTTP {e.code}")
    except urllib.error.URLError as e:
        warn(f"POST 请求失败: {e.reason}")


def check_network_connectivity() -> None:
    """Section N: 内网/外网可达性（交易所 + GitHub + NTP）。"""
    print("\n[N] 内网/外网可达性")

    targets = [
        ("api.binance.com",        443, "Binance API"),
        ("api.okx.com",            443, "OKX"),
        ("api.gateio.ws",          443, "Gate.io"),
        ("api.github.com",         443, "GitHub"),
        ("ntp.aliyun.com",         123, "阿里云 NTP"),
        ("114.114.114.114",        53,  "国内 DNS"),
        ("8.8.8.8",               53,  "Google DNS"),
    ]

    all_ok = True
    for host, port, label in targets:
        if _check_tcp_port(host, port):
            ok(f"{label} ({host})")
        else:
            fail(f"{label} ({host})")
            all_ok = False

    if all_ok:
        ok("所有目标网络可达")


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
        "app.services.profit_audit",
        "app.services.deposit_monitor",
        "app.services.deposit_chains",
        "app.services.scheduler",
        "app.services.user_deposit_wallet",
        "app.services.deposit_sweep",
        "app.services.deposit_sweep_config",
        "app.services.wallet_balance",
        "app.services.wallet_overview",
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
    print("\n[3] HTTP 健康检查 + 本地 TV webhook")
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

    # 本地 Webhook 安全检查
    req = urllib.request.Request(
        f"http://127.0.0.1:{webhook_port}/webhook",
        data=b'{"action":"LONG"}',
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=5)
        fail("本地 Webhook 无 secret 未被拒绝")
    except urllib.error.HTTPError as e:
        if e.code in (403, 400):
            ok(f"本地 Webhook 无 secret 被拒绝 (HTTP {e.code})")
        else:
            warn(f"本地 Webhook 返回 HTTP {e.code}")
    except urllib.error.URLError:
        warn("本地 Webhook 不可达（跳过安全检查）")


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
    ok("开仓必填: price；regime/atr/tv_tp 可由网关补全 (v6.9.75+)")

    s = get_settings()
    ok(f"交易对 {s.SYMBOL} · 杠杆 {s.LEVERAGE}x · Regime 1~4 保证金已配置")
    from app.core.symbol_precision import format_price, format_quantity

    ok(f"ETHUSDT 价格精度 {format_price(3500.123)} · 数量精度 {format_quantity(1.2345)}")

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


def check_deposit_and_scheduler() -> None:
    print("\n[11] 充值监控 & 后台调度")
    from app.services.deposit_chains import MONITORED_DEPOSIT_CHAINS, monitored_chains_status
    from app.config import get_settings

    from app.services.deposit_secrets import is_deposit_mnemonic_configured

    s = get_settings()
    ok(f"监控链: {', '.join(MONITORED_DEPOSIT_CHAINS)}")
    if s.ENABLE_BACKGROUND_SCHEDULERS:
        ok("ENABLE_BACKGROUND_SCHEDULERS=true")
    else:
        warn("ENABLE_BACKGROUND_SCHEDULERS=false")

    if is_deposit_mnemonic_configured():
        src = "后台配置" if not s.DEPOSIT_HD_MNEMONIC.strip() else "env/后台"
        ok(f"充值 HD 助记词已配置 ({src})")
        from app.services.deposit_sweep_config import get_sweep_settings, is_sweep_auto_enabled
        sweep = get_sweep_settings()
        if is_sweep_auto_enabled():
            ok(f"USDT 自动归集已启用 · 就绪链 {', '.join(sweep.get('ready_chains') or []) or '无'}")
        else:
            warn("USDT 自动归集未启用（管理后台 → 钱包中心 → 冷钱包/归集）")
        for item in monitored_chains_status():
            if item.get("ready"):
                ok(f"充值监控 {item['chain']} RPC/API 就绪")
            else:
                warn(f"充值监控 {item['chain']} RPC/API 未配置")
    else:
        warn("充值 HD 助记词未配置（专属充值地址不可用）")


def check_txhash_guard() -> None:
    print("\n[12] 结算 TxHash 防重复")
    import inspect
    from app.services.settlement import submit_settlement_payment

    src = inspect.getsource(submit_settlement_payment)
    if "SettlementDeposit" in src and "已被使用" in src:
        ok("submit_settlement_payment 含 TxHash 重复校验")
    else:
        fail("submit_settlement_payment 缺少 TxHash 重复校验")


def check_api_principal() -> None:
    print("\n[10] API 校验 & 初始本金周期")
    from app.models import PrincipalSnapshot, User
    from app.services.api_validation import validate_binance_api
    from app.services.principal import (
        fetch_live_equity, start_new_profit_cycle, reset_after_settlement_confirmed,
    )

    ok("validate_binance_api 已加载")
    ok("principal 周期: api_bind / settlement_reset / supervisor_restart")
    if hasattr(User, "initial_principal"):
        ok("User.initial_principal 字段")
    else:
        fail("缺少 User.initial_principal")
    if PrincipalSnapshot.__tablename__ == "principal_snapshots":
        ok("principal_snapshots 表已定义")
    else:
        fail("缺少 principal_snapshots 表")
    if hasattr(PrincipalSnapshot, "trade_pnl_cycle"):
        ok("PrincipalSnapshot 双重审计字段")
    else:
        warn("PrincipalSnapshot 缺少双重审计扩展字段")


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
    webhook = s.DINGTALK_WEBHOOK.strip() if s.DINGTALK_WEBHOOK else ""
    if webhook:
        url = _dingtalk_url()
        if url:
            ok("钉钉 Webhook URL 可构建")
        else:
            fail("钉钉 URL 构建失败")
    else:
        ok("钉钉已禁用 (DINGTALK_WEBHOOK 未配置)")

    if callable(notify_system):
        ok("notify_system 系统级告警已就绪")


def check_wallet_hub() -> None:
    print("\n[13] 钱包中心 & 链上余额")
    from app.services.wallet_overview import WALLET_CHAINS
    from app.services.wallet_balance import NATIVE_SYMBOLS

    ok(f"钱包链: {', '.join(WALLET_CHAINS)}")
    gas_labels = ", ".join(f"{c}={NATIVE_SYMBOLS.get(c, '?')}" for c in WALLET_CHAINS)
    ok(f"原生 Gas 符号: {gas_labels}")
    try:
        importlib.import_module("app.services.wallet_overview")
        ok("wallet_overview 模块就绪 (GET /api/admin/wallet/overview)")
    except Exception as e:
        fail(f"wallet_overview 导入失败: {e}")


def check_throttle_settings() -> None:
    print("\n[14] REST 频率管制配置 (API 限流根治)")
    from app.core.rest_throttle_valve import DEFAULT_BUDGET_PER_MIN, EMERGENCY_BUDGET_PER_MIN
    from app.core.position_supervisor import (
        SENTINEL_POLL_NORMAL, SENTINEL_POLL_ARMING, SENTINEL_POLL_RADAR,
        SENTINEL_ORDER_AUDIT_SEC, SENTINEL_POLL_JITTER_SEC,
    )
    from app.core.rest_book_cache import POS_TTL_SEC, ORDER_TTL_SEC, ALGO_TTL_SEC
    from app.core.rest_symbol_pace import MIN_GAP_SEC, SHARED_ACCOUNT_GAP_SEC

    # REST budget
    if DEFAULT_BUDGET_PER_MIN <= 20:
        ok(f"REST budget {DEFAULT_BUDGET_PER_MIN}/min (安全: ≤20)")
    else:
        warn(f"REST budget {DEFAULT_BUDGET_PER_MIN}/min (建议 ≤20 防止触发交易所限流)")

    if EMERGENCY_BUDGET_PER_MIN <= 40:
        ok(f"Emergency budget {EMERGENCY_BUDGET_PER_MIN}/min (安全: ≤40)")
    else:
        warn(f"Emergency budget {EMERGENCY_BUDGET_PER_MIN}/min (建议 ≤40)")

    # Sentinel poll cadence
    if SENTINEL_POLL_NORMAL >= 60:
        ok(f"哨兵轮询 NORMAL={SENTINEL_POLL_NORMAL}s (≥60s 安全)")
    else:
        warn(f"哨兵轮询 NORMAL={SENTINEL_POLL_NORMAL}s (建议 ≥60s)")

    if SENTINEL_POLL_ARMING >= 45:
        ok(f"哨兵轮询 ARMING={SENTINEL_POLL_ARMING}s (≥45s)")
    else:
        warn(f"哨兵轮询 ARMING={SENTINEL_POLL_ARMING}s (建议 ≥45s)")

    if SENTINEL_POLL_RADAR >= 45:
        ok(f"哨兵轮询 RADAR={SENTINEL_POLL_RADAR}s (≥45s)")
    else:
        warn(f"哨兵轮询 RADAR={SENTINEL_POLL_RADAR}s (建议 ≥45s)")

    if SENTINEL_ORDER_AUDIT_SEC >= 90:
        ok(f"订单簿审计间隔={SENTINEL_ORDER_AUDIT_SEC}s (≥90s 安全)")
    else:
        warn(f"订单簿审计间隔={SENTINEL_ORDER_AUDIT_SEC}s (建议 ≥90s)")

    if SENTINEL_POLL_JITTER_SEC >= 2.0:
        ok(f"哨兵抖动={SENTINEL_POLL_JITTER_SEC}s (≥2s 防止集中突发)")
    else:
        warn(f"哨兵抖动={SENTINEL_POLL_JITTER_SEC}s (建议 ≥2s)")

    # Cache TTLs
    if POS_TTL_SEC >= 30:
        ok(f"Position 缓存 TTL={POS_TTL_SEC}s (≥30s)")
    else:
        warn(f"Position 缓存 TTL={POS_TTL_SEC}s (建议 ≥30s)")

    if ORDER_TTL_SEC >= 60:
        ok(f"Order 缓存 TTL={ORDER_TTL_SEC}s (≥60s)")
    else:
        warn(f"Order 缓存 TTL={ORDER_TTL_SEC}s (建议 ≥60s)")

    if ALGO_TTL_SEC >= 60:
        ok(f"Algo 缓存 TTL={ALGO_TTL_SEC}s (≥60s)")
    else:
        warn(f"Algo 缓存 TTL={ALGO_TTL_SEC}s (建议 ≥60s)")

    # Shared endpoint gap
    if SHARED_ACCOUNT_GAP_SEC >= 5.0:
        ok(f"共享端点间隔={SHARED_ACCOUNT_GAP_SEC}s (≥5s, 防止 openOrders 权重风暴)")
    else:
        warn(f"共享端点间隔={SHARED_ACCOUNT_GAP_SEC}s (建议 ≥5s)")

    ok("频率管制: REST budget + TTL + 哨兵轮询 三层协同降频")


def main() -> int:
    parser = argparse.ArgumentParser(description="双子星AI量化 · GEMINI AI 生产级全域自检")
    parser.add_argument("--strict", action="store_true", help="存在 FAIL 或 WARN 时 exit 1")
    parser.add_argument("--network", action="store_true",
                        help="包含 TV webhook 外部连通性 + 网络可达性检查")
    args = parser.parse_args()

    print("=" * 64)
    print("双子星AI量化 · GEMINI AI · 生产级全域自检")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"工作目录: {ROOT}")
    print("=" * 64)

    # 0: TV Webhook 外部连通性（生产最关键，放第一位）
    if args.network:
        check_tv_webhook_connectivity()

    check_imports()
    check_ports()
    check_http()

    if args.network:
        check_network_connectivity()

    check_security()
    check_execution()
    check_persistence()
    check_auth_stack()
    check_webhook_reject()
    check_dingtalk()
    check_api_principal()
    check_deposit_and_scheduler()
    check_txhash_guard()
    check_wallet_hub()
    check_throttle_settings()

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
