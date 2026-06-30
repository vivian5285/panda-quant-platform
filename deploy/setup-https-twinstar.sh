#!/bin/bash
# TwinStar · twinstar.pro HTTPS 一键配置（不触碰 5002/5003/5004）
#
# 用法: sudo CERTBOT_EMAIL=admin@twinstar.pro bash deploy/setup-https-twinstar.sh
# 证书已存在仅重装 Nginx: sudo bash deploy/setup-https-twinstar.sh --nginx-only

set -euo pipefail

DOMAIN="${DOMAIN:-twinstar.pro}"
VPS_IP="${VPS_IP:-187.77.130.144}"
CERTBOT_EMAIL="${CERTBOT_EMAIL:-admin@${DOMAIN}}"
APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
NGINX_ONLY=false
if [ "${1:-}" = "--nginx-only" ]; then
  NGINX_ONLY=true
fi

CERT_DIR="/etc/letsencrypt/live/${DOMAIN}"

echo "=============================================="
echo " TwinStar HTTPS · ${DOMAIN} · ${VPS_IP}"
echo "=============================================="

if [ "$(id -u)" -ne 0 ]; then
  echo "[FAIL] 请使用 sudo 运行"
  exit 1
fi

ensure_ssl_params() {
  if [ ! -f /etc/letsencrypt/options-ssl-nginx.conf ]; then
    curl -fsSL https://raw.githubusercontent.com/certbot/certbot/master/certbot-nginx/certbot_nginx/_internal/tls_configs/options-ssl-nginx.conf \
      -o /etc/letsencrypt/options-ssl-nginx.conf 2>/dev/null || true
  fi
  if [ ! -f /etc/letsencrypt/ssl-dhparams.pem ]; then
    openssl dhparam -out /etc/letsencrypt/ssl-dhparams.pem 2048 2>/dev/null || true
  fi
}

deploy_nginx() {
  local template=$1
  mkdir -p /var/www/certbot /etc/nginx/snippets
  cp "${APP_DIR}/deploy/nginx-twinstar-locations.conf" /etc/nginx/snippets/twinstar-locations.conf
  sed "s/twinstar.pro/${DOMAIN}/g; s/187.77.130.144/${VPS_IP}/g" \
    "${APP_DIR}/deploy/${template}" > /etc/nginx/sites-available/twinstar.pro
  ln -sf /etc/nginx/sites-available/twinstar.pro /etc/nginx/sites-enabled/twinstar.pro
  rm -f /etc/nginx/sites-enabled/default
  nginx -t
  systemctl enable nginx
  systemctl reload nginx
}

echo ">>> 安装依赖..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq nginx certbot curl openssl >/dev/null 2>&1 || true

if [ "$NGINX_ONLY" = true ] && [ -f "${CERT_DIR}/fullchain.pem" ]; then
  echo ">>> 仅重装 Nginx HTTPS 配置..."
  ensure_ssl_params
  deploy_nginx "nginx-twinstar.pro.ssl.conf"
  echo "[OK] HTTPS Nginx 已加载"
else
  echo ">>> 检查 DNS..."
  RESOLVED=$(getent ahostsv4 "${DOMAIN}" 2>/dev/null | awk '{print $1; exit}')
  [ -z "${RESOLVED}" ] && RESOLVED=$(getent ahosts "${DOMAIN}" | awk '/RAW/ {print $1; exit}')
  echo "    ${DOMAIN} → ${RESOLVED:-未解析}"

  if [ -f "${CERT_DIR}/fullchain.pem" ]; then
    echo ">>> 检测到已有证书，直接部署 HTTPS Nginx..."
    ensure_ssl_params
    deploy_nginx "nginx-twinstar.pro.ssl.conf"
    echo "[OK] HTTPS 已启用"
  else
    echo ">>> 部署 HTTP（用于 ACME 验证）..."
    deploy_nginx "nginx-twinstar.pro.conf"

    echo ">>> 申请证书 (webroot)..."
    if certbot certonly --webroot -w /var/www/certbot \
      -d "${DOMAIN}" -d "www.${DOMAIN}" \
      --non-interactive --agree-tos -m "${CERTBOT_EMAIL}" --no-eff-email; then
      echo "[OK] 证书已签发"
    else
      echo "[FAIL] certbot certonly 失败，请检查 DNS 与 80 端口"
      exit 1
    fi

    ensure_ssl_params
    deploy_nginx "nginx-twinstar.pro.ssl.conf"
    echo "[OK] HTTPS Nginx 已加载"
  fi
fi

echo ">>> 验证 HTTPS..."
if curl -sfI --max-time 10 "https://${DOMAIN}/" >/dev/null; then
  echo "[OK] https://${DOMAIN}/ 可访问"
else
  echo "[WARN] https://${DOMAIN}/ 暂不可达，请检查防火墙 443 与 nginx 日志"
fi

echo ">>> 更新 backend/.env..."
ENV_FILE="${APP_DIR}/backend/.env"
if [ -f "${ENV_FILE}" ]; then
  grep -q '^FRONTEND_URL=' "${ENV_FILE}" && \
    sed -i "s|^FRONTEND_URL=.*|FRONTEND_URL=https://${DOMAIN}|" "${ENV_FILE}" || \
    echo "FRONTEND_URL=https://${DOMAIN}" >> "${ENV_FILE}"
  grep -q '^API_PUBLIC_URL=' "${ENV_FILE}" && \
    sed -i "s|^API_PUBLIC_URL=.*|API_PUBLIC_URL=https://${DOMAIN}|" "${ENV_FILE}" || \
    echo "API_PUBLIC_URL=https://${DOMAIN}" >> "${ENV_FILE}"
  if command -v docker >/dev/null 2>&1 && [ -f "${APP_DIR}/docker-compose.yml" ]; then
    (cd "${APP_DIR}" && docker compose restart backend) && echo "[OK] backend 已重启"
  fi
fi

echo ""
echo "=============================================="
echo " 平台:    https://${DOMAIN}/"
echo " 管理端:  https://${DOMAIN}/admin"
echo " Webhook: https://${DOMAIN}/gemini/webhook"
echo " IP HTTP: http://${VPS_IP}/  (5003/5004 路径保留)"
echo "=============================================="
