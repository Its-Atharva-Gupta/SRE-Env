---
title: SRE Terminal Agent RL Environment
emoji: 🔧
colorFrom: blue
colorTo: green
sdk: docker
pinned: false
app_port: 8000
base_path: /web
tags:
  - openenv
  - reinforcement-learning
  - site-reliability-engineering
---

# SRE Terminal Agent RL Environment

An OpenEnv-compatible reinforcement learning environment where LLM agents act as Site Reliability Engineers (SREs). Agents SSH into broken Linux servers, diagnose faults using shell commands, and receive dense reward signals based on **verified system state restoration** — not text generation.

## Overview

This environment simulates real SRE troubleshooting:
- **9 fault types** across 3 difficulty tiers (easy, medium, hard)
- **Real Linux containers** with nginx, cron, filesystem, and process state faults
- **Three-layer verification** to prevent degenerate fixes (e.g., `chmod 777 /` to bypass permission issues)
- **Dense reward shaping** with progress tracking, diagnostic bonuses, and efficiency rewards
- **Pre-warmed container pools** for sub-second episode resets during training

## Quick Start

### Build the Docker Image

```bash
docker build -t sre-env:latest -f server/Dockerfile .
```

### Run the Server

```bash
docker run -d --name sre-env-server \
  -p 8000:8000 \
  sre-env:latest
```

The server starts on `http://localhost:8000` with OpenEnv endpoints:
- **HTTP**: `/reset`, `/step`, `/state`, `/schema`
- **WebSocket**: `/ws` for persistent low-latency sessions
- **Web UI**: `/web` for interactive exploration
- **Docs**: `/docs` for OpenAPI documentation

### Client Example

```python
from SRE_Env import SREAction, SREObservation, SREEnv

# Create client
env = SREEnv(base_url="http://localhost:8000")

# Reset — agent receives a random fault and alert message
obs = env.reset()
print(f"Alert: {obs.alert}")
print(f"Health: {obs.health_score}")
print(f"Steps remaining: {obs.steps_remaining}")

# Episode loop
done = False
total_reward = 0.0

while not done:
    # Agent decides on a diagnostic command
    command = "systemctl status nginx"  # example
    
    action = SREAction(command=command)
    obs, reward, done, info = env.step(action)
    
    total_reward += reward
    print(f"Step {obs.step}: reward={reward:.3f}, health={obs.health_score:.2f}")
    print(f"Output:\n{obs.terminal_output}")
    
    if done:
        print(f"Episode finished. Total reward: {total_reward:.2f}")

env.close()
```

## Architecture

### High-Level Flow

```
1. reset()
   ├─ Acquire container from pre-warmed pool
   ├─ Sample random fault (tier-filtered)
   ├─ Inject fault (runs bash script)
   ├─ Create SSH session to container
   ├─ Run diagnostic suite (uptime, df, systemctl --failed, etc.)
   └─ Return alert + initial observation

2. step(action: SREAction)
   ├─ Validate command (not empty, not multi-line, < 500 chars)
   ├─ Execute via SSH (timeout: 10s)
   ├─ Compute multi-component reward
   │  ├─ Health score (weighted stage checks)
   │  ├─ Progress delta (health improvement)
   │  ├─ Action quality (diagnostic bonuses, one-time)
   │  ├─ Penalties (step cost, repeats, destructive)
   │  └─ Terminal reward (if verified fixed)
   ├─ If health >= 1.0: run three-layer verification
   │  ├─ Layer 1: Process state (systemctl, pgrep, etc.)
   │  ├─ Layer 2: Integrity (configs, permissions, no bad content)
   │  └─ Layer 3: Functional (curl, write test, etc.)
   ├─ Return (obs, reward, done, info)
   └─ If done: release container, close SSH

3. close()
   └─ Return container to pool, cleanup
```

### Component Modules

| Module | Purpose |
|--------|---------|
| `models.py` | SREAction, SREObservation dataclasses with validators |
| `faults/registry.py` | FaultSpec definitions, FaultRegistry (get/sample/all_ids) |
| `reward/health.py` | HealthScorer — weighted multi-stage health checks |
| `reward/verifier.py` | Three-layer verification (process/integrity/functional) |
| `reward/components.py` | Pure reward functions (progress, quality, penalties, terminal) |
| `reward/engine.py` | RewardEngine — orchestrates all reward components per episode |
| `sandbox/ssh.py` | SSHSession wrapper (paramiko) — stateless shell execution |
| `sandbox/pool.py` | ContainerPool — pre-warmed Docker containers with background spawning |
| `server/sre_environment.py` | SREEnvironment(Environment) — OpenEnv episode loop |
| `server/app.py` | FastAPI + OpenEnv HTTP/WebSocket server |
| `client.py` | SREEnv(EnvClient) — client-side interface |

