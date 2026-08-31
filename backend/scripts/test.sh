#!/usr/bin/env bash
# Run tests

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "$SCRIPT_DIR"

# Run unit tests
echo "Running unit tests..."
.venv/bin/pytest tests/unit -v

# Run integration tests (requires PostgreSQL)
if [ "${RUN_INTEGRATION:-false}" = "true" ]; then
    echo "Running integration tests..."
    .venv/bin/pytest tests/integration -v
fi

echo "All tests passed!"
