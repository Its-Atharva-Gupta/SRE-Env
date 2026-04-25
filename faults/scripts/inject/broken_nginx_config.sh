#!/bin/bash
# Inject broken_nginx_config fault: corrupt nginx.conf with invalid listen directive
set -e

echo "Injecting fault: broken_nginx_config"

# Backup original config
cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.backup

# Inject bad listen line in http block (find and replace first valid listen)
# This will break the syntax check
sed -i 's/listen 80/listen BROKEN/' /etc/nginx/nginx.conf

# Verify the injection
if ! grep -q 'listen BROKEN' /etc/nginx/nginx.conf; then
    echo "ERROR: failed to inject bad listen line"
    exit 1
fi

# Kill nginx if it's running (config is now broken)
pkill -9 nginx || true
sleep 1

echo "Fault injected: nginx config is broken"
exit 0