## Faults

All 9 faults are pre-defined with:
- **Health stages**: Multi-stage scoring (weighted checks summing to 1.0)
- **Process checks (Layer 1)**: Fast checks (systemctl, pgrep, test)
- **Integrity checks (Layer 2)**: Guard against degenerate fixes
- **Functional check (Layer 3)**: End-to-end validation (curl, write test)

### Tier 1 — Easy

**nginx_stopped**
- Simulates: Web server crashed after deployment
- Injection: `pkill -9 nginx`
- Alert: "ALERT: HTTP 502 errors spiking"
- Fix: `systemctl start nginx`
- Health: nginx process + listening port
- Verification: curl returns 200

**log_permissions**
- Simulates: Permissions issue preventing logging
- Injection: `chmod 000 /var/log/nginx`
- Alert: "ALERT: nginx write errors"
- Fix: `chmod 755 /var/log/nginx`
- Health: nginx process + log dir writable
- Verification: nginx can append to access.log

**missing_config**
- Simulates: Config deleted during emergency change
- Injection: `rm /etc/nginx/sites-enabled/default`
- Alert: "ALERT: nginx config missing"
- Fix: Restore config file
- Health: config file exists + nginx running
- Verification: curl returns 200

### Tier 2 — Medium

**broken_nginx_config**
- Simulates: Bad syntax in config (typo, bad directive)
- Injection: Inject `listen BROKEN` into nginx.conf
- Alert: "ALERT: nginx config parsing error"
- Fix: Remove bad line, fix to `listen 80`
- Health: Config syntax valid (nginx -t) + process running
- Verification: curl returns 200

**disk_full**
- Simulates: Disk space exhausted, nginx cannot write
- Injection: `dd` a 900MB file into /var/log
- Alert: "ALERT: disk space critically low"
- Fix: Delete large files, clean up logs
- Health: Disk usage < 80% + nginx running
- Verification: Can write 10MB test file

**broken_symlink**
- Simulates: Critical symlink dangling (e.g., python3 broken)
- Injection: Make `/usr/bin/python3` point to nonexistent target
- Alert: "ALERT: critical symlink broken"
- Fix: Restore symlink to actual python executable
- Health: Symlink valid + python3 executable
- Verification: `python3 --version` succeeds

**zombie_process**
- Simulates: Process count anomaly (zombies), system stress
- Injection: Fork bomb (controlled, limited)
- Alert: "ALERT: process count anomaly"
- Fix: Find and kill parent processes creating zombies
- Health: Zombie count low + system responsive
- Verification: uptime succeeds

### Tier 3 — Hard

**bad_cron**
- Simulates: Cron syntax corruption causing job failures
- Injection: Inject malformed cron entry
- Alert: "ALERT: cron job failing"
- Fix: Fix cron syntax
- Health: No bad cron syntax in crontab
- Verification: cron daemon running

**multi_fault**
- Simulates: Multiple simultaneous failures (cascading)
- Injection: `pkill -9 nginx` + `chmod 000 /var/log/nginx`
- Alert: "ALERT: multiple system failures"
- Fix: Both faults must be fixed
- Health: nginx running + logs writable + disk OK
- Verification: curl + write test both succeed

## Reward Structure

All rewards are computed from **verified system state**, never from text output.

### Reward Components

| Component | Typical Range | Trigger |
|-----------|---------------|---------|
| Progress | -0.5 to +0.8 | Health score improvement |
| Action Quality | 0 to +0.08 | Diagnostic bonuses (one-time) |
| Step Cost | -0.02 | Every step |
| Repeat Penalty | -0.15 | Exact same command twice |
| Interactive Penalty | -0.50 | vim/nano/less/more (hangs) |
| Destruction Penalty | -2.0 | Dangerous commands (episode ends) |
| Terminal Reward | +2.5 to +3.5 | All three layers verify |

### Reward Formulas

#### Progress Reward
```python
delta = current_health - prev_health
if delta > 0:
    return delta * 2.0      # rewards improvement
elif delta < 0:
    return delta * 1.0      # mild penalty for regression
else:
    return 0.0
```

