"""Fail if a copied canonical asset silently diverges from the recorded source PR.

Pure stdlib. Intentional refactors must record a new source/review decision.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def verify() -> int:
    lock = json.loads((ROOT / "ops/consolidated-source-lock.json").read_text(encoding="utf-8"))
    if lock.get("status") != "REVIEW_CANDIDATE_NOT_PRODUCTION":
        raise SystemExit("Source lock incorrectly claims release/production admission")
    files = lock.get("files")
    if not isinstance(files, list) or not files:
        raise SystemExit("No source assets locked")
    failures = []
    seen = set()
    for item in files:
        rel = item["path"]
        if rel in seen or rel.startswith("/") or ".." in Path(rel).parts:
            failures.append("duplicate/unsafe path: " + rel)
            continue
        seen.add(rel)
        file_path = ROOT / rel
        if not file_path.is_file():
            failures.append("missing: " + rel)
            continue
        source = file_path.read_bytes()
        blob_sha = hashlib.sha1(
            b"blob " + str(len(source)).encode("ascii") + b"\0" + source
        ).hexdigest()
        if blob_sha != item["blob_sha"]:
            failures.append("source drift: " + rel)
    if failures:
        raise SystemExit("PulseX shared asset source drift:\n" + "\n".join(failures))
    print("PULSEX_SOURCE_LOCK_PASS:", len(seen), "reviewed source files")
    return len(seen)


if __name__ == "__main__":
    verify()
