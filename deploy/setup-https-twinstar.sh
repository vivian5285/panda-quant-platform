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
  apt-get install -y -qq certbot python3-certbot-nginx >/dev/null 2>&1 || true
  if [ ! -f /etc/letsencrypt/options-ssl-nginx.conf ]; then
    if [ -f /usr/share/certbot/options-ssl-nginx.conf ]; then
      cp /usr/share/certbot/options-ssl-nginx.conf /etc/letsencrypt/options-ssl-nginx.conf
    else
      cat > /etc/letsencrypt/options-ssl-nginx.conf <<'EOF'
ssl_session_cache shared:le_nginx_SSL:10m;
ssl_session_timeout 1440m;
ssl_session_tickets off;
ssl_protocols TLSv1.2 TLSv1.3;
ssl_prefer_server_ciphers off;
EOF
    fi
  fi
  if [ ! -f /etc/letsencrypt/ssl-dhparams.pem ]; then
    echo ">>> 生成 ssl-dhparams（首次约 30s）..."
    openssl dhparam -out /etc/letsencrypt/ssl-dhparams.pem 2048
  fi
}

open_firewall() {
  if command -v ufw >/dev/null 2>&1; then
    ufw allow 80/tcp comment 'HTTP Nginx' >/dev/null 2>&1 || ufw allow 80/tcp
    ufw allow 443/tcp comment 'HTTPS Nginx' >/dev/null 2>&1 || ufw allow 443/tcp
    ufw --force enable >/dev/null 2>&1 || true
    ufw reload >/dev/null 2>&1 || true
    echo "[OK] UFW 已放行 80 / 443"
    ufw status | grep -E '80|443' || true
  else
    echo "[INFO] 未检测到 ufw，若仍无法访问请检查 Hostinger 防火墙面板"
  fi
}

verify_nginx_listeners() {
  echo ">>> 端口监听检查..."
  ss -tlnp | grep -E ':80 |:443 ' || true
  if ss -tlnp | grep -q ':443 '; then
    echo "[OK] 443 已在监听"
    return 0
  fi
  echo "[FAIL] 443 未监听 — Nginx 错误日志:"
  tail -40 /var/log/nginx/error.log 2>/dev/null || true
  echo "--- nginx -T (listen) ---"
  nginx -T 2>/dev/null | grep -E 'listen.*443|server_name' || true
  return 1
}

deploy_nginx() {
  local template=$1
  mkdir -p /var/www/certbot /etc/nginx/snippets
  cp "${APP_DIR}/deploy/nginx-twinstar-locations.conf" /etc/nginx/snippets/twinstar-locations.conf
  local site="/etc/nginx/sites-available/${DOMAIN}"
  sed "s/twinstar.pro/${DOMAIN}/g; s/187.77.130.144/${VPS_IP}/g" \
    "${APP_DIR}/deploy/${template}" > "${site}"
  ln -sf "${site}" "/etc/nginx/sites-enabled/${DOMAIN}"
  rm -f /etc/nginx/sites-enabled/default \
    /etc/nginx/sites-enabled/twinstar.conf \
    /etc/nginx/sites-available/twinstar.conf
  echo ">>> 已写入 ${site}"
  ls -la /etc/nginx/sites-enabled/ 2>/dev/null || true
  nginx -t
  systemctl enable nginx
  systemctl restart nginx
  sleep 1
  verify_nginx_listeners || {
    echo "[FAIL] Nginx 未能监听 443"
    echo "--- journalctl nginx ---"
    journalctl -u nginx -n 30 --no-pager 2>/dev/null || true
    exit 1
  }
}

echo ">>> 安装依赖..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq nginx certbot python3-certbot-nginx curl openssl >/dev/null 2>&1 || true

open_firewall

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
if curl -sfIk --max-time 10 "https://127.0.0.1/" -H "Host: ${DOMAIN}" >/dev/null; then
  echo "[OK] 本机 HTTPS 反代正常 (127.0.0.1:443)"
else
  echo "[WARN] 本机 127.0.0.1:443 不可达"
fi
if curl -sfIk --max-time 10 "https://${DOMAIN}/" >/dev/null; then
  echo "[OK] https://${DOMAIN}/ 可访问"
else
  echo "[WARN] 外网 https://${DOMAIN}/ 暂不可达（若本机 OK 则多为云防火墙未开 443）"
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
