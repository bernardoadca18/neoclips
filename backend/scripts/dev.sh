#!/usr/bin/env bash
# Start development environment

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

echo "Starting NeoClips development environment..."

# Start infrastructure
cd "$REPO_ROOT"
docker compose up -d db redis

# Wait for services to be ready
echo "Waiting for services..."
sleep 3

# Run migrations
cd "$SCRIPT_DIR"
.venv/bin/alembic upgrade head

# Start API
echo "Starting API on port 8020..."
.venv/bin/uvicorn app.main:app --reload --port 8020
