#!/bin/bash
# 修复 TwinStar HTTPS 部署后深币 webhook 404（与 quant_gateway.conf 共存）
# VPS: sudo bash deploy/fix-deepcoin-nginx.sh

set -euo pipefail
VPS_IP="${VPS_IP:-187.77.130.144}"
GATEWAY="/etc/nginx/conf.d/quant_gateway.conf"

if [ "$(id -u)" -ne 0 ]; then
  echo "[FAIL] 请 sudo 运行"
  exit 1
fi

echo ">>> 1. 移除会抢占 IP:80 的旧 twinstar 站点（保留 conf.d/twinstar-https.conf）"
rm -f /etc/nginx/sites-enabled/twinstar.conf \
  /etc/nginx/sites-enabled/twinstar.pro \
  /etc/nginx/sites-available/twinstar.conf \
  /etc/nginx/sites-available/twinstar.pro
ls -la /etc/nginx/sites-enabled/ 2>/dev/null || echo "  (sites-enabled 已空)"

echo ""
echo ">>> 2. 检查 quant_gateway.conf"
if [ ! -f "$GATEWAY" ]; then
  echo "[FAIL] 未找到 $GATEWAY"
  exit 1
fi

if grep -q 'location /deepcoin/webhook' "$GATEWAY"; then
  echo "[OK] quant_gateway.conf 已有 /deepcoin/webhook"
else
  echo "[WARN] quant_gateway.conf 缺少 deepcoin，正在追加..."
  cp "$GATEWAY" "${GATEWAY}.bak.$(date +%s)"
  # 在第一个 server { 的 closing brace 前插入（简单场景：单 server 块）
  DEEPCOIN=$'    location /deepcoin/webhook {\n        proxy_pass http://127.0.0.1:5004/webhook;\n        proxy_set_header Host $host;\n        proxy_set_header X-Real-IP $remote_addr;\n        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n        proxy_connect_timeout 3s;\n        proxy_read_timeout 10s;\n    }\n'
  awk -v block="$DEEPCOIN" '
    /^server \{/ { inserver=1 }
    inserver && /^}/ && !done {
      print block
      done=1
      inserver=0
    }
    { print }
  ' "$GATEWAY" > "${GATEWAY}.tmp" && mv "${GATEWAY}.tmp" "$GATEWAY"
  echo "[OK] 已追加 deepcoin location"
fi

echo ""
echo ">>> 3. nginx -T 中的 IP:80 路由"
nginx -T 2>/dev/null | grep -E 'server_name|location /(binance|deepcoin)' | head -20 || true

nginx -t
systemctl reload nginx
sleep 1

echo ""
echo ">>> 4. 本机 webhook 探测（POST PING）"
BIN=$(curl -s -X POST "http://127.0.0.1/binance/webhook" \
  -H "Host: ${VPS_IP}" -H "Content-Type: application/json" \
  -d '{"secret":"528586","action":"PING"}' | head -c 120)
DEEP=$(curl -s -X POST "http://127.0.0.1/deepcoin/webhook" \
  -H "Host: ${VPS_IP}" -H "Content-Type: application/json" \
  -d '{"secret":"528586","action":"PING"}' | head -c 120)

echo "binance:  $BIN"
echo "deepcoin: $DEEP"

if echo "$DEEP" | grep -qiE 'success|Signal received|PING'; then
  echo "[OK] 深币 webhook 已恢复"
elif echo "$DEEP" | grep -qi '404'; then
  echo "[FAIL] 深币仍 404 — 请把以下发管理员:"
  echo "  cat $GATEWAY"
  echo "  sudo nginx -T | grep -A5 deepcoin"
  exit 1
else
  echo "[WARN] 深币响应异常（可能 secret 不对），但已不是 nginx 404"
fi
