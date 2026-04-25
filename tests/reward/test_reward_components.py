"""
Unit tests for reward/components.py — pure reward functions.

All tests are deterministic and need no system access (no nginx, no Docker).
Run with: pytest tests/reward/test_reward_components.py -v
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.resolve()))

from reward.components import (  # noqa: E402
    action_quality_reward,
    penalty,
    progress_reward,
    terminal_reward,
)


# ---------------------------------------------------------------------------
# progress_reward
# ---------------------------------------------------------------------------

class TestProgressReward:
    def test_positive_delta_returns_positive(self):
        assert progress_reward(0.0, 0.5) > 0.0

    def test_negative_delta_returns_negative(self):
        assert progress_reward(0.8, 0.3) < 0.0

    def test_zero_delta_returns_zero(self):
        assert progress_reward(0.4, 0.4) == 0.0

    def test_positive_delta_weighted_2x(self):
        # delta = 0.3, reward = 0.3 * 2.0 = 0.6
        assert progress_reward(0.0, 0.3) == pytest.approx(0.6)

    def test_negative_delta_weighted_1x(self):
        # delta = -0.3, reward = -0.3 * 1.0 = -0.3
        assert progress_reward(0.5, 0.2) == pytest.approx(-0.3)

    def test_large_jump_proportional_to_small_jump(self):
        # Doubling the delta should double the reward
        r_small = progress_reward(0.0, 0.2)
        r_large = progress_reward(0.0, 0.4)
        assert r_large == pytest.approx(r_small * 2)

    def test_reaching_full_health_from_half(self):
        # delta = 0.5, reward = 0.5 * 2.0 = 1.0
        assert progress_reward(0.5, 1.0) == pytest.approx(1.0)

    def test_full_regression_to_zero(self):
        # delta = -1.0, reward = -1.0 * 1.0 = -1.0
        assert progress_reward(1.0, 0.0) == pytest.approx(-1.0)


# ---------------------------------------------------------------------------
# action_quality_reward
# ---------------------------------------------------------------------------

class TestActionQualityReward:
    def test_first_use_applies_bonus(self):
        used: set[str] = set()
        r = action_quality_reward("journalctl -xe", used)
        assert r == pytest.approx(0.08)

    def test_second_use_of_same_pattern_returns_zero(self):
        used: set[str] = set()
        action_quality_reward("journalctl -xe", used)
        r = action_quality_reward("journalctl --boot", used)  # same pattern, different cmd
        assert r == 0.0

    def test_unrecognized_command_returns_zero(self):
        used: set[str] = set()
        assert action_quality_reward("echo hello", used) == 0.0
        assert action_quality_reward("touch /tmp/x", used) == 0.0
        assert action_quality_reward("sleep 1", used) == 0.0

    def test_multiple_patterns_in_one_command_returns_sum(self):
        used: set[str] = set()
        # journalctl (0.08) + grep.*conf (0.03) = 0.11
        r = action_quality_reward("journalctl | grep nginx.conf", used)
        assert r == pytest.approx(0.08 + 0.03)

    def test_cat_log_and_cat_etc_are_separate_patterns(self):
        used: set[str] = set()
        # cat.*log (0.05) fires, cat /etc/ (0.03) does NOT (path is /var/log/)
        r1 = action_quality_reward("cat /var/log/nginx/error.log", used)
        assert r1 == pytest.approx(0.05)
        # cat /etc/ (0.03) should still fire on a different command
        r2 = action_quality_reward("cat /etc/nginx/nginx.conf", used)
        assert r2 == pytest.approx(0.03)

    def test_modifies_used_set_in_place(self):
        used: set[str] = set()
        assert len(used) == 0
        action_quality_reward("nginx -t", used)
        assert len(used) == 1

    def test_all_patterns_have_correct_bonuses(self):
        expected = {
            "journalctl -xe":              0.08,
            "systemctl status nginx":      0.08,
            "systemctl --failed":          0.06,
            "nginx -t":                    0.07,
            "tail -f /var/log/nginx/error.log": 0.05,
            "cat /var/log/nginx/access.log":    0.05,
            "ss -tlnp":                    0.04,
            "netstat -tlnp":               0.04,
            "df -h":                       0.04,
            "du -sh /var/log":             0.04,
            "ps aux":                      0.04,
            "ps -ef":                      0.04,
            "dmesg":                       0.05,
            "ls -la /var/log/":            0.02,
            "ls -l /etc/nginx/":           0.02,
            "cat /etc/nginx/nginx.conf":   0.03,
            "grep listen /etc/nginx/nginx.conf": 0.03,
        }
        for cmd, expected_bonus in expected.items():
            used: set[str] = set()
            r = action_quality_reward(cmd, used)
            assert r == pytest.approx(expected_bonus), (
                f"Command '{cmd}': expected {expected_bonus}, got {r}"
            )

    def test_cross_episode_isolation(self):
        # Each episode gets a fresh used set — bonuses should fire again
        for _ in range(3):
            used: set[str] = set()
            r = action_quality_reward("systemctl --failed", used)
            assert r == pytest.approx(0.06)


# ---------------------------------------------------------------------------
# penalty
# ---------------------------------------------------------------------------

class TestPenalty:
    def test_step_cost_always_applied(self):
        delta, done = penalty("df -h", "")
        assert delta == pytest.approx(-0.02)
        assert done is False

    def test_step_cost_applied_even_on_repeat(self):
        delta, done = penalty("ls", "ls")
        # -0.02 step + -0.15 repeat = -0.17
        assert delta == pytest.approx(-0.17)
        assert done is False

    def test_repeat_penalty_only_on_exact_match(self):
        delta_same, _ = penalty("ls", "ls")
        delta_diff, _ = penalty("ls -la", "ls")
        assert delta_same < delta_diff  # repeat is worse

    def test_repeat_ignores_leading_trailing_whitespace(self):
        delta, done = penalty("  ls  ", "ls")
        assert delta == pytest.approx(-0.17)

    def test_destructive_rm_rf_slash(self):
        delta, done = penalty("rm -rf /", "")
        assert delta == pytest.approx(-2.0)
        assert done is True

    def test_destructive_rm_rf_slash_star(self):
        delta, done = penalty("rm -rf /*", "echo hello")
        assert delta == pytest.approx(-2.0)
        assert done is True

    def test_destructive_mkfs(self):
        delta, done = penalty("mkfs /dev/sda", "")
        assert delta == pytest.approx(-2.0)
        assert done is True

    def test_destructive_dd_zero(self):
        delta, done = penalty("dd if=/dev/zero of=/dev/sda", "")
        assert delta == pytest.approx(-2.0)
        assert done is True

    def test_destructive_fork_bomb(self):
        delta, done = penalty(":(){:|:&};:", "")
        assert delta == pytest.approx(-2.0)
        assert done is True

    def test_destructive_chmod_recursive_root(self):
        delta, done = penalty("chmod -R 000 /", "")
        assert delta == pytest.approx(-2.0)
        assert done is True

    def test_destructive_overwrite_passwd(self):
        delta, done = penalty("> /etc/passwd", "")
        assert delta == pytest.approx(-2.0)
        assert done is True

    def test_interactive_vim_penalizes_but_continues(self):
        delta, done = penalty("vim /etc/nginx/nginx.conf", "")
        assert delta == pytest.approx(-0.52)  # -0.02 - 0.50
        assert done is False

    def test_interactive_nano_penalizes_but_continues(self):
        delta, done = penalty("nano /etc/hosts", "")
        assert delta == pytest.approx(-0.52)
        assert done is False

    def test_interactive_emacs_penalizes_but_continues(self):
        delta, done = penalty("emacs /tmp/test", "")
        assert delta == pytest.approx(-0.52)
        assert done is False

    def test_interactive_less_penalizes_but_continues(self):
        delta, done = penalty("less /var/log/nginx/error.log", "")
        assert delta == pytest.approx(-0.52)
        assert done is False

    def test_interactive_more_penalizes_but_continues(self):
        delta, done = penalty("more /var/log/nginx/error.log", "")
        assert delta == pytest.approx(-0.52)
        assert done is False

    def test_clean_command_just_step_cost(self):
        for cmd in ["systemctl status nginx", "nginx -t", "cat /etc/nginx/nginx.conf"]:
            delta, done = penalty(cmd, "something_different")
            assert delta == pytest.approx(-0.02), f"Clean cmd '{cmd}' should cost only -0.02"
            assert done is False


# ---------------------------------------------------------------------------
# terminal_reward
# ---------------------------------------------------------------------------

class TestTerminalReward:
    def test_step_1_near_3_5(self):
        # base=2.0, efficiency=(8-1)/8=0.875, layer=0.5 → 3.375
        r = terminal_reward(1, 8)
        assert 3.3 <= r <= 3.5

    def test_step_8_is_exactly_2_5(self):
        # base=2.0, efficiency=(8-8)/8=0.0, layer=0.5 → 2.5
        r = terminal_reward(8, 8)
        assert r == pytest.approx(2.5)

    def test_step_4_is_midpoint(self):
        # base=2.0, efficiency=(8-4)/8=0.5, layer=0.5 → 3.0
        r = terminal_reward(4, 8)
        assert r == pytest.approx(3.0)

    def test_linear_decreasing_with_steps(self):
        """Each additional step should strictly reduce terminal reward."""
        rewards = [terminal_reward(s, 8) for s in range(1, 9)]
        for i in range(len(rewards) - 1):
            assert rewards[i] > rewards[i + 1], (
                f"Non-linear at step {i + 1}: "
                f"{rewards[i]:.4f} should > {rewards[i + 1]:.4f}"
            )

    def test_all_steps_in_range_2_5_to_3_5(self):
        for s in range(1, 9):
            r = terminal_reward(s, 8)
            assert 2.5 <= r <= 3.5, f"Step {s}: {r:.3f} outside [2.5, 3.5]"

    def test_efficiency_bonus_proportional_to_steps_remaining(self):
        # step=2 → remaining=6/8=0.75, step=4 → remaining=4/8=0.50
        # difference in efficiency_bonus = (0.75 - 0.50) * 1.0 = 0.25
        r2 = terminal_reward(2, 8)
        r4 = terminal_reward(4, 8)
        assert r2 - r4 == pytest.approx(0.25)
