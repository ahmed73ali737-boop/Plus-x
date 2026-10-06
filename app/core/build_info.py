"""Central build metadata for PulseX.

Keep runtime, health endpoints, QA reports and deployment automation on one source
of truth. Environment overrides are intentional for packaged deployments.
"""
from __future__ import annotations
import os

APP_NAME = "PulseX"
APP_VERSION = os.environ.get("PULSEX_APP_VERSION", "0.9.0")
BUILD_LABEL = os.environ.get("PULSEX_BUILD_LABEL", "windows-12")
API_VERSION = os.environ.get("PULSEX_API_VERSION", "1")

def runtime_identity() -> dict[str, str]:
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "build": BUILD_LABEL,
        "api_version": API_VERSION,
    }
