# Docker Images — SRE Environment

This project uses **two separate Docker images** with distinct purposes:

## 1. Sandbox Image: `sre-sandbox:latest`

**Purpose**: Broken Linux server that agents SSH into to diagnose and fix faults.

**Location**: `sandbox/Dockerfile`

**Contains**:
- Ubuntu 22.04 base
- SSH daemon (agents connect here)
- Nginx web server
- Cron daemon
- Fault injection scripts (in `/faults/inject/`)
- sre user (password: fix123) with sudo access
- Basic diagnostics (systemctl, ps, df, etc.)

**Built and used by**: `ContainerPool` (sandbox/pool.py)

**Build command**:
```bash
docker build -t sre-sandbox:latest -f sandbox/Dockerfile .
```

**Docker run example** (for testing):
```bash
docker run -it --rm -p 2222:22 sre-sandbox:latest

# From another terminal:
ssh -p 2222 sre@localhost  # password: fix123
systemctl status nginx
```

**Environment variables**: None (stateless container)

**Port exposure**: 22 (SSH) — mapped to random host port by pool

**Memory/CPU limits** (set by pool):
- Memory: 512MB
- CPU: 0.5 cores

**Lifecycle**:
1. Pre-warmed in pool (8 containers by default)
2. Acquired for episode (agent SSHes in)
3. Fault injected (bash script from `/faults/inject/`)
4. Agent runs commands via SSH
5. Container killed after episode ends
6. Replacement spawned in background

---

## 2. OpenEnv Server Image: `sre-env:latest`

**Purpose**: FastAPI orchestration server that manages episodes and container pools.

**Location**: `server/Dockerfile`

**Contains**:
- OpenEnv base image (ghcr.io/meta-pytorch/openenv-base:latest)
- Multi-stage build (builder + runtime)
- FastAPI + uvicorn
- Docker CLI (to manage sandbox containers)
- Python virtual environment with dependencies
- SRE environment code (models, reward, sandbox, server)

**Runs**: FastAPI app from `server/app.py`

**Build command**:
```bash
docker build -t sre-env:latest -f server/Dockerfile .
```

**Docker run command**:
```bash
docker run -it --rm \
  -p 8000:8000 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  sre-env:latest
```

**Required mounts**:
- `-v /var/run/docker.sock:/var/run/docker.sock` — Docker daemon access (to spawn sandbox containers)

**Exposed ports**: 8000 (FastAPI HTTP/WebSocket)

**Endpoints**:
- `POST /reset` — Start new episode
- `POST /step` — Execute agent action
- `GET /state` — Current episode state
- `GET /health` — Health check
- `WS /ws` — WebSocket persistent connection
- `GET /docs` — OpenAPI documentation

**Health check**: Curl to `/health` endpoint

**Environment variables** (optional):
- None required (all config server-side)

**Lifecycle**:
1. Container starts, FastAPI server boots
2. Clients connect via HTTP/WebSocket
3. `/reset` call acquires sandbox from pool
4. `/step` calls run agent commands
5. Container cleanup on `/close` or episode end

---

## Build Sequence

### Development (Local Testing)

```bash
# 1. Build sandbox image
docker build -t sre-sandbox:latest -f sandbox/Dockerfile .

# 2. Build server image
docker build -t sre-env:latest -f server/Dockerfile .

# 3. Test sandbox directly
docker run -it --rm -p 2222:22 sre-sandbox:latest

# 4. Test server (requires docker socket)
docker run -it --rm -p 8000:8000 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  sre-env:latest

# 5. From another terminal, test API
curl http://localhost:8000/health
curl -X POST http://localhost:8000/reset \
  -H "Content-Type: application/json" \
  -d '{}'
```

### Production / Hugging Face Spaces

For Hugging Face Spaces, only deploy the **server image** (`sre-env`):

```bash
# HF Spaces will:
# 1. Build from server/Dockerfile
# 2. Mount Docker socket automatically
# 3. Run on port 8000
# 4. Expose via /web UI and API

docker build -t ghcr.io/your-org/sre-env:latest -f server/Dockerfile .
docker push ghcr.io/your-org/sre-env:latest
```

Note: The sandbox containers are created **dynamically** by the server container during episode reset. They do not need to be pre-built on HF Spaces.

---

## Image Size Reference

- **sre-sandbox:latest** ~400MB (ubuntu 22.04 + minimal tools)
- **sre-env:latest** ~1.2GB (openenv-base + Python + dependencies)

---

## Troubleshooting

### Sandbox container fails to start
- Check `/tmp/ready` is created in startup.sh
- Verify SSH daemon starts correctly: `docker run sre-sandbox:latest /usr/sbin/sshd -v`
- Check nginx config: `docker run sre-sandbox:latest nginx -t`

### Server container can't spawn sandboxes
- Verify Docker socket is mounted: `docker run -v /var/run/docker.sock:/var/run/docker.sock`
- Check sandbox image exists: `docker images | grep sre-sandbox`
- Check pool size in server/app.py initialization

### SSH connection times out
- Sandbox: Verify sshd is running inside container
- Server: Check ContainerPool.acquire() timeout (default 30s)
- Network: Verify bridge network is accessible

### Agent commands hang
- SSH timeout is 10s (set in sandbox/ssh.py)
- Interactive commands (vim, nano, less) are detected and penalized in reward/components.py
- Check exec_run timeout in server/sre_environment.py

---

## Quick Reference

| Image | Purpose | Build | Run | Mount |
|-------|---------|-------|-----|-------|
| `sre-sandbox` | Broken server simulator | `sandbox/Dockerfile` | Direct SSH | None |
| `sre-env` | OpenEnv orchestrator | `server/Dockerfile` | Port 8000 | Docker socket |

When troubleshooting, verify:
1. **Sandbox image exists**: `docker images | grep sre-sandbox`
2. **Server image exists**: `docker images | grep sre-env`
3. **Sandbox can SSH**: `docker run sre-sandbox:latest` + `ssh sre@localhost`
4. **Server can create containers**: Check ContainerPool logs
5. **Agent can connect**: `curl http://localhost:8000/health`
