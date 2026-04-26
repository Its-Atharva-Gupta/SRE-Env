"""
Variance check: verify the reward function produces sufficient spread for GRPO.

Runs 50 episodes with a random policy across all registered faults.
Requires nginx installed on the host.

A standard deviation below 0.5 means all policies score similarly, which
collapses GRPO's relative-advantage signal — there is nothing to learn from.

Exit 0 if stdev > 0.5, exit 1 otherwise.
"""
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from faults.registry import FaultRegistry  # noqa: E402
from reward.engine import RewardEngine  # noqa: E402

EPISODES = 50
MAX_STEPS = 8

RANDOM_COMMANDS = [
    "ls",
    "systemctl --failed",
    "nginx -t",
    "journalctl -xe",
    "df -h",
    "cat /etc/nginx/nginx.conf",
    "systemctl restart nginx",
    "ps aux",
    "systemctl status nginx",
    "chmod 755 /var/log/nginx/",
]


class _Sandbox:
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
        subprocess.run(["bash", str(inject)], capture_output=True, timeout=30, check=False)
        time.sleep(0.5)
        output, _ = self.exec("systemctl --failed --no-pager; df -h; uptime; whoami")
        return output

    def exec(self, command: str, timeout: int = 15) -> tuple[str, int]:
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


def run_episode(fault_id: str, sandbox: _Sandbox) -> float:
    """Run one episode with a random command policy. Returns total reward."""
    fault_spec = FaultRegistry.get(fault_id)
    sandbox.reset(fault_id)
    engine = RewardEngine(fault_spec, max_steps=MAX_STEPS)

    total = 0.0
    for _ in range(MAX_STEPS):
        cmd = random.choice(RANDOM_COMMANDS)
        sandbox.exec(cmd, timeout=15)
        reward, done, _ = engine.step(cmd)
        total += reward
        if done:
            break

    return total


def _histogram(values: list[float]) -> dict[str, int]:
    buckets: dict[str, int] = {"<-1": 0, "-1to0": 0, "0to1": 0, "1to2": 0, ">2": 0}
    for v in values:
        if v < -1:
            buckets["<-1"] += 1
        elif v < 0:
            buckets["-1to0"] += 1
        elif v < 1:
            buckets["0to1"] += 1
        elif v < 2:
            buckets["1to2"] += 1
        else:
            buckets[">2"] += 1
    return buckets


def main() -> int:
    fault_ids = FaultRegistry.all_ids()
    if not fault_ids:
        print("FAIL: no faults registered in FaultRegistry.")
        return 1

    print(f"Running {EPISODES} episodes across {len(fault_ids)} faults …\n")

    try:
        sandbox = _Sandbox()
    except Exception as e:
        print(f"ERROR creating sandbox: {e}")
        return 1

    rewards: list[float] = []
    for ep in range(EPISODES):
        fault_id = random.choice(fault_ids)
        try:
            r = run_episode(fault_id, sandbox)
        except Exception as e:
            print(f"  [ep {ep + 1}] ERROR ({fault_id}): {e}")
            r = 0.0
        rewards.append(r)

        if (ep + 1) % 10 == 0:
            print(f"  {ep + 1:>3}/{EPISODES} done  (last fault: {fault_id}, reward: {r:+.3f})")

    mean = statistics.mean(rewards)
    stdev = statistics.stdev(rewards)
    lo = min(rewards)
    hi = max(rewards)
    hist = _histogram(rewards)

    print(f"\nMean:   {mean:+.3f}")
    print(f"Stdev:  {stdev:.3f}   ← {'PASS' if stdev > 0.5 else 'FAIL'} (need > 0.5)")
    print(f"Min:    {lo:+.3f}")
    print(f"Max:    {hi:+.3f}")
    print(f"\nDistribution ({EPISODES} episodes):")
    for bucket, count in hist.items():
        bar = "█" * count
        print(f"  {bucket:<8} {count:>3}  {bar}")

    if stdev <= 0.5:
        print(
            "\nFAIL — stdev too low.\n"
            "Low reward variance collapses GRPO's relative-advantage signal.\n"
            "Fix: ensure health-stage weights create meaningful score spread,\n"
            "     action-quality bonuses are distinct from one another, and\n"
            "     terminal_reward is large enough to separate fixed vs not-fixed."
        )
        return 1

    print("\nPASS — sufficient variance for GRPO training.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
