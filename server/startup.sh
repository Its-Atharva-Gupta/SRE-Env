#!/bin/bash
# Start nginx for fault simulation
service nginx start || nginx || true
# Start the FastAPI server
exec uvicorn server.app:app --host 0.0.0.0 --port 7860
