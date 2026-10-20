"""Integration tests operate only on disposable Git repositories and ZIPs."""
from contextlib import nullcontext
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from types import SimpleNamespace
import zipfile

import pytest

from tools import export_local_test_patch as handoff


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], env=handoff.git_environment())


def make_repo(path):
    path.mkdir()
    git(path, "init", "-q")
    git(path, "config", "user.name", "Synthetic test")
    git(path, "config", "user.email", "synthetic@example.invalid")
    git(path, "config", "core.autocrlf", "false")
    git(path, "config", "core.fsmonitor", "false")
    git(path, "config", "core.hooksPath", str(path / "no-hooks"))
    git(path, "config", "commit.gpgsign", "false")
    (path / "tests").mkdir()
    (path / ".gitignore").write_text("/codex-audit-artifacts/\n", encoding="utf-8")
    for name in ("test_case.py", "test_deleted.py", "test_staged_deleted.py"):
        (path / "tests" / name).write_bytes(b"# original\nassert 1 == 1\n")
    git(path, "add", ".")
    git(path, "commit", "-qm", "Synthetic baseline")
    return path


@pytest.fixture
def repo(tmp_path):
    return make_repo(tmp_path / "repo")


def changed(repo):
    target = repo / "tests/test_case.py"
    target.write_bytes(b"# staged\nassert 2 == 2\n")
    git(repo, "add", "tests/test_case.py")
    target.write_bytes(b"# unstaged CRLF\r\nassert 3 == 3\r\n")
    (repo / "tests/test_deleted.py").unlink()
    git(repo, "rm", "-q", "tests/test_staged_deleted.py")
    (repo / "tests/test_new.mjs").write_bytes(b"export const synthetic = true;\r\n")


def fingerprint(repo):
    return {"head": git(repo, "rev-parse", "HEAD"), "index": (repo / ".git/index").read_bytes(),
            "files": {p.relative_to(repo).as_posix(): p.read_bytes() for p in (repo / "tests").rglob("*") if p.is_file()}}


def test_preserves_all_raw_states_deletions_and_untracked_without_mutation(repo, tmp_path):
    changed(repo)
    before = fingerprint(repo)
    archive = tmp_path / "handoff.zip"
    result = handoff.export(repo, archive)
    assert result["verified"] and result["file_count"] == 4
    assert result["r01_original_patch_recovered"] is False
    assert fingerprint(repo) == before
    with zipfile.ZipFile(archive) as packed:
        manifest = json.loads(packed.read("manifest.json"))
        files = {entry["path"]: entry for entry in manifest["files"]}
        case = files["tests/test_case.py"]
        assert case["status"] == "MM"
        assert packed.read(case["states"]["head"]["member"]) == b"# original\nassert 1 == 1\n"
        assert packed.read(case["states"]["index"]["member"]) == b"# staged\nassert 2 == 2\n"
        assert packed.read(case["states"]["worktree"]["member"]) == b"# unstaged CRLF\r\nassert 3 == 3\r\n"
        assert files["tests/test_deleted.py"]["states"]["worktree"] == {"present": False}
        assert files["tests/test_staged_deleted.py"]["states"]["index"] == {"present": False}
        assert files["tests/test_new.mjs"]["states"]["head"] == {"present": False}
        assert files["tests/test_new.mjs"]["untracked"] is True
        assert manifest["source"]["head"] == before["head"].decode().strip()
    assert handoff.verify(archive)["verified"]


def test_staged_delete_with_untracked_replacement_preserves_both_statuses(repo, tmp_path):
    git(repo, "rm", "-q", "tests/test_case.py")
    (repo / "tests/test_case.py").write_bytes(b"# replacement\r\n")
    result = handoff.export(repo, tmp_path / "replacement.zip")
    assert result["file_count"] == 1
    with zipfile.ZipFile(result["archive"]) as packed:
        entry = json.loads(packed.read("manifest.json"))["files"][0]
        assert set(entry["statuses"]) == {"D ", "??"}
        assert entry["states"]["index"] == {"present": False}
        assert packed.read(entry["states"]["worktree"]["member"]) == b"# replacement\r\n"


def test_dry_run_and_default_ignored_unique_output(repo):
    changed(repo)
    before = fingerprint(repo)
    listing = handoff.export(repo, dry_run=True)
    assert listing["dry_run"] and listing["file_count"] == 4
    assert not (repo / "codex-audit-artifacts").exists()
    first = handoff.export(repo)
    second = handoff.export(repo)
    assert first["archive"] != second["archive"]
    assert git(repo, "check-ignore", first["archive"])
    assert fingerprint(repo) == before


