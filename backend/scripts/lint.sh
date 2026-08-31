#!/usr/bin/env bash
# Run linter

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "$SCRIPT_DIR"

echo "Running ruff..."
.venv/bin/ruff check app/

echo "Linting complete!"
