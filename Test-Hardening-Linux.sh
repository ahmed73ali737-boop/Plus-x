#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
python -m pytest -q
python tests/native_acceptance.py
python tests/security_hardening.py
python tests/ux_contract_w08.py
python tests/capacity_smoke.py
python tests/sdk_native_smoke.py
node --check sdk/javascript/index.mjs
node tests/sdk_js_test.mjs
python tests/run_ui_bridge.py
python tests/browser_components.py
echo "All available local hardening checks passed. Review QA_REPORT_AR.md for remaining external gates."
