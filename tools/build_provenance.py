"""Bind CI results to the checked-out source and immutable evidence bytes.

Only allowlisted CI metadata is recorded. No environment dump, connection URL,
token, or pip direct_url is included. Generated qa/ and dist/ files are evidence,
not source; every other tracked byte is compared with the job's initial snapshot.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 1


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def command(args: list[str], root: Path = ROOT, timeout: int = 20) -> str:
    return subprocess.run(args, cwd=root, check=True, capture_output=True,
                          text=True, encoding="utf-8", timeout=timeout).stdout.strip()


def ci_context(env: dict | None = None) -> dict:
    env = os.environ if env is None else env
    expected = env.get("GITHUB_SHA", "")
    event_name = env.get("GITHUB_EVENT_NAME", "")
    if event_name == "pull_request":
        path = env.get("GITHUB_EVENT_PATH")
        if not path:
            raise ValueError("CI_PULL_REQUEST_EVENT_MISSING")
        expected = json.loads(Path(path).read_text(encoding="utf-8"))["pull_request"]["head"]["sha"]
    return {"expected_sha": expected, "run_id": env.get("GITHUB_RUN_ID", ""),
            "run_attempt": env.get("GITHUB_RUN_ATTEMPT", ""),
            "workflow": env.get("GITHUB_WORKFLOW", ""),
            "job": env.get("GITHUB_JOB", ""), "event": event_name,
            "repository": env.get("GITHUB_REPOSITORY", "")}


def source_inventory(root: Path = ROOT) -> dict:
    names = command(["git", "ls-files", "-z"], root).split("\0")
    files = {}
    for name in names:
        if not name or name.startswith(("qa/", "dist/")):
            continue
        path = root / name
        files[name] = digest(path.read_bytes()) if path.is_file() else None
    tests = {key: value for key, value in files.items() if key.startswith("tests/")}
    untracked = command(["git", "ls-files", "--others", "--exclude-standard", "-z"], root).split("\0")
    source_prefixes = ("app/", "web/", "templates/", "tests/", "tools/", "sdk/", "ops/", "requirements/", ".github/")
    untracked_source = {name: digest((root / name).read_bytes()) for name in untracked if name
                        and (root / name).is_file() and (name.startswith(source_prefixes)
                        or ("/" not in name and Path(name).suffix in (".py", ".js", ".mjs", ".toml")))}
    return {"sha": command(["git", "rev-parse", "HEAD"], root),
            "tree": command(["git", "rev-parse", "HEAD^{tree}"], root),
            "files": files,
            "test_files": tests,
            "test_digest": digest(json.dumps(tests, sort_keys=True).encode()),
            "untracked_source_files": untracked_source,
            "git_status": command(["git", "status", "--porcelain", "--untracked-files=all"], root).splitlines()}


def versions(probe_browser: bool = False, probe_postgres: bool = False) -> dict:
    result = {"python": platform.python_version(), "implementation": platform.python_implementation(),
              "system": platform.system(), "release": platform.release(), "machine": platform.machine(),
              "node": None, "chromium": None, "postgresql": None}
    node = shutil.which("node")
    if node:
        result["node"] = command([node, "--version"])
    if probe_browser:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                result["chromium"] = browser.version
            finally:
                browser.close()
    if probe_postgres:
        from sqlalchemy import create_engine, text
        url = os.environ.get("PX_POSTGRES_TEST_URL")
        if not url:
            raise ValueError("POSTGRES_PROBE_URL_MISSING")
        engine = create_engine(url, connect_args={"connect_timeout": 5})
        try:
            with engine.connect() as connection:
                result["postgresql"] = connection.execute(text("select version()" )).scalar_one()
        finally:
            engine.dispose()
    return result


def installed_packages() -> list[dict]:
    return sorted(({"name": distribution.metadata["Name"], "version": distribution.version}
                   for distribution in importlib.metadata.distributions()
                   if distribution.metadata.get("Name")), key=lambda row: row["name"].lower())


def report_verdict(path: Path, system: str = "") -> dict:
    """Validate designated acceptance reports, never intentional failure attachments."""
    if path.suffix == ".xml":
        document = ElementTree.parse(path).getroot()
        cases = list(document.iter("testcase"))
        skipped = [case.get("classname", "") + "." + case.get("name", "")
                   for case in cases if case.find("skipped") is not None]
        allowed = {"tests.test_linux_standalone_contract.test_credentials_are_exclusive_and_0600_under_permissive_umask"} if system == "Windows" else set()
        suites = list(document.iter("testsuite"))
        failed = any(case.find("failure") is not None or case.find("error") is not None for case in cases)
        failed |= any(int(suite.get("failures", 0)) or int(suite.get("errors", 0)) for suite in suites)
        failed |= any(name not in allowed for name in skipped)
        return {"verified": bool(cases) and len(cases) > len(skipped) and not failed,
                "kind": "junit", "executed_passes": len(cases) - len(skipped) if not failed else None,
                "excluded_not_passed": skipped}
    report = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        return {"verified": False, "kind": "json"}
    status = report.get("status")
    positive = status in ("passed", "success") or report.get("passed") is True or report.get("verified") is True
    if status is not None and status not in ("passed", "success"):
        positive = False
    if report.get("passed") is False or report.get("verified") is False:
        positive = False
    for key in ("failed", "failures", "errors", "skipped"):
        if report.get(key):
            positive = False
    if type(report.get("passed")) is int and report["passed"] <= 0:
        positive = False
    return {"verified": positive, "kind": "json", "status": status,
            "passed": report.get("passed"), "skipped": report.get("skipped", 0)}


def collect_evidence(root: Path, output: Path, patterns: list[str]) -> tuple[list[dict], list[str]]:
    evidence, errors, seen = [], [], set()
    for pattern in patterns:
        if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
            errors.append("UNSAFE_EVIDENCE_PATTERN:" + pattern)
            continue
        matches = []
        for candidate in root.glob(pattern):
            matches.extend(candidate.rglob("*") if candidate.is_dir() else [candidate])
        matches = [path for path in matches if path.is_file() and path.resolve() != output.resolve()]
        if not matches:
            errors.append("MISSING_EVIDENCE:" + pattern)
        for source in sorted(matches):
            if not source.resolve().is_relative_to(root.resolve()):
                errors.append("UNSAFE_EVIDENCE_PATH:" + str(source))
                continue
            relative = source.relative_to(root)
            if relative.as_posix() in seen:
                continue
            seen.add(relative.as_posix())
            destination = output.parent / "evidence" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.resolve() != destination.resolve():
                shutil.copyfile(source, destination)
            data = destination.read_bytes()
            evidence.append({"path": destination.relative_to(output.parent).as_posix(),
                             "source_path": relative.as_posix(), "sha256": digest(data), "bytes": len(data)})
    return evidence, errors


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def snapshot(args, root: Path = ROOT) -> int:
    context, source = ci_context(), source_inventory(root)
    failures = []
    output = Path(args.output)
    if not output.is_absolute():
        output = root / output
    if args.verify_ci and (not context["expected_sha"] or source["sha"] != context["expected_sha"]):
        failures.append("CI_SOURCE_SHA_MISMATCH")
    if args.verify_ci and args.job_id and args.job_id != context["job"]:
        failures.append("CI_JOB_ID_MISMATCH")
    if args.baseline:
        baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
        previous = baseline["source"]
        if previous["sha"] != source["sha"] or previous["tree"] != source["tree"]:
            failures.append("BASELINE_SOURCE_SHA_CHANGED")
        if previous["files"] != source["files"]:
            changed = sorted(key for key in previous["files"].keys() | source["files"].keys()
                             if previous["files"].get(key) != source["files"].get(key))
            failures.append("SOURCE_BYTES_CHANGED:" + ",".join(changed))
        for key in ("run_id", "run_attempt", "expected_sha", "workflow", "repository"):
            if baseline["ci"].get(key) != context.get(key):
                failures.append("BASELINE_CI_CONTEXT_CHANGED:" + key)
        if baseline.get("failures"):
            failures.append("BASELINE_WAS_INVALID")
        if source["untracked_source_files"]:
            failures.append("UNTRACKED_SOURCE_AFTER_BASELINE:" + ",".join(sorted(source["untracked_source_files"])))
    elif args.verify_ci and source["git_status"]:
        failures.append("INITIAL_CHECKOUT_NOT_CLEAN")
    evidence, evidence_failures = collect_evidence(root, output, args.evidence)
    failures.extend(evidence_failures)
    try:
        environment = versions(args.probe_browser, args.probe_postgres)
    except Exception as exc:
        # Drivers can include passwords in exception messages. Record type only.
        environment = {"probe_error": type(exc).__name__}
        failures.append("ENVIRONMENT_PROBE_FAILED:" + type(exc).__name__)
    required_reports = []
    by_source = {item["source_path"]: item for item in evidence}
    for name in args.require_pass:
        item = by_source.get(name)
        if not item:
            failures.append("REQUIRED_REPORT_NOT_ATTACHED:" + name)
            continue
        try:
            verdict = report_verdict(output.parent / item["path"], environment.get("system", ""))
        except (OSError, ValueError, ElementTree.ParseError):
            verdict = {"verified": False, "kind": "invalid_report"}
        required_reports.append({"path": item["path"], "source_path": name, **verdict})
        if not verdict["verified"]:
            failures.append("ACCEPTANCE_REPORT_NOT_PASSED:" + name)
    result = {"schema": SCHEMA, "recorded_at": datetime.now(timezone.utc).isoformat(),
              "job_id": args.job_id or context["job"], "job_status": args.job_status,
              "profile": args.profile, "ci": context, "source": source,
              "application": {"version": (root / "VERSION").read_text(encoding="utf-8").strip()},
              "environment": environment, "packages": installed_packages(),
              "evidence": evidence, "required_reports": required_reports, "failures": failures,
              "verified": not failures}
    write_json(output, result)
    print(json.dumps({"output": str(output), "source_sha": source["sha"], "verified": not failures,
                      "evidence_count": len(evidence), "failures": failures}, ensure_ascii=False))
    return 1 if failures else 0


def validate(evidence_root: Path, required_jobs: list[str], verify_ci: bool = False,
             context: dict | None = None, root: Path = ROOT) -> dict:
    context = ci_context() if context is None else context
    sha = command(["git", "rev-parse", "HEAD"], root)
    tree = command(["git", "rev-parse", "HEAD^{tree}"], root)
    failures, seen, records = [], set(), []
    if verify_ci and (not context.get("expected_sha") or sha != context["expected_sha"]):
        failures.append("CI_SOURCE_SHA_MISMATCH")
    for path in sorted(evidence_root.rglob("provenance.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        job = record.get("job_id")
        if job in seen:
            failures.append("DUPLICATE_JOB:" + str(job))
        seen.add(job)
        if record.get("schema") != SCHEMA or record.get("job_status") != "success" or not record.get("verified") or record.get("failures"):
            failures.append("JOB_NOT_VERIFIED_SUCCESS:" + str(job))
        if record.get("source", {}).get("sha") != sha or record.get("source", {}).get("tree") != tree:
            failures.append("STALE_SOURCE:" + str(job))
        if verify_ci:
            if record.get("ci", {}).get("job") != job:
                failures.append("CI_JOB_ID_MISMATCH:" + str(job))
            for key in ("run_id", "run_attempt", "expected_sha", "workflow", "repository"):
                if not context.get(key) or record.get("ci", {}).get(key) != context[key]:
                    failures.append("STALE_CI_CONTEXT:" + str(job) + ":" + key)
        for artifact in record.get("evidence", []):
            relative = Path(artifact["path"])
            evidence_path = path.parent / relative
            if relative.is_absolute() or ".." in relative.parts or not evidence_path.resolve().is_relative_to(path.parent.resolve()):
                failures.append("UNSAFE_EVIDENCE:" + str(job))
            elif not evidence_path.is_file() or digest(evidence_path.read_bytes()) != artifact["sha256"]:
                failures.append("EVIDENCE_HASH_MISMATCH:" + str(job) + ":" + str(relative))
        if not record.get("evidence"):
            failures.append("EMPTY_EVIDENCE:" + str(job))
        attached = {item["path"] for item in record.get("evidence", [])}
        if not record.get("required_reports"):
            failures.append("NO_ACCEPTANCE_REPORTS:" + str(job))
        for report in record.get("required_reports", []):
            report_path = path.parent / report["path"]
            try:
                safe = report["path"] in attached and report_path.resolve().is_relative_to(path.parent.resolve())
                verdict = report_verdict(report_path, record.get("environment", {}).get("system", "")) if safe else {"verified": False}
            except (OSError, ValueError, ElementTree.ParseError):
                verdict = {"verified": False}
            if not verdict["verified"]:
                failures.append("ACCEPTANCE_REPORT_NOT_PASSED:" + str(job) + ":" + report["path"])
        records.append({"job_id": job, "source_sha": record.get("source", {}).get("sha")})
    failures.extend("MISSING_JOB:" + job for job in required_jobs if job not in seen)
    return {"schema": SCHEMA, "source_sha": sha, "ci": context, "jobs": records,
            "verified": not failures, "failures": failures}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    snap = sub.add_parser("snapshot")
    snap.add_argument("--output", required=True)
    snap.add_argument("--baseline")
    snap.add_argument("--profile", default="runtime")
    snap.add_argument("--job-id")
    snap.add_argument("--job-status", default="running", choices=["running", "success", "failure", "cancelled", "skipped"])
    snap.add_argument("--verify-ci", action="store_true")
    snap.add_argument("--probe-browser", action="store_true")
    snap.add_argument("--probe-postgres", action="store_true")
    snap.add_argument("--evidence", action="append", default=[])
    snap.add_argument("--require-pass", action="append", default=[])
    check = sub.add_parser("validate")
    check.add_argument("--evidence-root", type=Path, required=True)
    check.add_argument("--require-job", action="append", default=[], required=True)
    check.add_argument("--verify-ci", action="store_true")
    check.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.action == "snapshot":
        return snapshot(args)
    result = validate(args.evidence_root, args.require_job, args.verify_ci)
    if args.output:
        write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
