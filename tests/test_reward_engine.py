# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for reward/engine.py — RewardEngine orchestration."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from faults.registry import FaultRegistry
from reward.engine import RewardEngine


class MockContainer:
    """Mock Docker container for testing."""

    def __init__(self, health_score_progression=None):
        self.commands_run = []
        self.responses = {}
        self.default_exit_code = 0
        self.default_output = "mock"
        self.health_score_progression = health_score_progression or [0.0]
        self.call_count = 0

    def exec_run(self, cmd: str, timeout: int = 10):
        """Mock exec_run that returns (exit_code, output)."""
        self.commands_run.append((cmd, timeout))
        if cmd in self.responses:
            return self.responses[cmd]
        return self.default_exit_code, self.default_output

    def set_response(self, cmd: str, exit_code: int, output: str = ""):
        """Set the response for a command."""
        self.responses[cmd] = (exit_code, output)


class TestRewardEngineInitialization:
    """Test RewardEngine initialization."""

    def test_engine_initializes_correctly(self):
        """Test initial engine state."""
        fault_spec = FaultRegistry.get("nginx_stopped")
        engine = RewardEngine(fault_spec, max_steps=8)

        assert engine.steps == 0
        assert engine.prev_score == 0.0
        assert engine.prev_command == ""
        assert engine.used_diagnostics == set()
        assert engine.done is False
        assert engine.max_steps == 8

    def test_custom_max_steps(self):
        """Test custom max_steps."""
        fault_spec = FaultRegistry.get("nginx_stopped")
        engine = RewardEngine(fault_spec, max_steps=16)
        assert engine.max_steps == 16


class TestRewardEngineDestructiveCommands:
    """Test RewardEngine with destructive commands."""

    def test_destructive_command_ends_episode(self):
        """Test that destructive command ends episode immediately."""
        fault_spec = FaultRegistry.get("nginx_stopped")
        container = MockContainer()
        engine = RewardEngine(fault_spec)

        reward, done, info = engine.step("rm -rf /", container)

        assert done is True
        assert reward == -2.0
        assert info["r_penalty"] == -2.0
        assert info["verified"] is False

    def test_steps_increment_on_destructive_command(self):
        """Test that steps increment even on destructive command."""
        fault_spec = FaultRegistry.get("nginx_stopped")
        container = MockContainer()
        engine = RewardEngine(fault_spec)

        engine.step("rm -rf /", container)
        assert engine.steps == 1


class TestRewardEngineProgressReward:
    """Test progress reward computation."""

    def test_health_improvement_generates_progress_reward(self):
        """Test that improving health generates positive progress reward."""
        fault_spec = FaultRegistry.get("nginx_stopped")
        container = MockContainer()

        # Set health to improve from 0 to 1.0
        for stage in fault_spec.health_stages:
            container.set_response(stage.check_cmd, 0)  # All pass = full health

        engine = RewardEngine(fault_spec)
        prev_score_before = engine.prev_score
        reward, _, info = engine.step("systemctl start nginx", container)

        # Should have positive progress reward
        assert info["r_progress"] > 0
        assert info["health_score"] > prev_score_before

    def test_health_degradation_generates_negative_reward(self):
        """Test that degrading health generates negative progress reward."""
        fault_spec = FaultRegistry.get("nginx_stopped")
        container = MockContainer()

        engine = RewardEngine(fault_spec)

        # First step: improve health
        for stage in fault_spec.health_stages:
            container.set_response(stage.check_cmd, 0)
        engine.step("systemctl start nginx", container)

        # Second step: degrade health (make all checks fail)
        for stage in fault_spec.health_stages:
            container.set_response(stage.check_cmd, 1)
        reward, _, info = engine.step("pkill -9 nginx", container)

        # Should have negative progress reward
        assert info["r_progress"] < 0


