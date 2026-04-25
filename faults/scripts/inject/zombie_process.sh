#!/bin/bash
# Inject zombie_process fault: create some zombie processes (limited fork bomb)
set -e

echo "Injecting fault: zombie_process"

# Create a few zombie processes (don't create too many to avoid system issues)
# Zombies are created by a parent process exiting without reaping child
for i in {1..5}; do
    (exit 0) &
done

sleep 1

# Verify there are zombie processes
zombie_count=$(ps aux | grep -c 'Z' || echo 0)
if [ "$zombie_count" -lt 5 ]; then
    echo "WARNING: Expected at least 5 zombie processes, found $zombie_count"
fi

echo "Fault injected: created zombie processes"
exit 0
