"""Tests for reward/engine.py — RewardEngine orchestration."""

import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from faults.registry import FaultRegistry
from reward.engine import RewardEngine


def _mock_run(returncode: int = 0, stdout: bytes = b"mock"):
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    return m


def _patch_subprocess(returncode: int = 0, stdout: bytes = b"mock"):
    """Patch subprocess.run in both health and verifier modules."""
    run_mock = _mock_run(returncode, stdout)
    return patch("reward.health.subprocess.run", return_value=run_mock), \
           patch("reward.verifier.subprocess.run", return_value=run_mock)


class TestRewardEngineInitialization:
    def test_engine_initializes_correctly(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        engine = RewardEngine(fault_spec, max_steps=8)
        assert engine.steps == 0
        assert engine.prev_score == 0.0
        assert engine.prev_command == ""
        assert engine.used_diagnostics == set()
        assert engine.done is False
        assert engine.max_steps == 8

    def test_custom_max_steps(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        engine = RewardEngine(fault_spec, max_steps=16)
        assert engine.max_steps == 16


class TestRewardEngineDestructiveCommands:
    def test_destructive_command_ends_episode(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        engine = RewardEngine(fault_spec)
        reward, done, info = engine.step("rm -rf /")
        assert done is True
        assert reward == pytest.approx(-2.0)
        assert info["r_penalty"] == pytest.approx(-2.0)
        assert info["verified"] is False

    def test_steps_increment_on_destructive_command(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        engine = RewardEngine(fault_spec)
        engine.step("rm -rf /")
        assert engine.steps == 1


class TestRewardEngineProgressReward:
    def test_health_improvement_generates_progress_reward(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        engine = RewardEngine(fault_spec)
        health_mock, _ = _patch_subprocess(0)
        with health_mock:
            reward, _, info = engine.step("systemctl start nginx")
        assert info["r_progress"] > 0
        assert info["health_score"] > 0.0

    def test_health_degradation_generates_negative_reward(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        engine = RewardEngine(fault_spec)

        # First step: full health
        with patch("reward.health.subprocess.run", return_value=_mock_run(0)):
            engine.step("systemctl start nginx")

        # Second step: no health
        with patch("reward.health.subprocess.run", return_value=_mock_run(1)):
            _, _, info = engine.step("pkill -9 nginx")
        assert info["r_progress"] < 0


class TestRewardEngineActionQuality:
    def test_diagnostic_commands_generate_bonuses(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        engine = RewardEngine(fault_spec)
        with patch("reward.health.subprocess.run", return_value=_mock_run(0)):
            _, _, info = engine.step("journalctl -xe")
        assert info["r_action"] == pytest.approx(0.08)

    def test_one_time_diagnostic_bonus(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        engine = RewardEngine(fault_spec)
        with patch("reward.health.subprocess.run", return_value=_mock_run(0)):
            _, _, info1 = engine.step("journalctl -xe")
            _, _, info2 = engine.step("journalctl -f")
        assert info1["r_action"] == pytest.approx(0.08)
        assert info2["r_action"] == pytest.approx(0.0)

    def test_multiple_diagnostic_patterns_same_command(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        engine = RewardEngine(fault_spec)
        with patch("reward.health.subprocess.run", return_value=_mock_run(0)):
            _, _, info = engine.step("grep listen /etc/nginx/nginx.conf")
        assert info["r_action"] > 0


class TestRewardEngineStepCost:
    def test_every_step_has_cost(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        engine = RewardEngine(fault_spec)
        with patch("reward.health.subprocess.run", return_value=_mock_run(0)):
            _, _, info = engine.step("echo test")
        assert info["r_penalty"] <= -0.02


class TestRewardEngineVerification:
    def test_terminal_reward_on_successful_verification(self):
        fault_spec = deepcopy(FaultRegistry.get("nginx_stopped"))
        engine = RewardEngine(fault_spec, max_steps=8)
        with patch("reward.health.subprocess.run", return_value=_mock_run(0)), \
             patch("reward.verifier.subprocess.run", return_value=_mock_run(0, b"200")):
            reward, done, info = engine.step("systemctl start nginx")
        assert done is True
        assert info["verified"] is True
        assert 2.5 <= info["r_terminal"] <= 3.5

    def test_no_terminal_reward_when_health_below_1(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        engine = RewardEngine(fault_spec)
        # Only first stage passes — health < 1.0
        n_stages = len(fault_spec.health_stages)
        side_effects = [_mock_run(0)] + [_mock_run(1)] * (n_stages - 1)
        with patch("reward.health.subprocess.run", side_effect=side_effects):
            _, done, info = engine.step("systemctl start nginx")
        assert done is False
        assert info["verified"] is False
        assert info["r_terminal"] == pytest.approx(0.0)


class TestRewardEngineStepLimit:
    def test_episode_ends_at_max_steps(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        engine = RewardEngine(fault_spec, max_steps=3)
        with patch("reward.health.subprocess.run", return_value=_mock_run(1)):
            _, done1, _ = engine.step("echo 1")
            _, done2, _ = engine.step("echo 2")
            _, done3, _ = engine.step("echo 3")
        assert done1 is False
        assert done2 is False
        assert done3 is True

    def test_info_dict_step_count(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        engine = RewardEngine(fault_spec)
        with patch("reward.health.subprocess.run", return_value=_mock_run(1)):
            for i in range(1, 4):
                _, _, info = engine.step(f"echo {i}")
                assert info["steps"] == i


class TestRewardEngineInfoDict:
    def test_info_dict_contains_all_required_keys(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        engine = RewardEngine(fault_spec)
        with patch("reward.health.subprocess.run", return_value=_mock_run(0)):
            _, _, info = engine.step("echo test")
        required_keys = {
            "health_score", "passing_stages", "r_progress", "r_action",
            "r_terminal", "r_penalty", "total", "verified", "steps",
        }
        assert set(info.keys()) >= required_keys

    def test_health_score_in_info_dict(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        engine = RewardEngine(fault_spec)
        with patch("reward.health.subprocess.run", return_value=_mock_run(0)):
            _, _, info = engine.step("echo test")
        assert 0.0 <= info["health_score"] <= 1.0

    def test_passing_stages_in_info_dict(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        engine = RewardEngine(fault_spec)
        with patch("reward.health.subprocess.run", return_value=_mock_run(0)):
            _, _, info = engine.step("echo test")
        assert isinstance(info["passing_stages"], list)


class TestRewardEngineRewardRanges:
    def test_successful_episode_reward_range(self):
        fault_spec = deepcopy(FaultRegistry.get("nginx_stopped"))
        engine = RewardEngine(fault_spec, max_steps=8)
        with patch("reward.health.subprocess.run", return_value=_mock_run(0)), \
             patch("reward.verifier.subprocess.run", return_value=_mock_run(0, b"200")):
            reward, done, info = engine.step("systemctl start nginx")
        assert done is True
        assert 2.5 <= info["r_terminal"] <= 3.5
        assert reward > 0

    def test_failed_episode_reward_range(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        engine = RewardEngine(fault_spec, max_steps=1)
        with patch("reward.health.subprocess.run", return_value=_mock_run(1)):
            reward, done, _ = engine.step("echo nothing")
        assert reward < 0.5


class TestRewardEngineStateTracking:
    def test_prev_command_updated(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        engine = RewardEngine(fault_spec)
        with patch("reward.health.subprocess.run", return_value=_mock_run(0)):
            engine.step("command1")
            assert engine.prev_command == "command1"
            engine.step("command2")
            assert engine.prev_command == "command2"

    def test_prev_score_updated(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        engine = RewardEngine(fault_spec)
        with patch("reward.health.subprocess.run", return_value=_mock_run(0)):
            engine.step("command1")
        assert engine.prev_score >= 0.5

    def test_used_diagnostics_tracked(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        engine = RewardEngine(fault_spec)
        with patch("reward.health.subprocess.run", return_value=_mock_run(0)):
            engine.step("journalctl -xe")
        assert len(engine.used_diagnostics) > 0
