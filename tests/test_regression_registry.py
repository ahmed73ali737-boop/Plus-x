from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "ops/regression_registry.json"


def test_regression_registry_is_structurally_valid_and_enforced():
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    cases = data["cases"]
    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids)), "Regression IDs must be unique"
    assert cases, "Regression registry must not be empty"

    automated = [case for case in cases if case["status"] == "regression_required"]
    manual = [case for case in cases if case["status"] == "manual_open"]
    assert automated, "At least one automated regression case is required"
    assert manual, "Field/manual gaps must remain explicit instead of being silently treated as passed"

    for case in cases:
        assert case["status"] in {"regression_required", "manual_open"}, case["id"]
        assert case["invariant"].strip(), case["id"]
        checks = case.get("checks", [])
        if case["status"] == "regression_required":
            assert checks, f"{case['id']} has no enforcing check"
        for check in checks:
            path = ROOT / check["path"]
            assert path.is_file(), f"{case['id']} missing {check['path']}"
            content = path.read_text(encoding="utf-8")
            for marker in check.get("markers", []):
                assert marker in content, f"{case['id']} lost marker {marker!r} in {check['path']}"


def test_regression_policy_keeps_manual_gaps_open():
    cases = {
        case["id"]: case
        for case in json.loads(REGISTRY.read_text(encoding="utf-8"))["cases"]
    }
    assert cases["FIELD-HARDWARE-UAT"]["status"] == "manual_open"
    assert cases["CROSS-BROWSER-WCAG"]["status"] == "manual_open"
