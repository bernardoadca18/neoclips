#!/usr/bin/env bash
# Run type checker

set -e

cd backend

echo "Running mypy..."
mypy app

echo "Type checking complete!"
