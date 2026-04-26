# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""SRE Terminal Agent RL Environment Client."""

from typing import Dict, Tuple

from openenv.core import EnvClient
from openenv.core.client_types import StepResult
from openenv.core.env_server.types import State

from models import SREAction, SREObservation


class SREEnv(EnvClient[SREAction, SREObservation, State]):
    """
    Client for the SRE Terminal Agent RL Environment.

    This client maintains a persistent WebSocket connection to the environment server,
    enabling efficient multi-step interactions with lower latency.
    Each client instance has its own dedicated episode session on the server.

    The agent receives a pager alert and SSH credentials to a sandboxed container,
    then outputs shell commands to diagnose and fix system faults.
    Reward is computed from verified system state restoration.

    Example:
        >>> # Connect to a running server
        >>> with SREEnv(base_url="http://localhost:8000") as env:
        ...     obs = env.reset()
        ...     print(obs.alert)  # "ALERT: HTTP 502 errors spiking"
        ...     print(env.render())
        ...
        ...     for i in range(8):
        ...         action = SREAction(command="systemctl status nginx")
        ...         obs, reward, done, info = env.step(action)
        ...         print(f"Step {i+1}, Reward: {reward:.2f}, Done: {done}")
        ...         if done:
        ...             break

    Example with Docker:
        >>> # Automatically start container and connect
        >>> client = SREEnv.from_docker_image("sre-server:latest")
        >>> try:
        ...     obs = client.reset()
        ...     obs, reward, done, info = client.step(SREAction(command="uptime"))
        ... finally:
        ...     client.close()
    """

    async def reset(self, **kwargs):
        """
        Force reconnect before every reset.
        Server closes WebSocket on done=True — _ws is stale but not None,
        so _ensure_connected() skips reconnect. We must null it out manually.
        """
        # Null out the stale websocket so _ensure_connected reconnects
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None  # force _ensure_connected to reconnect

        return await super().reset(**kwargs)    

    def _step_payload(self, action: SREAction) -> Dict:
        """Convert SREAction to JSON payload for step message.

        Args:
            action: SREAction instance with command

        Returns:
            Dictionary representation suitable for JSON encoding
        """
        return {"command": action.command}

    def _parse_result(self, payload: Dict) -> StepResult[SREObservation]:
        """Parse server response into StepResult[SREObservation].

        Args:
            payload: JSON response data from server

        Returns:
            StepResult with SREObservation and reward
        """
        obs_data = payload.get("observation", {})
        observation = SREObservation(
            terminal_output=obs_data.get("terminal_output", ""),
            prompt=obs_data.get("prompt", "[sre@prod-01 ~]$"),
            step=obs_data.get("step", 0),
            steps_remaining=obs_data.get("steps_remaining", 8),
            health_score=obs_data.get("health_score", 0.0),
            alert=obs_data.get("alert", ""),
            done=payload.get("done", False),
            reward=payload.get("reward", 0.0),
            metadata=obs_data.get("metadata", {}),
        )

        return StepResult(
            observation=observation,
            reward=payload.get("reward"),
            done=payload.get("done", False),
        )

    def _parse_state(self, payload: Dict) -> State:
        """Parse server response into State object.

        Args:
            payload: JSON response from state request

        Returns:
            State object with episode_id and step_count
        """
        return State(
            episode_id=payload.get("episode_id"),
            step_count=payload.get("step_count", 0),
        )

    def render(self) -> str:
        """Render the last observation as a terminal session string.

        Returns:
            Pretty-printed terminal output
        """
        if not self.last_obs:
            return "[Environment not initialized]"

        lines = [
            "=" * 80,
            f"ALERT: {self.last_obs.alert}",
            "=" * 80,
            "",
            self.last_obs.terminal_output,
            "",
            f"Health Score: {self.last_obs.health_score:.1%}",
            f"Step: {self.last_obs.step} / {self.last_obs.step + self.last_obs.steps_remaining}",
            "",
        ]
        return "\n".join(lines)
