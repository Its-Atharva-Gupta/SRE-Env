# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Tests for reward/components.py — pure reward functions."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from reward.components import (
    action_quality_reward,
    penalty,
    progress_reward,
    terminal_reward,
)


class TestProgressReward:
    """Test progress_reward function."""

    def test_positive_delta_multiplied_by_2(self):
        """Test that positive health improvements are weighted 2x."""
        reward = progress_reward(0.0, 0.5)
        assert reward == 1.0  # 0.5 * 2

    def test_negative_delta_multiplied_by_1(self):
        """Test that negative health changes are weighted 1x."""
        reward = progress_reward(0.5, 0.2)
        assert reward == -0.3  # (0.2 - 0.5) * 1

    def test_zero_delta_returns_zero(self):
        """Test that no change returns 0 reward."""
        reward = progress_reward(0.5, 0.5)
        assert reward == 0.0

    def test_small_positive_improvement(self):
        """Test small positive improvement."""
        reward = progress_reward(0.0, 0.1)
        assert reward == 0.2

    def test_reaching_full_health(self):
        """Test reaching full health."""
        reward = progress_reward(0.8, 1.0)
        assert abs(reward - 0.4) < 1e-6


class TestActionQualityReward:
    """Test action_quality_reward function."""

    def test_journalctl_bonus(self):
        """Test journalctl command bonus."""
        used = set()
        reward = action_quality_reward("journalctl -xe", used)
        assert reward == 0.08
        assert "journalctl" in used

    def test_systemctl_status_bonus(self):
        """Test systemctl status bonus."""
        used = set()
        reward = action_quality_reward("systemctl status nginx", used)
        assert reward == 0.08

    def test_systemctl_failed_bonus(self):
        """Test systemctl --failed bonus."""
        used = set()
        reward = action_quality_reward("systemctl --failed --no-pager", used)
        assert reward == 0.06

    def test_nginx_syntax_check_bonus(self):
        """Test nginx -t bonus."""
        used = set()
        reward = action_quality_reward("nginx -t", used)
        assert reward == 0.07

    def test_tail_log_bonus(self):
        """Test tail.*log pattern bonus."""
        used = set()
        reward = action_quality_reward("tail -f /var/log/nginx/error.log", used)
        assert reward == 0.05

    def test_cat_log_bonus(self):
        """Test cat.*log pattern bonus."""
        used = set()
        reward = action_quality_reward("cat /var/log/nginx/access.log", used)
        assert reward == 0.05

    def test_ss_bonus(self):
        """Test ss - bonus."""
        used = set()
        reward = action_quality_reward("ss -tlnp | grep :80", used)
        assert reward == 0.04

    def test_netstat_bonus(self):
        """Test netstat bonus."""
        used = set()
        reward = action_quality_reward("netstat -tlnp | grep :80", used)
        assert reward == 0.04

    def test_df_bonus(self):
        """Test df - bonus."""
        used = set()
        reward = action_quality_reward("df -h", used)
        assert reward == 0.04

    def test_du_bonus(self):
        """Test du - bonus."""
        used = set()
        reward = action_quality_reward("du -sh /var/log", used)
        assert reward == 0.04

    def test_ps_aux_bonus(self):
        """Test ps aux bonus."""
        used = set()
        reward = action_quality_reward("ps aux | grep nginx", used)
        assert reward == 0.04

    def test_ps_ef_bonus(self):
        """Test ps -ef bonus."""
        used = set()
        reward = action_quality_reward("ps -ef | grep nginx", used)
        assert reward == 0.04

    def test_dmesg_bonus(self):
        """Test dmesg bonus."""
        used = set()
        reward = action_quality_reward("dmesg | tail -20", used)
        assert reward == 0.05

    def test_ls_la_bonus(self):
        """Test ls -la bonus."""
        used = set()
        reward = action_quality_reward("ls -la /var/log/", used)
        assert reward == 0.02

    def test_ls_l_bonus(self):
        """Test ls -l bonus."""
        used = set()
        reward = action_quality_reward("ls -l /etc/nginx/", used)
        assert reward == 0.02

    def test_cat_etc_bonus(self):
        """Test cat /etc/ bonus."""
        used = set()
        reward = action_quality_reward("cat /etc/nginx/nginx.conf", used)
        assert reward == 0.03

    def test_grep_conf_bonus(self):
        """Test grep.*conf bonus."""
        used = set()
        reward = action_quality_reward("grep listen /etc/nginx/nginx.conf", used)
        assert reward == 0.03

    def test_one_time_only_per_episode(self):
        """Test that bonuses are only applied once per episode."""
        used = set()
        reward1 = action_quality_reward("journalctl -xe", used)
        assert reward1 == 0.08
        reward2 = action_quality_reward("journalctl -xe", used)
        assert reward2 == 0.0

    def test_multiple_patterns_in_single_command(self):
        """Test command matching multiple patterns."""
        used = set()
        # "grep.*conf" matches but not both
        reward = action_quality_reward("grep listen /etc/nginx/nginx.conf", used)
        assert reward > 0

    def test_no_pattern_match(self):
        """Test command with no matching pattern."""
        used = set()
        reward = action_quality_reward("echo hello", used)
        assert reward == 0.0


