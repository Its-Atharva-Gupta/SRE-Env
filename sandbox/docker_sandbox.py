# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Docker sandbox — runs in isolated containers with SSH (local training mode)."""

import queue
import re
import threading
import time
from pathlib import Path

import docker
import paramiko


class SSHSession:
    """SSH session wrapper using paramiko."""

    def __init__(self, host: str, port: int, user: str = "sre", password: str = "fix123"):
        """Initialize SSH session.

        Args:
            host: Target hostname/IP
            port: SSH port
            user: Username (default: "sre")
            password: Password (default: "fix123")
        """
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.client = None
        self._connect()

    def _connect(self):
        """Establish SSH connection."""
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.connect(
            hostname=self.host,
            port=self.port,
            username=self.user,
            password=self.password,
            timeout=10,
            allow_agent=False,
            look_for_keys=False,
        )

    def run(self, command: str, timeout: int = 10) -> tuple:
        """Execute a command and return output.

        Args:
            command: Shell command to execute
            timeout: Command timeout in seconds

        Returns:
            (stdout+stderr as str, exit_code as int)
        """
        try:
            stdin, stdout, stderr = self.client.exec_command(
                command, timeout=timeout
            )
            out = stdout.read().decode(errors="replace")
            err = stderr.read().decode(errors="replace")
            exit_code = stdout.channel.recv_exit_status()

            # Combine stdout and stderr
            output = out + err

            # Strip ANSI escape codes
            output = re.sub(r"\x1b\[[0-9;]*m", "", output)

            return output, exit_code
        except Exception as e:
            return str(e), 1

    def close(self):
        """Close SSH connection."""
        if self.client:
            self.client.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()


class ContainerPool:
    """Pre-warmed Docker container pool for instant episode resets."""

    def __init__(self, pool_size: int = 8, image: str = "sre-sandbox:latest"):
        """Initialize container pool.

        Args:
            pool_size: Number of pre-warmed containers (default: 8)
            image: Docker image name (default: "sre-sandbox:latest")
        """
        self._shutdown_event = threading.Event()
        self.container_queue = queue.Queue(maxsize=pool_size)
        self.pool_size = pool_size
        self.image = image
        self.client = docker.from_env()
        self._lock = threading.Lock()

        # Build the sandbox image if it doesn't already exist
        self._ensure_image()

        # Pre-warm the pool in background threads
        for _ in range(pool_size):
            threading.Thread(target=self._spawn_container, daemon=True).start()

    def _ensure_image(self) -> None:
        """Build the sandbox image from sandbox/Dockerfile if not already present."""
        try:
            self.client.images.get(self.image)
            return  # image already exists
        except docker.errors.ImageNotFound:
            pass

        # Locate Dockerfile and build context (project root, one level above sandbox/)
        sandbox_dir = Path(__file__).parent
        dockerfile = sandbox_dir / "Dockerfile"
        build_context = sandbox_dir.parent  # project root — needed for COPY faults/scripts/inject/

        if not dockerfile.exists():
            raise FileNotFoundError(
                f"sandbox/Dockerfile not found at {dockerfile}. "
                "Cannot build the sre-sandbox image automatically."
            )

        print(f"[ContainerPool] Image '{self.image}' not found — building from {dockerfile} …")
        _, logs = self.client.images.build(
            path=str(build_context),
            dockerfile=str(dockerfile),
            tag=self.image,
            rm=True,
        )
        for chunk in logs:
            line = chunk.get("stream", "").rstrip()
            if line:
                print(f"[build] {line}")
        print(f"[ContainerPool] Image '{self.image}' built successfully.")

    def _spawn_container(self):
        """Spawn a single container and add to queue."""
        try:
            # Start container
            container = self.client.containers.run(
                self.image,
                detach=True,
                tty=True,
                ports={"22/tcp": None},  # Random host port
                mem_limit="512m",
                cpu_quota=50000,  # 0.5 CPU
                network_mode="bridge",
                remove=True,
            )

            # Get assigned port
            container.reload()
            ssh_port = container.ports["22/tcp"][0]["HostPort"]

            # Wait for SSH readiness
            ready_time = 0
            while ready_time < 15:
                try:
                    exit_code, _ = container.exec_run("test -f /tmp/ready")
                    if exit_code == 0:
                        self.container_queue.put((container, ssh_port), timeout=5)
                        return
                except Exception:
                    pass

                time.sleep(0.1)
                ready_time += 0.1

            # Timeout — kill container
            container.kill()
            raise TimeoutError(f"Container {container.id[:12]} failed to become ready")

        except Exception as e:
            print(f"Failed to spawn container: {e}")
            # Try again in background
            if not self._shutdown_event.is_set():
                threading.Thread(
                    target=lambda: (time.sleep(1), self._spawn_container()),
                    daemon=True,
                ).start()

    def _refill_pool(self):
        """Spawn replacement container in background thread."""
        def _spawn_async():
            if not self._shutdown_event.is_set():
                self._spawn_container()

        threading.Thread(target=_spawn_async, daemon=True).start()

    def acquire(self) -> tuple:
        """Acquire a pre-warmed container from the pool.

        Returns:
            (container, ssh_port): Docker container object and assigned SSH port

        Raises:
            queue.Empty: If pool is exhausted
        """
        container, ssh_port = self.container_queue.get(timeout=30)

        # Spawn replacement in background
        self._refill_pool()

        return container, ssh_port

    def release(self, container):
        """Release a container (kill it).

        Does NOT return to pool — the pool refills itself via background threads.

        Args:
            container: Docker container to release
        """
        try:
            container.kill()
        except Exception as e:
            print(f"Error releasing container: {e}")

    def shutdown(self):
        """Shutdown pool and kill all containers."""
        if hasattr(self, '_shutdown_event'):
            self._shutdown_event.set()

        # Kill all containers currently in queue
        if hasattr(self, 'container_queue'):
            while not self.container_queue.empty():
                try:
                    container, _ = self.container_queue.get_nowait()
                    try:
                        container.kill()
                    except Exception:
                        pass
                except queue.Empty:
                    break

    def __del__(self):
        """Cleanup on garbage collection."""
        self.shutdown()


