#!/bin/bash
# Inject broken_symlink fault: make /usr/bin/python3 a dangling symlink
set -e

echo "Injecting fault: broken_symlink"

# Remove the existing symlink/binary
rm -f /usr/bin/python3

# Create a dangling symlink pointing to non-existent path
ln -s /nonexistent/python3 /usr/bin/python3

sleep 1

# Verify symlink is broken
if [ -e /usr/bin/python3 ]; then
    echo "ERROR: /usr/bin/python3 symlink is still valid"
    exit 1
fi

if ! [ -L /usr/bin/python3 ]; then
    echo "ERROR: /usr/bin/python3 is not a symlink"
    exit 1
fi

echo "Fault injected: /usr/bin/python3 is a dangling symlink"
exit 0
