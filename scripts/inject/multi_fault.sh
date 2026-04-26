#!/bin/bash
set -e
echo "[inject] injecting multi_fault (nginx_stopped + log_permissions)"
pkill -9 nginx || true
chmod 000 /var/log/nginx/
echo "[inject] multi_fault done"
