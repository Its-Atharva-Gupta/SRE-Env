"""Local sandbox — runs in same process via subprocess."""

import os
import re
import subprocess
import time
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
SRE_USER = "sre"

INTERACTIVE_COMMANDS = [
    "vim", "nano", "emacs", "less", "more", "man", "htop",
    "top", "watch", "vi", "pico", "joe",
]


class LocalSandbox:
    """Subprocess-based sandbox. No Docker, no SSH.

    Works on Kaggle, Colab, HF Spaces, and local desktop.
    Episodes reset via restore.sh + per-fault inject script.
    """

    def __init__(self):
        restore = SCRIPTS_DIR / "restore.sh"
        if not restore.exists():
            raise FileNotFoundError(
                f"restore.sh not found at {restore}. "
                "Ensure the scripts/ directory is present in the project root."
            )
        inject_dir = SCRIPTS_DIR / "inject"
        if not inject_dir.exists():
            raise FileNotFoundError(
                f"inject/ directory not found at {inject_dir}."
            )
        self.current_fault_id = None
        print(f"[LocalSandbox] initialized. Scripts dir: {SCRIPTS_DIR}")

    def reset(self, fault_id: str) -> str:
        """Restore system to healthy state, inject fault, return diagnostic output."""
        self._run_script("restore.sh", timeout=30)

        inject_path = SCRIPTS_DIR / "inject" / f"{fault_id}.sh"
        if not inject_path.exists():
            raise FileNotFoundError(
                f"No inject script for fault '{fault_id}': {inject_path}"
            )
        self._run_script(f"inject/{fault_id}.sh", timeout=15)

        self.current_fault_id = fault_id
        time.sleep(0.5)

        diag_cmd = (
            "service nginx status 2>&1 | head -5; "
            "echo '---'; "
            "df -h /; "
            "echo '---'; "
            "uptime; "
            "echo '---'; "
            "ls /var/log/nginx/ 2>&1"
        )
        output, _ = self.exec(diag_cmd)
        return output

    def exec(self, command: str, timeout: int = 10) -> tuple[str, int]:
        """Execute a shell command, return (output, exit_code)."""
        cmd_stripped = command.strip().split()[0] if command.strip() else ""
        if cmd_stripped in INTERACTIVE_COMMANDS:
            return "ERROR: interactive commands are not supported in this environment", 1

        import pwd
        try:
            pwd.getpwnam(SRE_USER)
            run_cmd = ["sudo", "-u", SRE_USER, "bash", "-c", command]
        except KeyError:
            run_cmd = ["bash", "-c", command]

        try:
            result = subprocess.run(
                run_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, "TERM": "xterm-256color"},
            )
            output = result.stdout + result.stderr
            output = self._strip_ansi(output)
            return output, result.returncode
        except subprocess.TimeoutExpired:
            return f"ERROR: command timed out after {timeout}s", 1
        except Exception as e:
            return f"ERROR: {e}", 1

    def _run_script(self, script_name: str, timeout: int = 30) -> tuple[str, int]:
        """Run a script under SCRIPTS_DIR as root."""
        script_path = SCRIPTS_DIR / script_name
        result = subprocess.run(
            ["bash", str(script_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            print(f"[LocalSandbox] Script {script_name} exited {result.returncode}:")
            print(result.stdout[-500:] if result.stdout else "")
            print(result.stderr[-500:] if result.stderr else "")
        return result.stdout + result.stderr, result.returncode

    def _strip_ansi(self, text: str) -> str:
        return re.sub(r'\x1b\[[0-9;]*[mGKHFJA-Z]', '', text)

    def run_check(self, cmd: str) -> int:
        """Run a health check command as root. Returns exit code."""
        result = subprocess.run(
            ["bash", "-c", cmd],
            capture_output=True,
            timeout=10,
        )
        return result.returncode
