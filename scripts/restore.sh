#!/bin/bash
# restore.sh — return system to healthy state before each episode
# Must be idempotent. Must be bulletproof. Exit 0 always.

set -e

echo "[restore] starting system restore"

# ── Kill any runaway processes from previous episode ────────────────────────
pkill -f "fill.log" 2>/dev/null || true
pkill -f "fork_bomb" 2>/dev/null || true

# ── Remove any injected junk files ──────────────────────────────────────────
rm -f /var/log/fill.log
rm -f /tmp/zombie.pid

# ── Restore nginx config from backup ────────────────────────────────────────
if [ -f /etc/nginx/nginx.conf.bak ]; then
    cp /etc/nginx/nginx.conf.bak /etc/nginx/nginx.conf
else
    echo "[restore] WARNING: nginx.conf.bak not found — skipping config restore"
fi

# ── Restore nginx sites-enabled ─────────────────────────────────────────────
if [ -f /etc/nginx/sites-enabled/default.bak ]; then
    cp /etc/nginx/sites-enabled/default.bak /etc/nginx/sites-enabled/default
fi

# ── Restore index.html ──────────────────────────────────────────────────────
mkdir -p /var/www/html
if [ ! -f /var/www/html/index.html ]; then
    echo "<!DOCTYPE html><html><body>OK</body></html>" > /var/www/html/index.html
    chown www-data:www-data /var/www/html/index.html 2>/dev/null || true
fi

# ── Restore log directory permissions ───────────────────────────────────────
mkdir -p /var/log/nginx/
chmod 755 /var/log/nginx/
chown -R www-data:adm /var/log/nginx/ 2>/dev/null || \
    chown -R www-data /var/log/nginx/ 2>/dev/null || true

# ── Restore python3 symlink ──────────────────────────────────────────────────
if [ -f /tmp/python3_orig_target.txt ]; then
    ORIG=$(cat /tmp/python3_orig_target.txt)
    ln -sf "$ORIG" /usr/bin/python3 2>/dev/null || true
    rm -f /tmp/python3_orig_target.txt
else
    for v in 3.12 3.11 3.10 3.9 3.8; do
        if [ -f "/usr/bin/python${v}" ]; then
            ln -sf "/usr/bin/python${v}" /usr/bin/python3 2>/dev/null || true
            break
        fi
    done
fi

# ── Restart nginx cleanly ────────────────────────────────────────────────────
service nginx stop 2>/dev/null || true
sleep 0.3
service nginx start 2>/dev/null || nginx 2>/dev/null || true
sleep 0.5

# ── Verify nginx is up ───────────────────────────────────────────────────────
if service nginx status >/dev/null 2>&1; then
    echo "[restore] nginx: running OK"
else
    echo "[restore] WARNING: nginx failed to start after restore"
    nginx -t 2>/dev/null && nginx 2>/dev/null || true
fi

echo "[restore] done"
exit 0
