# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Pre-warmed Docker container pool for instant episode resets."""

import queue
import threading
import time

import docker


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
        self.client = docker.from_env()
        self._lock = threading.Lock()

        # Pre-warm the pool in background threads
        for _ in range(pool_size):
            threading.Thread(target=self._spawn_container, daemon=True).start()

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
                        # Container is ready
                        self.container_queue.put((container, ssh_port), timeout=5)
                        return
                except Exception:
                    pass

                time.sleep(0.1)
                ready_time += 0.1

            # Timeout — kill and remove
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
            queue.Empty: If pool is exhausted (shouldn't happen with daemon threads)
        """
        container, ssh_port = self.container_queue.get(timeout=30)

        # Spawn replacement in background
        self._refill_pool()

        return container, ssh_port

    def release(self, container):
        """Release a container (kill it).

        Does NOT return to pool — the pool refills itself via background threads.
        Container is auto-removed due to remove=True in containers.run().

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
