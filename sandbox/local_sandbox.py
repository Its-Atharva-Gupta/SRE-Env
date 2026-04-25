# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Local sandbox — runs in same container via subprocess (HF Spaces mode)."""

import re
import subprocess
import time


class LocalSandbox:
    """Sandbox running as subprocess in same container (HF mode).

    No Docker, no SSH. Episodes reset via restore script.
    Used when deployed to HF Spaces.
    """

    def reset(self, fault_id: str) -> str:
        """Reset to healthy state and inject fault.

        Args:
            fault_id: Fault identifier (e.g., "nginx_stopped")

        Returns:
            Diagnostic output (systemctl, df, uptime, whoami)
        """
        # Restore healthy state
        subprocess.run(
            ["bash", "/sre_env/scripts/restore.sh"],
            capture_output=True,
            timeout=30,
            check=False,
        )
        time.sleep(0.5)

        # Inject fault
        subprocess.run(
            ["bash", f"/sre_env/scripts/inject/{fault_id}.sh"],
            capture_output=True,
            timeout=30,
            check=False,
        )
        time.sleep(0.5)

        # Run diagnostic suite
        output, _ = self.exec(
            "systemctl --failed --no-pager; df -h; uptime; whoami"
        )
        return output

    def exec(self, command: str, timeout: int = 10) -> tuple:
        """Execute a command as sre user.

        Args:
            command: Shell command to run
            timeout: Timeout in seconds

        Returns:
            (stdout+stderr, exit_code)
        """
        # Block interactive commands
        interactive = ["vim", "nano", "emacs", "less", "more", "man"]
        if any(cmd in command for cmd in interactive):
            return ("interactive commands not supported", 1)

        try:
            result = subprocess.run(
                ["sudo", "-u", "sre", "bash", "-c", command],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            output = result.stdout + result.stderr

            # Strip ANSI escape codes
            output = re.sub(r"\x1b\[[0-9;]*m", "", output)

            return output, result.returncode

        except subprocess.TimeoutExpired:
            return "command timed out", 1
