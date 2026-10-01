#!/bin/sh
set -eu
cd "$(dirname "$0")"
umask 077
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
exec .venv/bin/python run.py
