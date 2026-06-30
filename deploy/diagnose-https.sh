#!/bin/bash
# 快速诊断 HTTPS / Nginx / 防火墙（在 VPS 上: sudo bash deploy/diagnose-https.sh）
set -uo pipefail
DOMAIN="${DOMAIN:-twinstar.pro}"

echo "=== 1. 证书 ==="
certbot certificates 2>/dev/null || echo "certbot 不可用"
ls -la "/etc/letsencrypt/live/${DOMAIN}/" 2>/dev/null || echo "证书目录不存在"

echo ""
echo "=== 2. Nginx 状态 ==="
systemctl is-active nginx || true
nginx -t 2>&1 || true

echo ""
echo "=== 3. 监听端口 (80/443) ==="
ss -tlnp | grep -E ':80 |:443 ' || echo "80/443 均未监听"

echo ""
echo "=== 4. 站点配置 ==="
echo "nginx.conf include 规则:"
grep -E 'include.*sites-enabled|include.*conf\.d' /etc/nginx/nginx.conf 2>/dev/null || true
echo "sites-enabled:"
ls -la /etc/nginx/sites-enabled/ 2>/dev/null || true
SITE_FILE="/etc/nginx/sites-available/twinstar.conf"
LEGACY="/etc/nginx/sites-available/${DOMAIN}"
for f in "$SITE_FILE" "$LEGACY"; do
  [ -f "$f" ] || continue
  echo "--- ${f} ($(wc -l < "$f") 行) ---"
  grep -n 'listen\|server_name\|ssl_certificate' "$f" || true
done
if [ -f "$LEGACY" ] && [ ! -f "$SITE_FILE" ]; then
  echo "[!!] 只有 twinstar.pro 无 twinstar.conf — 若 nginx.conf 为 sites-enabled/*.conf 则不会加载"
fi
if [ -f "$SITE_FILE" ] && ! grep -q 'listen 443' "$SITE_FILE"; then
  echo "[!!] twinstar.conf 里没有 listen 443"
fi
if ls /etc/nginx/sites-enabled/*.conf >/dev/null 2>&1; then
  echo "[INFO] sites-enabled 下 .conf 文件:"
  ls /etc/nginx/sites-enabled/*.conf 2>/dev/null || echo "  (无 .conf 文件 — 站点不会被加载!)"
fi
echo "--- nginx -T (listen / ssl) ---"
nginx -T 2>/dev/null | grep -E '^\s*listen|server_name|ssl_certificate' || true
if ! nginx -T 2>/dev/null | grep -q 'listen.*443'; then
  echo "[!!] nginx 运行时未加载 443 — 请改用 sites-enabled/twinstar.conf"
fi

echo ""
echo "=== 5. UFW ==="
ufw status 2>/dev/null || echo "ufw 未安装"

echo ""
echo "=== 6. 本机探测 ==="
curl -sI --max-time 5 "http://127.0.0.1/" -H "Host: ${DOMAIN}" | head -3 || echo "HTTP 本机失败"
curl -skI --max-time 5 "https://127.0.0.1/" -H "Host: ${DOMAIN}" | head -3 || echo "HTTPS 本机失败"

echo ""
echo "=== 8. journalctl nginx (最后 20 行) ==="
journalctl -u nginx -n 20 --no-pager 2>/dev/null || true

echo ""
echo "=== 9. nginx 是否编译 SSL 模块 ==="
nginx -V 2>&1 | tr ' ' '\n' | grep -i ssl || true
