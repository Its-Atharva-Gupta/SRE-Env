#!/bin/bash
# Start the Sandbox Manager on port 9000
#
# This script runs on the machine with Docker access (desktop or VPS).
# It allows remote clients (e.g., HF Spaces) to create/manage sandboxes via HTTP.
#
# Usage:
#   ./sandbox/manager_launcher.sh
#   # Manager runs on http://localhost:9000
#
# Then on the remote client, set:
#   SANDBOX_MODE=remote
#   SANDBOX_MANAGER_URL=http://<your-machine-ip>:9000

set -e

echo "Starting SRE Sandbox Manager on port 9000..."
echo "This machine's Docker will be exposed via HTTP REST API"
echo ""
echo "Remote clients should set:"
echo "  SANDBOX_MODE=remote"
echo "  SANDBOX_MANAGER_URL=http://$(hostname -I | awk '{print $1}'):9000"
echo ""

cd "$(dirname "$0")/.."
uv run uvicorn sandbox.manager:app --host 0.0.0.0 --port 9000 --reload
