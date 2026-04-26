#!/bin/bash
set -e
echo "[inject] stopping nginx"
service nginx stop || pkill -9 nginx || true
