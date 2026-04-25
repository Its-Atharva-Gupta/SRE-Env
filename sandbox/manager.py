# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""
Sandbox Manager — Remote Docker API server.

Runs on the machine with Docker access. Exposes REST endpoints to create/exec/destroy
sandboxes. Used by HF Spaces (or other remote environments) that can't access Docker directly.

Start with: uvicorn sandbox.manager:app --host 0.0.0.0 --port 9000
"""

import os
import time
import logging
from typing import Optional

import docker
from docker.errors import NotFound, ContainerError
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

app = FastAPI(title="SRE Sandbox Manager")
client = docker.from_env()

# Track spawned containers for cleanup
_active_containers = {}


class CreateSandboxRequest(BaseModel):
    """Request to create a sandbox."""
    image: str
    mem_limit: str = "512m"
    cpu_quota: int = 50000
    network_mode: str = "bridge"
    remove: bool = True


class CreateSandboxResponse(BaseModel):
    """Response with sandbox details."""
    sandbox_id: str
    ssh_host: str
    ssh_port: int


class ExecRequest(BaseModel):
    """Request to execute command in sandbox."""
    command: str
    timeout: int = 10


class ExecResponse(BaseModel):
    """Response with command output."""
    exit_code: int
    output: str


@app.post("/sandbox/create", response_model=CreateSandboxResponse)
async def create_sandbox(req: CreateSandboxRequest):
    """Create a new sandbox container.

    Starts a container and waits for SSH readiness.

    Args:
        req: CreateSandboxRequest with image and resource limits

    Returns:
        CreateSandboxResponse with sandbox_id and SSH connection details

    Raises:
        HTTPException: If container creation or SSH readiness check fails
    """
    try:
        # Start container
        container = client.containers.run(
            req.image,
            detach=True,
            tty=True,
            ports={"22/tcp": None},  # Random host port
            mem_limit=req.mem_limit,
            cpu_quota=req.cpu_quota,
            network_mode=req.network_mode,
            remove=req.remove,
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
                    _active_containers[container.id] = container
                    return CreateSandboxResponse(
                        sandbox_id=container.id,
                        ssh_host="localhost",
                        ssh_port=ssh_port,
                    )
            except Exception:
                pass

            time.sleep(0.1)
            ready_time += 0.1

        # Timeout — kill container
        container.kill()
        raise TimeoutError(f"Container {container.id[:12]} failed to become ready")

    except Exception as e:
        logger.error(f"Failed to create sandbox: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/sandbox/{sandbox_id}/exec", response_model=ExecResponse)
async def exec_command(sandbox_id: str, req: ExecRequest):
    """Execute a command in a sandbox.

    Args:
        sandbox_id: Container ID
        req: ExecRequest with command and timeout

    Returns:
        ExecResponse with exit code and output

    Raises:
        HTTPException: If container not found or command execution fails
    """
    try:
        container = client.containers.get(sandbox_id)
        exit_code, output = container.exec_run(req.command)

        # Decode output if bytes
        if isinstance(output, bytes):
            output = output.decode(errors="replace")

        return ExecResponse(exit_code=exit_code, output=output)

    except NotFound:
        raise HTTPException(status_code=404, detail=f"Sandbox {sandbox_id} not found")
    except Exception as e:
        logger.error(f"Failed to execute command in {sandbox_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/sandbox/{sandbox_id}")
async def destroy_sandbox(sandbox_id: str):
    """Destroy a sandbox container.

    Args:
        sandbox_id: Container ID

    Raises:
        HTTPException: If container not found
    """
    try:
        container = client.containers.get(sandbox_id)
        container.kill()
        _active_containers.pop(sandbox_id, None)
        return {"status": "destroyed"}

    except NotFound:
        _active_containers.pop(sandbox_id, None)
        return {"status": "not_found"}
    except Exception as e:
        logger.error(f"Failed to destroy sandbox {sandbox_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    try:
        client.ping()
        return {"status": "healthy", "active_containers": len(_active_containers)}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail=str(e))


@app.on_event("shutdown")
async def cleanup():
    """Clean up all active containers on shutdown."""
    for container_id, container in _active_containers.items():
        try:
            container.kill()
            logger.info(f"Killed container {container_id[:12]}")
        except Exception as e:
            logger.warning(f"Failed to kill container {container_id[:12]}: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9000)
