#!/bin/bash
set -e
echo "[inject] breaking python3 symlink"
ORIG=$(readlink -f /usr/bin/python3 2>/dev/null || echo "/usr/bin/python3.10")
echo "$ORIG" > /tmp/python3_orig_target.txt
ln -sf /usr/bin/python3_does_not_exist /usr/bin/python3
