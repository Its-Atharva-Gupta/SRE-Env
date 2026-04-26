"""
Reward validation runner — execute before any LLM training.

Decision tree:
  components → sanity → variance

Exit 0 only when all three pass.
Run as: python tests/reward/run_all.py
"""
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

_TESTS_DIR = Path(__file__).parent


def _run_components() -> bool:
    """Run pure-function unit tests via pytest (no system access needed)."""
    print("\n" + "=" * 60)
    print("STEP 1/3 — component unit tests (pytest)")
    print("=" * 60)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(_TESTS_DIR / "test_reward_components.py"), "-v"],
        cwd=str(PROJECT_ROOT),
    )
    return result.returncode == 0


def _run_sanity() -> bool:
    """Run policy-ordering sanity test."""
    print("\n" + "=" * 60)
    print("STEP 2/3 — policy ordering sanity check")
    print("=" * 60)
    from tests.reward.test_reward_sanity import main as sanity_main
    return sanity_main() == 0


def _run_variance() -> bool:
    """Run reward variance check (GRPO signal strength)."""
    print("\n" + "=" * 60)
    print("STEP 3/3 — reward variance check (GRPO signal)")
    print("=" * 60)
    from tests.reward.test_reward_variance import main as variance_main
    return variance_main() == 0


def main() -> int:
    results: dict[str, bool] = {}

    results["components"] = _run_components()
    if not results["components"]:
        print("\nFAIL — component tests failed. Fix reward/components.py before proceeding.")
        return 1

    results["sanity"] = _run_sanity()
    if not results["sanity"]:
        print("\nFAIL — sanity check failed. Policy ordering is broken.")
        print("Compare per-step rewards to isolate which component is mis-shaped.")
        return 1

    results["variance"] = _run_variance()
    if not results["variance"]:
        print("\nFAIL — variance too low. GRPO relative-advantage signal will collapse.")
        print("Tune health-stage weights, action-quality bonuses, or terminal_reward scale.")
        return 1

    print("\n" + "=" * 60)
    print("ALL CHECKS PASSED — reward function is correctly shaped.")
    print("Safe to begin training.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
