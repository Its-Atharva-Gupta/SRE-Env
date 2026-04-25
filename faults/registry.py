# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Fault registry and specifications."""

import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class Stage:
    """Health check stage for a fault.

    Attributes:
        name: Stage name (e.g. "nginx_running")
        weight: Contribution to total health score (0.0-1.0, sum across all stages = 1.0)
        check_cmd: Shell command to execute; exit 0 = passing, non-zero = failing
    """
    name: str
    weight: float
    check_cmd: str


@dataclass
class FaultSpec:
    """Specification for a single fault type.

    Attributes:
        id: Unique fault identifier (e.g. "nginx_stopped")
        tier: Difficulty level (1=easy, 2=medium, 3=hard)
        alert: One-line pager alert that agent receives
        inject_script: Path to injection script relative to /faults/inject/
        health_stages: List of Stage objects for health scoring
        process_checks: List of (cmd, failure_reason) tuples for Layer 1 verification
        integrity_checks: List of (cmd, failure_reason) tuples for Layer 2 verification
        functional_check: Dict with 'cmd', 'expected_exit', and 'output_validator' for Layer 3
        max_steps: Max steps allowed for this fault (default 8)
    """
    id: str
    tier: int
    alert: str
    inject_script: str
    health_stages: List[Stage]
    process_checks: List[Tuple[str, str]]
    integrity_checks: List[Tuple[str, str]]
    functional_check: Dict[str, Any]
    max_steps: int = 8


class FaultRegistry:
    """Central registry of all fault definitions."""

    _REGISTRY: Dict[str, FaultSpec] = {}

    @classmethod
    def register(cls, fault_spec: FaultSpec) -> None:
        """Register a fault specification."""
        cls._REGISTRY[fault_spec.id] = fault_spec

    @classmethod
    def get(cls, fault_id: str) -> FaultSpec:
        """Get a fault specification by ID.

        Args:
            fault_id: Fault identifier

        Returns:
            FaultSpec for the given ID

        Raises:
            ValueError: If fault_id not found
        """
        if fault_id not in cls._REGISTRY:
            raise ValueError(f"Fault not found: {fault_id}")
        return cls._REGISTRY[fault_id]

    @classmethod
    def sample(cls, tier: Optional[int] = None) -> FaultSpec:
        """Sample a random fault specification.

        Args:
            tier: Optional tier filter (1, 2, or 3). If None, sample from all faults.

        Returns:
            Randomly selected FaultSpec

        Raises:
            ValueError: If no faults match the tier filter
        """
        if not cls._REGISTRY:
            raise ValueError("No faults registered")

        candidates = cls._REGISTRY.values()
        if tier is not None:
            candidates = [f for f in candidates if f.tier == tier]
            if not candidates:
                raise ValueError(f"No faults registered for tier {tier}")

        return random.choice(list(candidates))

    @classmethod
    def all_ids(cls) -> List[str]:
        """Get all registered fault IDs.

        Returns:
            List of fault IDs
        """
        return list(cls._REGISTRY.keys())

    @classmethod
    def all_faults(cls) -> List[FaultSpec]:
        """Get all registered fault specifications.

        Returns:
            List of FaultSpec objects
        """
        return list(cls._REGISTRY.values())


# =============================================================================
# Fault Definitions (Tier 1 and 2 — Phase 1)
# =============================================================================

# Tier 1: nginx_stopped
# Alert: ALERT: HTTP 502 errors spiking
# Fix: systemctl start nginx
NGINX_STOPPED = FaultSpec(
    id="nginx_stopped",
    tier=1,
    alert="ALERT: HTTP 502 errors spiking",
    inject_script="nginx_stopped.sh",
    health_stages=[
        Stage(
            name="nginx_process",
            weight=0.5,
            check_cmd="pgrep -f 'nginx: master' > /dev/null && exit 0 || exit 1",
        ),
        Stage(
            name="nginx_listening",
            weight=0.5,
            check_cmd="ss -tlnp 2>/dev/null | grep -q ':80 ' && exit 0 || exit 1",
        ),
    ],
    process_checks=[
        ("systemctl is-active nginx", "nginx service not active"),
        ("pgrep -f 'nginx: master'", "nginx master process not found"),
    ],
    integrity_checks=[
        ("test -f /etc/nginx/nginx.conf", "/etc/nginx/nginx.conf does not exist"),
        ("test -d /etc/nginx/sites-enabled", "sites-enabled directory missing"),
    ],
    functional_check={
        "cmd": "curl -sf http://localhost/",
        "expected_exit": 0,
        "output_validator": lambda out: "200" in str(out) or len(out) > 0,
    },
    max_steps=8,
)

