#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
python tests/load_profiles.py --profile x5
python tests/load_profiles.py --profile x10
