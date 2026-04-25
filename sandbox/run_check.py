# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Shared utility for running health checks in both local (Docker) and HF modes."""

import os
import subprocess


def run_check(cmd: str) -> int:
    """Run a health check command.

    In HF mode: runs directly via subprocess (we are inside the container).
    In local mode: this is called only for HF mode checks.

    Args:
        cmd: Bash command to run

    Returns:
        Exit code (0 = success, non-zero = failure)
    """
    mode = os.getenv("SANDBOX_MODE", "local").lower()

    if mode == "hf":
        # HF mode: run directly
        result = subprocess.run(
            ["bash", "-c", cmd],
            capture_output=True,
            timeout=30,
        )
        return result.returncode
    else:
        raise RuntimeError(
            "In local (Docker) mode, use container.exec_run() directly. "
            "Do not use run_check()."
        )
