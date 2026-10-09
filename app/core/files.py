"""POSIX-safe creation of credentials; independent of launcher umask."""
from __future__ import annotations
import os
from pathlib import Path
from .paths import ROOT,resolve_path

def create_private_file(path: str | Path, content: str) -> Path:
    target=resolve_path(path)
    # Secrets must never be written into StaticFiles source.
    if ROOT / "web" in target.parents:
        raise RuntimeError("CREDENTIAL_PATH_PUBLIC")
    if target.is_symlink() or target.exists():
        raise FileExistsError("CREDENTIAL_FILE_EXISTS")
    target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL
    if hasattr(os,"O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd=os.open(target,flags,0o600)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target