class TestRewardEngineActionQuality:
    """Test action quality reward computation."""

    def test_diagnostic_commands_generate_bonuses(self):
        """Test that diagnostic commands generate action quality bonuses."""
        fault_spec = FaultRegistry.get("nginx_stopped")
        container = MockContainer()
        container.default_exit_code = 0

        engine = RewardEngine(fault_spec)
        reward, _, info = engine.step("journalctl -xe", container)

        # journalctl should give 0.08 bonus
        assert info["r_action"] == 0.08

    def test_one_time_diagnostic_bonus(self):
        """Test that diagnostic bonuses only apply once per episode."""
        fault_spec = FaultRegistry.get("nginx_stopped")
        container = MockContainer()
        container.default_exit_code = 0

        engine = RewardEngine(fault_spec)

        # First journalctl command
        _, _, info1 = engine.step("journalctl -xe", container)
        assert info1["r_action"] == 0.08

        # Second journalctl command
        _, _, info2 = engine.step("journalctl -f", container)
        assert info2["r_action"] == 0.0

    def test_multiple_diagnostic_patterns_same_command(self):
        """Test command matching multiple diagnostic patterns."""
        fault_spec = FaultRegistry.get("nginx_stopped")
        container = MockContainer()
        container.default_exit_code = 0

        engine = RewardEngine(fault_spec)
        # This command might match multiple patterns
        _, _, info = engine.step("grep listen /etc/nginx/nginx.conf", container)

        # Should get action quality reward
        assert info["r_action"] > 0


class TestRewardEngineStepCost:
    """Test step cost penalty."""

    def test_every_step_has_cost(self):
        """Test that every step costs -0.02."""
        fault_spec = FaultRegistry.get("nginx_stopped")
        container = MockContainer()
        container.default_exit_code = 0

        engine = RewardEngine(fault_spec)
        _, _, info = engine.step("echo test", container)

        # Should have at least the -0.02 step cost
        assert info["r_penalty"] <= -0.02


class TestRewardEngineVerification:
    """Test verification and terminal reward."""

    def test_terminal_reward_on_successful_verification(self):
        """Test terminal reward is applied on successful verification."""
        from copy import deepcopy
        fault_spec = deepcopy(FaultRegistry.get("nginx_stopped"))
        container = MockContainer()

        # Set all checks to pass (full health)
        for stage in fault_spec.health_stages:
            container.set_response(stage.check_cmd, 0)
        for cmd, _ in fault_spec.process_checks:
            container.set_response(cmd, 0)
        for cmd, _ in fault_spec.integrity_checks:
            container.set_response(cmd, 0)
        container.set_response(fault_spec.functional_check["cmd"], 0, "output")

        engine = RewardEngine(fault_spec, max_steps=8)
        reward, done, info = engine.step("systemctl start nginx", container)

        assert done is True
        assert info["verified"] is True
        assert info["r_terminal"] > 0
        # Terminal reward should be in range [2.5, 3.5]
        assert 2.5 <= info["r_terminal"] <= 3.5

    def test_no_terminal_reward_on_health_below_1(self):
        """Test that terminal reward only applies at health >= 1.0."""
        fault_spec = FaultRegistry.get("nginx_stopped")
        container = MockContainer()

        # Set partial health (0.5)
        container.set_response(fault_spec.health_stages[0].check_cmd, 0)
        container.set_response(fault_spec.health_stages[1].check_cmd, 1)

        engine = RewardEngine(fault_spec)
        _, done, info = engine.step("systemctl start nginx", container)

        assert done is False
        assert info["verified"] is False
        assert info["r_terminal"] == 0.0


class TestRewardEngineStepLimit:
    """Test maximum step limit."""

    def test_episode_ends_at_max_steps(self):
        """Test that episode ends when max_steps is reached."""
        fault_spec = FaultRegistry.get("nginx_stopped")
        container = MockContainer()
        container.default_exit_code = 1  # Ensure health stays below 1.0

        engine = RewardEngine(fault_spec, max_steps=3)

        # Step 1
        _, done, _ = engine.step("echo 1", container)
        assert done is False

        # Step 2
        _, done, _ = engine.step("echo 2", container)
        assert done is False

        # Step 3
        _, done, _ = engine.step("echo 3", container)
        assert done is True

    def test_info_dict_step_count(self):
        """Test that info_dict contains correct step count."""
        fault_spec = FaultRegistry.get("nginx_stopped")
        container = MockContainer()
        engine = RewardEngine(fault_spec)

        for i in range(1, 4):
            _, _, info = engine.step(f"echo {i}", container)
            assert info["steps"] == i


