"""Upgrade an exact pre-V3 ORM schema from retained source without changing its data."""
from pathlib import Path
from types import SimpleNamespace
import builtins,hashlib
import pytest
from sqlalchemy import MetaData,insert,select
from app.db import metadata,make_engine
from app.server import create_app
from app.self_certificates_db import exports

def test_sqlite_pre_v3_export_schema_upgrades_without_replacing_historical_rows(tmp_path,monkeypatch):
    source=Path(__file__).parent/'fixtures/certificates/pre_v3_schema.py.txt'
    old=source.read_bytes()
    expected='cd363b429c78f10f2b4fe28f8230e0c6cf6b95f4af5e03056b7e0034539c84a6'
    assert hashlib.sha256(old).hexdigest()==expected
    historical=MetaData()
    for table in metadata.sorted_tables:
        if not table.name.startswith('px_self_'):table.to_metadata(historical)
    original=builtins.__import__
    def importer(name,globals=None,locals=None,fromlist=(),level=0):
        if name=='app.db':return SimpleNamespace(metadata=historical)
        return original(name,globals,locals,fromlist,level)
    context={'__builtins__':{**vars(builtins),'__import__':importer}}
    exec(compile(old,'verified-pre-v3-self-certificates-schema','exec'),context)
    path=tmp_path/'old.sqlite';engine=make_engine('sqlite:///'+str(path))
    historical.create_all(engine)
    with engine.begin() as conn:
        conn.execute(insert(historical.tables['px_users']).values(id='a',email='a@example.test',name='Synthetic',role='organizer',password_hash='unused-synthetic',active=1,must_change_password=0))
        conn.execute(insert(historical.tables[exports.name]).values(id='legacy-pending',owner_account_id='a',cutoff='2026-01-01',format='csv',status='pending',attempts=0,created_at='2026-01-01'))
    engine.dispose()
    monkeypatch.setenv('DATA_DIR',str(tmp_path/'data'))
    app=create_app('sqlite:///'+str(path),origin='http://testserver',seed_demo=False)
    try:
        with app.state.engine.connect() as conn:
            row=conn.execute(select(exports).where(exports.c.id=='legacy-pending')).mappings().one()
            assert row['cutoff']=='2026-01-01' and row['owner_account_id']=='a'
            assert row['snapshot_version']==1 and row['status']=='failed'
            assert row['error_code']=='EXPORT_SNAPSHOT_LEGACY_REQUIRED'
    finally:app.state.engine.dispose()
