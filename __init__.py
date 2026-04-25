# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""SRE Terminal Agent RL Environment.

OpenEnv-compatible RL environment where an LLM agent acts as a Site Reliability
Engineer, SSHing into a broken Linux server to diagnose and fix faults.
Reward is computed from verified system state restoration, not model output text.
"""

from .client import SREEnv
from .models import SREAction, SREObservation

__all__ = [
    "SREAction",
    "SREObservation",
    "SREEnv",
]
