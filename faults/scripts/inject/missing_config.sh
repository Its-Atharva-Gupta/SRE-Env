#!/bin/bash
# Inject missing_config fault: delete nginx default site config
set -e

echo "Injecting fault: missing_config"
rm -f /etc/nginx/sites-enabled/default
sleep 1

# Verify config is gone
if [ -f /etc/nginx/sites-enabled/default ]; then
    echo "ERROR: /etc/nginx/sites-enabled/default still exists"
    exit 1
fi

# Restart nginx to apply config change
systemctl restart nginx || true

echo "Fault injected: nginx default config is missing"
exit 0
