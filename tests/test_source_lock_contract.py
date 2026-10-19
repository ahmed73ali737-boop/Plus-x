"""Source locks remain separate byte contracts across EOL policies and drift."""
from pathlib import Path

import pytest

from tools.source_lock_diagnostics import (
    GUARDS, LOCKS, byte_evidence, checkout_control, collect_report,
    copy_lock_closure, hashes, negative_controls, run_guards,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def copied_sources(tmp_path):
    copied = tmp_path / "isolated-source-copy"
    copy_lock_closure(ROOT, copied)
    return copied


@pytest.mark.parametrize("algorithm", [name for name, _ in GUARDS])
def test_each_guard_accepts_reviewed_bytes_independently(copied_sources, algorithm):
    result = next(item for item in run_guards(copied_sources) if item["algorithm"] == algorithm)
    assert result["accepted"], result


@pytest.mark.parametrize("algorithm", [name for name, _ in GUARDS])
def test_each_guard_rejects_real_content_change_without_lock_edits(copied_sources, algorithm):
    before = {path: (copied_sources / path).read_bytes() for path, _, _ in LOCKS}
    target = copied_sources / "requirements-observability.txt"
    target.write_bytes(target.read_bytes() + b"\n# modified dependency content\n")
    result = next(item for item in run_guards(copied_sources) if item["algorithm"] == algorithm)
    assert result["exit_code"] != 0 and not result["accepted"], result
    assert "requirements-observability.txt" in result["stderr"]
    assert all((copied_sources / path).read_bytes() == original for path, original in before.items())


@pytest.mark.parametrize("algorithm", [name for name, _ in GUARDS])
def test_accidental_crlf_is_rejected_and_exact_restore_passes(copied_sources, algorithm):
    target = copied_sources / "requirements-observability.txt"
    original = target.read_bytes()
    assert b"\r" not in original and b"\n" in original
    changed = original.replace(b"\n", b"\r\n")
    target.write_bytes(changed)
    evidence = byte_evidence(changed)
    assert evidence["normalized_lf_diagnostic_only"][algorithm] == hashes(original)[algorithm]
    assert evidence[algorithm] != hashes(original)[algorithm]
    rejected = next(item for item in run_guards(copied_sources) if item["algorithm"] == algorithm)
    assert not rejected["accepted"], rejected
    target.write_bytes(original)
    restored = next(item for item in run_guards(copied_sources) if item["algorithm"] == algorithm)
    assert restored["accepted"], restored


@pytest.mark.parametrize("windows_policy", [False, True])
def test_clean_checkout_respects_lf_locked_assets_and_platform_scripts(windows_policy):
    result = checkout_control(ROOT, windows_policy)
    assert result["passed"], result["guards"]
    for path, evidence in result["locked_files"].items():
        assert evidence["eol"]["crlf"] == evidence["eol"]["bare_cr"] == 0, path
    assert result["platform_script_eol"]["Start-Windows.cmd"]["eol"]["crlf"] > 0
    assert result["platform_script_eol"]["Start-Linux.sh"]["eol"]["crlf"] == 0


def test_negative_control_report_keeps_hash_contracts_independent():
    result = negative_controls(ROOT)
    assert result["passed"] and result["locks_unchanged"]
    assert result["crlf_normalization_matches_original"]
    assert {item["algorithm"] for item in result["content_change"]} == {"sha256", "git_blob_sha1"}


def test_diagnostic_distinguishes_working_index_and_head_without_mutation():
    before = {path: (ROOT / path).read_bytes() for path, _, _ in LOCKS}
    report = collect_report(ROOT)
    assert report["passed"]
    assert report["source_layers_match_locks"] and report["lock_files_match_head"]
    for contract in report["contracts"]:
        assert contract["working_classification"] == "exact", contract
        assert all(contract["matches_raw_bytes"].values()), contract
    assert all((ROOT / path).read_bytes() == original for path, original in before.items())
