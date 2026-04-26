#!/bin/bash
set -e
echo "[inject] injecting bad cron syntax"
# Only inject if not already broken
if ! crontab -l 2>/dev/null | grep -q "bad syntax"; then
    (crontab -l 2>/dev/null; echo "bad syntax * * * * *") | crontab - 2>&1 || true
fi
echo "[inject] bad_cron done"
