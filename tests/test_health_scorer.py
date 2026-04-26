"""Tests for reward/health.py — HealthScorer."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from faults.registry import FaultRegistry
from reward.health import HealthScorer


def _mock_run(returncode: int = 0):
    """Return a mock subprocess.run result with the given returncode."""
    m = MagicMock()
    m.returncode = returncode
    return m


class TestHealthScorer:
    def test_all_stages_passing(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        with patch("reward.health.subprocess.run", return_value=_mock_run(0)):
            score, passing = HealthScorer.score(fault_spec)
        assert score == pytest.approx(1.0)
        assert len(passing) == len(fault_spec.health_stages)

    def test_all_stages_failing(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        with patch("reward.health.subprocess.run", return_value=_mock_run(1)):
            score, passing = HealthScorer.score(fault_spec)
        assert score == pytest.approx(0.0)
        assert passing == []

    def test_partial_stages_passing(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        stages = fault_spec.health_stages
        side_effects = [_mock_run(0), _mock_run(1)]
        with patch("reward.health.subprocess.run", side_effect=side_effects):
            score, passing = HealthScorer.score(fault_spec)
        assert score == pytest.approx(stages[0].weight)
        assert passing == [stages[0].name]

    def test_stages_weights_sum_correctly(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        with patch("reward.health.subprocess.run", return_value=_mock_run(0)):
            score, _ = HealthScorer.score(fault_spec)
        total_weight = sum(s.weight for s in fault_spec.health_stages)
        assert score == pytest.approx(total_weight)

    def test_score_clamped_to_zero(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        with patch("reward.health.subprocess.run", return_value=_mock_run(1)):
            score, _ = HealthScorer.score(fault_spec)
        assert score >= 0.0

    def test_score_clamped_to_one(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        with patch("reward.health.subprocess.run", return_value=_mock_run(0)):
            score, _ = HealthScorer.score(fault_spec)
        assert score <= 1.0

    def test_broken_nginx_config_scoring(self):
        fault_spec = FaultRegistry.get("broken_nginx_config")
        stages = fault_spec.health_stages
        side_effects = [_mock_run(0), _mock_run(1)]
        with patch("reward.health.subprocess.run", side_effect=side_effects):
            score, passing = HealthScorer.score(fault_spec)
        assert score == pytest.approx(stages[0].weight)
        assert passing == [stages[0].name]

    def test_exception_treated_as_failure(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        with patch("reward.health.subprocess.run", side_effect=Exception("timeout")):
            score, passing = HealthScorer.score(fault_spec)
        assert score == pytest.approx(0.0)
        assert passing == []

    def test_passing_stages_list_correct(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        side_effects = [_mock_run(0), _mock_run(1)]
        with patch("reward.health.subprocess.run", side_effect=side_effects):
            _, passing = HealthScorer.score(fault_spec)
        assert len(passing) == 1
        assert passing[0] == fault_spec.health_stages[0].name

    def test_all_faults_scorable(self):
        for fault in FaultRegistry.all_faults():
            with patch("reward.health.subprocess.run", return_value=_mock_run(0)):
                score, passing = HealthScorer.score(fault)
            assert 0.0 <= score <= 1.0
            assert len(passing) == len(fault.health_stages)

    def test_non_zero_exit_code_is_failure(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        with patch("reward.health.subprocess.run", return_value=_mock_run(1)):
            score, passing = HealthScorer.score(fault_spec)
        assert score == pytest.approx(0.0)
        assert passing == []

    def test_only_zero_exit_code_is_success(self):
        fault_spec = FaultRegistry.get("nginx_stopped")
        with patch("reward.health.subprocess.run", return_value=_mock_run(0)):
            score1, _ = HealthScorer.score(fault_spec)
        with patch("reward.health.subprocess.run", return_value=_mock_run(1)):
            score2, _ = HealthScorer.score(fault_spec)
        assert score1 > score2

    def test_none_fault_spec_returns_zero(self):
        score, passing = HealthScorer.score(None)
        assert score == pytest.approx(0.0)
        assert passing == []
