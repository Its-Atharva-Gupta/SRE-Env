"""Health scoring — multi-stage per-fault scoring."""

import subprocess
from typing import List, Optional, Tuple

from faults.registry import FaultSpec


class HealthScorer:
    """Multi-stage health scoring for faults. Uses subprocess directly."""

    @staticmethod
    def score(fault_spec: Optional[FaultSpec] = None) -> Tuple[float, List[str]]:
        """Score system health based on fault specification stages.

        Args:
            fault_spec: FaultSpec defining health check stages

        Returns:
            (health_score, passing_stage_names): Score 0.0–1.0 and passing stage names
        """
        if fault_spec is None:
            return 0.0, []

        total_score = 0.0
        passing_stages = []

        for stage in fault_spec.health_stages:
            try:
                result = subprocess.run(
                    ["bash", "-c", stage.check_cmd],
                    capture_output=True,
                    timeout=10,
                )
                exit_code = result.returncode
                if exit_code == 0:
                    total_score += stage.weight
                    passing_stages.append(stage.name)
            except Exception:
                pass

        total_score = max(0.0, min(1.0, total_score))
        return total_score, passing_stages
