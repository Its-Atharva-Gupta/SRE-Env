# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for reward/verifier.py — Three-layer verification."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from faults.registry import FaultRegistry, Stage
from reward.verifier import Verifier


class MockContainer:
    """Mock Docker container for testing."""

    def __init__(self):
        self.commands_run = []
        self.responses = {}
        self.default_exit_code = 0
        self.default_output = "mock output"

    def exec_run(self, cmd: str, timeout: int = 10):
        """Mock exec_run that returns (exit_code, output)."""
        self.commands_run.append((cmd, timeout))
        if cmd in self.responses:
            return self.responses[cmd]
        return self.default_exit_code, self.default_output

    def set_response(self, cmd: str, exit_code: int, output: str = ""):
        """Set the response for a command."""
        self.responses[cmd] = (exit_code, output)


class TestVerifierLayer1:
    """Test Layer 1: Process state checks."""

    def test_all_process_checks_pass(self):
        """Test Layer 1 when all process checks pass."""
        container = MockContainer()
        container.default_exit_code = 0
        fault_spec = FaultRegistry.get("nginx_stopped")

        verifier = Verifier(container, fault_spec)
        passed, msg = verifier._check_process_state()
        assert passed is True
        assert "layer1 passed" in msg

    def test_first_process_check_fails(self):
        """Test Layer 1 failure when first check fails."""
        container = MockContainer()
        fault_spec = FaultRegistry.get("nginx_stopped")

        # Fail the first process check
        first_cmd, _ = fault_spec.process_checks[0]
        container.set_response(first_cmd, 1)

        verifier = Verifier(container, fault_spec)
        passed, msg = verifier._check_process_state()
        assert passed is False
        assert "layer1 failed" in msg

    def test_process_check_exception_handled(self):
        """Test Layer 1 handles exceptions gracefully."""
        container = MagicMock()
        container.exec_run.side_effect = Exception("Connection error")
        fault_spec = FaultRegistry.get("nginx_stopped")

        verifier = Verifier(container, fault_spec)
        passed, msg = verifier._check_process_state()
        assert passed is False
        assert "layer1 error" in msg


class TestVerifierLayer2:
    """Test Layer 2: Integrity checks."""

    def test_all_integrity_checks_pass(self):
        """Test Layer 2 when all integrity checks pass."""
        container = MockContainer()
        container.default_exit_code = 0
        fault_spec = FaultRegistry.get("nginx_stopped")

        verifier = Verifier(container, fault_spec)
        passed, msg = verifier._check_integrity()
        assert passed is True
        assert "layer2 passed" in msg

    def test_integrity_check_fails(self):
        """Test Layer 2 failure when integrity check fails."""
        container = MockContainer()
        fault_spec = FaultRegistry.get("nginx_stopped")

        # Fail the first integrity check
        first_cmd, _ = fault_spec.integrity_checks[0]
        container.set_response(first_cmd, 1)

        verifier = Verifier(container, fault_spec)
        passed, msg = verifier._check_integrity()
        assert passed is False
        assert "layer2 failed" in msg

    def test_integrity_check_exception_handled(self):
        """Test Layer 2 handles exceptions gracefully."""
        container = MagicMock()
        container.exec_run.side_effect = Exception("Permission denied")
        fault_spec = FaultRegistry.get("nginx_stopped")

        verifier = Verifier(container, fault_spec)
        passed, msg = verifier._check_integrity()
        assert passed is False
        assert "layer2 error" in msg


class TestVerifierLayer3:
    """Test Layer 3: Functional checks."""

    def test_functional_check_passes(self):
        """Test Layer 3 when functional check passes."""
        container = MockContainer()
        fault_spec = FaultRegistry.get("nginx_stopped")

        # Set up successful functional check response
        check_cmd = fault_spec.functional_check["cmd"]
        container.set_response(check_cmd, 0, "HTTP/1.1 200 OK")

        verifier = Verifier(container, fault_spec)
        passed, msg = verifier._check_functional()
        assert passed is True
        assert "layer3 passed" in msg

    def test_functional_check_wrong_exit_code(self):
        """Test Layer 3 failure when exit code is wrong."""
        container = MockContainer()
        fault_spec = FaultRegistry.get("nginx_stopped")

        # Set up functional check with wrong exit code
        check_cmd = fault_spec.functional_check["cmd"]
        container.set_response(check_cmd, 1, "")  # Wrong exit code

        verifier = Verifier(container, fault_spec)
        passed, msg = verifier._check_functional()
        assert passed is False
        assert "layer3 failed" in msg
        assert "exit code" in msg

    def test_functional_check_validator_fails(self):
        """Test Layer 3 failure when output validator fails."""
        container = MockContainer()
        fault_spec = FaultRegistry.get("nginx_stopped")

        # Set up functional check with output that fails validation
        check_cmd = fault_spec.functional_check["cmd"]
        container.set_response(check_cmd, 0, "")  # Empty output, validator will fail

        verifier = Verifier(container, fault_spec)
        passed, msg = verifier._check_functional()
        assert passed is False
        assert "layer3 failed" in msg
        assert "output validation" in msg

    def test_functional_check_timeout_handled(self):
        """Test Layer 3 handles timeout gracefully."""
        container = MagicMock()
        container.exec_run.side_effect = TimeoutError("Check timed out")
        fault_spec = FaultRegistry.get("nginx_stopped")

        verifier = Verifier(container, fault_spec)
        passed, msg = verifier._check_functional()
        assert passed is False
        assert "layer3 failed" in msg
        assert "timeout" in msg

    def test_functional_check_exception_handled(self):
        """Test Layer 3 handles exceptions gracefully."""
        container = MagicMock()
        container.exec_run.side_effect = Exception("curl not found")
        fault_spec = FaultRegistry.get("nginx_stopped")

        verifier = Verifier(container, fault_spec)
        passed, msg = verifier._check_functional()
        assert passed is False
        assert "layer3 error" in msg

    def test_functional_check_missing_cmd(self):
        """Test Layer 3 when functional_check has no cmd."""
        from copy import deepcopy
        container = MockContainer()
        fault_spec = deepcopy(FaultRegistry.get("nginx_stopped"))
        fault_spec.functional_check = {"cmd": None}

        verifier = Verifier(container, fault_spec)
        passed, msg = verifier._check_functional()
        assert passed is False
        assert "layer3:" in msg

    def test_functional_check_missing_validator(self):
        """Test Layer 3 when functional_check has no validator."""
        from copy import deepcopy
        container = MockContainer()
        fault_spec = deepcopy(FaultRegistry.get("nginx_stopped"))
        fault_spec.functional_check = {"cmd": "curl localhost"}

        verifier = Verifier(container, fault_spec)
        passed, msg = verifier._check_functional()
        assert passed is False
        assert "layer3:" in msg


