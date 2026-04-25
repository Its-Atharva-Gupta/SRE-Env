#!/bin/bash
# Inject disk_full fault: fill /var/log with dummy file
set -e

echo "Injecting fault: disk_full"

# Create 900MB dummy file in /var/log to fill the disk
fallocate -l 900M /var/log/dummy.img 2>/dev/null || \
    dd if=/dev/zero of=/var/log/dummy.img bs=1M count=900

sleep 1

# Verify disk is nearly full
usage=$(df /var/log | awk 'NR==2 {print $5}' | sed 's/%//')
if [ "$usage" -lt 80 ]; then
    echo "ERROR: /var/log not full enough (usage: $usage%)"
    exit 1
fi

echo "Fault injected: /var/log is nearly full (${usage}%)"
exit 0
