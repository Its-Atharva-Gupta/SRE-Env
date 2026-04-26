#!/bin/bash
set -e
echo "[inject] stopping nginx"
pkill -9 nginx || true
echo "[inject] nginx_stopped done"
