"""
Sanity check: verify reward ordering across four policy archetypes.

Requires nginx installed on the host and scripts/restore.sh + scripts/inject/ present.

Policies tested:
  optimal        -- diagnostic sequence then targeted fix
  wrong_harmless -- unrelated-but-safe commands, no fix attempted
  random_spam    -- ls x 8 (repeat spam)
  destructive    -- ls then rm -rf / (episode-ending penalty)

Key assertion: optimal > wrong_harmless > random_spam > destructive

Exit 0 on success, 1 on any ordering violation.
"""
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from faults.registry import FaultRegistry  # noqa: E402
from reward.engine import RewardEngine  # noqa: E402

FAULT_ID = "broken_nginx_config"

_NEVER_EXEC = frozenset([
    "rm -rf /",
    "rm -rf /*",
    "mkfs",
    ":(){:|:&};:",
    "chmod -R 000 /",
    "> /etc/passwd",
    "dd if=/dev/zero of=/dev/sd",
])

POLICIES: dict[str, list[str]] = {
    "optimal": [
        "systemctl --failed",
        "nginx -t",
        "sed -i 's/listen BROKEN/listen 80/' /etc/nginx/nginx.conf",
        "systemctl restart nginx",
    ],
    "random_spam": ["ls"] * 8,
    "destructive": [
        "ls",
        "rm -rf /",
    ],
    "wrong_harmless": [
        "systemctl restart postgresql",
        "apt-get update",
        "df -h",
        "ps aux",
    ],
}


class _Sandbox:
    """Subprocess sandbox. Requires nginx on the host."""

    def _find_script(self, kind: str, name: str = "") -> Path:
        if kind == "restore":
            candidates = [
                Path("/app/env/scripts/restore.sh"),
                PROJECT_ROOT / "scripts" / "restore.sh",
            ]
        else:
            candidates = [
                Path(f"/app/env/scripts/inject/{name}.sh"),
                PROJECT_ROOT / "scripts" / "inject" / f"{name}.sh",
                Path(f"/app/env/faults/scripts/inject/{name}.sh"),
                PROJECT_ROOT / "faults" / "scripts" / "inject" / f"{name}.sh",
            ]
        for p in candidates:
            if p.exists():
                return p
        raise FileNotFoundError(f"Script not found: {kind}/{name}")

    def reset(self, fault_id: str) -> str:
        restore = self._find_script("restore")
        subprocess.run(["bash", str(restore)], capture_output=True, timeout=30, check=False)
        time.sleep(0.5)
        inject = self._find_script("inject", fault_id)
        result = subprocess.run(
            ["bash", str(inject)], capture_output=True, timeout=30, check=False
        )
        if result.returncode != 0:
            print(f"  [warn] inject exited {result.returncode}: "
                  f"{result.stderr.decode(errors='replace').strip()}")
        time.sleep(0.5)
        output, _ = self.exec("systemctl --failed --no-pager; df -h; uptime; whoami")
        return output

    def exec(self, command: str, timeout: int = 60) -> tuple[str, int]:
        try:
            r = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                timeout=timeout, check=False,
            )
            return r.stdout + r.stderr, r.returncode
        except subprocess.TimeoutExpired:
            return "[timeout]", 1

    def release(self) -> None:
        pass


StepDetail = tuple[str, float, float, list[str]]


def run_policy(name: str, commands: list[str]) -> tuple[float, list[StepDetail]]:
    """Reset the fault, run each command through the reward engine, return results."""
    fault_spec = FaultRegistry.get(FAULT_ID)
    sandbox = _Sandbox()
    sandbox.reset(FAULT_ID)
    engine = RewardEngine(fault_spec, max_steps=fault_spec.max_steps)

    total = 0.0
    steps: list[StepDetail] = []

    for cmd in commands:
        if not any(d in cmd for d in _NEVER_EXEC):
            sandbox.exec(cmd, timeout=60)

        reward, done, info = engine.step(cmd)
        total += reward

        health = info.get("health_score", 0.0)
        stages = info.get("passing_stages", [])
        steps.append((cmd, reward, health, stages))

        if done:
            break

    sandbox.release()
    return total, steps


def main() -> int:
    print(f"Fault: {FAULT_ID}\n")

    totals: dict[str, float] = {}
    for name, commands in POLICIES.items():
        print(f"--- policy: {name} ---")
        try:
            total, steps = run_policy(name, commands)
        except (FileNotFoundError, Exception) as e:
            print(f"  ERROR: {e}")
            return 1

        totals[name] = total
        for cmd, r, h, stages in steps:
            print(f"  {cmd:<45} r={r:+.3f}  health={h:.2f}  stages={stages}")
        print(f"  TOTAL: {total:+.3f}\n")

    print("=== ORDERING ASSERTIONS ===")
    ordering_checks = [
        ("optimal > wrong_harmless", totals["optimal"], totals["wrong_harmless"]),
        ("wrong_harmless > random_spam", totals["wrong_harmless"], totals["random_spam"]),
        ("random_spam > destructive", totals["random_spam"], totals["destructive"]),
    ]

    failures: list[str] = []
    for label, left, right in ordering_checks:
        passed = left > right
        status = "PASS" if passed else "FAIL"
        print(f"  {label:<35} {status}", end="")
        if not passed:
            print(f"  (got {left:+.3f} vs {right:+.3f}, delta={left - right:+.3f})", end="")
            failures.append(label)
        print()

    print("\n=== RANGE HINTS (informational) ===")
    hints = [
        ("optimal",        "expected ≥ 2.5",        totals["optimal"] >= 2.5),
        ("wrong_harmless", "expected [-0.3, 0.2]",  -0.3 <= totals["wrong_harmless"] <= 0.2),
        ("random_spam",    "expected [-1.5, -0.2]", -1.5 <= totals["random_spam"] <= -0.2),
        ("destructive",    "expected ≈ -2.0",        totals["destructive"] <= -1.9),
    ]
    for name, hint, ok in hints:
        status = "ok" if ok else "warn"
        print(f"  {name:<15} {hint:<25} [{status}]  actual={totals[name]:+.3f}")

    print()
    if failures:
        print(f"FAIL — ordering broken: {failures}")
        print("Examine per-step rewards above to find the broken shaping.")
        return 1

    print("PASS — all ordering assertions hold.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
