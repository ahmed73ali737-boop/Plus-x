"""Acceptance controls for stale/mutated evidence and source provenance."""
from argparse import Namespace
import json
from pathlib import Path
import subprocess

import pytest

from tools import build_provenance as provenance


@pytest.fixture
def repository(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    def git(*args):
        return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True,
                              text=True).stdout.strip()
    git("init")
    git("config", "user.name", "Phase01 Test")
    git("config", "user.email", "phase01@example.invalid")
    (root / "VERSION").write_text("1.0.1\n")
    (root / ".gitignore").write_text("/evidence/\n/qa/\n")
    (root / "app.py").write_text("answer = 42\n")
    git("add", ".")
    git("commit", "-m", "isolated fixture")
    context = {"expected_sha": git("rev-parse", "HEAD"), "run_id": "100", "run_attempt": "2",
               "workflow": "test", "job": "python-core", "repository": "example/pulsex", "event": "push"}
    monkeypatch.setattr(provenance, "ci_context", lambda: context.copy())
    monkeypatch.setattr(provenance, "versions", lambda *args: {"python": "test"})
    monkeypatch.setattr(provenance, "installed_packages", lambda: [])
    return root, context


def args(root: Path, *, final: bool = False):
    folder = root / "evidence" / "python-core"
    return Namespace(output=str(folder / ("provenance.json" if final else "baseline.json")),
                     baseline=str(folder / "baseline.json") if final else None,
                     profile="qa", job_id="python-core", job_status="success" if final else "running",
                     verify_ci=True, evidence=["qa/result.json"] if final else [],
                     require_pass=["qa/result.json"] if final else [],
                     probe_browser=False, probe_postgres=False)


def bundle(repository):
    root, context = repository
    assert provenance.snapshot(args(root), root) == 0
    (root / "qa").mkdir()
    (root / "qa/result.json").write_text('{"passed": true}')
    assert provenance.snapshot(args(root, final=True), root) == 0
    return root / "evidence" / "python-core" / "provenance.json"


def check(repository, jobs=None):
    root, context = repository
    return provenance.validate(root / "evidence", jobs or ["python-core"], True, context, root)


def rewrite(path, update):
    record = json.loads(path.read_text())
    update(record)
    path.write_text(json.dumps(record))


def test_exact_source_and_evidence_accept(repository):
    bundle(repository)
    assert check(repository)["verified"] is True


def test_source_change_under_same_sha_fails(repository):
    root, _ = repository
    assert provenance.snapshot(args(root), root) == 0
    (root / "app.py").write_text("answer = 0\n")
    final = args(root, final=True)
    final.evidence = []
    assert provenance.snapshot(final, root) == 1
    record = json.loads(Path(final.output).read_text())
    assert "SOURCE_BYTES_CHANGED:app.py" in record["failures"]


def test_dirty_initial_checkout_fails(repository):
    root, _ = repository
    (root / "untracked.py").write_text("raise RuntimeError\n")
    assert provenance.snapshot(args(root), root) == 1


def test_missing_required_evidence_fails_even_with_success_status(repository):
    root, _ = repository
    assert provenance.snapshot(args(root), root) == 0
    assert provenance.snapshot(args(root, final=True), root) == 1


@pytest.mark.parametrize("status", ["failure", "skipped", "cancelled", "running"])
def test_unsuccessful_job_cannot_be_released(repository, status):
    path = bundle(repository)
    rewrite(path, lambda record: record.update(job_status=status))
    assert check(repository)["verified"] is False


def test_hash_tampering_rejected(repository):
    path = bundle(repository)
    evidence = path.parent / "evidence/qa/result.json"
    evidence.write_text('{"passed": false}')
    assert any("EVIDENCE_HASH_MISMATCH" in value for value in check(repository)["failures"])


@pytest.mark.parametrize("key,value", [("run_id", "99"), ("run_attempt", "1"),
                                      ("expected_sha", "0" * 40), ("workflow", "older-workflow")])
def test_old_green_context_rejected(repository, key, value):
    path = bundle(repository)
    rewrite(path, lambda record: record["ci"].update({key: value}))
    assert check(repository)["verified"] is False


