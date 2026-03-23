#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

python3 "$PROJECT_ROOT/scripts/run_migrations.py"
python3 "$SCRIPT_DIR/app.py"
