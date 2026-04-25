# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Fault registry and specifications for SRE environment."""

from .registry import FaultRegistry, FaultSpec, Stage

__all__ = [
    "FaultRegistry",
    "FaultSpec",
    "Stage",
]
