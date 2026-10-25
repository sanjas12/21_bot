#!/usr/bin/env bash
# РІРµСЂСЃРёСЏ: 0.2
# Windows/Git Bash: portable ZIP without modifying source files.
# Default: current .venv, no downloads. --prepare installs locked dependencies.
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"
case "$(uname -s)" in
    MINGW*|MSYS*) ;;
    *) echo '[ERROR] Windows build requires Git Bash on Windows.'; exit 1 ;;
esac
if [ "$#" -gt 1 ]; then
    echo 'Usage: bash scripts/build.sh [--prepare|--prepare-offline]'
    exit 1
fi
case "${1:-}" in
    '') ;;
    --prepare|--prepare-offline)
        command -v uv >/dev/null || { echo '[ERROR] Install uv first.'; exit 1; }
        export UV_LINK_MODE=copy
        args=(sync --locked --group dev --group build)
        if [ "$1" = --prepare-offline ]; then args+=(--offline); fi
        uv "${args[@]}"
        ;;
    *) echo 'Usage: bash scripts/build.sh [--prepare|--prepare-offline]'; exit 1 ;;
esac
PYTHON_EXE="$PROJECT_ROOT/.venv/Scripts/python.exe"
test -f "$PYTHON_EXE" || { echo '[ERROR] Run: bash scripts/build.sh --prepare'; exit 1; }
"$PYTHON_EXE" -c 'import cx_Freeze' || {
    echo '[ERROR] Install locked build dependencies: bash scripts/build.sh --prepare'
    exit 1
}
"$PYTHON_EXE" build.py build_exe
