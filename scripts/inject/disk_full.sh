#!/bin/bash
set -e
echo "[inject] filling disk"
FILL_TARGET_MB=800
dd if=/dev/zero of=/var/log/fill.log bs=1M count=${FILL_TARGET_MB} 2>/dev/null || true
echo "[inject] disk fill done"
