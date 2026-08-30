#!/usr/bin/env bash
# Run linter

set -e

cd backend

echo "Running ruff..."
ruff check .

echo "Linting complete!"
