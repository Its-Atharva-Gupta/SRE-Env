# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Health scoring — multi-stage per-fault scoring."""

import os
from typing import Any, List, Optional, Tuple

from faults.registry import FaultSpec


class HealthScorer:
    """Multi-stage health scoring for faults.

    Works in both modes:
    - Local (Docker): Uses container.exec_run()
    - HF (subprocess): Uses run_check()
    """

    @staticmethod
    def score(
        container: Optional[Any] = None, fault_spec: Optional[FaultSpec] = None
    ) -> Tuple[float, List[str]]:
        """Score system health based on fault specification stages.

        Args:
            container: Docker container object with exec_run method (local mode).
                      None in HF mode.
            fault_spec: FaultSpec defining health check stages

        Returns:
            (health_score, passing_stage_names): Score from 0.0 to 1.0 and
            list of stage names that passed
        """
        if fault_spec is None:
            return 0.0, []

        total_score = 0.0
        passing_stages = []
        mode = os.getenv("SANDBOX_MODE", "local").lower()

        for stage in fault_spec.health_stages:
            try:
                if mode == "hf":
                    # HF mode: run via subprocess
                    import subprocess
                    result = subprocess.run(
                        ["bash", "-c", stage.check_cmd],
                        capture_output=True,
                        timeout=30,
                    )
                    exit_code = result.returncode
                else:
                    # Local (Docker) mode: run via container
                    if container is None:
                        continue
                    exit_code, _ = container.exec_run(stage.check_cmd)

                if exit_code == 0:
                    total_score += stage.weight
                    passing_stages.append(stage.name)
            except Exception:
                # If the check fails (timeout, network error, etc.), treat as failed
                pass

        # Clamp to [0.0, 1.0]
        total_score = max(0.0, min(1.0, total_score))

        return total_score, passing_stages