def test_empty_or_only_sensitive_non_sources_fail_without_archive(repo, tmp_path):
    for name in (".env", "debug.log", "cache.db", "app.apk", "secrets.py"):
        (repo / "tests" / name).write_bytes(b"must not export")
    archive = tmp_path / "empty.zip"
    with pytest.raises(handoff.HandoffError, match="No eligible"):
        handoff.export(repo, archive)
    assert not archive.exists()


@pytest.mark.parametrize("location", ["existing", "tests", "dotdot", "git", "tracked"])
def test_output_cannot_overwrite_or_enter_tests_or_git(repo, tmp_path, location):
    changed(repo)
    outputs = {"existing": tmp_path / "exists.zip", "tests": repo / "tests/export.zip",
               "dotdot": repo / "other/../tests/export.zip", "git": repo / ".git/export.zip", "tracked": repo / "tracked.zip"}
    output = outputs[location]
    if location == "existing":
        output.write_bytes(b"keep original")
    if location == "tracked":
        output.write_bytes(b"tracked original")
        git(repo, "add", "tracked.zip")
    with pytest.raises(handoff.HandoffError):
        handoff.export(repo, output)
    if location in ("existing", "tracked"):
        assert output.read_bytes() in (b"keep original", b"tracked original")
    else:
        assert not output.exists()


def test_source_and_output_symlinks_are_rejected(repo, tmp_path, monkeypatch):
    outside = tmp_path / "outside.py"
    outside.write_bytes(b"outside data")
    linked = repo / "tests/test_link.py"
    if os.name != "nt":
        linked.symlink_to(outside)
    else:
        # Windows symlink privileges are optional. Exercise its explicit
        # FILE_ATTRIBUTE_REPARSE_POINT contract without requesting privileges.
        flagged = {linked}
        real_lstat = Path.lstat
        def reparse_lstat(path, *args, **kwargs):
            if path in flagged:
                return SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=0x400)
            return real_lstat(path, *args, **kwargs)
        linked.write_bytes(b"synthetic reparse point")
        monkeypatch.setattr(Path, "lstat", reparse_lstat)
    with pytest.raises(handoff.HandoffError, match="Symlink"):
        handoff.export(repo, tmp_path / "blocked.zip")
    linked.unlink()
    changed(repo)
    parent = tmp_path / "alias"
    if os.name != "nt":
        parent.symlink_to(tmp_path, target_is_directory=True)
    else:
        parent.mkdir()
        flagged.add(parent)
    with pytest.raises(handoff.HandoffError, match="Symlink"):
        handoff.export(repo, parent / "output.zip")
    with pytest.raises(handoff.HandoffError, match="Symlink"):
        handoff.export(parent / repo.name, tmp_path / "alias-repo.zip")
    broken = tmp_path / "broken.zip"
    if os.name != "nt":
        broken.symlink_to(tmp_path / "does-not-exist")
    else:
        flagged.add(broken)
    with pytest.raises(handoff.HandoffError, match="Symlink"):
        handoff.export(repo, broken)
    assert outside.read_bytes() == b"outside data"


def rewrite_zip(source, target, *, mutate=None, extra=None):
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(target, "w") as replacement:
        for info in original.infolist():
            data = original.read(info.filename)
            replacement.writestr(info, mutate(info.filename, data) if mutate else data)
        if extra:
            replacement.writestr(*extra)


@pytest.mark.parametrize("attack", ["tamper", "unlisted", "traversal", "backslash", "duplicate", "symlink", "malformed"])
def test_verifier_rejects_corrupt_or_unsafe_archives_without_extraction(repo, tmp_path, attack):
    changed(repo)
    source = tmp_path / "valid.zip"
    handoff.export(repo, source)
    target = tmp_path / (attack + ".zip")
    if attack == "tamper":
        rewrite_zip(source, target, mutate=lambda name, data: data + b"changed" if name.startswith("states/worktree/") else data)
    elif attack == "malformed":
        rewrite_zip(source, target, mutate=lambda name, data: b'{"schema":1}' if name == "manifest.json" else data)
    else:
        name = {"unlisted": "extra.py", "traversal": "../outside.py", "backslash": "states\\worktree\\tests\\test_case.py", "duplicate": "manifest.json", "symlink": "states/worktree/tests/test_link.py"}[attack]
        info = zipfile.ZipInfo(name)
        if attack == "symlink":
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with pytest.warns(UserWarning) if attack == "duplicate" else nullcontext():
            rewrite_zip(source, target, extra=(info, b"bad"))
    with pytest.raises((handoff.HandoffError, zipfile.BadZipFile)):
        handoff.verify(target)
    assert not (tmp_path / "outside.py").exists()


