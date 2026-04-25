#!/bin/bash
# Inject multi_fault: combine nginx_stopped + log_permissions
set -e

echo "Injecting fault: multi_fault"

# Kill nginx
pkill -9 nginx || true

# Make logs unwritable
chmod 000 /var/log/nginx/

sleep 1

# Verify both faults are present
if ! pgrep -f 'nginx: master' > /dev/null && ! [ -w /var/log/nginx ]; then
    echo "Fault injected: nginx stopped + logs unwritable"
    exit 0
else
    echo "ERROR: Failed to inject multi_fault"
    exit 1
fi
