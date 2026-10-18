#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
exec uv run --locked --no-dev --env-file .env python src/main.py
