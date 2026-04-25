# Dual-Mode Sandbox System

The SRE environment supports two modes for sandbox container management:

## Mode 1: Local (Default)

**Use this for:** Desktop development, local VPS with Docker daemon

```bash
# Set environment (or use default)
export SANDBOX_MODE=local

# Run the environment
python -m server.app
```

The environment uses Docker directly via `docker.from_env()`.

### Pros
- ✅ Fast (no network latency)
- ✅ Simple setup
- ✅ Full Docker SDK feature access

### Cons
- ❌ Requires Docker daemon on same machine
- ❌ Not suitable for HF Spaces / managed cloud

---

## Mode 2: Remote

**Use this for:** HF Spaces, serverless platforms, Docker-in-Docker-free environments

### Step 1: Start the Sandbox Manager (on Docker-enabled machine)

```bash
# On your desktop/VPS with Docker
./sandbox/manager_launcher.sh

# Or manually:
uv run uvicorn sandbox.manager:app --host 0.0.0.0 --port 9000
```

This exposes three REST endpoints:
- `POST /sandbox/create` → Create a sandbox
- `POST /sandbox/{id}/exec` → Execute command
- `DELETE /sandbox/{id}` → Destroy sandbox

### Step 2: Configure the remote client (HF Spaces or other platform)

```bash
# On HF Spaces or remote environment
export SANDBOX_MODE=remote
export SANDBOX_MANAGER_URL=http://<your-machine-ip>:9000

# Now run the environment
python -m server.app
```

The environment talks to the manager via HTTP.

### Pros
- ✅ Works in HF Spaces, Gradio, serverless
- ✅ Decouples sandbox creation from training
- ✅ Sandboxes run on dedicated machine

### Cons
- ❌ Network latency
- ❌ Requires separate manager process
- ❌ Manager is a single point of failure

---

## Configuration

### Environment Variables

```bash
# Sandbox mode (default: local)
SANDBOX_MODE=local|remote

# Remote manager URL (only needed if SANDBOX_MODE=remote)
SANDBOX_MANAGER_URL=http://localhost:9000
```

### .env.example

```
SANDBOX_MODE=local
SANDBOX_MANAGER_URL=http://localhost:9000
```

---

## Architecture

### Local Mode
```
pool.py ──→ LocalDockerBackend ──→ docker.from_env() ──→ Docker daemon
```

### Remote Mode
```
pool.py ──→ SandboxManagerClient ──→ HTTP ──→ manager.py ──→ docker.from_env() ──→ Docker daemon
```

Both modes expose the same `SandboxBackend` interface, so `pool.py` and `sre_environment.py` are mode-agnostic.

---

## Implementation Details

### `sandbox/backends.py`
Abstract backend interface with two implementations:
- `LocalDockerBackend`: Direct Docker calls
- `SandboxManagerClient`: HTTP client
- `get_backend()`: Factory function reads `SANDBOX_MODE` env var

### `sandbox/manager.py`
FastAPI server that wraps Docker. Runs on the machine with Docker access.

Endpoints:
- `POST /sandbox/create` — Spin up a container, wait for SSH
- `POST /sandbox/{id}/exec` — Run a command in a sandbox
- `DELETE /sandbox/{id}` — Kill a sandbox
- `GET /health` — Health check

### `sandbox/pool.py`
Container pool uses `SandboxBackend` abstraction. Returns `ContainerProxy` objects that mimic Docker container objects but use the backend.

### `sandbox/manager_launcher.sh`
One-liner to start the manager: `./sandbox/manager_launcher.sh`

---

## Example: HF Spaces Setup

### On your desktop (with Docker)
```bash
# Terminal 1: Start the manager
cd /path/to/SRE_Env
./sandbox/manager_launcher.sh
# Listens on http://localhost:9000
# Note your machine's IP address (or use ngrok to expose)
```

### In HF Spaces repository
```bash
# .env (or set as secrets)
SANDBOX_MODE=remote
SANDBOX_MANAGER_URL=http://192.168.1.100:9000  # Your machine's IP

# Then start the app
python -m server.app
```

---

## Testing

All 127 tests pass with both modes (tests use local mode by default).

To test remote mode locally:
```bash
# Terminal 1: Start manager
./sandbox/manager_launcher.sh

# Terminal 2: Run with remote mode
export SANDBOX_MODE=remote
export SANDBOX_MANAGER_URL=http://localhost:9000
python -m pytest tests/
```

---

## Security Notes

⚠️ **The sandbox manager exposes Docker as a REST API.**

- ✅ Use only on trusted networks (VPN, private VPS)
- ✅ Add authentication/TLS for production
- ✅ Run manager in a restricted user context
- ❌ Do NOT expose to the public internet without authentication

For HF Spaces, use ngrok with password protection:
```bash
ngrok http 9000 --auth "user:password"
```

---

## Backward Compatibility

The entire dual-mode system is internal to `sandbox/`. The rest of the codebase (`pool.py`, `sre_environment.py`, `reward/`, `faults/`) does not change.

`ContainerProxy` mimics the Docker container object interface, so existing code continues to work unchanged.
