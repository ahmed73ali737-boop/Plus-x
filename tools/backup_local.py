"""Consistent local SQLite snapshot; never a substitute for PostgreSQL backup."""
from __future__ import annotations
from datetime import datetime, timezone
import json
import os
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import zipfile
ROOT=Path(__file__).resolve().parents[1]

def backup() -> Path:
    if os.environ.get('DATABASE_URL'):
        raise RuntimeError('Custom databases require their own approved backup process. Default SQLite only.')
    source=ROOT/'data/pulsex-pilot.sqlite3'
    if not source.is_file():
        raise RuntimeError('No local database found. Start the application first.')
    destination=ROOT/'backups';destination.mkdir(exist_ok=True)
    out=destination/('pulsex-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.zip')
    with tempfile.TemporaryDirectory(prefix='pulsex-backup-') as td:
        snapshot=Path(td)/'pulsex-pilot.sqlite3'
        # sqlite3.Connection's context manager commits/rolls back but does not
        # close the handle. Explicit closing is required on Windows before the
        # snapshot can be reopened by zipfile.
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as src, closing(sqlite3.connect(snapshot)) as dst:
            src.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                raise RuntimeError('Snapshot failed integrity check.')
        with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot,'data/pulsex-pilot.sqlite3')
            media=ROOT/'data/media'
            if media.exists():
                for p in media.rglob('*'):
                    if p.is_file():archive.write(p,str(p.relative_to(ROOT)).replace('\\','/'))
            archive.writestr('BACKUP-INFO.json',json.dumps({'build':'windows-04','database':'SQLite','contains_sensitive_data':True,'generated_credentials_included':False,'restore':'Stop application; keep an extra copy of current data; extract this data folder only. Never extract over a live database.'},indent=2))
    return out
if __name__=='__main__':
    try: print('Backup created (sensitive): '+str(backup()))
    except Exception as exc:
        print('Backup failed: '+str(exc));raise SystemExit(1)
