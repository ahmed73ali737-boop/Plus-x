"""Central build metadata for PulseX.

VERSION is the source release number. Environment overrides are reserved for
packaged deployments and CI build labels.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _source_version() -> str:
    try:
        value = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        return value or "0.0.0-dev"
    except OSError:
        return "0.0.0-dev"


APP_NAME = "PulseX"
APP_VERSION = os.environ.get("PULSEX_APP_VERSION") or _source_version()
BUILD_LABEL = os.environ.get("PULSEX_BUILD_LABEL") or f"source-v{APP_VERSION}"
API_VERSION = os.environ.get("PULSEX_API_VERSION", "1")


def runtime_identity() -> dict[str, str]:
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "build": BUILD_LABEL,
        "api_version": API_VERSION,
    }