class TestVerifierIntegration:
    """Integration tests for full verification flow."""

    def test_full_verification_passes(self):
        """Test full verification when all layers pass."""
        container = MockContainer()
        container.default_exit_code = 0
        fault_spec = FaultRegistry.get("nginx_stopped")

        # Ensure functional check passes with proper output
        check_cmd = fault_spec.functional_check["cmd"]
        container.set_response(check_cmd, 0, "200")

        verifier = Verifier(container, fault_spec)
        verified, msg = verifier.verify()
        assert verified is True
        assert "all checks passed" in msg

    def test_verification_short_circuits_on_layer1_failure(self):
        """Test that verification stops at Layer 1 failure."""
        container = MockContainer()
        fault_spec = FaultRegistry.get("nginx_stopped")

        # Fail Layer 1
        first_cmd, _ = fault_spec.process_checks[0]
        container.set_response(first_cmd, 1)

        # Set Layer 2 and 3 to pass (shouldn't be reached)
        for cmd, _ in fault_spec.integrity_checks:
            container.set_response(cmd, 0)
        container.set_response(fault_spec.functional_check["cmd"], 0, "output")

        verifier = Verifier(container, fault_spec)
        verified, msg = verifier.verify()
        assert verified is False
        assert "layer1" in msg
        # Layer 2 and 3 commands shouldn't be run due to short-circuit

    def test_verification_short_circuits_on_layer2_failure(self):
        """Test that verification stops at Layer 2 failure."""
        container = MockContainer()
        fault_spec = FaultRegistry.get("nginx_stopped")

        # Pass Layer 1
        for cmd, _ in fault_spec.process_checks:
            container.set_response(cmd, 0)

        # Fail Layer 2
        first_cmd, _ = fault_spec.integrity_checks[0]
        container.set_response(first_cmd, 1)

        # Set Layer 3 to pass (shouldn't be reached)
        container.set_response(fault_spec.functional_check["cmd"], 0, "output")

        verifier = Verifier(container, fault_spec)
        verified, msg = verifier.verify()
        assert verified is False
        assert "layer2" in msg

    def test_verification_all_faults_exist(self):
        """Test that all registered faults can be instantiated with verifiers."""
        for fault in FaultRegistry.all_faults():
            container = MockContainer()
            # Just verify that Verifier can be instantiated for each fault
            verifier = Verifier(container, fault)
            assert verifier is not None
            assert verifier.fault_spec.id == fault.id


class TestVerifierBrokenNginxConfig:
    """Tests specific to broken_nginx_config fault."""

    def test_broken_nginx_config_full_verification(self):
        """Test full verification for broken_nginx_config fault."""
        container = MockContainer()
        fault_spec = FaultRegistry.get("broken_nginx_config")

        # Pass all checks
        for cmd, _ in fault_spec.process_checks:
            container.set_response(cmd, 0)
        for cmd, _ in fault_spec.integrity_checks:
            container.set_response(cmd, 0)
        container.set_response(fault_spec.functional_check["cmd"], 0, "output")

        verifier = Verifier(container, fault_spec)
        verified, msg = verifier.verify()
        assert verified is True

    def test_broken_nginx_config_integrity_fails_on_bad_config(self):
        """Test that integrity check catches bad config still present."""
        container = MockContainer()
        fault_spec = FaultRegistry.get("broken_nginx_config")

        # Pass Layer 1
        for cmd, _ in fault_spec.process_checks:
            container.set_response(cmd, 0)

        # Fail integrity check that verifies bad config is gone
        # Find the grep check that looks for "listen BROKEN"
        for cmd, reason in fault_spec.integrity_checks:
            if "BROKEN" in cmd:
                container.set_response(cmd, 1)  # Fail: bad content still present
            else:
                container.set_response(cmd, 0)

        verifier = Verifier(container, fault_spec)
        verified, msg = verifier.verify()
        assert verified is False
        assert "layer2" in msg
