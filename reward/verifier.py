"""Three-layer terminal verification for fault recovery."""

import subprocess
from typing import Tuple

from faults.registry import FaultSpec


class Verifier:
    """Three-layer verification of system state recovery.

    Only runs when health_score >= 1.0. Uses subprocess directly.
    """

    def __init__(self, fault_spec: FaultSpec):
        self.fault_spec = fault_spec

    def verify(self) -> Tuple[bool, str]:
        """Run three-layer verification. Short-circuits on first failure."""
        verified, msg = self._check_process_state()
        if not verified:
            return False, msg

        verified, msg = self._check_integrity()
        if not verified:
            return False, msg

        verified, msg = self._check_functional()
        if not verified:
            return False, msg

        return True, "all checks passed"

    def _check_process_state(self) -> Tuple[bool, str]:
        for cmd, failure_reason in self.fault_spec.process_checks:
            try:
                result = subprocess.run(
                    ["bash", "-c", cmd],
                    capture_output=True,
                    timeout=10,
                )
                if result.returncode != 0:
                    return False, f"layer1 failed: {failure_reason}"
            except Exception as e:
                return False, f"layer1 error: {str(e)}"
        return True, "layer1 passed"

    def _check_integrity(self) -> Tuple[bool, str]:
        for cmd, failure_reason in self.fault_spec.integrity_checks:
            try:
                result = subprocess.run(
                    ["bash", "-c", cmd],
                    capture_output=True,
                    timeout=10,
                )
                if result.returncode != 0:
                    return False, f"layer2 failed: {failure_reason}"
            except Exception as e:
                return False, f"layer2 error: {str(e)}"
        return True, "layer2 passed"

    def _check_functional(self) -> Tuple[bool, str]:
        check = self.fault_spec.functional_check
        cmd = check.get("cmd")
        expected_exit = check.get("expected_exit", 0)
        output_validator = check.get("output_validator")

        if not cmd or output_validator is None:
            return False, "layer3: no functional check defined"

        try:
            result = subprocess.run(
                ["bash", "-c", cmd],
                capture_output=True,
                timeout=30,
            )
            exit_code = result.returncode
            output = result.stdout.decode(errors="replace")

            if exit_code != expected_exit:
                return False, f"layer3 failed: exit code {exit_code} != {expected_exit}"

            if not output_validator(output):
                return False, "layer3 failed: output validation failed"

        except subprocess.TimeoutExpired:
            return False, "layer3 failed: timeout (curl/write took too long)"
        except Exception as e:
            return False, f"layer3 error: {str(e)}"

        return True, "layer3 passed"
