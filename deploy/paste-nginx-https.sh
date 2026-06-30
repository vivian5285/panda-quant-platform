#!/bin/bash
# 一键写入 Nginx HTTPS（写入 conf.d，兼容不加载 sites-enabled 的 VPS）
# VPS: cd ~/panda-quant-platform && sudo bash deploy/paste-nginx-https.sh

set -euo pipefail

DOMAIN="${DOMAIN:-twinstar.pro}"
VPS_IP="${VPS_IP:-187.77.130.144}"
CONFD="/etc/nginx/conf.d/twinstar-https.conf"
CERT="/etc/letsencrypt/live/${DOMAIN}/fullchain.pem"
KEY="/etc/letsencrypt/live/${DOMAIN}/privkey.pem"

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

# 旧配置全部清掉，避免 map/server 重复导致整站被跳过
rm -f /etc/nginx/sites-enabled/twinstar.conf \
  /etc/nginx/sites-enabled/twinstar.pro \
  /etc/nginx/sites-enabled/default \
  /etc/nginx/sites-available/twinstar.conf \
  /etc/nginx/sites-available/twinstar.pro \
  /etc/nginx/conf.d/twinstar.conf
if [ -f /etc/nginx/conf.d/default.conf ]; then
  mv /etc/nginx/conf.d/default.conf /etc/nginx/conf.d/default.conf.bak.$(date +%s)
  echo "[OK] 已禁用 conf.d/default.conf（避免抢占 80 默认站）"
fi

cat > "$CONFD" <<EOF
map \$http_upgrade \$connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 443 ssl;
    server_name ${DOMAIN} www.${DOMAIN};

    ssl_certificate ${CERT};
    ssl_certificate_key ${KEY};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1d;

    location /binance/webhook {
        proxy_pass http://127.0.0.1:5003/webhook;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /deepcoin/webhook {
        proxy_pass http://127.0.0.1:5004/webhook;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /gemini/webhook {
        proxy_pass http://127.0.0.1:6010/webhook;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location / {
        proxy_pass http://127.0.0.1:6080;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Authorization \$http_authorization;
        proxy_set_header X-Access-Token \$http_x_access_token;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$connection_upgrade;
        proxy_read_timeout 3600s;
    }
}

server {
    listen 80;
    server_name ${DOMAIN} www.${DOMAIN};

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 301 https://\$host\$request_uri;
    }
}

server {
    listen 80;
    server_name ${VPS_IP};

    location /binance/webhook {
        proxy_pass http://127.0.0.1:5003/webhook;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }

    location /deepcoin/webhook {
        proxy_pass http://127.0.0.1:5004/webhook;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }

    location /gemini/webhook {
        proxy_pass http://127.0.0.1:6010/webhook;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }

    location / {
        proxy_pass http://127.0.0.1:6080;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
}
EOF

# 若 nginx.conf 未 include conf.d，自动补上
if ! grep -qE 'conf\.d/\*\.conf|conf\.d/' /etc/nginx/nginx.conf 2>/dev/null; then
  echo "[WARN] nginx.conf 未 include conf.d，正在修补..."
  cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.bak.$(date +%s)
  sed -i '/^http {/a \    include /etc/nginx/conf.d/*.conf;' /etc/nginx/nginx.conf
fi

echo ">>> 已写入 $CONFD ($(wc -l < "$CONFD") 行)"
echo ">>> nginx.conf include:"
grep -E 'include.*conf\.d|include.*sites-enabled' /etc/nginx/nginx.conf || true
echo ">>> conf.d:"
ls -la /etc/nginx/conf.d/ || true
grep -n 'listen' "$CONFD" || true

nginx -t
systemctl restart nginx
sleep 2

echo ">>> nginx -T 是否含证书路径:"
if nginx -T 2>/dev/null | grep -q 'letsencrypt/live'; then
  echo "[OK] 证书配置已被 nginx 加载"
  nginx -T 2>/dev/null | grep -E 'listen.*443|ssl_certificate' | head -6
else
  echo "[FAIL] nginx 仍未加载 twinstar 配置"
  echo "--- nginx.conf ---"
  cat /etc/nginx/nginx.conf
  echo "--- nginx -T (listen) ---"
  nginx -T 2>/dev/null | grep -E 'listen|server_name' || true
  exit 1
fi

echo ">>> 监听端口:"
ss -tlnp | grep -E ':80 |:443 ' || true

if ss -tlnp | grep -q ':443 '; then
  echo "[OK] 443 已在监听"
  curl -skI --max-time 8 "https://127.0.0.1/" -H "Host: ${DOMAIN}" | head -5 || true
else
  echo "[FAIL] 443 仍未监听"
  journalctl -u nginx -n 30 --no-pager || true
  exit 1
fi