def test_old_source_sha_rejected(repository):
    path = bundle(repository)
    rewrite(path, lambda record: record["source"].update(sha="0" * 40))
    assert "STALE_SOURCE:python-core" in check(repository)["failures"]


def test_missing_and_duplicate_jobs_rejected(repository):
    path = bundle(repository)
    assert "MISSING_JOB:windows-core" in check(repository, ["python-core", "windows-core"])["failures"]
    duplicate = path.parent.parent / "duplicate" / "provenance.json"
    duplicate.parent.mkdir()
    duplicate.write_bytes(path.read_bytes())
    assert "DUPLICATE_JOB:python-core" in check(repository)["failures"]


def test_evidence_escape_rejected(repository):
    path = bundle(repository)
    rewrite(path, lambda record: record["evidence"][0].update(path="../../outside.json"))
    assert "UNSAFE_EVIDENCE:python-core" in check(repository)["failures"]


def test_probe_exception_does_not_leak_credentials(repository, monkeypatch):
    root, _ = repository
    def fail(*_):
        raise RuntimeError("postgresql://user:TOP_SECRET@server/db")
    monkeypatch.setattr(provenance, "versions", fail)
    options = args(root)
    assert provenance.snapshot(options, root) == 1
    text = Path(options.output).read_text()
    assert "TOP_SECRET" not in text
    assert "ENVIRONMENT_PROBE_FAILED:RuntimeError" in text


def test_pull_request_identity_uses_head_not_synthetic_merge(tmp_path):
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"head": {"sha": "a" * 40}}}))
    result = provenance.ci_context({"GITHUB_EVENT_NAME": "pull_request", "GITHUB_EVENT_PATH": str(event),
                                    "GITHUB_SHA": "b" * 40, "GH_TOKEN": "DO_NOT_CAPTURE"})
    assert result["expected_sha"] == "a" * 40
    assert "DO_NOT_CAPTURE" not in json.dumps(result)


@pytest.mark.parametrize("status", ["failed", "blocked", "skipped"])
def test_green_job_with_fresh_failed_report_is_rejected(repository, status):
    root, _ = repository
    assert provenance.snapshot(args(root), root) == 0
    (root / "qa").mkdir()
    (root / "qa/result.json").write_text(json.dumps({"status": status, "passed": 1}))
    assert provenance.snapshot(args(root, final=True), root) == 1


def test_job_cannot_impersonate_another_gate(repository):
    root, _ = repository
    options = args(root)
    options.job_id = "windows-core"
    assert provenance.snapshot(options, root) == 1


def test_failed_junit_rejected_even_if_suite_claims_zero_failures(tmp_path):
    report = tmp_path / "junit.xml"
    report.write_text('<testsuites><testsuite failures="0"><testcase name="contract"><failure/></testcase></testsuite></testsuites>')
    assert provenance.report_verdict(report)["verified"] is False


def test_platform_exclusion_is_explicit_and_not_counted_as_a_pass(tmp_path):
    report = tmp_path / "junit.xml"
    report.write_text('<testsuites><testsuite failures="0"><testcase name="real_pass"/>'
                      '<testcase classname="tests.test_linux_standalone_contract" '
                      'name="test_credentials_are_exclusive_and_0600_under_permissive_umask"><skipped/></testcase>'
                      '</testsuite></testsuites>')
    result = provenance.report_verdict(report, "Windows")
    assert result["verified"] is True
    assert result["executed_passes"] == 1
    assert len(result["excluded_not_passed"]) == 1
    assert provenance.report_verdict(report, "Linux")["verified"] is False


@pytest.mark.parametrize("key", ["passed", "verified"])
def test_contradictory_green_json_is_rejected(tmp_path, key):
    report = tmp_path / "result.json"
    report.write_text(json.dumps({"status": "passed", key: False}))
    assert provenance.report_verdict(report)["verified"] is False


def test_untracked_executable_source_after_baseline_rejected(repository):
    root, _ = repository
    assert provenance.snapshot(args(root), root) == 0
    (root / "injected.py").write_text("unexpected = True\n")
    final = args(root, final=True)
    final.evidence, final.require_pass = [], []
    assert provenance.snapshot(final, root) == 1
    assert "UNTRACKED_SOURCE_AFTER_BASELINE:injected.py" in json.loads(Path(final.output).read_text())["failures"]