# Tier 2: broken_nginx_config
# Alert: ALERT: nginx config parsing error
# Fix: fix the "listen BROKEN" line in /etc/nginx/nginx.conf
BROKEN_NGINX_CONFIG = FaultSpec(
    id="broken_nginx_config",
    tier=2,
    alert="ALERT: nginx config parsing error",
    inject_script="broken_nginx_config.sh",
    health_stages=[
        Stage(
            name="nginx_syntax_valid",
            weight=0.6,
            check_cmd="nginx -t -c /etc/nginx/nginx.conf 2>&1 | grep -q 'successful' && exit 0 || exit 1",
        ),
        Stage(
            name="nginx_running",
            weight=0.4,
            check_cmd="pgrep -f 'nginx: master' > /dev/null && exit 0 || exit 1",
        ),
    ],
    process_checks=[
        ("systemctl is-active nginx", "nginx service not active"),
        ("pgrep -f 'nginx: master'", "nginx master process not found"),
    ],
    integrity_checks=[
        ("! grep -q 'listen BROKEN' /etc/nginx/nginx.conf", "bad 'listen BROKEN' line still in config"),
        ("grep -q 'listen 80' /etc/nginx/nginx.conf", "valid listen 80 line not found"),
    ],
    functional_check={
        "cmd": "curl -sf http://localhost/",
        "expected_exit": 0,
        "output_validator": lambda out: len(out) > 0,
    },
    max_steps=8,
)

# Tier 1: log_permissions
LOG_PERMISSIONS = FaultSpec(
    id="log_permissions",
    tier=1,
    alert="ALERT: nginx write errors",
    inject_script="log_permissions.sh",
    health_stages=[
        Stage(
            name="nginx_process",
            weight=0.4,
            check_cmd="pgrep -f 'nginx: master' > /dev/null && exit 0 || exit 1",
        ),
        Stage(
            name="log_writable",
            weight=0.6,
            check_cmd="test -w /var/log/nginx || exit 1",
        ),
    ],
    process_checks=[
        ("systemctl is-active nginx", "nginx service not active"),
        ("test -d /var/log/nginx", "nginx log directory missing"),
    ],
    integrity_checks=[
        ("test -r /var/log/nginx", "nginx log directory not readable"),
        ("stat -c '%a' /var/log/nginx | grep -q '^7'", "nginx log directory has wrong permissions"),
    ],
    functional_check={
        "cmd": "curl -s http://localhost/ > /tmp/test.html && test -f /var/log/nginx/access.log && grep -q 'GET' /var/log/nginx/access.log",
        "expected_exit": 0,
        "output_validator": lambda out: True,
    },
    max_steps=8,
)

# Tier 1: missing_config
MISSING_CONFIG = FaultSpec(
    id="missing_config",
    tier=1,
    alert="ALERT: nginx config missing",
    inject_script="missing_config.sh",
    health_stages=[
        Stage(
            name="config_exists",
            weight=0.4,
            check_cmd="test -f /etc/nginx/sites-enabled/default && exit 0 || exit 1",
        ),
        Stage(
            name="nginx_running",
            weight=0.6,
            check_cmd="pgrep -f 'nginx: master' > /dev/null && exit 0 || exit 1",
        ),
    ],
    process_checks=[
        ("test -f /etc/nginx/sites-enabled/default", "default config not found"),
        ("systemctl is-active nginx", "nginx not running"),
    ],
    integrity_checks=[
        ("test -f /etc/nginx/sites-enabled/default", "default config missing"),
    ],
    functional_check={
        "cmd": "curl -sf http://localhost/",
        "expected_exit": 0,
        "output_validator": lambda out: len(out) > 0,
    },
    max_steps=8,
)

# Tier 2: disk_full
DISK_FULL = FaultSpec(
    id="disk_full",
    tier=2,
    alert="ALERT: disk space critically low",
    inject_script="disk_full.sh",
    health_stages=[
        Stage(
            name="disk_available",
            weight=0.5,
            check_cmd="df /var/log | awk 'NR==2 {print $5}' | grep -qE '^[0-8][0-9]|^9[0-9]' && exit 1 || exit 0",
        ),
        Stage(
            name="nginx_running",
            weight=0.5,
            check_cmd="pgrep -f 'nginx: master' > /dev/null && exit 0 || exit 1",
        ),
    ],
    process_checks=[
        ("df /var/log | awk 'NR==2 {print $5+0}' | awk '{if($1>85) exit 1; else exit 0}'", "disk usage still high"),
    ],
    integrity_checks=[
        ("test -d /var/log", "/var/log directory missing"),
    ],
    functional_check={
        "cmd": "dd if=/dev/zero of=/tmp/test_write.bin bs=1M count=10 && rm /tmp/test_write.bin",
        "expected_exit": 0,
        "output_validator": lambda out: True,
    },
    max_steps=8,
)

