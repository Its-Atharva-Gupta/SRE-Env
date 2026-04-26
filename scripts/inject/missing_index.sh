#!/bin/bash
set -e
echo "[inject] removing nginx default index"
rm -f /var/www/html/index.html
service nginx restart || true
