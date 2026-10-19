"""Run the actual invitations DOM contract and prove failure reaches pytest.

These tests are Node/pytest integration gates, not browser, OS or field acceptance.
PULSEX_CONTRACT_ARTIFACT_DIR can place persistent logs in a CI artifact directory.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

import pytest


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "tests" / "invitations_ui_contract.mjs"


def _artifact_directory() -> Path:
    path = Path(os.environ.get(
        "PULSEX_CONTRACT_ARTIFACT_DIR", str(ROOT / "codex-audit-artifacts" / "contracts")
    )).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _output(value: str | bytes | None) -> str:
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or ""


def _source_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=10, check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return os.environ.get("SOURCE_HEAD")


def _run_contract(contract: Path, log_path: Path, node_executable: str = "node") -> dict:
    """Always preserve output; neither a green marker nor missing Node can pass."""
    command = [node_executable, str(contract)]
    evidence = {
        "scope": "Isolated DOM contract, not real browser or field acceptance",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "command": command,
        "cwd": str(ROOT),
        "contract_sha256": None,
        "source_sha": _source_sha(),
        "expected_source_sha": os.environ.get("SOURCE_HEAD"),
        "github_sha": os.environ.get("GITHUB_SHA"),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "status": "incomplete",
        "returncode": None,
        "stdout": "",
        "stderr": "",
    }
    try:
        evidence["contract_sha256"] = hashlib.sha256(contract.read_bytes()).hexdigest()
        result = subprocess.run(
            command, cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30, check=False,
        )
        evidence.update(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
    except OSError as exc:
        evidence.update(
            failure_kind="launch_error" if evidence["contract_sha256"] else "contract_unavailable",
            stderr=str(exc),
        )
    except subprocess.TimeoutExpired as exc:
        evidence.update(failure_kind="timeout", stdout=_output(exc.stdout), stderr=_output(exc.stderr))
    finally:
        evidence["finished_at"] = datetime.now(timezone.utc).isoformat()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def reject(kind: str, message: str) -> None:
        evidence.update(status="failed", failure_kind=kind, failure_reason=message)
        log_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        pytest.fail(f"Node invitation contract {message}; log: {log_path}")

    if evidence.get("failure_kind"):
        reject(evidence["failure_kind"], f"could not finish: {evidence['failure_kind']}")
    if evidence["expected_source_sha"] and evidence["source_sha"] != evidence["expected_source_sha"]:
        reject("source_revision_mismatch", "checkout does not match the requested source revision")
    if evidence["returncode"] != 0:
        reject("nonzero_exit", f"exited {evidence['returncode']}")

    reports = []
    for line in evidence["stdout"].splitlines():
        try:
            report = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(report, dict) and report.get("suite") == "INVITATIONS_UI_CONTRACT":
            reports.append(report)
    if len(reports) != 1:
        reject("report_missing_or_duplicated", "must emit exactly one result report")
    report = reports[0]
    if (type(report.get("passed")) is not int or report["passed"] <= 0
            or type(report.get("failed")) is not int or report["failed"] != 0
            or report.get("skipped", 0) != 0):
        reject("report_not_passed", "report is not a complete pass")
    evidence.update(status="passed", report=report)
    log_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def test_invitations_javascript_ui_contract():
    _run_contract(CONTRACT, _artifact_directory() / "invitations-ui-contract.json")


def _failed_child_pytest(tmp_path: Path, scenario: str, source: str, node_executable: str = "node") -> dict:
    """Launch a real failing pytest process; no mocked subprocess/return code."""
    artifacts = _artifact_directory() / scenario
    artifacts.mkdir(parents=True, exist_ok=True)
    script = tmp_path / "intentional-contract.mjs"
    script.write_text(source, encoding="utf-8")
    log_path = artifacts / "node-contract.json"
    test_file = tmp_path / "test_child_contract.py"
    test_file.write_text(
        "import runpy\nfrom pathlib import Path\n"
        f"wrapper = runpy.run_path({str(Path(__file__).resolve())!r})\n"
        "def test_child_contract():\n"
        f"    wrapper['_run_contract'](Path({str(script)!r}), Path({str(log_path)!r}), {node_executable!r})\n",
        encoding="utf-8",
    )
    junit = artifacts / "expected-failure.junit.xml"
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(test_file), f"--junitxml={junit}"]
    result = subprocess.run(
        command, cwd=tmp_path, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60, check=False,
        env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTEST_ADDOPTS": ""},
    )
    (artifacts / "pytest-process.json").write_text(json.dumps({
        "expected_result": "One genuine pytest failure is required for this negative control",
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    assert result.returncode == 1, result.stdout + result.stderr
    suites = list(ElementTree.parse(junit).getroot().iter("testsuite"))
    assert sum(int(s.get("tests", 0)) for s in suites) == 1
    assert sum(int(s.get("failures", 0)) for s in suites) == 1
    assert sum(int(s.get("errors", 0)) for s in suites) == 0
    assert sum(int(s.get("skipped", 0)) for s in suites) == 0
    assert "Node invitation contract" in result.stdout
    return json.loads(log_path.read_text(encoding="utf-8"))


def test_nonzero_node_fails_real_pytest_and_keeps_log(tmp_path):
    evidence = _failed_child_pytest(tmp_path, "negative-node-exit", (
        'console.log(JSON.stringify({suite:"INVITATIONS_UI_CONTRACT",passed:24,failed:0}));\n'
        'console.error("P01-T03 intentional Node failure, despite the green marker");\n'
        'process.exit(37);\n'
    ))
    assert evidence["returncode"] == 37
    assert evidence["status"] == "failed"
    assert "intentional Node failure" in evidence["stderr"]
    assert '"failed":0' in evidence["stdout"]


def test_missing_node_fails_real_pytest_and_keeps_log(tmp_path):
    evidence = _failed_child_pytest(
        tmp_path, "negative-missing-node", "", str(tmp_path / "node-executable-does-not-exist")
    )
    assert evidence["failure_kind"] == "launch_error"
    assert evidence["status"] == "failed"
    assert evidence["returncode"] is None
    assert evidence["stderr"]


def test_empty_success_output_fails_real_pytest_and_keeps_log(tmp_path):
    evidence = _failed_child_pytest(tmp_path, "negative-empty-success", "process.exit(0);\n")
    assert evidence["returncode"] == 0
    assert evidence["failure_kind"] == "report_missing_or_duplicated"
    assert evidence["stdout"] == ""