def test_git_environment_cannot_redirect_explicit_repository(repo, tmp_path, monkeypatch):
    changed(repo)
    foreign = make_repo(tmp_path / "foreign")
    (foreign / "tests/test_case.py").write_bytes(b"FOREIGN MUST NOT EXPORT")
    monkeypatch.setenv("GIT_DIR", str(foreign / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(foreign))
    monkeypatch.setenv("GIT_INDEX_FILE", str(foreign / ".git/index"))
    archive = tmp_path / "explicit.zip"
    handoff.export(repo, archive)
    with zipfile.ZipFile(archive) as packed:
        assert all(b"FOREIGN MUST NOT EXPORT" not in packed.read(info) for info in packed.infolist())


def test_rejects_conflict_and_cleans_archive_if_readback_fails(repo, tmp_path, monkeypatch):
    changed(repo)
    oid = git(repo, "rev-parse", "HEAD:tests/test_case.py").decode().strip()
    subprocess.run(["git", "-C", str(repo), "update-index", "--index-info"], input=f"100644 {oid} 2\ttests/conflict.py\n".encode(), check=True, env=handoff.git_environment())
    with pytest.raises(handoff.HandoffError, match="conflicts"):
        handoff.export(repo, tmp_path / "conflict.zip")
    git(repo, "update-index", "--force-remove", "tests/conflict.py")
    monkeypatch.setattr(handoff, "verify", lambda path: (_ for _ in ()).throw(handoff.HandoffError("readback failed")))
    output = tmp_path / "cleaned.zip"
    with pytest.raises(handoff.HandoffError, match="readback"):
        handoff.export(repo, output)
    assert not output.exists()


def test_cli_returns_nonzero_json_for_empty_export(repo, tmp_path):
    script = Path(handoff.__file__)
    result = subprocess.run([sys.executable, str(script), "export", "--repo", str(repo), "--output", str(tmp_path / "none.zip")], text=True, capture_output=True)
    assert result.returncode == 1
    assert json.loads(result.stderr)["ok"] is False


def test_head_tracked_deleted_output_is_never_recreated(repo):
    output = repo / "source.zip"
    output.write_bytes(b"tracked source")
    git(repo, "add", "source.zip")
    git(repo, "commit", "-qm", "Synthetic tracked ZIP")
    git(repo, "rm", "-q", "source.zip")
    changed(repo)
    with pytest.raises(handoff.HandoffError, match="tracked source"):
        handoff.export(repo, output)
    assert not output.exists()


def test_actual_separate_git_directory_cannot_receive_output(repo, tmp_path):
    changed(repo)
    metadata = tmp_path / "repository-metadata"
    shutil.move(str(repo / ".git"), metadata)
    (repo / ".git").write_text("gitdir: " + metadata.as_posix() + "\n", encoding="utf-8")
    with pytest.raises(handoff.HandoffError, match="Git metadata"):
        handoff.export(repo, metadata / "output.zip")
    assert not (metadata / "output.zip").exists()


@pytest.mark.parametrize("mode", ["120000", "160000"])
def test_git_symlink_and_gitlink_modes_are_rejected_on_every_platform(repo, tmp_path, mode):
    if mode == "120000":
        oid = subprocess.check_output(["git", "-C", str(repo), "hash-object", "-w", "--stdin"], input=b"../../outside", env=handoff.git_environment()).decode().strip()
    else:
        oid = git(repo, "rev-parse", "HEAD").decode().strip()
    git(repo, "update-index", "--add", "--cacheinfo", mode, oid, "tests/test_link.py")
    with pytest.raises(handoff.HandoffError, match="Symlink/gitlink"):
        handoff.export(repo, tmp_path / "blocked-mode.zip")


def test_local_worktree_override_cannot_change_explicit_repository(repo, tmp_path):
    changed(repo)
    foreign = make_repo(tmp_path / "foreign-worktree")
    git(repo, "config", "core.worktree", str(foreign))
    with pytest.raises(handoff.HandoffError, match="outside the discovered"):
        handoff.export(repo, tmp_path / "wrong-root.zip")