class DockerSandbox:
    """Sandbox running in isolated Docker containers with SSH (local mode).

    Used for training on desktop with full isolation.
    """

    def __init__(self):
        """Initialize Docker sandbox."""
        self.pool = None  # Lazy-initialized on first reset()
        self.container = None
        self.ssh_session = None

    def _ensure_pool(self):
        """Lazily initialize container pool on first use."""
        if self.pool is None:
            self.pool = ContainerPool(pool_size=8, image="sre-sandbox:latest")

    def reset(self, fault_id: str) -> tuple:
        """Reset to healthy state and inject fault.

        Args:
            fault_id: Fault identifier (e.g., "nginx_stopped")

        Returns:
            (output, ssh_port): Diagnostic output and SSH port for agent
        """
        # Lazily initialize pool on first use
        self._ensure_pool()

        # Clean up previous episode
        if self.ssh_session:
            self.ssh_session.close()

        # Acquire fresh container
        self.container, ssh_port = self.pool.acquire()

        # Inject fault (scripts live at /faults/inject/ inside the sandbox image)
        inject_cmd = f"bash /faults/inject/{fault_id}.sh"
        self.container.exec_run(inject_cmd)
        time.sleep(0.5)

        # Create SSH session (use 127.0.0.1 to avoid IPv6 resolution of "localhost")
        self.ssh_session = SSHSession(
            host="127.0.0.1", port=ssh_port, user="sre", password="fix123"
        )

        # Run diagnostic suite
        output, _ = self.exec("systemctl --failed --no-pager; df -h; uptime; whoami")

        return output, ssh_port

    def exec(self, command: str, timeout: int = 10) -> tuple:
        """Execute a command via SSH.

        Args:
            command: Shell command to run
            timeout: Timeout in seconds

        Returns:
            (stdout+stderr, exit_code)
        """
        if not self.ssh_session:
            return "Error: not connected to sandbox", 1

        return self.ssh_session.run(command, timeout)

    def release(self):
        """Release resources (called at end of episode)."""
        if self.ssh_session:
            self.ssh_session.close()
        if self.container and self.pool:
            self.pool.release(self.container)
