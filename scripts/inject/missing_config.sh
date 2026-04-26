#!/bin/bash
set -e
echo "[inject] removing nginx default site config"
rm -f /etc/nginx/sites-enabled/default
echo "[inject] missing_config done"
