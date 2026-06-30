#!/bin/bash
# TwinStar · twinstar.pro HTTPS 一键配置（不触碰 5002/5003/5004 上的其它进程）
#
# 前置（Hostinger DNS）:
#   A   @    → 187.77.130.144
#   A   www  → 187.77.130.144
#   邮件 MX 记录勿删
#
# 用法（在仓库根目录）:
#   chmod +x deploy/setup-https-twinstar.sh
#   sudo CERTBOT_EMAIL=admin@twinstar.pro bash deploy/setup-https-twinstar.sh
#
# 可选环境变量:
#   DOMAIN=twinstar.pro
#   VPS_IP=187.77.130.144
#   APP_DIR=/root/panda-quant-platform   # git 仓库路径
#   CERTBOT_EMAIL=admin@twinstar.pro

set -euo pipefail

DOMAIN="${DOMAIN:-twinstar.pro}"
VPS_IP="${VPS_IP:-187.77.130.144}"
CERTBOT_EMAIL="${CERTBOT_EMAIL:-admin@${DOMAIN}}"
APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"

echo "=============================================="
echo " TwinStar HTTPS · ${DOMAIN} · ${VPS_IP}"
echo " 不修改 5002/5003/5004 端口与其它脚本"
echo "=============================================="

if [ "$(id -u)" -ne 0 ]; then
  echo "[FAIL] 请使用 sudo 运行"
  exit 1
fi

echo ">>> 检查 DNS..."
RESOLVED=$(getent ahosts "${DOMAIN}" | awk '/STREAM/ {print $1; exit}')
if [ -z "${RESOLVED}" ]; then
  echo "[WARN] ${DOMAIN} 尚未解析，Certbot 可能失败。请先在 Hostinger 添加 A 记录 → ${VPS_IP}"
else
  echo "    ${DOMAIN} → ${RESOLVED}"
  if [ "${RESOLVED}" != "${VPS_IP}" ]; then
    echo "[WARN] 解析 IP 与 VPS_IP 不一致（期望 ${VPS_IP}），继续执行但证书可能失败"
  fi
fi

echo ">>> 安装依赖（nginx / certbot）..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq nginx certbot python3-certbot-nginx curl >/dev/null 2>&1 || true

echo ">>> 部署 Nginx 片段与站点配置..."
mkdir -p /var/www/certbot
mkdir -p /etc/nginx/snippets
cp "${APP_DIR}/deploy/nginx-twinstar-locations.conf" /etc/nginx/snippets/twinstar-locations.conf

# 生成站点配置（替换域名/IP 占位）
sed "s/twinstar.pro/${DOMAIN}/g; s/187.77.130.144/${VPS_IP}/g" \
  "${APP_DIR}/deploy/nginx-twinstar.pro.conf" > /etc/nginx/sites-available/twinstar.pro

ln -sf /etc/nginx/sites-available/twinstar.pro /etc/nginx/sites-enabled/twinstar.pro
if [ -f /etc/nginx/sites-enabled/default ]; then
  rm -f /etc/nginx/sites-enabled/default
fi

nginx -t
systemctl enable nginx
systemctl reload nginx
echo "[OK] Nginx HTTP 已加载（IP 与域名共用 location，5003/5004 路径保留）"

echo ">>> 申请 Let's Encrypt 证书..."
if certbot --nginx \
  -d "${DOMAIN}" -d "www.${DOMAIN}" \
  --non-interactive --agree-tos -m "${CERTBOT_EMAIL}" \
  --redirect --no-eff-email; then
  echo "[OK] HTTPS 证书已安装，HTTP 自动跳转 HTTPS（仅域名，不影响 ${VPS_IP} 的 HTTP）"
else
  echo "[WARN] Certbot 失败 — 请确认 DNS A 记录已生效后重跑本脚本"
  echo "       手动: sudo certbot --nginx -d ${DOMAIN} -d www.${DOMAIN}"
fi

echo ">>> 更新 backend/.env 公网地址..."
ENV_FILE="${APP_DIR}/backend/.env"
if [ -f "${ENV_FILE}" ]; then
  grep -q '^FRONTEND_URL=' "${ENV_FILE}" && \
    sed -i "s|^FRONTEND_URL=.*|FRONTEND_URL=https://${DOMAIN}|" "${ENV_FILE}" || \
    echo "FRONTEND_URL=https://${DOMAIN}" >> "${ENV_FILE}"
  grep -q '^API_PUBLIC_URL=' "${ENV_FILE}" && \
    sed -i "s|^API_PUBLIC_URL=.*|API_PUBLIC_URL=https://${DOMAIN}|" "${ENV_FILE}" || \
    echo "API_PUBLIC_URL=https://${DOMAIN}" >> "${ENV_FILE}"
  echo "[OK] 已写入 FRONTEND_URL / API_PUBLIC_URL"
  if command -v docker >/dev/null 2>&1 && [ -f "${APP_DIR}/docker-compose.yml" ]; then
    (cd "${APP_DIR}" && docker compose restart backend) && echo "[OK] backend 已重启"
  fi
else
  echo "[SKIP] 未找到 ${ENV_FILE}，请手动设置:"
  echo "  FRONTEND_URL=https://${DOMAIN}"
  echo "  API_PUBLIC_URL=https://${DOMAIN}"
fi

echo ""
echo "=============================================="
echo " 完成"
echo "  平台:     https://${DOMAIN}/"
echo "  管理端:   https://${DOMAIN}/admin"
echo "  Webhook:  https://${DOMAIN}/gemini/webhook"
echo "  IP 入口:  http://${VPS_IP}/  (HTTP 保留)"
echo "  币安 WH:  http://${VPS_IP}/binance/webhook  (5003 未动)"
echo "  深币 WH:  http://${VPS_IP}/deepcoin/webhook  (5004 未动)"
echo "  5002:     未修改"
echo "=============================================="