# Tier 2: broken_symlink
BROKEN_SYMLINK = FaultSpec(
    id="broken_symlink",
    tier=2,
    alert="ALERT: critical symlink broken",
    inject_script="broken_symlink.sh",
    health_stages=[
        Stage(
            name="symlink_valid",
            weight=0.7,
            check_cmd="test -L /usr/bin/python3 && test -e /usr/bin/python3 && exit 0 || exit 1",
        ),
        Stage(
            name="python_executable",
            weight=0.3,
            check_cmd="python3 --version > /dev/null 2>&1 && exit 0 || exit 1",
        ),
    ],
    process_checks=[
        ("python3 --version", "python3 not working"),
    ],
    integrity_checks=[
        ("test -e /usr/bin/python3", "python3 symlink broken"),
    ],
    functional_check={
        "cmd": "python3 -c 'print(\"ok\")'",
        "expected_exit": 0,
        "output_validator": lambda out: "ok" in (out.decode(errors="replace") if isinstance(out, bytes) else out),
    },
    max_steps=8,
)

# Tier 2: zombie_process
ZOMBIE_PROCESS = FaultSpec(
    id="zombie_process",
    tier=2,
    alert="ALERT: process count anomaly",
    inject_script="zombie_process.sh",
    health_stages=[
        Stage(
            name="zombie_count",
            weight=0.6,
            check_cmd="ps aux | grep -c 'Z' | awk '{if($1<=2) exit 0; else exit 1}'",
        ),
        Stage(
            name="system_responsive",
            weight=0.4,
            check_cmd="uptime > /dev/null && exit 0 || exit 1",
        ),
    ],
    process_checks=[
        ("ps aux | grep -c 'Z' | awk '{if($1<=2) exit 0; else exit 1}'", "too many zombie processes"),
    ],
    integrity_checks=[
        ("! ps aux | grep -qP '\bZ\b'", "zombie processes still present"),
    ],
    functional_check={
        "cmd": "echo test",
        "expected_exit": 0,
        "output_validator": lambda out: "test" in out,
    },
    max_steps=8,
)

# Tier 3: bad_cron
BAD_CRON = FaultSpec(
    id="bad_cron",
    tier=3,
    alert="ALERT: cron job failing",
    inject_script="bad_cron.sh",
    health_stages=[
        Stage(
            name="cron_syntax_valid",
            weight=0.5,
            check_cmd="! crontab -l 2>&1 | grep -q 'bad syntax'",
        ),
        Stage(
            name="system_responsive",
            weight=0.5,
            check_cmd="uptime > /dev/null && exit 0 || exit 1",
        ),
    ],
    process_checks=[
        ("pgrep cron > /dev/null || pgrep crond > /dev/null", "cron daemon not running"),
    ],
    integrity_checks=[
        ("! crontab -l 2>&1 | grep -q 'bad syntax'", "cron still has bad syntax"),
    ],
    functional_check={
        "cmd": "echo test",
        "expected_exit": 0,
        "output_validator": lambda out: "test" in (out.decode(errors="replace") if isinstance(out, bytes) else out),
    },
    max_steps=8,
)

# Tier 3: multi_fault
MULTI_FAULT = FaultSpec(
    id="multi_fault",
    tier=3,
    alert="ALERT: multiple system failures",
    inject_script="multi_fault.sh",
    health_stages=[
        Stage(
            name="nginx_running",
            weight=0.4,
            check_cmd="pgrep -f 'nginx: master' > /dev/null && exit 0 || exit 1",
        ),
        Stage(
            name="log_writable",
            weight=0.3,
            check_cmd="test -w /var/log/nginx || exit 1",
        ),
        Stage(
            name="disk_available",
            weight=0.3,
            check_cmd="df /var/log | awk 'NR==2 {print $5}' | grep -qE '^[0-8][0-9]|^9[0-9]' && exit 1 || exit 0",
        ),
    ],
    process_checks=[
        ("systemctl is-active nginx", "nginx not running"),
        ("test -w /var/log/nginx", "log directory not writable"),
    ],
    integrity_checks=[
        ("test -d /var/log/nginx", "log directory missing"),
        ("test -r /var/log/nginx", "log directory not readable"),
    ],
    functional_check={
        "cmd": "curl -sf http://localhost/",
        "expected_exit": 0,
        "output_validator": lambda out: len(out) > 0,
    },
    max_steps=8,
)

# Register all faults
FaultRegistry.register(NGINX_STOPPED)
FaultRegistry.register(LOG_PERMISSIONS)
FaultRegistry.register(MISSING_CONFIG)
FaultRegistry.register(BROKEN_NGINX_CONFIG)
FaultRegistry.register(DISK_FULL)
FaultRegistry.register(BROKEN_SYMLINK)
FaultRegistry.register(ZOMBIE_PROCESS)
FaultRegistry.register(BAD_CRON)
FaultRegistry.register(MULTI_FAULT)
