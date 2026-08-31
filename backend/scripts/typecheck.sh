#!/usr/bin/env bash
# Run type checker

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "$SCRIPT_DIR"

echo "Running mypy..."
.venv/bin/mypy app/

echo "Type checking complete!"
