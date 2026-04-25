#!/bin/bash
# Inject log_permissions fault: make nginx log directory unwritable
set -e

echo "Injecting fault: log_permissions"
chmod 000 /var/log/nginx/
sleep 1

# Verify nginx can't write to logs
if [ -w /var/log/nginx ]; then
    echo "ERROR: /var/log/nginx is still writable"
    exit 1
fi

echo "Fault injected: nginx log directory is unwritable"
exit 0
