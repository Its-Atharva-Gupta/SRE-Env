"""Reward engine — orchestrates all reward components."""

from typing import Dict, Tuple

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
    """Stateful per-episode reward orchestrator."""

    def __init__(self, fault_spec: FaultSpec, max_steps: int = 8):
        self.fault_spec = fault_spec
        self.max_steps = max_steps
        self.steps = 0
        self.prev_score = 0.0
        self.prev_command = ""
        self.used_diagnostics = set()
        self.done = False

    def step(self, command: str) -> Tuple[float, bool, Dict]:
        """Execute one step and compute rewards.

        Args:
            command: Shell command executed

        Returns:
            (total_reward, done, info_dict)
        """
        self.steps += 1

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

        health_score, passing_stages = HealthScorer.score(self.fault_spec)

        r_progress = progress_reward(self.prev_score, health_score)
        r_action = action_quality_reward(command, self.used_diagnostics)

        r_terminal = 0.0
        verified = False
        if health_score >= 1.0:
            verifier = Verifier(self.fault_spec)
            verified, _ = verifier.verify()
            if verified:
                r_terminal = terminal_reward(self.steps, self.max_steps)
                self.done = True

        if self.steps >= self.max_steps:
            self.done = True

        total_reward = r_progress + r_action + r_penalty + r_terminal

        self.prev_score = health_score
        self.prev_command = command

        return total_reward, self.done, {
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
