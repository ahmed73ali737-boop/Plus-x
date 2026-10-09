"""Focused Linux portability and data-safety regressions; runs on Linux and Windows."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import func, select

from app.core.files import create_private_file
from app.core.paths import ROOT, resolve_database_url
from app.core.settings import load_settings
from app.core.migrations import migration_checksum
from app.db import make_engine, metadata, sites, users
from tools.bootstrap_production import bootstrap

def test_entrypoint_import_is_side_effect_free(tmp_path):
    env={**os.environ,"DATA_DIR":str(tmp_path/"unused"),
         "SEED_DEMO":"true","PULSEX_ENV":"test","PYTHONPATH":str(ROOT)}
    code="import os,run;print(os.getcwd())"
    proc=subprocess.run([sys.executable,"-c",code],cwd=tmp_path,env=env,
                        capture_output=True,text=True)
    assert proc.returncode==0,proc.stderr
    assert proc.stdout.strip()==str(tmp_path)
    assert not (tmp_path/"unused").exists()

def test_sqlite_file_is_resolved_independently_of_cwd(monkeypatch,tmp_path):
    monkeypatch.chdir(tmp_path)
    assert resolve_database_url("sqlite:///./data/pulsex-pilot.sqlite3").startswith(
        "sqlite:////")
    assert str(ROOT/"data"/"pulsex-pilot.sqlite3") in resolve_database_url(
        "sqlite:///./data/pulsex-pilot.sqlite3")
    assert resolve_database_url("sqlite:///:memory:")=="sqlite:///:memory:"
    url="postgresql+psycopg://user:password@db:5432/mydb"
    assert resolve_database_url(url)==url

def test_settings_explicit_false_overrides_env_true(monkeypatch):
    monkeypatch.setenv("PULSEX_ENV","test")
    monkeypatch.setenv("SEED_DEMO","true")
    assert load_settings(seed_demo=False).seed_demo is False
    assert load_settings().seed_demo is True

@pytest.mark.parametrize("value",["maybe","truthiness","2"])
def test_invalid_boolean_rejected(monkeypatch,value):
    monkeypatch.setenv("REQUIRE_POSTGRES",value)
    with pytest.raises(ValueError,match="INVALID_BOOLEAN"):
        load_settings()

@pytest.mark.parametrize("field,value",[("PORT","bad"),("WEB_WORKERS","0"),
                                        ("PORT","65536")])
def test_invalid_port_worker_rejected(monkeypatch,field,value):
    monkeypatch.setenv(field,value)
    with pytest.raises(ValueError):
        load_settings()

def test_gate_uses_effective_factory_overrides_before_opening_database(monkeypatch):
    from app import server
    from tests.test_production_gate import production_env
    production_env(monkeypatch)
    monkeypatch.setenv("PULSEX_ENV","production")
    monkeypatch.setenv("GUEST_ID_SECRET","a"*64)
    def must_not_touch_database(*_args,**_kwargs):
        raise AssertionError("DATABASE_TOUCHED_BEFORE_GATE")
    monkeypatch.setattr(server,"make_engine",must_not_touch_database)
    with pytest.raises(RuntimeError,match="PRODUCTION_GATE_FAILED"):
        server.create_app(database_url="sqlite:///:memory:",origin="http://testserver",seed_demo=True)

def test_sqlite_savepoint_rollback_keeps_outer_transaction_atomic(tmp_path):
    engine=make_engine(f"sqlite:///{tmp_path/'rollback.db'}")
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("CREATE TABLE demo (id INTEGER PRIMARY KEY)")
        with pytest.raises(RuntimeError):
            with engine.begin() as conn:
                with conn.begin_nested():
                    conn.exec_driver_sql("INSERT INTO demo(id) VALUES (1)")
                raise RuntimeError("late failure")
        with engine.connect() as conn:
            assert conn.exec_driver_sql("SELECT count(*) FROM demo").scalar_one()==0
    finally:
        engine.dispose()

@pytest.mark.skipif(os.name=="nt",reason="POSIX permission bits")
def test_credentials_are_exclusive_and_0600_under_permissive_umask(tmp_path):
    target=tmp_path/"secrets"/"admin.json"
    current=os.umask(0)
    try:
        create_private_file(target,'{"secret":"test"}')
    finally:
        os.umask(current)
    assert target.stat().st_mode & 0o777==0o600
    with pytest.raises(FileExistsError):
        create_private_file(target,"overwrite")
    assert target.read_text(encoding="utf-8")=='{"secret":"test"}'

def test_bootstrap_write_failure_rolls_back_account(tmp_path,monkeypatch):
    import tools.bootstrap_production as bootstrap_module
    engine=make_engine(f"sqlite:///{tmp_path/'bootstrap.db'}")
    try:
        def fail_write(*_args,**_kwargs):
            raise OSError("simulated write denied")
        monkeypatch.setattr(bootstrap_module,"create_private_file",fail_write)
        with pytest.raises(OSError,match="simulated"):
            bootstrap(engine,email="admin@example.test",name="Admin",
                      credentials_path=tmp_path/"admin.json")
        with engine.connect() as c:
            assert c.execute(select(func.count()).select_from(sites)).scalar_one()==0
            assert c.execute(select(func.count()).select_from(users)).scalar_one()==0
    finally:
        engine.dispose()

def test_seed_write_failure_rolls_back_demo_rows(tmp_path,monkeypatch):
    from app.infrastructure import seed
    engine=make_engine(f"sqlite:///{tmp_path/'seed.db'}")
    try:
        metadata.create_all(engine)
        monkeypatch.setattr(seed,"create_private_file",lambda *_args,**_kwargs:
                            (_ for _ in ()).throw(OSError("disk refused")))
        with pytest.raises(OSError,match="disk refused"):
            seed.seed_demo_data(engine,credentials_path=tmp_path/"demo.json",count=1)
        with engine.connect() as c:
            assert c.execute(select(func.count()).select_from(sites)).scalar_one()==0
    finally:
        engine.dispose()

def test_migration_checksum_matches_historical_newline_normalization(tmp_path):
    file=tmp_path/"migration.sql"
    original="-- تأريخ\nSELECT 'value';\n"
    file.write_bytes(original.encode("utf-8"))
    expected=migration_checksum(file)
    file.write_bytes(original.replace("\n","\r\n").encode("utf-8"))
    assert migration_checksum(file)==expected
    file.write_bytes(original.replace("value","CHANGED").encode("utf-8"))
    assert migration_checksum(file)!=expected
