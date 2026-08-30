#!/usr/bin/env bash
# Run database migrations

set -e

cd backend

echo "Running Alembic migrations..."
alembic upgrade head

echo "Migrations complete!"
