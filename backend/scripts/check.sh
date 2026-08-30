#!/usr/bin/env bash
# Run all quality checks

set -e

echo "Running all quality checks..."

./scripts/lint.sh
./scripts/typecheck.sh
./scripts/test.sh

echo "All checks passed!"
