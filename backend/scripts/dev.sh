#!/usr/bin/env bash
# Start development environment

set -e

echo "Starting NeoClips development environment..."

# Start infrastructure
docker compose up -d db redis

# Wait for services to be ready
echo "Waiting for services..."
sleep 3

# Run migrations
cd backend
alembic upgrade head

# Start API
echo "Starting API on port 8020..."
uvicorn app.main:app --reload --port 8020
