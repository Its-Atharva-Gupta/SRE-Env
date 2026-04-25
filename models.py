# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""
Data models for the SRE Terminal Agent RL Environment.

OpenEnv-compatible observation and action types for SRE agent training.
"""

from openenv.core.env_server.types import Action, Observation
from pydantic import Field, field_validator


class SREAction(Action):
    """Action: single shell command to execute on the remote server."""

    command: str = Field(..., description="Shell command to execute (single line, max 500 chars)")

    @field_validator("command", mode="before")
    @classmethod
    def validate_command(cls, v):
        """Strip whitespace, reject empty, enforce single-line and 500 char limit."""
        if not isinstance(v, str):
            raise ValueError("command must be a string")
        v = v.strip()
        if not v:
            raise ValueError("command cannot be empty")
        if "\n" in v:
            raise ValueError("command must be a single line")
        if len(v) > 500:
            v = v[:500]
        return v


class SREObservation(Observation):
    """Observation: terminal output, health state, and context from the remote server."""

    terminal_output: str = Field(
        default="", description="Raw stdout+stderr from the last command"
    )
    prompt: str = Field(
        default="[sre@prod-01 ~]$", description="Shell prompt line (e.g. [sre@prod-01 ~]$)"
    )
    step: int = Field(default=0, description="Current step number (1-indexed)")
    steps_remaining: int = Field(default=8, description="Steps remaining in episode")
    health_score: float = Field(
        default=0.0, description="System health score from 0.0 to 1.0"
    )
    alert: str = Field(default="", description="Original pager alert message (repeated every step)")
