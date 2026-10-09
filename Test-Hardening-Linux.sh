#!/bin/sh
set -eu
CDPATH= cd -P "$(dirname "$0")"
ROOT=$(pwd)
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || { echo "Run: python3 -m tools.prepare_runtime --profile qa" >&2; exit 2; }
"$PY" -m pytest -q
"$PY" tests/native_acceptance.py
"$PY" tests/security_hardening.py
"$PY" tests/ux_contract_w08.py
"$PY" tests/capacity_smoke.py
"$PY" tests/sdk_native_smoke.py
node --check sdk/javascript/index.mjs
node tests/sdk_js_test.mjs
"$PY" tests/run_ui_bridge.py
"$PY" tests/browser_components.py
echo "Local available hardening checks passed. PostgreSQL/field acceptance requires separate evidence."
