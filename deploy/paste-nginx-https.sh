#!/bin/bash
# TwinStar HTTPS · 与币安/深币现有 Nginx 共存（只新增 twinstar-https.conf）
# VPS: cd ~/panda-quant-platform && sudo bash deploy/paste-nginx-https.sh

set -euo pipefail

DOMAIN="${DOMAIN:-twinstar.pro}"
CONFD="/etc/nginx/conf.d/twinstar-https.conf"
CERT="/etc/letsencrypt/live/${DOMAIN}/fullchain.pem"
KEY="/etc/letsencrypt/live/${DOMAIN}/privkey.pem"
APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"

if [ "$(id -u)" -ne 0 ]; then
  echo "[FAIL] 请 sudo 运行"
  exit 1
fi

if [ ! -f "$CERT" ] || [ ! -f "$KEY" ]; then
  echo "[FAIL] 证书不存在: $CERT"
  exit 1
fi

if ! nginx -V 2>&1 | grep -q 'http_ssl_module'; then
  echo "[FAIL] nginx 无 SSL 模块: apt-get install -y nginx-full"
  exit 1
fi

mkdir -p /var/www/certbot /etc/nginx/conf.d

echo ">>> 现有 Nginx 配置（本脚本不会删除或修改这些文件）:"
ls -la /etc/nginx/conf.d/ 2>/dev/null || true
ls -la /etc/nginx/sites-enabled/ 2>/dev/null || true

# 只清理我们之前误装的 twinstar 站点，不动 gemini-quant / 币安 / 深币
rm -f /etc/nginx/sites-enabled/twinstar.conf \
  /etc/nginx/sites-enabled/twinstar.pro \
  /etc/nginx/sites-available/twinstar.conf \
  /etc/nginx/sites-available/twinstar.pro \
  /etc/nginx/conf.d/twinstar.conf

sed "s/twinstar.pro/${DOMAIN}/g" \
  "${APP_DIR}/deploy/nginx-twinstar-https-only.conf" > "$CONFD"

# 若 nginx.conf 未 include conf.d，自动补上
if ! grep -qE 'conf\.d/\*\.conf|conf\.d/' /etc/nginx/nginx.conf 2>/dev/null; then
  echo "[WARN] nginx.conf 未 include conf.d，正在修补..."
  cp /etc/nginx/nginx.conf "/etc/nginx/nginx.conf.bak.$(date +%s)"
  sed -i '/^http {/a \    include /etc/nginx/conf.d/*.conf;' /etc/nginx/nginx.conf
fi

echo ">>> 已新增 $CONFD ($(wc -l < "$CONFD") 行，仅 twinstar.pro 域名)"
echo ">>> nginx.conf include:"
grep -E 'include.*conf\.d|include.*sites-enabled' /etc/nginx/nginx.conf || true
grep -n 'listen\|server_name' "$CONFD" || true

nginx -t
systemctl reload nginx
sleep 2

echo ">>> nginx -T 是否含证书:"
if nginx -T 2>/dev/null | grep -q "letsencrypt/live/${DOMAIN}"; then
  echo "[OK] twinstar HTTPS 配置已加载"
  nginx -T 2>/dev/null | grep -E 'listen.*443|ssl_certificate.*${DOMAIN}' | head -4 || \
    nginx -T 2>/dev/null | grep -E 'listen.*443|ssl_certificate' | head -4
else
  echo "[FAIL] 证书配置仍未出现在 nginx -T"
  echo "--- 请把以下输出发管理员 ---"
  cat /etc/nginx/nginx.conf
  nginx -T 2>/dev/null | grep -E 'listen|server_name|ssl_certificate' | head -30
  exit 1
fi

echo ">>> 监听端口:"
ss -tlnp | grep -E ':80 |:443 ' || true

if ss -tlnp | grep -q ':443 '; then
  echo "[OK] 443 已在监听"
  curl -skI --max-time 8 "https://127.0.0.1/" -H "Host: ${DOMAIN}" | head -5 || true
  echo ""
  echo "币安/深币 Webhook 仍走原有 IP 配置，例如:"
  echo "  http://187.77.130.144/binance/webhook"
  echo "  http://187.77.130.144/deepcoin/webhook"
  echo "TwinStar 平台: https://${DOMAIN}/"
else
  echo "[FAIL] 443 仍未监听"
  journalctl -u nginx -n 30 --no-pager || true
  exit 1
fi
