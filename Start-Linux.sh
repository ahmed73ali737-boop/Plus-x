#!/bin/sh
set -eu
CDPATH= cd -P "$(dirname "$0")"
ROOT=$(pwd)
umask 077
export PYTHONUTF8=1
export PYTHONUNBUFFERED=1
if [ ! -x "$ROOT/.venv/bin/python" ]; then
    echo "PulseX .venv missing. Execute: python3 -m tools.prepare_runtime --profile local" >&2
    exit 2
fi
exec "$ROOT/.venv/bin/python" "$ROOT/run.py"
