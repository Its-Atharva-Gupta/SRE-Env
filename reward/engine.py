# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Reward engine — orchestrates all reward components."""

from typing import Any, Dict, Tuple

from faults.registry import FaultSpec
from reward.components import (
    action_quality_reward,
    penalty,
    progress_reward,
    terminal_reward,
)
from reward.health import HealthScorer
from reward.verifier import Verifier


class RewardEngine:
    """Stateful per-episode reward orchestrator.

    Combines progress, action quality, penalties, and terminal rewards
    into a single scalar reward signal.
    """

    def __init__(self, fault_spec: FaultSpec, max_steps: int = 8):
        """Initialize reward engine for an episode.

        Args:
            fault_spec: FaultSpec defining health stages and verification
            max_steps: Maximum steps allowed in episode (default 8)
        """
        self.fault_spec = fault_spec
        self.max_steps = max_steps
        self.steps = 0
        self.prev_score = 0.0
        self.prev_command = ""
        self.used_diagnostics = set()
        self.done = False

    def step(self, command: str, container: Any) -> Tuple[float, bool, Dict]:
        """Execute one step and compute rewards.

        Args:
            command: Shell command executed
            container: Docker container for health scoring

        Returns:
            (total_reward, done, info_dict)
        """
        self.steps += 1

        # Step 1: Compute penalty (checks for destructive commands, etc.)
        r_penalty, episode_destroyed = penalty(command, self.prev_command)
        if episode_destroyed:
            self.done = True
            return r_penalty, self.done, {
                "health_score": self.prev_score,
                "passing_stages": [],
                "r_progress": 0.0,
                "r_action": 0.0,
                "r_terminal": 0.0,
                "r_penalty": r_penalty,
                "total": r_penalty,
                "verified": False,
                "steps": self.steps,
            }

        # Step 2: Score health
        health_score, passing_stages = HealthScorer.score(container, self.fault_spec)

        # Step 3: Progress reward
        r_progress = progress_reward(self.prev_score, health_score)

        # Step 4: Action quality reward
        r_action = action_quality_reward(command, self.used_diagnostics)

        # Step 5-6: Terminal reward (only if health == 1.0 and verified)
        r_terminal = 0.0
        verified = False
        if health_score >= 1.0:
            verifier = Verifier(container, self.fault_spec)
            verified, _ = verifier.verify()
            if verified:
                r_terminal = terminal_reward(self.steps, self.max_steps)
                self.done = True

        # Step 7: Check step limit
        if self.steps >= self.max_steps:
            self.done = True

        # Step 8: Sum all components
        total_reward = r_progress + r_action + r_penalty + r_terminal

        # Step 9: Update state
        self.prev_score = health_score
        self.prev_command = command

        # Step 10: Return (total, done, info_dict)
        info_dict = {
            "health_score": health_score,
            "passing_stages": passing_stages,
            "r_progress": r_progress,
            "r_action": r_action,
            "r_terminal": r_terminal,
            "r_penalty": r_penalty,
            "total": total_reward,
            "verified": verified,
            "steps": self.steps,
        }

        return total_reward, self.done, info_dict
