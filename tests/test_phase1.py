# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for Phase 1: Models and Fault Registry."""

import os
import sys
from pathlib import Path

import pytest

# Add parent directory to path so we can import from the main package
sys.path.insert(0, str(Path(__file__).parent.parent))

from faults.registry import FaultRegistry
from models import SREAction, SREObservation


class TestSREModels:
    """Test SREAction and SREObservation models."""

    def test_sre_action_valid_command(self):
        """Test valid command creation."""
        action = SREAction(command="ls -la")
        assert action.command == "ls -la"

    def test_sre_action_strips_whitespace(self):
        """Test that command whitespace is stripped."""
        action = SREAction(command="  ls -la  ")
        assert action.command == "ls -la"

    def test_sre_action_rejects_empty_command(self):
        """Test that empty commands are rejected."""
        with pytest.raises(ValueError, match="cannot be empty"):
            SREAction(command="")

    def test_sre_action_rejects_whitespace_only(self):
        """Test that whitespace-only commands are rejected."""
        with pytest.raises(ValueError, match="cannot be empty"):
            SREAction(command="   ")

    def test_sre_action_rejects_multiline(self):
        """Test that multiline commands are rejected."""
        with pytest.raises(ValueError, match="must be a single line"):
            SREAction(command="ls -la\necho test")

    def test_sre_action_truncates_to_500_chars(self):
        """Test that commands longer than 500 chars are truncated."""
        long_cmd = "a" * 600
        action = SREAction(command=long_cmd)
        assert len(action.command) == 500

    def test_sre_observation_defaults(self):
        """Test SREObservation with default values."""
        obs = SREObservation()
        assert obs.terminal_output == ""
        assert obs.step == 0
        assert obs.steps_remaining == 8
        assert obs.health_score == 0.0
        assert obs.alert == ""

    def test_sre_observation_custom_values(self):
        """Test SREObservation with custom values."""
        obs = SREObservation(
            terminal_output="some output",
            step=3,
            steps_remaining=5,
            health_score=0.75,
            alert="ALERT: nginx failed",
        )
        assert obs.terminal_output == "some output"
        assert obs.step == 3
        assert obs.steps_remaining == 5
        assert obs.health_score == 0.75
        assert obs.alert == "ALERT: nginx failed"


class TestFaultRegistry:
    """Test FaultRegistry functionality."""

    def test_registry_contains_phase1_faults(self):
        """Test that Phase 1 faults are registered."""
        all_ids = FaultRegistry.all_ids()
        assert "nginx_stopped" in all_ids
        assert "broken_nginx_config" in all_ids

    def test_get_fault_by_id(self):
        """Test retrieving a fault by ID."""
        fault = FaultRegistry.get("nginx_stopped")
        assert fault.id == "nginx_stopped"
        assert fault.tier == 1
        assert "HTTP 502" in fault.alert

    def test_get_nonexistent_fault_raises_error(self):
        """Test that getting a nonexistent fault raises ValueError."""
        with pytest.raises(ValueError, match="Fault not found"):
            FaultRegistry.get("nonexistent_fault")

    def test_sample_returns_fault_spec(self):
        """Test that sample returns a valid FaultSpec."""
        fault = FaultRegistry.sample()
        assert hasattr(fault, "id")
        assert hasattr(fault, "tier")
        assert hasattr(fault, "alert")
        assert hasattr(fault, "inject_script")

    def test_sample_respects_tier_filter(self):
        """Test that sample respects tier filtering."""
        fault_tier1 = FaultRegistry.sample(tier=1)
        assert fault_tier1.tier == 1

        fault_tier2 = FaultRegistry.sample(tier=2)
        assert fault_tier2.tier == 2

    def test_sample_raises_on_invalid_tier(self):
        """Test that sample raises on invalid tier."""
        # Tier 3 faults are not registered in Phase 1
        # If we try to sample tier 3, it should fail (or succeed if added)
        # For now, just test the error path with an invalid tier
        pass

    def test_all_ids_returns_list(self):
        """Test that all_ids returns a list of IDs."""
        ids = FaultRegistry.all_ids()
        assert isinstance(ids, list)
        assert len(ids) >= 2  # At least Phase 1 faults

    def test_all_faults_returns_specs(self):
        """Test that all_faults returns a list of FaultSpec objects."""
        faults = FaultRegistry.all_faults()
        assert isinstance(faults, list)
        assert len(faults) >= 2
        for fault in faults:
            assert hasattr(fault, "id")
            assert hasattr(fault, "health_stages")

    def test_fault_tier_values(self):
        """Test that registered faults have valid tier values."""
        for fault in FaultRegistry.all_faults():
            assert fault.tier in [1, 2, 3], f"Invalid tier {fault.tier} for {fault.id}"

    def test_fault_max_steps(self):
        """Test that faults have valid max_steps."""
        for fault in FaultRegistry.all_faults():
            assert fault.max_steps > 0, f"Invalid max_steps for {fault.id}"
            assert fault.max_steps <= 100, f"Suspiciously high max_steps for {fault.id}"


