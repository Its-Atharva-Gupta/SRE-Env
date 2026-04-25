# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Three-layer terminal verification for fault recovery."""

from typing import Any, Tuple

from faults.registry import FaultSpec


class Verifier:
    """Three-layer verification of system state recovery.

    Only runs when health_score >= 1.0. Ensures the fix is legitimate
    and the system is actually functional (not just superficially healthy).
    """

    def __init__(self, container: Any, fault_spec: FaultSpec):
        """Initialize verifier.

        Args:
            container: Docker container object with exec_run method
            fault_spec: FaultSpec with verification requirements
        """
        self.container = container
        self.fault_spec = fault_spec

    def verify(self) -> Tuple[bool, str]:
        """Run three-layer verification. Short-circuits on first failure.

        Returns:
            (verified, message): True if all checks pass, False with error reason
        """
        # Layer 1: Process state
        verified, msg = self._check_process_state()
        if not verified:
            return False, msg

        # Layer 2: Integrity (guard against degenerate fixes)
        verified, msg = self._check_integrity()
        if not verified:
            return False, msg

        # Layer 3: Functional (expensive check)
        verified, msg = self._check_functional()
        if not verified:
            return False, msg

        return True, "all checks passed"

    def _check_process_state(self) -> Tuple[bool, str]:
        """Layer 1: Verify required processes are running and ports are listening.

        Returns:
            (passed, failure_reason)
        """
        for cmd, failure_reason in self.fault_spec.process_checks:
            try:
                exit_code, _ = self.container.exec_run(cmd)
                if exit_code != 0:
                    return False, f"layer1 failed: {failure_reason}"
            except Exception as e:
                return False, f"layer1 error: {str(e)}"

        return True, "layer1 passed"

    def _check_integrity(self) -> Tuple[bool, str]:
        """Layer 2: Verify system integrity (files exist, configs valid, bad content gone).

        Guards against degenerate fixes like:
        - Deleting config files instead of fixing them
        - chmod 777 / to fix permission issues
        - Killing processes that shouldn't be killed

        Returns:
            (passed, failure_reason)
        """
        for cmd, failure_reason in self.fault_spec.integrity_checks:
            try:
                exit_code, _ = self.container.exec_run(cmd)
                if exit_code != 0:
                    return False, f"layer2 failed: {failure_reason}"
            except Exception as e:
                return False, f"layer2 error: {str(e)}"

        return True, "layer2 passed"

    def _check_functional(self) -> Tuple[bool, str]:
        """Layer 3: Functional verification (curl, write test, etc.).

        This is the most expensive check (may take 2-5 seconds).
        Only run when Verifier.verify() is called (i.e., health == 1.0).

        Returns:
            (passed, failure_reason)
        """
        check = self.fault_spec.functional_check
        cmd = check.get("cmd")
        expected_exit = check.get("expected_exit", 0)
        output_validator = check.get("output_validator")

        if not cmd or output_validator is None:
            return False, "layer3: no functional check defined"

        try:
            exit_code, output = self.container.exec_run(cmd, timeout=5)

            # Check exit code
            if exit_code != expected_exit:
                return False, f"layer3 failed: exit code {exit_code} != {expected_exit}"

            # Check output validator
            if not output_validator(output):
                return False, "layer3 failed: output validation failed"

        except TimeoutError:
            return False, "layer3 failed: timeout (curl/write took too long)"
        except Exception as e:
            return False, f"layer3 error: {str(e)}"

        return True, "layer3 passed"
