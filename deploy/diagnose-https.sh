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
grep -E 'listen|server_name|ssl_certificate' /etc/nginx/sites-enabled/* 2>/dev/null || true

echo ""
echo "=== 5. UFW ==="
ufw status 2>/dev/null || echo "ufw 未安装"

echo ""
echo "=== 6. 本机探测 ==="
curl -sI --max-time 5 "http://127.0.0.1/" -H "Host: ${DOMAIN}" | head -3 || echo "HTTP 本机失败"
curl -skI --max-time 5 "https://127.0.0.1/" -H "Host: ${DOMAIN}" | head -3 || echo "HTTPS 本机失败"

echo ""
echo "=== 7. Nginx 错误日志 (最后 15 行) ==="
tail -15 /var/log/nginx/error.log 2>/dev/null || true
