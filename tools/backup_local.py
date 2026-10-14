"""SQLite-only local snapshot; explicit database and media paths, never PostgreSQL."""
from __future__ import annotations
import json
import os
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
from sqlalchemy.engine import make_url
from app.core.build_info import runtime_identity
from app.core.settings import load_settings
ROOT=Path(__file__).resolve().parents[1]  # Legacy local-backup root override; production uses resolved Settings.

def backup() -> Path:
    config=load_settings()
    db=make_url(config.database_url)
    if db.get_backend_name()!="sqlite" or not db.database or db.database==":memory:":
        raise RuntimeError("SQLITE_LOCAL_BACKUP_ONLY_POSTGRESQL_NOT_SUPPORTED")
    source=Path(db.database)
    if not os.environ.get("DATABASE_URL") and not os.environ.get("DATA_DIR"):
        # Preserve old local tooling/tests that inject a separate workspace ROOT.
        source=ROOT/"data/pulsex-pilot.sqlite3"
    if not source.is_file():
        raise RuntimeError("LOCAL_SQLITE_DATABASE_NOT_FOUND")
    destination=config.backup_dir
    destination.mkdir(mode=0o700,parents=True,exist_ok=True)
    out=destination/("pulsex-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")+".zip")
    descriptor=os.open(out,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with tempfile.TemporaryDirectory(prefix="pulsex-sqlite-backup-") as tmp:
            snapshot=Path(tmp)/source.name
            with closing(sqlite3.connect(source.as_uri()+"?mode=ro",uri=True)) as src, closing(sqlite3.connect(snapshot)) as dst:
                src.backup(dst)
                if dst.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
                    raise RuntimeError("SQLITE_BACKUP_INTEGRITY_FAILED")
            with os.fdopen(descriptor,"wb") as handle:
                descriptor=-1
                with zipfile.ZipFile(handle,"w",compression=zipfile.ZIP_DEFLATED) as archive:
                    archive.write(snapshot,"data/"+source.name)
                    media=config.media_dir
                    if media.exists():
                        for file in media.rglob("*"):
                            if file.is_file() and not file.is_symlink():
                                archive.write(file,"data/media/"+file.relative_to(media).as_posix())
                    archive.writestr("BACKUP-INFO.json",json.dumps({
                        **runtime_identity(),"database":"SQLite",
                        "source_basename":source.name,
                        "contains_sensitive_data":True,"generated_credentials_included":False,
                        "restore":"Stop the application. Restore into an isolated DATA_DIR and verify before use."
                    },ensure_ascii=False,indent=2))
        return out
    except BaseException:
        if descriptor>=0:
            os.close(descriptor)
        out.unlink(missing_ok=True)
        raise

if __name__=="__main__":
    print("Sensitive local SQLite snapshot: "+str(backup()))