class TestPenalty:
    """Test penalty function."""

    def test_step_cost(self):
        """Test that every step costs -0.02."""
        delta, done = penalty("ls", "")
        assert delta == -0.02
        assert done is False

    def test_repeat_command_penalty(self):
        """Test penalty for repeating the same command."""
        delta, done = penalty("ls -la", "ls -la")
        # -0.02 step cost + -0.15 repeat penalty = -0.17
        assert abs(delta - (-0.17)) < 1e-6
        assert done is False

    def test_repeat_command_with_whitespace_variation(self):
        """Test that whitespace variations are detected as repeats."""
        delta, done = penalty("  ls -la  ", "ls -la")
        assert abs(delta - (-0.17)) < 1e-6

    def test_vim_interactive_penalty(self):
        """Test penalty for vim command."""
        delta, done = penalty("vim /etc/nginx/nginx.conf", "")
        # -0.02 step cost + -0.5 interactive = -0.52
        assert delta == -0.52
        assert done is False

    def test_nano_interactive_penalty(self):
        """Test penalty for nano command."""
        delta, done = penalty("nano /etc/nginx/nginx.conf", "")
        assert delta == -0.52
        assert done is False

    def test_emacs_interactive_penalty(self):
        """Test penalty for emacs command."""
        delta, done = penalty("emacs /etc/nginx/nginx.conf", "")
        assert delta == -0.52
        assert done is False

    def test_less_interactive_penalty(self):
        """Test penalty for less command."""
        delta, done = penalty("less /var/log/nginx/error.log", "")
        assert delta == -0.52
        assert done is False

    def test_more_interactive_penalty(self):
        """Test penalty for more command."""
        delta, done = penalty("more /var/log/nginx/error.log", "")
        assert delta == -0.52
        assert done is False

    def test_rm_rf_slash_destructive(self):
        """Test penalty for rm -rf / command."""
        delta, done = penalty("rm -rf /", "")
        assert delta == -2.0
        assert done is True

    def test_rm_rf_slash_star_destructive(self):
        """Test penalty for rm -rf /* command."""
        delta, done = penalty("rm -rf /*", "")
        assert delta == -2.0
        assert done is True

    def test_mkfs_destructive(self):
        """Test penalty for mkfs command."""
        delta, done = penalty("mkfs /dev/sda", "")
        assert delta == -2.0
        assert done is True

    def test_dd_zero_destructive(self):
        """Test penalty for dd if=/dev/zero of=/dev/sd* command."""
        delta, done = penalty("dd if=/dev/zero of=/dev/sda", "")
        assert delta == -2.0
        assert done is True

    def test_forkbomb_destructive(self):
        """Test penalty for fork bomb."""
        delta, done = penalty(":(){:|:&};:", "")
        assert delta == -2.0
        assert done is True

    def test_chmod_000_destructive(self):
        """Test penalty for chmod -R 000 / command."""
        delta, done = penalty("chmod -R 000 /", "")
        assert delta == -2.0
        assert done is True

    def test_overwrite_passwd_destructive(self):
        """Test penalty for > /etc/passwd command."""
        delta, done = penalty("> /etc/passwd", "")
        assert delta == -2.0
        assert done is True

    def test_normal_command(self):
        """Test normal command has only step cost."""
        delta, done = penalty("systemctl status nginx", "")
        assert delta == -0.02
        assert done is False


class TestTerminalReward:
    """Test terminal_reward function."""

    def test_fast_completion_first_step(self):
        """Test reward for solving in 1 step."""
        reward = terminal_reward(1, 8)
        # base=2.0, efficiency=(8-1)/8=0.875, layer=0.5
        expected = 2.0 + 0.875 + 0.5
        assert abs(reward - expected) < 1e-6
        assert 3.3 <= reward <= 3.5  # Should be in high range

    def test_slow_completion_last_step(self):
        """Test reward for solving in max steps."""
        reward = terminal_reward(8, 8)
        # base=2.0, efficiency=(8-8)/8=0, layer=0.5
        expected = 2.0 + 0.0 + 0.5
        assert reward == expected
        assert reward == 2.5

    def test_medium_completion_step_4(self):
        """Test reward for solving in middle."""
        reward = terminal_reward(4, 8)
        # base=2.0, efficiency=(8-4)/8=0.5, layer=0.5
        expected = 2.0 + 0.5 + 0.5
        assert reward == expected
        assert reward == 3.0

    def test_reward_range_is_valid(self):
        """Test that all rewards fall in expected 2.5-3.5 range."""
        for steps in range(1, 9):
            reward = terminal_reward(steps, 8)
            assert 2.5 <= reward <= 3.5, f"Reward out of range at step {steps}: {reward}"

    def test_reward_decreases_with_steps(self):
        """Test that reward decreases as steps increase."""
        rewards = [terminal_reward(s, 8) for s in range(1, 9)]
        for i in range(len(rewards) - 1):
            assert rewards[i] >= rewards[i + 1], f"Rewards should decrease: {rewards}"
