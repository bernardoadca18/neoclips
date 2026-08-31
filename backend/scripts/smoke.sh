#!/usr/bin/env bash
# Smoke tests - basic health check

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

echo "Running smoke tests..."

API_URL="${API_URL:-http://localhost:8020}"

# Check API is responding
echo "Checking API health..."
curl -s -f "$API_URL/health" > /dev/null
echo "✓ API health check passed"

# Check readiness endpoint - MUST pass for dependencies
echo "Checking API readiness..."
curl -s -f "$API_URL/health/readiness" > /dev/null
echo "✓ API readiness check passed"

# Check docs are available
echo "Checking API docs..."
curl -s -f "$API_URL/docs" > /dev/null
echo "✓ API docs accessible"

echo "Smoke tests complete!"
