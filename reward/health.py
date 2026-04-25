# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Health scoring — multi-stage per-fault scoring."""

from typing import Any, List, Tuple

from faults.registry import FaultSpec


class HealthScorer:
    """Multi-stage health scoring for faults.

    Runs each stage's check command via container.exec_run(). Accumulates
    weights of passing stages to compute a 0.0-1.0 health score.
    """

    @staticmethod
    def score(container: Any, fault_spec: FaultSpec) -> Tuple[float, List[str]]:
        """Score system health based on fault specification stages.

        Args:
            container: Docker container object with exec_run method
            fault_spec: FaultSpec defining health check stages

        Returns:
            (health_score, passing_stage_names): Score from 0.0 to 1.0 and
            list of stage names that passed
        """
        total_score = 0.0
        passing_stages = []

        for stage in fault_spec.health_stages:
            try:
                # Run the health check command
                exit_code, output = container.exec_run(stage.check_cmd)
                if exit_code == 0:
                    total_score += stage.weight
                    passing_stages.append(stage.name)
            except Exception:
                # If the check fails (timeout, network error, etc.), treat as failed
                pass

        # Clamp to [0.0, 1.0]
        total_score = max(0.0, min(1.0, total_score))

        return total_score, passing_stages
