"""
Reward validation runner — execute before any LLM training.

Decision tree (from README):
  components → sanity → variance

Exit 0 only when all three pass.
Run as: python tests/reward/run_all.py
"""
import queue
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

SANDBOX_IMAGE = "sre-sandbox:latest"
POOL_SIZE = 4
SSH_USER = "sre"
SSH_PASSWORD = "fix123"
SSH_TIMEOUT = 10
READY_TIMEOUT = 15


# ---------------------------------------------------------------------------
# Docker infrastructure (self-contained — used by the integration sub-tests)
# ---------------------------------------------------------------------------

class SSHSession:
    def __init__(self, host: str, port: int):
        import paramiko
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.connect(
            host,
            port=port,
            username=SSH_USER,
            password=SSH_PASSWORD,
            timeout=SSH_TIMEOUT,
            look_for_keys=False,
            allow_agent=False,
        )

    def run(self, command: str, timeout: int = 10) -> tuple[str, int]:
        stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout)
        out = stdout.read().decode(errors="replace")
        err = stderr.read().decode(errors="replace")
        exit_code = stdout.channel.recv_exit_status()
        combined = out + err
        combined = re.sub(r'\x1b\[[0-9;]*[mGKHF]', '', combined)
        return combined, exit_code

    def close(self):
        try:
            self.client.close()
        except Exception:
            pass


