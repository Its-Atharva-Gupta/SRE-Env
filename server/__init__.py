# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""SRE Terminal Agent environment server components."""

# Lazy import to avoid circular dependencies and missing optional dependencies
def __getattr__(name):
    if name == "SREEnvironment":
        from .SRE_Env_environment import SREEnvironment
        return SREEnvironment
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["SREEnvironment"]