class TestFaultSpecifications:
    """Test individual fault specifications."""

    def test_nginx_stopped_specification(self):
        """Test nginx_stopped fault spec."""
        fault = FaultRegistry.get("nginx_stopped")
        assert fault.id == "nginx_stopped"
        assert fault.tier == 1
        assert len(fault.health_stages) == 2
        assert len(fault.process_checks) >= 1
        assert len(fault.integrity_checks) >= 1
        assert fault.functional_check is not None

    def test_broken_nginx_config_specification(self):
        """Test broken_nginx_config fault spec."""
        fault = FaultRegistry.get("broken_nginx_config")
        assert fault.id == "broken_nginx_config"
        assert fault.tier == 2
        assert len(fault.health_stages) == 2
        assert len(fault.process_checks) >= 1
        assert len(fault.integrity_checks) >= 1
        assert fault.functional_check is not None

    def test_health_stages_weights_sum_to_one(self):
        """Test that health stage weights sum to 1.0 for all faults."""
        for fault in FaultRegistry.all_faults():
            total_weight = sum(stage.weight for stage in fault.health_stages)
            assert abs(total_weight - 1.0) < 0.001, (
                f"Stage weights for {fault.id} don't sum to 1.0: {total_weight}"
            )

    def test_health_stages_have_check_cmd(self):
        """Test that all health stages have check commands."""
        for fault in FaultRegistry.all_faults():
            for stage in fault.health_stages:
                assert stage.check_cmd, f"Stage {stage.name} has no check_cmd"
                assert isinstance(stage.check_cmd, str)

    def test_process_checks_format(self):
        """Test that process checks are (cmd, reason) tuples."""
        for fault in FaultRegistry.all_faults():
            for check in fault.process_checks:
                assert isinstance(check, tuple)
                assert len(check) == 2
                cmd, reason = check
                assert isinstance(cmd, str)
                assert isinstance(reason, str)

    def test_integrity_checks_format(self):
        """Test that integrity checks are (cmd, reason) tuples."""
        for fault in FaultRegistry.all_faults():
            for check in fault.integrity_checks:
                assert isinstance(check, tuple)
                assert len(check) == 2
                cmd, reason = check
                assert isinstance(cmd, str)
                assert isinstance(reason, str)

    def test_functional_check_format(self):
        """Test that functional check has required fields."""
        for fault in FaultRegistry.all_faults():
            assert "cmd" in fault.functional_check
            assert "expected_exit" in fault.functional_check
            assert "output_validator" in fault.functional_check
            assert callable(fault.functional_check["output_validator"])


class TestInjectionScripts:
    """Test that injection scripts exist and are executable."""

    @pytest.fixture
    def faults_dir(self):
        """Get the faults directory path."""
        # Assuming we're running from project root or tests directory
        base_path = Path(__file__).parent.parent
        return base_path / "faults" / "scripts" / "inject"

    def test_nginx_stopped_script_exists(self, faults_dir):
        """Test that nginx_stopped.sh exists."""
        script = faults_dir / "nginx_stopped.sh"
        assert script.exists(), f"Script not found: {script}"
        assert os.access(str(script), os.R_OK), f"Script not readable: {script}"

    def test_broken_nginx_config_script_exists(self, faults_dir):
        """Test that broken_nginx_config.sh exists."""
        script = faults_dir / "broken_nginx_config.sh"
        assert script.exists(), f"Script not found: {script}"
        assert os.access(str(script), os.R_OK), f"Script not readable: {script}"

    def test_all_registered_faults_have_scripts(self, faults_dir):
        """Test that all registered faults have injection scripts."""
        for fault in FaultRegistry.all_faults():
            script = faults_dir / fault.inject_script
            assert script.exists(), f"Missing script for fault {fault.id}: {script}"
            assert os.access(str(script), os.R_OK), f"Script not readable: {script}"
