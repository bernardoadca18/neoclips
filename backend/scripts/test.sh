#!/usr/bin/env bash
# Run tests

set -e

cd backend

# Run unit tests
echo "Running unit tests..."
pytest tests/unit -v

# Run integration tests (requires PostgreSQL)
if [ "${RUN_INTEGRATION:-false}" = "true" ]; then
    echo "Running integration tests..."
    pytest tests/integration -v -m postgres
fi

echo "All tests passed!"
