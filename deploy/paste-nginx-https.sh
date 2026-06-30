#!/bin/bash
# 一键写入完整 Nginx HTTPS 配置（不依赖 snippets，避免粘贴不全）
# VPS: cd ~/panda-quant-platform && sudo bash deploy/paste-nginx-https.sh

set -euo pipefail

DOMAIN="${DOMAIN:-twinstar.pro}"
VPS_IP="${VPS_IP:-187.77.130.144}"
SITE="/etc/nginx/sites-available/${DOMAIN}"
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
  echo "[FAIL] 当前 nginx 未编译 SSL 模块，请执行:"
  echo "  apt-get install -y nginx-full"
  exit 1
fi

mkdir -p /var/www/certbot

cat > "$SITE" <<EOF
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

rm -f /etc/nginx/sites-enabled/default /etc/nginx/sites-enabled/twinstar.conf
ln -sf "$SITE" "/etc/nginx/sites-enabled/${DOMAIN}"

echo ">>> 已写入 $SITE ($(wc -l < "$SITE") 行)"
grep -n 'listen' "$SITE" || true

nginx -t
systemctl restart nginx
sleep 1

echo ">>> 监听端口:"
ss -tlnp | grep -E ':80 |:443 ' || true

if ss -tlnp | grep -q ':443 '; then
  echo "[OK] 443 已在监听"
  curl -skI --max-time 8 "https://127.0.0.1/" -H "Host: ${DOMAIN}" | head -5 || true
else
  echo "[FAIL] 443 仍未监听，请运行: sudo bash deploy/diagnose-https.sh"
  exit 1
fi