class TestRewardEngineInfoDict:
    """Test info dictionary structure."""

    def test_info_dict_contains_all_required_keys(self):
        """Test that info_dict contains all required keys."""
        fault_spec = FaultRegistry.get("nginx_stopped")
        container = MockContainer()
        engine = RewardEngine(fault_spec)

        _, _, info = engine.step("echo test", container)

        required_keys = {
            "health_score",
            "passing_stages",
            "r_progress",
            "r_action",
            "r_terminal",
            "r_penalty",
            "total",
            "verified",
            "steps",
        }
        assert set(info.keys()) >= required_keys

    def test_health_score_in_info_dict(self):
        """Test that health_score is in info_dict."""
        fault_spec = FaultRegistry.get("nginx_stopped")
        container = MockContainer()
        container.default_exit_code = 0

        engine = RewardEngine(fault_spec)
        _, _, info = engine.step("echo test", container)

        assert 0.0 <= info["health_score"] <= 1.0

    def test_passing_stages_in_info_dict(self):
        """Test that passing_stages list is in info_dict."""
        fault_spec = FaultRegistry.get("nginx_stopped")
        container = MockContainer()
        container.default_exit_code = 0

        engine = RewardEngine(fault_spec)
        _, _, info = engine.step("echo test", container)

        assert isinstance(info["passing_stages"], list)


class TestRewardEngineRewardRanges:
    """Test reward value ranges."""

    def test_successful_episode_reward_range(self):
        """Test that successful episode yields terminal reward in 2.5-3.5 range."""
        from copy import deepcopy
        fault_spec = deepcopy(FaultRegistry.get("nginx_stopped"))
        container = MockContainer()

        # Set all checks to pass
        for stage in fault_spec.health_stages:
            container.set_response(stage.check_cmd, 0)
        for cmd, _ in fault_spec.process_checks:
            container.set_response(cmd, 0)
        for cmd, _ in fault_spec.integrity_checks:
            container.set_response(cmd, 0)
        container.set_response(fault_spec.functional_check["cmd"], 0, "output")

        engine = RewardEngine(fault_spec, max_steps=8)
        reward, done, info = engine.step("systemctl start nginx", container)

        assert done is True
        # Terminal reward component should be in expected range
        assert 2.5 <= info["r_terminal"] <= 3.5
        # Total can be higher due to action quality bonuses
        assert reward > 0

    def test_failed_episode_reward_range(self):
        """Test that failed episode yields negative or low reward."""
        fault_spec = FaultRegistry.get("nginx_stopped")
        container = MockContainer()
        container.default_exit_code = 1  # Make all checks fail

        engine = RewardEngine(fault_spec, max_steps=1)

        # One step with no improvement
        reward, done, _ = engine.step("echo nothing", container)

        # Should be negative or close to zero
        assert reward < 0.5


class TestRewardEngineStateTracking:
    """Test RewardEngine state tracking."""

    def test_prev_command_updated(self):
        """Test that previous command is tracked."""
        fault_spec = FaultRegistry.get("nginx_stopped")
        container = MockContainer()
        engine = RewardEngine(fault_spec)

        engine.step("command1", container)
        assert engine.prev_command == "command1"

        engine.step("command2", container)
        assert engine.prev_command == "command2"

    def test_prev_score_updated(self):
        """Test that previous score is tracked."""
        fault_spec = FaultRegistry.get("nginx_stopped")
        container = MockContainer()

        # Set health to full for first step
        for stage in fault_spec.health_stages:
            container.set_response(stage.check_cmd, 0)

        engine = RewardEngine(fault_spec)
        engine.step("command1", container)

        # prev_score should be updated to current health (1.0)
        assert engine.prev_score >= 0.5  # At least some health achieved

    def test_used_diagnostics_tracked(self):
        """Test that used diagnostics are tracked."""
        fault_spec = FaultRegistry.get("nginx_stopped")
        container = MockContainer()
        container.default_exit_code = 0

        engine = RewardEngine(fault_spec)
        engine.step("journalctl -xe", container)

        # journalctl pattern should be in used_diagnostics
        assert len(engine.used_diagnostics) > 0
