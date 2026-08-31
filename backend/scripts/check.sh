#!/usr/bin/env bash
# Run all quality checks

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Running all quality checks..."

"$SCRIPT_DIR/lint.sh"
"$SCRIPT_DIR/typecheck.sh"
"$SCRIPT_DIR/test.sh"

echo "All checks passed!"
