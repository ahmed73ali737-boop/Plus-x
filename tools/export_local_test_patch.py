"""Export original local test changes as raw HEAD/index/worktree snapshots.

This is a handoff archive, not an automatic patch application or R01 closure.
No source files or Git index are modified, and exported tests are never run.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import uuid
import zipfile
import zlib

SCHEMA = "pulsex-local-test-handoff-v1"
STATES = ("head", "index", "worktree")
EXTENSIONS = {".py", ".mjs", ".js", ".cjs", ".ts", ".tsx", ".jsx", ".sh", ".ps1", ".cmd", ".bat", ".sql", ".feature"}
SECRET_NAMES = {"secret", "secrets", "credential", "credentials", "password", "passwords", "token", "tokens", "id_rsa", "id_ed25519"}
MAX_FILES = 300
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 24 * 1024 * 1024
MAX_ZIP_BYTES = 32 * 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024


class HandoffError(ValueError):
    pass


def git_environment() -> dict:
    overrides = {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                 "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_NAMESPACE",
                 "GIT_CONFIG", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS", "GIT_CEILING_DIRECTORIES",
                 "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_DISCOVERY_ACROSS_FILESYSTEM"}
    env = {key: value for key, value in os.environ.items()
           if key not in overrides and not key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))}
    return {**env, "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_LAZY_FETCH": "1"}


def git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", str(repo), *args], env=git_environment(), capture_output=True)
    if result.returncode:
        raise HandoffError("Git read failed: " + " ".join(args[:2]))
    return result.stdout


def digests(data: bytes) -> dict:
    return {"size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "git_blob_sha1": hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()}


def canonical_path(value: str) -> tuple[str, ...]:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value or any(ord(c) < 32 for c in value):
        raise HandoffError("Invalid portable path")
    parts = tuple(value.split("/"))
    if any(p in ("", ".", "..") or p.endswith((" ", ".")) for p in parts):
        raise HandoffError("Non-canonical path")
    if PurePosixPath(value).is_absolute():
        raise HandoffError("Absolute path forbidden")
    return parts


def source_allowed(path: str) -> bool:
    parts = canonical_path(path)
    if len(parts) < 2 or parts[0] != "tests":
        return False
    if any(p.startswith(".") or Path(p).stem.casefold() in SECRET_NAMES or re.fullmatch(r"CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]", p.split(".")[0], re.I) for p in parts):
        return False
    return Path(parts[-1]).suffix.lower() in EXTENSIONS


def no_links(path: Path) -> None:
    """Reject leaf/parent links, including Windows junction/reparse points."""
    for item in reversed((path, *path.parents)):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise HandoffError("Symlink/reparse path forbidden: " + str(item))


def read_regular(path: Path, limit: int = MAX_FILE_BYTES) -> bytes | None:
    no_links(path)
    try:
        before = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
        raise HandoffError("Not a bounded regular file: " + str(path))
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
    with os.fdopen(descriptor, "rb") as stream:
        data = stream.read(limit + 1)
        opened = os.fstat(stream.fileno())
    no_links(path)
    after = path.lstat()
    if len(data) > limit or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) or (opened.st_dev, opened.st_ino) != (after.st_dev, after.st_ino):
        raise HandoffError("File changed while reading: " + str(path))
    return data


def status_rows(raw: bytes) -> list[dict]:
    rows = []
    for record in raw.split(b"\0"):
        if record:
            if len(record) < 4 or record[2:3] != b" ":
                raise HandoffError("Invalid Git status record")
            rows.append({"status": record[:2].decode("ascii"), "path": os.fsdecode(record[3:])})
    return rows


def git_state(repo: Path) -> dict:
    if git(repo, "ls-files", "--unmerged", "-z"):
        raise HandoffError("Unresolved Git conflicts must be resolved before handoff")
    return {"head": git(repo, "rev-parse", "HEAD").decode().strip(),
            "tree": git(repo, "rev-parse", "HEAD^{tree}").decode().strip(),
            "status": git(repo, "-c", "status.renames=false", "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", "tests"),
            "index": git(repo, "ls-files", "--stage", "-z", "--", "tests")}


def objects(raw: bytes, *, index: bool) -> dict:
    result = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        header, path = record.split(b"\t", 1)
        mode, middle, last = header.decode("ascii").split(" ")
        if index and last != "0":
            raise HandoffError("Unmerged index stage")
        result[os.fsdecode(path)] = {"mode": mode, "oid": middle if index else last}
    return result


def collect(repo: Path) -> tuple[dict, dict[str, bytes]]:
    repo = repository_root(repo)
    no_links(repo / "tests")
    initial = git_state(repo)
    index = objects(initial["index"], index=True)
    head = objects(git(repo, "ls-tree", "-r", "-z", initial["head"], "--", "tests"), index=False)
    rows = status_rows(initial["status"])
    candidates = {}
    for row in rows:
        candidate = candidates.setdefault(row["path"], {**row, "statuses": []})
        candidate["statuses"].append(row["status"])
    files, skipped, payloads = [], [], {}
    seen = set()
    for row in candidates.values():
        path = row["path"]
        canonical_path(path)
        no_links(repo / path)
        for layer in (head, index):
            if path in layer and layer[path]["mode"] not in ("100644", "100755"):
                raise HandoffError("Symlink/gitlink test entry forbidden: " + path)
        if not source_allowed(path):
            skipped.append({**row, "reason": "not_visible_test_source_or_sensitive_path"})
            continue
        if len(files) >= MAX_FILES:
            raise HandoffError("Handoff file limit exceeded")
        if path.casefold() in seen:
            raise HandoffError("Case-insensitive source path collision")
        seen.add(path.casefold())
        entry = {**row, "untracked": path not in head and path not in index, "states": {}}
        for state in STATES:
            obj = (head if state == "head" else index).get(path) if state != "worktree" else None
            if state == "worktree":
                data = read_regular(repo / path)
                mode = "100755" if data is not None and (repo / path).stat().st_mode & stat.S_IXUSR else "100644"
            elif obj:
                if int(git(repo, "cat-file", "-s", obj["oid"])) > MAX_FILE_BYTES:
                    raise HandoffError("Git blob exceeds handoff limit")
                data, mode = git(repo, "cat-file", "blob", obj["oid"]), obj["mode"]
            else:
                data, mode = None, None
            if data is None:
                entry["states"][state] = {"present": False}
                continue
            member = f"states/{state}/{path}"
            payloads[member] = data
            if sum(map(len, payloads.values())) > MAX_TOTAL_BYTES:
                raise HandoffError("Handoff byte limit exceeded")
            entry["states"][state] = {"present": True, "mode": mode, "member": member, **digests(data)}
        files.append(entry)
    if not files:
        raise HandoffError("No eligible changed test source files found")
    if len(files) > MAX_FILES or sum(map(len, payloads.values())) > MAX_TOTAL_BYTES:
        raise HandoffError("Handoff size/file limit exceeded")
    # Status=M does not detect a second edit: compare exact worktree bytes too.
    for entry in files:
        state = entry["states"]["worktree"]
        current = read_regular(repo / entry["path"])
        if (current is not None) != state["present"] or (current is not None and digests(current) != {k: state[k] for k in ("size", "sha256", "git_blob_sha1")}):
            raise HandoffError("Test source changed during handoff")
    if git_state(repo) != initial:
        raise HandoffError("Git HEAD/index/status changed during handoff")
    manifest = {"schema": SCHEMA, "created_at": datetime.now(timezone.utc).isoformat(),
                "source": {"head": initial["head"], "tree": initial["tree"], "status": rows},
                "file_count": len(files), "files": files, "skipped": skipped,
                "purpose": "raw_state_handoff_not_auto_apply", "r01_original_patch_recovered": False,
                "note": "Actual local count only; no assumption of six original files. Original R01 patch remains unverified until received and reviewed."}
    return manifest, payloads


def unique_json(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise HandoffError("Duplicate manifest key")
        obj[key] = value
    return obj


def verify(archive: Path) -> dict:
    raw = read_regular(archive.absolute(), MAX_ZIP_BYTES)
    if raw is None:
        raise HandoffError("Archive missing or over size limit")
    with zipfile.ZipFile(io.BytesIO(raw)) as packed:
        members = packed.infolist()
        if len(members) > MAX_FILES * 3 + 1 or sum(item.file_size for item in members) > MAX_TOTAL_BYTES + MAX_MANIFEST_BYTES:
            raise HandoffError("Archive member/size limit exceeded")
        names, folded = {}, set()
        for info in members:
            canonical_path(info.orig_filename)
            if info.orig_filename != info.filename:
                raise HandoffError("Ambiguous ZIP member name")
            canonical_path(info.filename)
            mode = info.external_attr >> 16
            if info.is_dir() or stat.S_IFMT(mode) not in (0, stat.S_IFREG) or info.flag_bits & 1 or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise HandoffError("Non-regular/encrypted ZIP member forbidden")
            if info.filename.casefold() in folded:
                raise HandoffError("Duplicate/colliding ZIP member")
            folded.add(info.filename.casefold())
            names[info.filename] = info
            if info.file_size > (MAX_MANIFEST_BYTES if info.filename == "manifest.json" else MAX_FILE_BYTES):
                raise HandoffError("ZIP member too large")
        if "manifest.json" not in names:
            raise HandoffError("Missing manifest")
        manifest = json.loads(packed.read("manifest.json"), object_pairs_hook=unique_json)
        if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA or manifest.get("purpose") != "raw_state_handoff_not_auto_apply" or manifest.get("r01_original_patch_recovered") is not False:
            raise HandoffError("Unsupported handoff manifest")
        source = manifest.get("source")
        if not isinstance(source, dict):
            raise HandoffError("Invalid source identity")
        for key in ("head", "tree"):
            if not isinstance(source.get(key), str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", source[key]):
                raise HandoffError("Invalid source Git identity")
        files = manifest.get("files")
        if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES or manifest.get("file_count") != len(files):
            raise HandoffError("Invalid file count")
        expected, sources = {"manifest.json"}, set()
        for entry in files:
            if not isinstance(entry, dict) or not isinstance(entry.get("states"), dict):
                raise HandoffError("Invalid source entry structure")
            path = entry.get("path", "")
            if not source_allowed(path) or path.casefold() in sources or set(entry.get("states", {})) != set(STATES):
                raise HandoffError("Invalid/duplicate test source entry")
            sources.add(path.casefold())
            if not any(isinstance(item, dict) and item.get("present") is True for item in entry["states"].values()):
                raise HandoffError("Empty source entry")
            for state, item in entry["states"].items():
                if item == {"present": False}:
                    continue
                member = f"states/{state}/{path}"
                if not isinstance(item, dict) or item.get("present") is not True or item.get("member") != member or item.get("mode") not in ("100644", "100755") or member not in names:
                    raise HandoffError("Invalid or missing state payload")
                expected.add(member)
                data = packed.read(member)
                if any(item.get(k) != value for k, value in digests(data).items()):
                    raise HandoffError("State payload hash/size mismatch: " + member)
        if set(names) != expected:
            raise HandoffError("Unlisted payloads in handoff")
    return {"verified": True, "source_head": manifest["source"]["head"], "file_count": len(files),
            "archive_sha256": hashlib.sha256(raw).hexdigest(),
            "r01_original_patch_recovered": False, "verification_scope": "archive_integrity_and_structure_only"}


def repository_root(supplied: Path) -> Path:
    no_links(supplied.absolute())
    supplied = supplied.resolve()
    root = Path(os.fsdecode(git(supplied, "rev-parse", "--show-toplevel")).strip()).resolve()
    if not supplied.is_relative_to(root):
        raise HandoffError("Explicit --repo is outside the discovered Git worktree")
    return root


def export(repo: Path, output: Path | None = None, *, dry_run: bool = False) -> dict:
    repo = repository_root(repo)
    manifest, payloads = collect(repo)
    if dry_run:
        return {"dry_run": True, "source_head": manifest["source"]["head"], "file_count": manifest["file_count"],
                "files": [{"path": f["path"], "status": f["status"]} for f in manifest["files"]], "skipped": manifest["skipped"], "r01_original_patch_recovered": False}
    if output is None:
        name = "test-changes-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex[:8] + ".zip"
        output = repo / "codex-audit-artifacts" / "phase01-handoff" / name
        check = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", str(repo), "check-ignore", "--quiet", str(output)], env=git_environment())
        if check.returncode:
            raise HandoffError("Default handoff directory is not ignored; supply an external --output ZIP")
    output = output.absolute()
    no_links(output)
    output = output.resolve(strict=False)
    no_links(output)
    if output.suffix.lower() != ".zip" or any(part.casefold() == ".git" for part in output.parts) or output.is_relative_to(repo / "tests"):
        raise HandoffError("Output must be a ZIP outside tests and Git metadata")
    for option in ("--absolute-git-dir", "--git-common-dir"):
        metadata = Path(os.fsdecode(git(repo, "rev-parse", option)).strip())
        metadata = (repo / metadata).resolve() if not metadata.is_absolute() else metadata.resolve()
        if output.is_relative_to(metadata):
            raise HandoffError("Output inside Git metadata is forbidden")
    if output.is_relative_to(repo):
        rel = output.relative_to(repo).as_posix()
        literal = ":(literal)" + rel
        if git(repo, "ls-files", "-z", "--", literal) or git(repo, "ls-tree", "-r", "-z", "HEAD", "--", literal):
            raise HandoffError("Output cannot replace a tracked source path")
    if os.path.lexists(output):
        raise HandoffError("Output already exists; overwrite is forbidden")
    output.parent.mkdir(parents=True, exist_ok=True)
    no_links(output)
    temporary = output.with_name(output.name + "." + uuid.uuid4().hex + ".part")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0), 0o600)
    published = False
    try:
        with os.fdopen(descriptor, "wb") as stream, zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as packed:
            entries = {"manifest.json": json.dumps(manifest, ensure_ascii=True, indent=2).encode("utf-8"), **payloads}
            for name, data in entries.items():
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o600) << 16
                packed.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)
        verify(temporary)
        no_links(output)
        # Rename is no-clobber on Windows. POSIX hard-link publication is atomic
        # and refuses any existing destination; both paths use the same folder.
        if os.name == "nt":
            os.rename(temporary, output)
        else:
            os.link(temporary, output)
        published = True
        result = verify(output)
    except Exception:
        if published:
            output.unlink(missing_ok=True)
        raise
    finally:
        temporary.unlink(missing_ok=True)
    return {**result, "archive": str(output)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    writer = commands.add_parser("export")
    writer.add_argument("--repo", required=True, type=Path)
    writer.add_argument("--output", type=Path)
    writer.add_argument("--dry-run", action="store_true")
    reader = commands.add_parser("verify")
    reader.add_argument("archive", type=Path)
    args = parser.parse_args(argv)
    try:
        result = export(args.repo, args.output, dry_run=args.dry_run) if args.command == "export" else verify(args.archive)
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except (HandoffError, OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, zlib.error, RuntimeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
