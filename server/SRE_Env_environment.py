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

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from openenv.core.env_server.interfaces import Environment
from openenv.core.env_server.types import State

try:
    from ..faults.registry import FaultRegistry
    from ..models import SREAction, SREObservation
    from ..reward.engine import RewardEngine
    from ..sandbox.pool import ContainerPool
    from ..sandbox.ssh import SSHSession
except ImportError:
    from faults.registry import FaultRegistry
    from models import SREAction, SREObservation
    from reward.engine import RewardEngine
    from sandbox.pool import ContainerPool
    from sandbox.ssh import SSHSession


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
            pool_size: Number of pre-warmed containers (default: 8)
        """
        self.container_pool = ContainerPool(pool_size=pool_size)
        self.current_state: Optional[SREState] = None
        self.ssh_session: Optional[SSHSession] = None
        self.reward_engine: Optional[RewardEngine] = None

    def reset(self, config: Optional[Dict] = None) -> SREObservation:
        """Reset environment to a new episode.

        Args:
            config: Optional config dict with 'tier' key to filter faults

        Returns:
            SREObservation with alert + diagnostic output
        """
        # Clean up previous episode
        if self.ssh_session:
            self.ssh_session.close()

        # Acquire container from pool
        container, ssh_port = self.container_pool.acquire()

        # Sample a fault (optionally filtered by tier)
        tier = config.get("tier") if config else None
        fault_spec = FaultRegistry.sample(tier=tier)

        # Inject the fault
        inject_cmd = f"bash /faults/inject/{fault_spec.inject_script}"
        container.exec_run(inject_cmd)

        # Create SSH session
        self.ssh_session = SSHSession(
            host="localhost", port=ssh_port, user="sre", password="fix123"
        )

        # Create reward engine
        self.reward_engine = RewardEngine(fault_spec, max_steps=fault_spec.max_steps)

        # Initialize state
        self.current_state = SREState(
            container_id=container.id,
            fault_id=fault_spec.id,
            ssh_port=ssh_port,
            step=0,
            prev_score=0.0,
            prev_command="",
            alert=fault_spec.alert,
            done=False,
        )

        # Run diagnostic suite
        diag_cmd = "systemctl --failed --no-pager; df -h; uptime; whoami"
        diag_output, _ = self.ssh_session.run(diag_cmd)

        # Return observation
        return SREObservation(
            terminal_output=diag_output,
            prompt="[sre@prod-01 ~]$",
            step=0,
            steps_remaining=fault_spec.max_steps,
            health_score=0.0,
            alert=fault_spec.alert,
        )

    def step(self, action: SREAction) -> Tuple[SREObservation, float, bool, Dict]:
        """Execute one step (one command).

        Args:
            action: SREAction with command string

        Returns:
            (observation, reward, done, info)
        """
        if not self.current_state or not self.ssh_session or not self.reward_engine:
            raise RuntimeError("Environment not initialized; call reset() first")

        # Validate command
        if not action.command or "\n" in action.command:
            return (
                SREObservation(
                    terminal_output="ERROR: Invalid command",
                    step=self.current_state.step,
                    steps_remaining=self.reward_engine.max_steps - self.current_state.step,
                    alert=self.current_state.alert,
                ),
                -0.5,
                True,
                {"error": "invalid_command"},
            )

        # Handle interactive commands (return error without running)
        interactive = ["vim", "nano", "emacs", "less", "more"]
        if any(cmd in action.command for cmd in interactive):
            return (
                SREObservation(
                    terminal_output=f"ERROR: Interactive command '{action.command}' not allowed",
                    step=self.current_state.step,
                    steps_remaining=self.reward_engine.max_steps - self.current_state.step,
                    alert=self.current_state.alert,
                ),
                -0.5,
                False,
                {"interactive_command": True},
            )

        # Execute command via SSH
        try:
            output, exit_code = self.ssh_session.run(action.command, timeout=10)
        except Exception as e:
            output = f"SSH ERROR: {str(e)}"
            exit_code = 1

        # Get container for reward computation
        container = self.container_pool.client.containers.get(
            self.current_state.container_id
        )

        # Compute reward
        fault_spec = FaultRegistry.get(self.current_state.fault_id)
        reward, done, info = self.reward_engine.step(action.command, container)

        # Update state
        self.current_state.step += 1

        # Format output as terminal
        formatted_output = output + "\n[sre@prod-01 ~]$"

        # Create observation
        obs = SREObservation(
            terminal_output=formatted_output,
            prompt="[sre@prod-01 ~]$",
            step=self.current_state.step,
            steps_remaining=max(0, fault_spec.max_steps - self.current_state.step),
            health_score=info.get("health_score", 0.0),
            alert=self.current_state.alert,
        )

        # Clean up if done
        if done:
            self.container_pool.release(container)
            if self.ssh_session:
                self.ssh_session.close()

        return obs, reward, done, info

    def close(self):
        """Close environment and clean up resources."""
        if self.ssh_session:
            self.ssh_session.close()
        if self.current_state:
            try:
                container = self.container_pool.client.containers.get(
                    self.current_state.container_id
                )
                self.container_pool.release(container)
            except Exception:
                pass

    @property
    def state(self) -> State:
        """Get current environment state (OpenEnv compatible)."""
        if not self.current_state:
            return State(episode_id="", step_count=0)
        return State(
            episode_id=self.current_state.container_id,
            step_count=self.current_state.step,
        )
