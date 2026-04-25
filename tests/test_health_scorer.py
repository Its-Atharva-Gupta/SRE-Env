# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for reward/health.py — HealthScorer."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from faults.registry import FaultRegistry, Stage
from reward.health import HealthScorer


class MockContainer:
    """Mock Docker container for testing."""

    def __init__(self):
        self.commands_run = []
        self.responses = {}

    def exec_run(self, cmd: str):
        """Mock exec_run that returns (exit_code, output)."""
        self.commands_run.append(cmd)
        if cmd in self.responses:
            return self.responses[cmd]
        return 0, ""

    def set_response(self, cmd: str, exit_code: int, output: str = ""):
        """Set the response for a command."""
        self.responses[cmd] = (exit_code, output)


class TestHealthScorer:
    """Test HealthScorer class."""

    def test_all_stages_passing(self):
        """Test scoring when all stages pass."""
        container = MockContainer()
        fault_spec = FaultRegistry.get("nginx_stopped")

        # Set all checks to pass (exit code 0)
        for stage in fault_spec.health_stages:
            container.set_response(stage.check_cmd, 0)

        score, passing = HealthScorer.score(container, fault_spec)
        assert score == 1.0
        assert len(passing) == len(fault_spec.health_stages)

    def test_all_stages_failing(self):
        """Test scoring when all stages fail."""
        container = MockContainer()
        fault_spec = FaultRegistry.get("nginx_stopped")

        # Set all checks to fail (exit code 1)
        for stage in fault_spec.health_stages:
            container.set_response(stage.check_cmd, 1)

        score, passing = HealthScorer.score(container, fault_spec)
        assert score == 0.0
        assert len(passing) == 0

    def test_partial_stages_passing(self):
        """Test scoring with some stages passing."""
        container = MockContainer()
        fault_spec = FaultRegistry.get("nginx_stopped")

        # Pass first stage, fail second
        stages = fault_spec.health_stages
        container.set_response(stages[0].check_cmd, 0)  # Pass
        container.set_response(stages[1].check_cmd, 1)  # Fail

        score, passing = HealthScorer.score(container, fault_spec)
        expected_score = stages[0].weight
        assert abs(score - expected_score) < 1e-6
        assert len(passing) == 1
        assert passing[0] == stages[0].name

    def test_stages_weights_sum_correctly(self):
        """Test that stage weights sum to total score."""
        container = MockContainer()
        fault_spec = FaultRegistry.get("nginx_stopped")

        # Pass all stages
        for stage in fault_spec.health_stages:
            container.set_response(stage.check_cmd, 0)

        score, _ = HealthScorer.score(container, fault_spec)
        total_weight = sum(s.weight for s in fault_spec.health_stages)
        assert abs(score - total_weight) < 1e-6

    def test_score_clamped_to_zero(self):
        """Test that score is clamped to minimum 0.0."""
        container = MockContainer()
        fault_spec = FaultRegistry.get("nginx_stopped")

        # Fail all checks
        for stage in fault_spec.health_stages:
            container.set_response(stage.check_cmd, 1)

        score, _ = HealthScorer.score(container, fault_spec)
        assert score >= 0.0

    def test_score_clamped_to_one(self):
        """Test that score is clamped to maximum 1.0."""
        container = MockContainer()
        fault_spec = FaultRegistry.get("nginx_stopped")

        # Pass all checks
        for stage in fault_spec.health_stages:
            container.set_response(stage.check_cmd, 0)

        score, _ = HealthScorer.score(container, fault_spec)
        assert score <= 1.0

    def test_broken_nginx_config_scoring(self):
        """Test scoring for broken_nginx_config fault."""
        container = MockContainer()
        fault_spec = FaultRegistry.get("broken_nginx_config")

        # Pass nginx_syntax_valid, fail nginx_running
        stages = fault_spec.health_stages
        container.set_response(stages[0].check_cmd, 0)  # nginx_syntax_valid pass
        container.set_response(stages[1].check_cmd, 1)  # nginx_running fail

        score, passing = HealthScorer.score(container, fault_spec)
        expected_score = stages[0].weight  # 0.6
        assert abs(score - expected_score) < 1e-6
        assert passing == [stages[0].name]

    def test_exception_in_exec_run_treated_as_failure(self):
        """Test that exceptions during exec_run are treated as stage failures."""
        container = MagicMock()
        fault_spec = FaultRegistry.get("nginx_stopped")

        # Make exec_run raise an exception
        container.exec_run.side_effect = Exception("Container error")

        score, passing = HealthScorer.score(container, fault_spec)
        assert score == 0.0
        assert len(passing) == 0

    def test_passing_stages_list_correct(self):
        """Test that passing_stages list contains correct stage names."""
        container = MockContainer()
        fault_spec = FaultRegistry.get("nginx_stopped")

        # Pass first stage only
        container.set_response(fault_spec.health_stages[0].check_cmd, 0)
        container.set_response(fault_spec.health_stages[1].check_cmd, 1)

        _, passing = HealthScorer.score(container, fault_spec)
        assert len(passing) == 1
        assert passing[0] == fault_spec.health_stages[0].name

    def test_all_faults_scorable(self):
        """Test that all registered faults can be scored."""
        container = MockContainer()

        for fault in FaultRegistry.all_faults():
            # Set all checks to pass
            for stage in fault.health_stages:
                container.set_response(stage.check_cmd, 0)

            score, passing = HealthScorer.score(container, fault)
            assert 0.0 <= score <= 1.0
            assert len(passing) == len(fault.health_stages)

    def test_non_zero_exit_code_is_failure(self):
        """Test that non-zero exit codes are treated as failures."""
        container = MockContainer()
        fault_spec = FaultRegistry.get("nginx_stopped")

        # Set different non-zero exit codes
        container.set_response(fault_spec.health_stages[0].check_cmd, 1)
        container.set_response(fault_spec.health_stages[1].check_cmd, 127)

        score, passing = HealthScorer.score(container, fault_spec)
        assert score == 0.0
        assert len(passing) == 0

    def test_only_zero_exit_code_is_success(self):
        """Test that only exit code 0 counts as success."""
        container = MockContainer()
        fault_spec = FaultRegistry.get("nginx_stopped")

        stage = fault_spec.health_stages[0]
        # Test that exit code 0 passes
        container.set_response(stage.check_cmd, 0)
        score1, _ = HealthScorer.score(container, fault_spec)

        # Test that any non-zero exit fails
        container.set_response(stage.check_cmd, 1)
        score2, _ = HealthScorer.score(container, fault_spec)

        # Score with 0 should be higher
        assert score1 > score2