#### Action Quality Reward
One-time bonuses for systematic diagnostics:
```
journalctl          → +0.08 (logs)
systemctl status    → +0.08 (service state)
systemctl --failed  → +0.06 (failed units)
nginx -t            → +0.07 (config validation)
tail <log>          → +0.05 (recent events)
cat <log>           → +0.05 (full logs)
ss - / netstat      → +0.04 (network state)
df - / du -         → +0.04 (disk usage)
ps aux / ps -ef     → +0.04 (process list)
dmesg               → +0.05 (kernel messages)
ls -la / ls -l      → +0.02 (file list)
cat /etc/           → +0.03 (config inspection)
grep <pattern>      → +0.03 (content search)
```

Each pattern bonuses once per episode. Matching is `re.search()`, so `tail /var/log/nginx/error.log` matches `tail.*log`.

#### Step Cost
```python
return -0.02  # every step, incentivizes efficiency
```

#### Repeat Penalty
```python
if command.strip() == prev_command.strip():
    return -0.15
return 0.0
```

#### Destructive Commands (Episode Ends)
```python
destructive = [
    "rm -rf /",
    "rm -rf /*",
    "mkfs",
    "dd if=/dev/zero of=/dev/sd",
    ":(){:|:&};:",      # fork bomb
    "chmod -R 000 /",
    "> /etc/passwd",
]
if any(d in command for d in destructive):
    return (-2.0, done=True)
```

