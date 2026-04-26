"""SRE Terminal Agent RL Environment — subprocess-only implementation."""

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

from openenv.core.env_server.interfaces import Environment
from openenv.core.env_server.types import State

try:
    from faults.registry import FaultRegistry
    from models import SREAction, SREObservation
    from reward.engine import RewardEngine
    from sandbox.local_sandbox import LocalSandbox
except (ImportError, ModuleNotFoundError):
    try:
        from ..faults.registry import FaultRegistry
        from ..models import SREAction, SREObservation
        from ..reward.engine import RewardEngine
        from ..sandbox.local_sandbox import LocalSandbox
    except (ImportError, ModuleNotFoundError):
        parent_dir = str(Path(__file__).parent.parent)
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)
        from faults.registry import FaultRegistry
        from models import SREAction, SREObservation
        from reward.engine import RewardEngine
        from sandbox.local_sandbox import LocalSandbox


@dataclass
class SREState:
    """Server-side episode state (not exported to client)."""

    fault_id: str
    step: int
    prev_score: float
    prev_command: str
    used_diagnostics: set = field(default_factory=set)
    alert: str = ""
    done: bool = False


class SREEnvironment(Environment):
    """SRE Terminal Agent RL Environment.

    Agent receives a pager alert + runs shell commands via subprocess.
    Reward computed from verified system state — not from model output text.
    """

    SUPPORTS_CONCURRENT_SESSIONS: bool = True

    def __init__(self):
        self.sandbox = LocalSandbox()
        self.current_state: Optional[SREState] = None
        self.reward_engine: Optional[RewardEngine] = None

    def reset(self, config: Optional[Dict] = None) -> SREObservation:
        tier = config.get("tier") if config else None
        fault_spec = FaultRegistry.sample(tier=tier)

        diag_output = self.sandbox.reset(fault_spec.id)
        self.reward_engine = RewardEngine(fault_spec, max_steps=fault_spec.max_steps)
        self.current_state = SREState(
            fault_id=fault_spec.id,
            step=0,
            prev_score=0.0,
            prev_command="",
            alert=fault_spec.alert,
            done=False,
        )

        return SREObservation(
            terminal_output=diag_output,
            prompt="[sre@prod-01 ~]$",
            step=0,
            steps_remaining=fault_spec.max_steps,
            health_score=0.0,
            alert=fault_spec.alert,
        )

    def step(self, action: SREAction) -> SREObservation:
        if not self.current_state or not self.reward_engine:
            raise RuntimeError("Call reset() first")

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

        output, exit_code = self.sandbox.exec(action.command, timeout=10)

        reward, done, info = self.reward_engine.step(action.command)

        self.current_state.step += 1
        fault_spec = FaultRegistry.get(self.current_state.fault_id)

        return SREObservation(
            terminal_output=output + "\n[sre@prod-01 ~]$",
            prompt="[sre@prod-01 ~]$",
            step=self.current_state.step,
            steps_remaining=max(0, fault_spec.max_steps - self.current_state.step),
            health_score=info.get("health_score", 0.0),
            alert=self.current_state.alert,
            reward=reward,
            done=done,
            metadata=info,
        )

    def close(self):
        pass  # nothing to clean up — no containers

    @property
    def state(self) -> State:
        if not self.current_state:
            return State(episode_id="", step_count=0)
        return State(
            episode_id=self.current_state.fault_id,
            step_count=self.current_state.step,
        )
