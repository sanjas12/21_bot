@echo off
cd /d "%~dp0"
uv run --locked --no-dev --env-file .env python src/main.py
