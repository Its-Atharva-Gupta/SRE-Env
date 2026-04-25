# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""
SRE Terminal Agent RL Environment Implementation.

LLM agent acts as SRE: SSH into broken Linux server, diagnose and fix faults.
Reward based on verified system state restoration, not model output text.
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from openenv.core.env_server.interfaces import Environment
from openenv.core.env_server.types import State

# Handle imports for both Docker (PYTHONPATH=/app/env) and local execution
try:
    from faults.registry import FaultRegistry
    from models import SREAction, SREObservation
    from reward.engine import RewardEngine
    from sandbox import get_sandbox
except (ImportError, ModuleNotFoundError):
    # Try relative imports (when run as a package)
    try:
        from ..faults.registry import FaultRegistry
        from ..models import SREAction, SREObservation
        from ..reward.engine import RewardEngine
        from ..sandbox import get_sandbox
    except (ImportError, ModuleNotFoundError):
        # Add parent directory to path and retry
        parent_dir = str(Path(__file__).parent.parent)
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)
        from faults.registry import FaultRegistry
        from models import SREAction, SREObservation
        from reward.engine import RewardEngine
        from sandbox import get_sandbox


@dataclass
class SREState:
    """Server-side episode state (not exported to client)."""

    container_id: str
    fault_id: str
    ssh_port: int
    step: int
    prev_score: float
    prev_command: str
    used_diagnostics: set = field(default_factory=set)
    alert: str = ""
    done: bool = False


class SREEnvironment(Environment):
    """
    SRE Terminal Agent RL Environment.

    Agent receives one-line pager alert + SSH credentials to sandboxed container.
    Outputs one shell command per step. Environment executes, returns real terminal output.
    Reward computed from verified system state — not from model output text.
    """

    SUPPORTS_CONCURRENT_SESSIONS: bool = True

    def __init__(self, pool_size: int = 8):
        """Initialize SRE environment.

        Args:
            pool_size: Number of pre-warmed containers (default: 8, local mode only)
        """
        import os
        self.sandbox = get_sandbox()
        self.mode = os.getenv("SANDBOX_MODE", "local").lower()
        self.current_state: Optional[SREState] = None
        self.container: Optional[Any] = None
        self.reward_engine: Optional[RewardEngine] = None

    def reset(self, config: Optional[Dict] = None) -> SREObservation:
        """Reset environment to a new episode.

        Args:
            config: Optional config dict with 'tier' key to filter faults

        Returns:
            SREObservation with alert + diagnostic output
        """
        # Sample a fault (optionally filtered by tier)
        tier = config.get("tier") if config else None
        fault_spec = FaultRegistry.sample(tier=tier)

        # Reset sandbox (calls restore.sh + inject script)
        if self.mode == "local":
            # Local (Docker) mode: returns (output, ssh_port)
            diag_output, ssh_port = self.sandbox.reset(fault_spec.id)
            container_id = "docker-container"  # Not used in HF mode
        else:
            # HF (subprocess) mode: returns just output
            diag_output = self.sandbox.reset(fault_spec.id)
            ssh_port = None
            container_id = "local-sandbox"

        # Create reward engine
        self.reward_engine = RewardEngine(fault_spec, max_steps=fault_spec.max_steps)

        # Initialize state
        self.current_state = SREState(
            container_id=container_id,
            fault_id=fault_spec.id,
            ssh_port=ssh_port or 0,
            step=0,
            prev_score=0.0,
            prev_command="",
            alert=fault_spec.alert,
            done=False,
        )

        # Return observation
        return SREObservation(
            terminal_output=diag_output,
            prompt="[sre@prod-01 ~]$",
            step=0,
            steps_remaining=fault_spec.max_steps,
            health_score=0.0,
            alert=fault_spec.alert,
        )

    def step(self, action: SREAction) -> SREObservation:
        """Execute one step (one command).

        Args:
            action: SREAction with command string

        Returns:
            SREObservation with reward/done/info embedded in reward, done, metadata fields
        """
        if not self.current_state or not self.reward_engine:
            raise RuntimeError("Environment not initialized; call reset() first")

        # Validate command
        if not action.command or "\n" in action.command:
            return SREObservation(
                terminal_output="ERROR: Invalid command",
                step=self.current_state.step,
                steps_remaining=self.reward_engine.max_steps - self.current_state.step,
                alert=self.current_state.alert,
                reward=-0.5,
                done=True,
                metadata={"error": "invalid_command"},
            )

        # Execute command via sandbox (same interface in both modes)
        output, exit_code = self.sandbox.exec(action.command, timeout=10)

        # Compute reward
        # In local mode: pass container object
        # In HF mode: pass None (reward system will use subprocess)
        container = None
        if self.mode == "local":
            container = self.sandbox.container

        reward, done, info = self.reward_engine.step(action.command, container)

        # Update state
        self.current_state.step += 1
        fault_spec = FaultRegistry.get(self.current_state.fault_id)

        # Format output as terminal
        formatted_output = output + "\n[sre@prod-01 ~]$"

        # Create observation — embed reward/done/info so OpenEnv can serialize it
        obs = SREObservation(
            terminal_output=formatted_output,
            prompt="[sre@prod-01 ~]$",
            step=self.current_state.step,
            steps_remaining=max(0, fault_spec.max_steps - self.current_state.step),
            health_score=info.get("health_score", 0.0),
            alert=self.current_state.alert,
            reward=reward,
            done=done,
            metadata=info,
        )

        # Clean up if done
        if done:
            if self.mode == "local":
                self.sandbox.release()

        return obs

    def close(self):
        """Close environment and clean up resources."""
        if self.mode == "local":
            self.sandbox.release()

    @property
    def state(self) -> State:
        """Get current environment state (OpenEnv compatible)."""
        if not self.current_state:
            return State(episode_id="", step_count=0)
        return State(
            episode_id=self.current_state.container_id,
            step_count=self.current_state.step,
        )
