# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""
Sandbox backends — abstractions over Docker and remote managers.

Provides two implementations:
- LocalDockerBackend: Direct Docker access (desktop/VPS)
- SandboxManagerClient: HTTP client to remote manager (HF Spaces)

Both implement the same SandboxBackend interface.
"""

import re
import time
from abc import ABC, abstractmethod
from typing import Tuple

import docker
import requests


class SandboxBackend(ABC):
    """Abstract base for sandbox backends."""

    @abstractmethod
    def create(self, image: str, **kwargs) -> Tuple[str, str, int]:
        """Create a sandbox.

        Returns:
            (sandbox_id, ssh_host, ssh_port)
        """
        pass

    @abstractmethod
    def exec(self, sandbox_id: str, cmd: str, timeout: int = 10) -> Tuple[int, str]:
        """Execute a command in a sandbox.

        Returns:
            (exit_code, output)
        """
        pass

    @abstractmethod
    def destroy(self, sandbox_id: str) -> None:
        """Destroy a sandbox."""
        pass


class LocalDockerBackend(SandboxBackend):
    """Direct Docker backend for local development."""

    def __init__(self):
        """Initialize with Docker client."""
        self.client = docker.from_env()

    def create(self, image: str, **kwargs) -> Tuple[str, str, int]:
        """Create a sandbox container.

        Args:
            image: Docker image name
            **kwargs: Container run options (mem_limit, cpu_quota, etc.)

        Returns:
            (container_id, ssh_host, ssh_port)
        """
        # Start container
        container = self.client.containers.run(
            image,
            detach=True,
            tty=True,
            ports={"22/tcp": None},
            **kwargs,
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
                    return container.id, "localhost", ssh_port
            except Exception:
                pass

            time.sleep(0.1)
            ready_time += 0.1

        # Timeout — kill and remove
        container.kill()
        raise TimeoutError(f"Container {container.id[:12]} failed to become ready")

    def exec(self, sandbox_id: str, cmd: str, timeout: int = 10) -> Tuple[int, str]:
        """Execute a command in a sandbox.

        Args:
            sandbox_id: Container ID
            cmd: Command to execute
            timeout: Timeout in seconds (not directly used by Docker SDK)

        Returns:
            (exit_code, output)
        """
        container = self.client.containers.get(sandbox_id)
        exit_code, output = container.exec_run(cmd)

        # Decode if bytes
        if isinstance(output, bytes):
            output = output.decode(errors="replace")

        # Strip ANSI codes
        output = re.sub(r"\x1b\[[0-9;]*m", "", output)

        return exit_code, output

    def destroy(self, sandbox_id: str) -> None:
        """Destroy a sandbox.

        Args:
            sandbox_id: Container ID
        """
        try:
            container = self.client.containers.get(sandbox_id)
            container.kill()
        except Exception:
            pass  # Already gone or not found


class SandboxManagerClient(SandboxBackend):
    """HTTP client to remote sandbox manager."""

    def __init__(self, manager_url: str):
        """Initialize with remote manager URL.

        Args:
            manager_url: Base URL of sandbox manager (e.g., http://localhost:9000)
        """
        self.manager_url = manager_url.rstrip("/")
        self._verify_connection()

    def _verify_connection(self) -> None:
        """Verify connection to manager."""
        try:
            response = requests.get(f"{self.manager_url}/health", timeout=5)
            response.raise_for_status()
        except Exception as e:
            raise RuntimeError(
                f"Cannot reach sandbox manager at {self.manager_url}: {e}"
            )

    def create(self, image: str, **kwargs) -> Tuple[str, str, int]:
        """Create a sandbox via remote manager.

        Args:
            image: Docker image name
            **kwargs: Container run options (mem_limit, cpu_quota, etc.)

        Returns:
            (sandbox_id, ssh_host, ssh_port)
        """
        payload = {"image": image, **kwargs}
        response = requests.post(
            f"{self.manager_url}/sandbox/create",
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return data["sandbox_id"], data["ssh_host"], data["ssh_port"]

    def exec(self, sandbox_id: str, cmd: str, timeout: int = 10) -> Tuple[int, str]:
        """Execute a command in a sandbox via remote manager.

        Args:
            sandbox_id: Sandbox ID
            cmd: Command to execute
            timeout: Timeout in seconds

        Returns:
            (exit_code, output)
        """
        payload = {"command": cmd, "timeout": timeout}
        response = requests.post(
            f"{self.manager_url}/sandbox/{sandbox_id}/exec",
            json=payload,
            timeout=timeout + 5,
        )
        response.raise_for_status()
        data = response.json()
        return data["exit_code"], data["output"]

    def destroy(self, sandbox_id: str) -> None:
        """Destroy a sandbox via remote manager.

        Args:
            sandbox_id: Sandbox ID
        """
        try:
            requests.delete(
                f"{self.manager_url}/sandbox/{sandbox_id}",
                timeout=10,
            ).raise_for_status()
        except Exception:
            pass  # Best effort


def get_backend() -> SandboxBackend:
    """Get the configured sandbox backend.

    Returns:
        SandboxBackend instance (local or remote)

    Reads SANDBOX_MODE env var:
    - "local" (default): Use Docker directly
    - "remote": Use remote manager via HTTP
    """
    import os

    mode = os.getenv("SANDBOX_MODE", "local").lower()

    if mode == "remote":
        manager_url = os.getenv("SANDBOX_MANAGER_URL", "http://localhost:9000")
        return SandboxManagerClient(manager_url)
    else:
        return LocalDockerBackend()
