#!/bin/bash
# Exhaustively restore to healthy state — undo all possible faults

set -e

# Kill any lingering processes that might interfere
pkill -f "fill.log" 2>/dev/null || true
pkill -f "zombie" 2>/dev/null || true

# Restore nginx config
cp /etc/nginx/nginx.conf.bak /etc/nginx/nginx.conf 2>/dev/null || true
cp /etc/nginx/sites-enabled/default.bak /etc/nginx/sites-enabled/default 2>/dev/null || true

# Fix permissions
chmod 755 /var/log/nginx/ 2>/dev/null || true
chown -R www-data:www-data /var/log/nginx/ 2>/dev/null || true

# Clean up disk space (covers both inject script filenames)
find /var/log/ -name "fill.log" -delete 2>/dev/null || true
find /var/log/ -name "dummy.img" -delete 2>/dev/null || true
find /tmp/ -name "test_write.bin" -delete 2>/dev/null || true

# Fix symlinks
ln -sf /usr/bin/python3.10 /usr/bin/python3 2>/dev/null || true

# Kill lingering processes from restarts
kill $(cat /tmp/zombie.pid 2>/dev/null) 2>/dev/null || true
rm -f /tmp/zombie.pid 2>/dev/null || true

# Clear bad cron entries
(crontab -r 2>/dev/null || true)

# Restart services cleanly
systemctl restart nginx 2>/dev/null || true
systemctl restart ssh 2>/dev/null || true

# Give services time to start
sleep 1

# Signal readiness
touch /tmp/ready
