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
grep -E 'include.*conf\.d|include.*sites-enabled' /etc/nginx/nginx.conf 2>/dev/null || true
echo "conf.d:"
ls -la /etc/nginx/conf.d/ 2>/dev/null || true
echo "sites-enabled:"
ls -la /etc/nginx/sites-enabled/ 2>/dev/null || true
for f in /etc/nginx/conf.d/twinstar-https.conf /etc/nginx/sites-available/twinstar.conf; do
  [ -f "$f" ] || continue
  echo "--- ${f} ($(wc -l < "$f") 行) ---"
  grep -n 'listen\|server_name\|ssl_certificate' "$f" || true
done
echo "--- nginx -T 是否加载证书 ---"
if nginx -T 2>/dev/null | grep -q 'letsencrypt/live'; then
  echo "[OK] letsencrypt 路径出现在 nginx -T"
  nginx -T 2>/dev/null | grep -E 'listen.*443|ssl_certificate' | head -8
else
  echo "[!!] nginx -T 里没有 letsencrypt — 配置文件未被加载"
  nginx -T 2>/dev/null | grep -E '^\s*listen|server_name' || true
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
