#!/bin/bash
# Inject bad_cron fault: inject malformed cron syntax
set -e

echo "Injecting fault: bad_cron"

# Create a cron job with bad syntax
(crontab -l 2>/dev/null; echo "bad syntax * * * * *") | crontab - 2>&1 || true

sleep 1

# Verify cron has bad syntax
if crontab -l 2>&1 | grep -q "bad syntax"; then
    echo "Fault injected: cron has malformed syntax"
    exit 0
else
    echo "ERROR: Failed to inject bad cron syntax"
    exit 1
fi