Interactive commands (penalize but don't end):
```python
interactive = ["vim", "nano", "emacs", "less", "more"]
if any(i in command for i in interactive):
    return (-0.5, done=False)
```

#### Terminal Reward (Only When Verified)
```python
steps_remaining = max_steps - steps_taken
base = 2.0
efficiency_bonus = (steps_remaining / max_steps) * 1.0    # 0 to 1.0
layer_bonus = 0.5                                          # flat bonus
return base + efficiency_bonus + layer_bonus
```

Range: **+2.5 (slow, step 8/8) to +3.5 (fast, step 1/8)**

### Episode Reward Examples

**Efficient fix (steps 1-3):**
```
Step 1: -0.02 (step cost) + 0.08 (journalctl) = +0.06
Step 2: -0.02 (step cost) + 0.08 (systemctl status) = +0.06
Step 3: -0.02 (step cost) + 0.3 (health: 0→1.0) × 2.0 = +0.58
       → Terminal: 2.0 + (5/8)×1.0 + 0.5 = +3.125
Total: +3.84 ✓ Excellent
```

**Slow fix (steps 6-8):**
```
Step 6: -0.02 + 0.05 (tail log) + 0.15 (health: 0.5→0.7) × 2.0 = +0.26
Step 7: -0.02 + 0.05 (grep) + 0.2 (health: 0.7→0.9) × 2.0 = +0.38
Step 8: -0.02 + 0.1 (health: 0.9→1.0) × 2.0 = +0.18
       → Terminal: 2.0 + (0/8)×1.0 + 0.5 = +2.5
Total: +1.30 ✓ Still positive
```

**Failed episode (random commands):**
```
Step 1: -0.02 (step cost)
Step 2: -0.15 (repeated command)
Step 3: -0.02 (step cost)
Step 4: -0.50 (tried 'vim')
Step 5: -0.02 (step cost) ... (no improvement)
Total: -0.71 ✗ Negative
```

## Implementation Details

### Health Scoring

Each fault has 2-3 health stages with weights summing to 1.0:

```python
health_stages=[
    Stage(name="nginx_process", weight=0.5,
          check_cmd="pgrep -f 'nginx: master' > /dev/null && exit 0 || exit 1"),
    Stage(name="nginx_listening", weight=0.5,
          check_cmd="ss -tlnp 2>/dev/null | grep -q ':80 ' && exit 0 || exit 1"),
]
```

Scoring:
```python
def score(container, fault_spec):
    total = 0.0
    passing_stages = []
    for stage in fault_spec.health_stages:
        exit_code, _ = container.exec_run(stage.check_cmd, timeout=5)
        if exit_code == 0:
            total += stage.weight
            passing_stages.append(stage.name)
    return (total, passing_stages)
```

Health checks run on **every step** (~50–100ms per check). Functional checks (Layer 3) only run when `health >= 1.0` because they're expensive (2–5s for curl timeouts).

### Three-Layer Verification

Runs sequentially only when `health_score == 1.0`. Stops at first failure.

**Layer 1 — Process State**
Fast checks on process state, service readiness, port binding:
```python
process_checks=[
    ("systemctl is-active nginx", "nginx service not active"),
    ("pgrep -f 'nginx: master'", "nginx master process not found"),
]
```

**Layer 2 — Integrity**
Ensures the fault is actually fixed (not just papered over):
```python
integrity_checks=[
    ("test -f /etc/nginx/nginx.conf", "config does not exist"),
    ("! grep -q 'listen BROKEN' /etc/nginx/nginx.conf", "bad listen BROKEN still present"),
    ("grep -q 'listen 80' /etc/nginx/nginx.conf", "valid listen 80 not found"),
]
```

**Layer 3 — Functional**
Real-world end-to-end tests:
```python
functional_check={
    "cmd": "curl -sf http://localhost/",
    "expected_exit": 0,
    "output_validator": lambda out: "200" in str(out) or len(out) > 0,
}
```

Validator is a lambda. Can check:
- HTTP status codes in curl output
- File contents after writes
- Absence of error messages in logs

### Container Pool

Pre-warmed Docker containers reduce reset latency from ~2s to <100ms.

```python
pool = ContainerPool(pool_size=8, image="sre-env:latest")

# acquire() pops from queue, spawns replacement async
container, ssh_port = pool.acquire()
# ... run episode ...
pool.release(container)  # kills container, pool auto-fills
```

Container config:
```python
container_config = {
    "image": "sre-env:latest",
    "detach": True,
    "tty": True,
    "ports": {"22/tcp": None},      # random host port
    "mem_limit": "512m",
    "cpu_quota": 50000,             # 0.5 CPU
    "network_mode": "bridge",
    "remove": True,                 # auto-remove on kill
}
```

### SSH Sessions

Stateless by design — each `run(command)` is a fresh `exec_command` call. No persistent shell state means:
- `cd` does not persist → agent uses absolute paths
- Environment variables don't carry over → agent uses `export VAR=val && command`
- Prevents agent confusion from shell state

```python
session = SSHSession(host="localhost", port=22, user="sre", password="fix123")
stdout, exit_code = session.run("systemctl status nginx", timeout=10)
```

## Development

### Project Structure

```
SRE_Env/
├── .dockerignore
├── __init__.py
├── models.py                 # SREAction, SREObservation
├── client.py                 # SREEnv client
├── README.md
├── openenv.yaml
├── pyproject.toml
├── uv.lock
├── faults/
│   ├── __init__.py
│   ├── registry.py           # All 9 FaultSpec definitions
│   └── scripts/
│       └── inject/
│           ├── nginx_stopped.sh
│           ├── log_permissions.sh
│           ├── missing_config.sh
│           ├── broken_nginx_config.sh
│           ├── disk_full.sh
│           ├── broken_symlink.sh
│           ├── zombie_process.sh
│           ├── bad_cron.sh
│           └── multi_fault.sh
├── reward/
│   ├── __init__.py
│   ├── components.py         # Pure reward functions
│   ├── health.py             # HealthScorer
│   ├── verifier.py           # Three-layer Verifier
│   └── engine.py             # RewardEngine orchestrator
├── sandbox/
│   ├── __init__.py
│   ├── ssh.py                # SSHSession
│   └── pool.py               # ContainerPool
└── server/
    ├── __init__.py
    ├── sre_environment.py     # SREEnvironment(Environment)
    ├── app.py                 # FastAPI app
    ├── requirements.txt
    ├── startup.sh             # Container entrypoint
    └── Dockerfile
```

### Running Locally

**Terminal 1: Start server**
```bash
docker build -t sre-env:latest -f server/Dockerfile .
docker run -it --rm -p 8000:8000 sre-env:latest
```

**Terminal 2: Run client**
```bash
python3 -c "
from SRE_Env import SREAction, SREEnv

env = SREEnv(base_url='http://localhost:8000')
obs = env.reset()
print(f'Alert: {obs.alert}')
print(f'Health: {obs.health_score}')

for _ in range(5):
    obs, reward, done, info = env.step(SREAction(command='uptime'))
    print(f'Reward: {reward:.3f}, Health: {obs.health_score:.2f}')
    if done:
        break

env.close()
"
```

### Running Tests

```bash
# Unit tests (no Docker required)
pytest tests/ -v

# Integration test (requires Docker)
pytest tests/test_verifier.py::TestVerifierIntegration -v
```

Test structure:
- `test_verifier.py` — Three-layer verification logic
- Mocks container, tests all fault types
- Validates reward ranges
- Tests short-circuiting (Layer 2 failure prevents Layer 3 run)

### Debugging Reward Issues

Enable detailed logging in `reward/engine.py`:

```python
def step(self, command: str, container):
    # ...
    info_dict = {
        "health_score": curr_score,
        "passing_stages": passing_stages,
        "r_progress": r_progress,
        "r_action": r_action,
        "r_penalty": r_penalty,
        "r_terminal": r_terminal,
        "total": total,
        "verified": verified,
        "steps": self.steps,
    }
    print(f"DEBUG: {info_dict}")  # Add this
    return (total, done, info_dict)
```

Common issues:
- **Health stuck at 0.5**: One stage always passing, one always failing
  - Check: Are both stage checks correct? Do they match the fault?
- **No action bonuses**: Bonus pattern not matching command
  - Check: Is regex pattern correct? Use `re.search()` logic
- **Verification succeeds but shouldn't**: Degenerate fix not caught
  - Check: Layer 2 integrity checks — add a grep for the bad content
- **Episode ends too early**: max_steps reached before any fix
  - Check: Are health improvements progressive? Is progress_reward working?

## Performance & Deployment

### Throughput

With a container pool of size N and average episode length 4 steps:
- **Reset time**: <100ms (pre-warmed containers)
- **Step time**: 50ms (health checks) + 10ms (SSH)
- **Per-episode time**: ~300ms
- **Throughput**: ~3–4 episodes/sec per container, ~24–32 episodes/sec with N=8

### Scaling

For parallel training:
```python
# Async episode runner
from concurrent.futures import ThreadPoolExecutor

with ThreadPoolExecutor(max_workers=8) as executor:
    futures = [executor.submit(run_episode, env) for _ in range(8)]
    results = [f.result() for f in futures]
```

Each worker gets its own `SREEnv` client connecting to the same server.
The server automatically spawns new environments via `create_app(..., max_concurrent_envs=8)`.

### Memory

Per container: 512MB (configurable in `sandbox/pool.py`)
Per episode: ~10MB (SSH session, fault state)

For 8 parallel workers with pool size 8: ~5GB total.

### Monitoring

Health check endpoint:
```bash
curl http://localhost:8000/health
# {"status": "ok", "uptime": 123.45}
```

OpenAPI docs:
```
http://localhost:8000/docs
```

WebSocket latency test:
```bash
time wscat -c ws://localhost:8000/ws
# Measure: ping latency should be <50ms
```

## Architecture Decisions

### Why Three-Layer Verification?

Real SREs verify fixes at multiple levels:
1. **Layer 1**: Is the process/service running? (Fast, observable)
2. **Layer 2**: Is the config correct? (Checks actual state, no degenerate fixes)
3. **Layer 3**: Does it actually work? (End-to-end, real client interaction)

Single-layer (just curl) would reward `nginx -s reload` falsely.
Two-layer (process + functional) would reward `chmod 777 / && curl`.
Three layers catch degenerate fixes.

### Why Pre-Warmed Pools?

Cold container startup is ~2–3s. With 100-step training sessions and dense step rewards, this creates a huge bottleneck. Pre-warming amortizes startup cost across ~100 episodes per container.

### Why Weighted Health Stages?

Different faults have different criticality. For nginx:
- Process running: 50% (visible to curl)
- Port listening: 50% (ensures socket ready)

For disk_full:
- Disk usage: 50% (direct issue)
- nginx running: 50% (downstream effect)

Weights let us give partial credit and guide the agent's exploration.

### Why One-Time Diagnostic Bonuses?

Encourages systematic troubleshooting:
- First `journalctl` → +0.08
- Second `journalctl` → 0 (already bonused)

This prevents reward spamming (running `ls` 10 times) and incentivizes breadth (try different diagnostics).

## License

BSD-style license (see LICENSE in root directory).

## Citation

```bibtex
@software{sre_env_2024,
  title={SRE Terminal Agent RL Environment},
  author={Meta Platforms, Inc.},
  year={2024},
  url={https://huggingface.co/spaces/...},
}
```

## Contributing

Contributions welcome! To add a new fault:

1. Create `/faults/scripts/inject/my_fault.sh`
2. Define `MY_FAULT = FaultSpec(...)` in `/faults/registry.py`
3. Add health stages (weighted, summing to 1.0)
4. Define process, integrity, functional checks
5. Add test case in `tests/test_verifier.py`
6. Run `pytest tests/` to verify
