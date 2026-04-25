#!/bin/bash
# Inject nginx_stopped fault: kill nginx process
set -e

echo "Injecting fault: nginx_stopped"
pkill -9 nginx || true
sleep 1

# Verify it's stopped
if pgrep -f 'nginx: master' > /dev/null; then
    echo "ERROR: nginx still running after pkill"
    exit 1
fi

echo "Fault injected: nginx is stopped"
exit 0
