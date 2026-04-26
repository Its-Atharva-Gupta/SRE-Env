"""Tests for reward/verifier.py — Three-layer verification."""

import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from faults.registry import FaultRegistry
from reward.verifier import Verifier


def _mock_run(returncode: int = 0, stdout: bytes = b"mock output"):
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    return m


class TestVerifierLayer1:
    def test_all_process_checks_pass(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        with patch("reward.verifier.subprocess.run", return_value=_mock_run(0)):
            verifier = Verifier(fault_spec)
            passed, msg = verifier._check_process_state()
        assert passed is True
        assert "layer1 passed" in msg

    def test_first_process_check_fails(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        with patch("reward.verifier.subprocess.run", return_value=_mock_run(1)):
            verifier = Verifier(fault_spec)
            passed, msg = verifier._check_process_state()
        assert passed is False
        assert "layer1 failed" in msg

    def test_process_check_exception_handled(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        with patch("reward.verifier.subprocess.run", side_effect=Exception("Connection error")):
            verifier = Verifier(fault_spec)
            passed, msg = verifier._check_process_state()
        assert passed is False
        assert "layer1 error" in msg


class TestVerifierLayer2:
    def test_all_integrity_checks_pass(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        with patch("reward.verifier.subprocess.run", return_value=_mock_run(0)):
            verifier = Verifier(fault_spec)
            passed, msg = verifier._check_integrity()
        assert passed is True
        assert "layer2 passed" in msg

    def test_integrity_check_fails(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        with patch("reward.verifier.subprocess.run", return_value=_mock_run(1)):
            verifier = Verifier(fault_spec)
            passed, msg = verifier._check_integrity()
        assert passed is False
        assert "layer2 failed" in msg

    def test_integrity_check_exception_handled(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        with patch("reward.verifier.subprocess.run", side_effect=Exception("Permission denied")):
            verifier = Verifier(fault_spec)
            passed, msg = verifier._check_integrity()
        assert passed is False
        assert "layer2 error" in msg


class TestVerifierLayer3:
    def test_functional_check_passes(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        with patch("reward.verifier.subprocess.run",
                   return_value=_mock_run(0, b"HTTP/1.1 200 OK")):
            verifier = Verifier(fault_spec)
            passed, msg = verifier._check_functional()
        assert passed is True
        assert "layer3 passed" in msg

    def test_functional_check_wrong_exit_code(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        with patch("reward.verifier.subprocess.run", return_value=_mock_run(1, b"")):
            verifier = Verifier(fault_spec)
            passed, msg = verifier._check_functional()
        assert passed is False
        assert "layer3 failed" in msg
        assert "exit code" in msg

    def test_functional_check_validator_fails(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        # exit 0 but empty output — validator expects "200" or similar
        with patch("reward.verifier.subprocess.run", return_value=_mock_run(0, b"")):
            verifier = Verifier(fault_spec)
            passed, msg = verifier._check_functional()
        assert passed is False
        assert "layer3 failed" in msg
        assert "output validation" in msg

    def test_functional_check_timeout_handled(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        with patch("reward.verifier.subprocess.run",
                   side_effect=subprocess.TimeoutExpired("curl", 30)):
            verifier = Verifier(fault_spec)
            passed, msg = verifier._check_functional()
        assert passed is False
        assert "layer3 failed" in msg
        assert "timeout" in msg

    def test_functional_check_exception_handled(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        with patch("reward.verifier.subprocess.run",
                   side_effect=Exception("curl not found")):
            verifier = Verifier(fault_spec)
            passed, msg = verifier._check_functional()
        assert passed is False
        assert "layer3 error" in msg

    def test_functional_check_missing_cmd(self):
        fault_spec = deepcopy(FaultRegistry.get("nginx_stopped"))
        fault_spec.functional_check = {"cmd": None}
        verifier = Verifier(fault_spec)
        passed, msg = verifier._check_functional()
        assert passed is False
        assert "layer3:" in msg

    def test_functional_check_missing_validator(self):
        fault_spec = deepcopy(FaultRegistry.get("nginx_stopped"))
        fault_spec.functional_check = {"cmd": "curl localhost"}
        verifier = Verifier(fault_spec)
        passed, msg = verifier._check_functional()
        assert passed is False
        assert "layer3:" in msg


class TestVerifierIntegration:
    def test_full_verification_passes(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        with patch("reward.verifier.subprocess.run",
                   return_value=_mock_run(0, b"200")):
            verifier = Verifier(fault_spec)
            verified, msg = verifier.verify()
        assert verified is True
        assert "all checks passed" in msg

    def test_verification_short_circuits_on_layer1_failure(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        with patch("reward.verifier.subprocess.run", return_value=_mock_run(1)):
            verifier = Verifier(fault_spec)
            verified, msg = verifier.verify()
        assert verified is False
        assert "layer1" in msg

    def test_verification_short_circuits_on_layer2_failure(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        n_layer1 = len(fault_spec.process_checks)
        # layer1 all pass, layer2 first fails
        side_effects = [_mock_run(0)] * n_layer1 + [_mock_run(1)]
        with patch("reward.verifier.subprocess.run", side_effect=side_effects):
            verifier = Verifier(fault_spec)
            verified, msg = verifier.verify()
        assert verified is False
        assert "layer2" in msg

    def test_all_faults_can_be_instantiated(self):
        for fault in FaultRegistry.all_faults():
            verifier = Verifier(fault)
            assert verifier is not None
            assert verifier.fault_spec.id == fault.id


class TestVerifierBrokenNginxConfig:
    def test_broken_nginx_config_full_verification(self):
        fault_spec = FaultRegistry.get("broken_nginx_config")
        with patch("reward.verifier.subprocess.run",
                   return_value=_mock_run(0, b"output")):
            verifier = Verifier(fault_spec)
            verified, msg = verifier.verify()
        assert verified is True

    def test_broken_nginx_config_integrity_fails_on_bad_config(self):
        fault_spec = FaultRegistry.get("broken_nginx_config")
        n_layer1 = len(fault_spec.process_checks)
        # layer1 all pass, layer2 all fail (bad config still present)
        side_effects = [_mock_run(0)] * n_layer1 + [_mock_run(1)]
        with patch("reward.verifier.subprocess.run", side_effect=side_effects):
            verifier = Verifier(fault_spec)
            verified, msg = verifier.verify()
        assert verified is False
        assert "layer2" in msg
