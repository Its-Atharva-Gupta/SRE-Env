#!/bin/bash
set -e
echo "[inject] corrupting nginx config"
if ! grep -q "listen BROKEN" /etc/nginx/nginx.conf; then
    sed -i 's/listen 80/listen BROKEN/' /etc/nginx/nginx.conf
fi
echo "[inject] broken_nginx_config done"
