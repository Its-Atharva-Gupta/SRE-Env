# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Sandbox: dual-mode sandbox system for local (Docker) and HF Spaces (subprocess) deployment."""

import os


def get_sandbox():
    """Factory function to get the appropriate sandbox for the environment.

    Returns:
        LocalSandbox (SANDBOX_MODE=hf) — subprocess-based, no Docker/SSH
        DockerSandbox (SANDBOX_MODE=local, default) — Docker containers with SSH

    Environment Variable:
        SANDBOX_MODE — "local" (default) or "hf"
    """
    mode = os.getenv("SANDBOX_MODE", "local").lower()

    if mode == "hf":
        from .local_sandbox import LocalSandbox
        return LocalSandbox()
    else:
        from .docker_sandbox import DockerSandbox
        return DockerSandbox()


__all__ = ["get_sandbox"]
