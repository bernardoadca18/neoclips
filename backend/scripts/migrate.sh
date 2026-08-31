#!/usr/bin/env bash
# Run database migrations

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "$SCRIPT_DIR"

echo "Running Alembic migrations..."
.venv/bin/alembic upgrade head

echo "Migrations complete!"
