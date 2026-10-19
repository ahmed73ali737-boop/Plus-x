"""Read-only source-lock/EOL evidence; optional controls use disposable copies.

The two existing guards remain independent and byte-exact. LF normalization in
this report is diagnostic only, never a reason to accept a failing source lock.
No lock, migration, Git index, or working-tree source is rewritten by this tool.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
LOCKS = (
    ("components/g-observability/source-lock.json", "sha256", "sha256"),
    ("ops/consolidated-source-lock.json", "git_blob_sha1", "blob_sha"),
)
GUARDS = (
    ("sha256", "tools/verify_shared_observability.py"),
    ("git_blob_sha1", "tools/verify_consolidation_assets.py"),
)
CONTROL_TARGET = "requirements-observability.txt"


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=check)


def hashes(data: bytes) -> dict[str, str]:
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "git_blob_sha1": hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest(),
    }


def byte_evidence(data: bytes | None) -> dict:
    if data is None:
        return {"present": False}
    crlf = data.count(b"\r\n")
    lf = data.count(b"\n") - crlf
    cr = data.count(b"\r") - crlf
    normalized = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return {
        "present": True, "size": len(data), **hashes(data),
        "eol": {"crlf": crlf, "lf": lf, "bare_cr": cr},
        "normalized_lf_diagnostic_only": hashes(normalized),
    }


def read_lock_entries(repo: Path) -> list[dict]:
    entries = []
    for lock_path, algorithm, key in LOCKS:
        lock = json.loads((repo / lock_path).read_text(encoding="utf-8"))
        for item in lock["files"]:
            path = item["path"]
            if Path(path).is_absolute() or ".." in Path(path).parts:
                raise ValueError("Unsafe locked source path: " + path)
            entries.append({"lock": lock_path, "path": path, "algorithm": algorithm, "expected": item[key]})
    return entries


def run_guards(repo: Path) -> list[dict]:
    result = []
    for algorithm, guard in GUARDS:
        run = subprocess.run([sys.executable, str(repo / guard)], cwd=repo, text=True, capture_output=True)
        result.append({"algorithm": algorithm, "guard": guard, "exit_code": run.returncode,
                       "accepted": run.returncode == 0, "stdout": run.stdout.strip(), "stderr": run.stderr.strip()})
    return result


def copy_lock_closure(repo: Path, destination: Path) -> None:
    paths = {entry["path"] for entry in read_lock_entries(repo)}
    paths.update(path for path, _, _ in LOCKS)
    paths.update(path for _, path in GUARDS)
    paths.add(".gitattributes")
    for path in paths:
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repo / path, target)


def negative_controls(repo: Path) -> dict:
    """Prove both real guard programs reject drift without editing either lock."""
    with tempfile.TemporaryDirectory(prefix="pulsex-source-lock-controls-") as directory:
        copied = Path(directory)
        copy_lock_closure(repo, copied)
        locks_before = {path: hashes((copied / path).read_bytes()) for path, _, _ in LOCKS}
        target = copied / CONTROL_TARGET
        original = target.read_bytes()
        baseline = run_guards(copied)
        target.write_bytes(original + b"\n# source-lock content negative control\n")
        changed_content = run_guards(copied)
        target.write_bytes(original.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
        crlf_bytes = target.read_bytes()
        accidental_crlf = run_guards(copied)
        target.write_bytes(original)
        restored = run_guards(copied)
        unchanged = all(hashes((copied / path).read_bytes()) == before for path, before in locks_before.items())
        return {
            "target": CONTROL_TARGET, "isolated_temporary_copy": True,
            "baseline": baseline, "content_change": changed_content,
            "accidental_crlf": accidental_crlf, "restored_original_bytes": restored,
            "crlf_evidence": byte_evidence(crlf_bytes),
            "crlf_normalization_matches_original": crlf_bytes.replace(b"\r\n", b"\n") == original,
            "locks_unchanged": unchanged,
            "passed": unchanged and all(item["accepted"] for item in baseline + restored)
            and all(not item["accepted"] for item in changed_content + accidental_crlf),
        }


def checkout_control(repo: Path, windows_policy: bool) -> dict:
    """A native Git checkout on this host with explicit platform EOL policy.

    This is not a claim that Windows itself ran. The actual host and source SHA
    are recorded; Windows CI must still exercise the operating system runtime.
    """
    sha = git(repo, "rev-parse", "HEAD").stdout.decode().strip()
    policy = ["-c", "core.autocrlf=" + ("true" if windows_policy else "false"),
              "-c", "core.eol=" + ("crlf" if windows_policy else "lf")]
    with tempfile.TemporaryDirectory(prefix="pulsex-source-lock-checkout-") as directory:
        checkout = Path(directory) / "checkout"
        subprocess.run(["git", "clone", "--shared", "--no-checkout", "--quiet", str(repo), str(checkout)],
                       check=True, capture_output=True)
        git(checkout, *policy, "checkout", "--detach", "--quiet", sha)
        guards = run_guards(checkout)
        paths = sorted({entry["path"] for entry in read_lock_entries(checkout)})
        eol = git(checkout, *policy, "ls-files", "--eol", "--", *paths).stdout.decode().splitlines()
        controls = {}
        for path in ("Start-Windows.cmd", "Start-Linux.sh"):
            if (checkout / path).is_file():
                controls[path] = byte_evidence((checkout / path).read_bytes())
        locked = {path: byte_evidence((checkout / path).read_bytes()) for path in paths}
        return {
            "source_sha": sha, "host_os": platform.system(), "host_platform": platform.platform(),
            "policy": "Windows-EOL-simulation" if windows_policy else "Linux-EOL-policy",
            "native_windows_executed": platform.system() == "Windows",
            "git_options": policy, "guards": guards, "git_ls_files_eol": eol,
            "locked_files": locked, "platform_script_eol": controls,
            "passed": all(item["accepted"] for item in guards),
        }


def collect_report(repo: Path, *, controls: bool = False, checkouts: bool = False) -> dict:
    repo = repo.resolve()
    entries = read_lock_entries(repo)
    paths = sorted({entry["path"] for entry in entries})
    layers = {}
    for path in paths:
        working = (repo / path).read_bytes() if (repo / path).is_file() else None
        index = git(repo, "show", ":" + path, check=False)
        head = git(repo, "show", "HEAD:" + path, check=False)
        layers[path] = {
            "working": byte_evidence(working),
            "index": byte_evidence(index.stdout if index.returncode == 0 else None),
            "head": byte_evidence(head.stdout if head.returncode == 0 else None),
        }
    for entry in entries:
        evidence = layers[entry["path"]]
        entry["matches_raw_bytes"] = {layer: data.get(entry["algorithm"]) == entry["expected"] for layer, data in evidence.items()}
        entry["normalized_lf_matches_diagnostic_only"] = {
            layer: data.get("normalized_lf_diagnostic_only", {}).get(entry["algorithm"]) == entry["expected"]
            for layer, data in evidence.items()
        }
        entry["working_classification"] = (
            "exact" if entry["matches_raw_bytes"]["working"] else
            "newline_only_drift_rejected" if entry["normalized_lf_matches_diagnostic_only"]["working"] else
            "content_drift_or_missing_rejected"
        )
    attrs = git(repo, "check-attr", "-z", "text", "eol", "--", *paths).stdout.decode().strip("\0").split("\0")
    guards = run_guards(repo)
    report = {
        "schema": "pulsex-source-lock-diagnostics-v1", "mode": "read_only",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_sha": git(repo, "rev-parse", "HEAD").stdout.decode().strip(),
        "git_status": git(repo, "status", "--short").stdout.decode().splitlines(),
        "runtime": {"python": platform.python_version(), "os": platform.system(), "platform": platform.platform(),
                    "git": git(repo, "--version").stdout.decode().strip()},
        "attributes": [{"path": attrs[i], "attribute": attrs[i + 1], "value": attrs[i + 2]} for i in range(0, len(attrs), 3)],
        "git_ls_files_eol": git(repo, "ls-files", "--eol", "--", *paths).stdout.decode().splitlines(),
        "lock_files": {path: {"working": hashes((repo / path).read_bytes()), "head": hashes(git(repo, "show", "HEAD:" + path).stdout)} for path, _, _ in LOCKS},
        "files": layers, "contracts": entries, "guards": guards,
        "limitations": ["Newline-normalized hashes are explanatory only; both acceptance guards hash raw bytes.",
                        "Checkout policy simulation on Linux does not prove Windows runtime execution.",
                        "Migration checksums and migration files are outside this diagnostic and are never edited."],
    }
    if controls:
        report["negative_controls"] = negative_controls(repo)
    if checkouts:
        report["checkouts"] = [checkout_control(repo, False), checkout_control(repo, True)]
    report["source_layers_match_locks"] = all(all(item["matches_raw_bytes"].values()) for item in entries)
    report["lock_files_match_head"] = all(item["working"] == item["head"] for item in report["lock_files"].values())
    report["passed"] = all(item["accepted"] for item in guards)
    report["passed"] &= report["source_layers_match_locks"] and report["lock_files_match_head"]
    report["passed"] &= report.get("negative_controls", {}).get("passed", True)
    report["passed"] &= all(item["passed"] for item in report.get("checkouts", []))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--controls", action="store_true")
    parser.add_argument("--checkouts", action="store_true")
    args = parser.parse_args()
    report = collect_report(args.repo, controls=args.controls, checkouts=args.checkouts)
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
        print(json.dumps({"passed": report["passed"], "source_sha": report["source_sha"], "output": str(args.output)}, ensure_ascii=False))
    else:
        print(encoded, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
