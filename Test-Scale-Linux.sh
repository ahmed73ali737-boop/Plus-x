#!/bin/sh
set -eu
CDPATH= cd -P "$(dirname "$0")"
ROOT=$(pwd)
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || { echo "Run: python3 -m tools.prepare_runtime --profile qa" >&2; exit 2; }
for profile in pilot x5 x10 stretch; do
    "$PY" tests/load_profiles.py --profile "$profile"
done
