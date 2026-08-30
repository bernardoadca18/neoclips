#!/usr/bin/env bash
# Smoke tests - basic health check

set -e

echo "Running smoke tests..."

# Check API is responding
echo "Checking API health..."
curl -s -f http://localhost:8020/health > /dev/null
echo "✓ API health check passed"

# Check readiness endpoint
echo "Checking API readiness..."
curl -s -f http://localhost:8020/health/readiness > /dev/null || echo "⚠ Dependencies may not be ready"

# Check docs are available
echo "Checking API docs..."
curl -s -f http://localhost:8020/docs > /dev/null
echo "✓ API docs accessible"

echo "Smoke tests complete!"
