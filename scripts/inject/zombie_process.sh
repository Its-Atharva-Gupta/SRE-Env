#!/bin/bash
set -e
echo "[inject] creating zombie processes"
# Spawn a small C program via shell that leaves zombie children
python3 -c "
import os, time
for _ in range(5):
    pid = os.fork()
    if pid == 0:
        os._exit(0)
# Parent stays alive briefly, orphaning the children as zombies
time.sleep(10)
" &
echo $! > /tmp/zombie.pid
echo "[inject] zombie_process done"
