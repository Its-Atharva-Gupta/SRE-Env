#!/bin/bash
set -e
echo "[inject] breaking nginx log permissions"
chmod 000 /var/log/nginx/
echo "[inject] log_permissions done"