def _wait_for_tcp(host: str, port: int, timeout: int = 15) -> bool:
    """Poll until a TCP connection succeeds or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except (ConnectionRefusedError, OSError):
            time.sleep(0.2)
    return False


def _spawn_container(client) -> tuple:
    """Spin up one sandbox container and wait for SSH readiness."""
    container = client.containers.run(
        SANDBOX_IMAGE,
        detach=True,
        tty=True,
        publish_all_ports=True,
        mem_limit="512m",
        cpu_quota=50000,
        remove=True,
    )

    time.sleep(0.5)
    container.reload()

    if not container.ports.get("22/tcp"):
        time.sleep(0.5)
        container.reload()

    port_bindings = container.ports.get("22/tcp")
    if not port_bindings:
        container.kill()
        raise RuntimeError(
            f"Container started but 22/tcp not published. "
            f"All ports: {container.ports}"
        )

    ssh_port = int(port_bindings[0]["HostPort"])

    deadline = time.time() + READY_TIMEOUT
    ready = False
    while time.time() < deadline:
        result = container.exec_run("test -f /tmp/ready")
        if result.exit_code == 0:
            ready = True
            break
        time.sleep(0.1)

    if not ready:
        container.kill()
        raise RuntimeError("Container never became ready (/tmp/ready not found)")

    if not _wait_for_tcp("127.0.0.1", ssh_port, timeout=10):
        container.kill()
        raise RuntimeError(f"SSH port {ssh_port} never accepted connections")

    return container, ssh_port


class ContainerPool:
    def __init__(self, size: int = POOL_SIZE):
        self.size = size
        self._client = __import__("docker").from_env()
        self._queue: queue.Queue = queue.Queue()
        self._lock = threading.Lock()

        print(f"[ContainerPool] Pre-warming {size} containers...")
        threads = [
            threading.Thread(target=self._fill_one, daemon=True)
            for _ in range(size)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        print(f"[ContainerPool] Ready with {self._queue.qsize()} containers.")

    def _fill_one(self):
        try:
            container, port = _spawn_container(self._client)
            self._queue.put((container, port))
        except Exception as e:
            print(f"[ContainerPool] Failed to spawn container: {e}")

    def acquire(self) -> tuple:
        container, port = self._queue.get(timeout=30)
        threading.Thread(target=self._fill_one, daemon=True).start()
        return container, port

    def release(self, container):
        try:
            container.kill()
        except Exception:
            pass

    def shutdown(self):
        while not self._queue.empty():
            try:
                container, _ = self._queue.get_nowait()
                container.kill()
            except Exception:
                pass


class DockerSandbox:
    def __init__(self):
        self._check_image()
        self._pool = ContainerPool(size=POOL_SIZE)
        self._container = None
        self._ssh: SSHSession | None = None
        self._ssh_port: int | None = None

    @property
    def container(self):
        """Raw Docker container for the reward engine (local mode)."""
        return self._container

    def _check_image(self):
        result = subprocess.run(
            ["docker", "image", "inspect", SANDBOX_IMAGE],
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Image '{SANDBOX_IMAGE}' not found. Build it first:\n"
                f"  docker build -f sandbox/Dockerfile -t {SANDBOX_IMAGE} ."
            )

    def reset(self, fault_id: str) -> str:
        if self._container is not None:
            self._release_current()

        self._container, self._ssh_port = self._pool.acquire()

        result = self._container.exec_run(
            f"/bin/bash /faults/inject/{fault_id}.sh"
        )
        if result.exit_code != 0:
            output = result.output.decode(errors="replace")
            raise RuntimeError(f"Fault injection failed for '{fault_id}': {output}")

        self._ssh = SSHSession("127.0.0.1", self._ssh_port)

        diag_cmd = "systemctl --failed --no-pager; df -h; uptime"
        output, _ = self._ssh.run(diag_cmd)
        return output

    def exec(self, command: str, timeout: int = 10) -> tuple[str, int]:
        INTERACTIVE = ["vim", "nano", "emacs", "less", "more", "man", "htop", "top"]
        if any(re.search(rf"\b{i}\b", command) for i in INTERACTIVE):
            return "interactive commands are not supported", 1

        if self._ssh is None:
            return "no active session — call reset() first", 1

        try:
            return self._ssh.run(command, timeout=timeout)
        except Exception as e:
            return f"command error: {e}", 1

    def _release_current(self):
        if self._ssh:
            self._ssh.close()
            self._ssh = None
        if self._container:
            self._pool.release(self._container)
            self._container = None
        self._ssh_port = None

    def close(self):
        self._release_current()
        self._pool.shutdown()


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

_TESTS_DIR = Path(__file__).parent


def _run_components() -> bool:
    """Run pure-function unit tests via pytest (no Docker needed)."""
    print("\n" + "=" * 60)
    print("STEP 1/3 — component unit tests (pytest)")
    print("=" * 60)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(_TESTS_DIR / "test_reward_components.py"), "-v"],
        cwd=str(PROJECT_ROOT),
    )
    return result.returncode == 0


def _run_sanity() -> bool:
    """Run policy-ordering sanity test."""
    print("\n" + "=" * 60)
    print("STEP 2/3 — policy ordering sanity check")
    print("=" * 60)
    # Import here so sys.path is already set up
    from tests.reward.test_reward_sanity import main as sanity_main
    return sanity_main() == 0


def _run_variance() -> bool:
    """Run reward variance check (GRPO signal strength)."""
    print("\n" + "=" * 60)
    print("STEP 3/3 — reward variance check (GRPO signal)")
    print("=" * 60)
    from tests.reward.test_reward_variance import main as variance_main
    return variance_main() == 0


def main() -> int:
    results: dict[str, bool] = {}

    results["components"] = _run_components()
    if not results["components"]:
        print("\nFAIL — component tests failed. Fix reward/components.py before proceeding.")
        return 1

    results["sanity"] = _run_sanity()
    if not results["sanity"]:
        print("\nFAIL — sanity check failed. Policy ordering is broken.")
        print("Compare per-step rewards to isolate which component is mis-shaped.")
        return 1

    results["variance"] = _run_variance()
    if not results["variance"]:
        print("\nFAIL — variance too low. GRPO relative-advantage signal will collapse.")
        print("Tune health-stage weights, action-quality bonuses, or terminal_reward scale.")
        return 1

    print("\n" + "=" * 60)
    print("ALL CHECKS PASSED — reward function is correctly shaped.")
    print("Safe to begin training.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
