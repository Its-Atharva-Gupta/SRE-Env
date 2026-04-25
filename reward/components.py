# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Pure reward function components (no state, no container access)."""

import re
from typing import Set, Tuple


def progress_reward(prev_score: float, curr_score: float) -> float:
    """Reward based on health score delta.

    Args:
        prev_score: Previous health score (0.0-1.0)
        curr_score: Current health score (0.0-1.0)

    Returns:
        Reward delta: positive improvements weighted 2x, negative weighted 1x
    """
    delta = curr_score - prev_score
    if delta > 0:
        return delta * 2.0
    elif delta < 0:
        return delta * 1.0
    else:
        return 0.0


def action_quality_reward(command: str, used_diagnostics: Set[str]) -> float:
    """One-time bonus rewards for using useful diagnostic commands.

    Args:
        command: The command executed
        used_diagnostics: Set of diagnostic patterns already used (modified in place)

    Returns:
        Bonus reward (0 to +0.08) for first use of each diagnostic pattern
    """
    # Pattern → bonus mapping (one-time per episode)
    DIAGNOSTICS = {
        r"journalctl": 0.08,
        r"systemctl\s+status": 0.08,
        r"systemctl\s+--failed": 0.06,
        r"nginx\s+-t": 0.07,
        r"tail.*log": 0.05,
        r"cat.*log": 0.05,
        r"(ss\s+|netstat)": 0.04,
        r"(df\s+|du\s+)": 0.04,
        r"(ps\s+aux|ps\s+-ef)": 0.04,
        r"dmesg": 0.05,
        r"(ls\s+-la|ls\s+-l)": 0.02,
        r"cat\s+/etc/": 0.03,
        r"grep.*conf": 0.03,
    }

    reward = 0.0
    for pattern, bonus in DIAGNOSTICS.items():
        if re.search(pattern, command):
            if pattern not in used_diagnostics:
                used_diagnostics.add(pattern)
                reward += bonus

    return reward


def penalty(command: str, prev_command: str) -> Tuple[float, bool]:
    """Compute penalties for bad commands.

    Args:
        command: Current command
        prev_command: Previous command (to detect repeats)

    Returns:
        (reward_delta, episode_over): Penalty amount and whether episode should end
    """
    # Always apply step cost
    reward_delta = -0.02
    episode_over = False

    # Destructive commands: episode-ending penalty
    DESTRUCTIVE = [
        "rm -rf /",
        "rm -rf /*",
        "mkfs",
        "dd if=/dev/zero of=/dev/sd",
        ":(){:|:&};:",
        "chmod -R 000 /",
        "> /etc/passwd",
    ]

    if any(d in command for d in DESTRUCTIVE):
        return -2.0, True

    # Interactive commands: penalty but don't end episode
    INTERACTIVE = ["vim", "nano", "emacs", "less", "more"]
    if any(i in command for i in INTERACTIVE):
        return reward_delta - 0.5, False

    # Repeat command penalty
    if command.strip() == prev_command.strip():
        reward_delta -= 0.15

    return reward_delta, episode_over


def terminal_reward(steps_taken: int, max_steps: int) -> float:
    """Reward for successfully completing the episode (after full verification).

    Called only when Verifier.verify() returns True.

    Args:
        steps_taken: Number of steps used (1 to max_steps)
        max_steps: Maximum allowed steps (default 8)

    Returns:
        Terminal reward (2.5 to 3.5 range)
    """
    base = 2.0
    steps_remaining = max_steps - steps_taken
    efficiency_bonus = (steps_remaining / max_steps) * 1.0  # max +1.0
    layer_bonus = 0.5  # flat bonus for passing all verification layers

    return base + efficiency_bonus + layer_bonus
