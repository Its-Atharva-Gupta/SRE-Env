# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""
FastAPI application for the SRE Terminal Agent Environment.

This module creates an HTTP server that exposes the SREEnvironment
over HTTP and WebSocket endpoints, compatible with OpenEnv clients.

Endpoints:
    - POST /reset: Reset the environment to a new episode
    - POST /step: Execute a shell command
    - GET /state: Get current environment state
    - GET /schema: Get action/observation schemas
    - WS /ws: WebSocket endpoint for persistent sessions

Usage:
    # Development (with auto-reload):
    uvicorn server.app:app --reload --host 0.0.0.0 --port 8000

    # Production:
    uvicorn server.app:app --host 0.0.0.0 --port 8000 --workers 4

    # Or run directly:
    python -m server.app
"""

import sys
from pathlib import Path

try:
    from openenv.core.env_server.http_server import create_app
except Exception as e:  # pragma: no cover
    raise ImportError(
        "openenv is required for the web interface. Install dependencies with 'uv sync'"
    ) from e

# Handle imports for both Docker (PYTHONPATH=/app/env) and local execution
try:
    from models import SREAction, SREObservation
    from server.SRE_Env_environment import SREEnvironment
except (ModuleNotFoundError, ImportError):
    # Try relative imports (when run as a package)
    try:
        from ..models import SREAction, SREObservation
        from .SRE_Env_environment import SREEnvironment
    except (ModuleNotFoundError, ImportError):
        # Add parent directory to path and retry
        parent_dir = str(Path(__file__).parent.parent)
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)
        from models import SREAction, SREObservation
        from server.SRE_Env_environment import SREEnvironment


# Create the app with web interface and README integration
app = create_app(
    SREEnvironment,
    SREAction,
    SREObservation,
    env_name="sre-terminal-agent",
    max_concurrent_envs=1,  # increase for more concurrent WebSocket sessions
)


def main(host: str = "0.0.0.0", port: int = 8000):
    """
    Entry point for direct execution via uv run or python -m.

    This function enables running the server without Docker:
        uv run --project . server
        uv run --project . server --port 8001
        python -m server.app

    Args:
        host: Host address to bind to (default: "0.0.0.0")
        port: Port number to listen on (default: 8000)

    For production deployments, use uvicorn directly with multiple workers:
        uvicorn server.app:app --workers 4
    """
    import uvicorn

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    main(port=args.port)
