# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Pre-warmed container pool for instant episode resets.

Uses SandboxBackend abstraction to work with both local Docker and remote managers.
"""

import queue
import threading
import time

from .backends import get_backend


class ContainersFactory:
    """Factory for getting container proxies by ID.

    Mimics the Docker client.containers interface.
    """

    def __init__(self, backend):
        """Initialize factory.

        Args:
            backend: SandboxBackend instance
        """
        self.backend = backend

    def get(self, container_id: str) -> "ContainerProxy":
        """Get a container proxy by ID.

        Args:
            container_id: Container/sandbox ID

        Returns:
            ContainerProxy that can exec commands
        """
        return ContainerProxy(container_id, self.backend)


class ClientCompat:
    """Backward-compatible Docker client replacement.

    Provides the same interface as docker.DockerClient.containers
    for use in sre_environment.py.
    """

    def __init__(self, backend):
        """Initialize compat client.

        Args:
            backend: SandboxBackend instance
        """
        self.containers = ContainersFactory(backend)


class ContainerProxy:
    """Proxy object that acts like a Docker container but uses the backend.

    This allows sre_environment.py to work unchanged with both local Docker
    and remote sandbox managers.
    """

    def __init__(self, container_id: str, backend):
        """Initialize proxy.

        Args:
            container_id: Container/sandbox ID
            backend: SandboxBackend instance
        """
        self.id = container_id
        self.backend = backend

    def exec_run(self, cmd: str, timeout: int = 10) -> tuple:
        """Execute a command (same interface as Docker container).

        Args:
            cmd: Command to execute
            timeout: Timeout in seconds

        Returns:
            (exit_code, output)
        """
        return self.backend.exec(self.id, cmd, timeout)


class ContainerPool:
    """Pre-warms Docker containers so episode reset is near-instant.

    Containers are started in background threads and stored in a queue.
    When acquire() is called, a container is popped from the queue, and
    a replacement is spawned in the background.
    """

    def __init__(self, pool_size: int = 8, image: str = "sre-sandbox:latest"):
        """Initialize container pool.

        Args:
            pool_size: Number of pre-warmed containers (default: 8)
            image: Docker image name (default: "sre-sandbox:latest")
        """
        # Initialize critical attributes first (needed by __del__ if init fails)
        self._shutdown_event = threading.Event()
        self.container_queue = queue.Queue(maxsize=pool_size)

        # Then set the rest
        self.pool_size = pool_size
        self.image = image
        self.backend = get_backend()
        self._lock = threading.Lock()

        # Pre-warm the pool in background threads
        for _ in range(pool_size):
            threading.Thread(target=self._spawn_container, daemon=True).start()

    def _spawn_container(self):
        """Spawn a single container and add to queue."""
        try:
            # Create container via backend
            container_id, ssh_host, ssh_port = self.backend.create(
                self.image,
                mem_limit="512m",
                cpu_quota=50000,  # 0.5 CPU
                network_mode="bridge",
                remove=True,
            )

            # Wrap in proxy and add to queue
            proxy = ContainerProxy(container_id, self.backend)
            self.container_queue.put((proxy, ssh_port), timeout=5)

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
            (container_proxy, ssh_port): ContainerProxy and assigned SSH port.
            ContainerProxy has the same interface as a Docker container object.

        Raises:
            queue.Empty: If pool is exhausted (shouldn't happen with daemon threads)
        """
        proxy, ssh_port = self.container_queue.get(timeout=30)

        # Spawn replacement in background
        self._refill_pool()

        return proxy, ssh_port

    def release(self, container_proxy) -> None:
        """Release a container (destroy it).

        Does NOT return to pool — the pool refills itself via background threads.

        Args:
            container_proxy: ContainerProxy to release
        """
        try:
            self.backend.destroy(container_proxy.id)
        except Exception as e:
            print(f"Error releasing container: {e}")

    def shutdown(self):
        """Shutdown pool and kill all containers."""
        if hasattr(self, '_shutdown_event'):
            self._shutdown_event.set()

        # Kill all containers currently in queue
        if hasattr(self, 'container_queue') and hasattr(self, 'backend'):
            while not self.container_queue.empty():
                try:
                    proxy, _ = self.container_queue.get_nowait()
                    try:
                        self.backend.destroy(proxy.id)
                    except Exception:
                        pass
                except queue.Empty:
                    break

    @property
    def client(self):
        """Provide backward-compatible Docker client interface.

        This is accessed by sre_environment.py which calls
        self.container_pool.client.containers.get(container_id).
        We return a compatibility wrapper that provides the same interface.
        """
        return ClientCompat(self.backend)

    def __del__(self):
        """Cleanup on garbage collection."""
        self.shutdown()
