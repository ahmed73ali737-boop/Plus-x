"""P05: inventory privacy, stable history and isolated logical SQLite restore."""
from datetime import date
import json, sqlite3, zipfile
from sqlalchemy import create_engine, insert, select, text, update
import pytest
from app.db import event_guests, sites, versions
from app.core.migrations import MIGRATION_PATHS
from app.infrastructure.seed import seed_demo_data
from app.server import create_app
from tools.upgrade_inventory import inventory, state_fingerprints
from tools import backup_local
from harness_support import app_client
from test_admission_gate_integration import admission, scan


def test_inventory_is_read_only_redacted_and_detects_forged_links(admission):
    app,_,_,scanner,number,_=admission
    assert scan(scanner,number,'inventory-scan',quantity=2)['status']=='accepted'
    with app.state.engine.connect() as c:
        before=state_fingerprints(c)
        report=inventory(c)
        assert state_fingerprints(c)==before
    assert report['events']['event-demo']['linked_invitations']==1
    output=json.dumps(report)
    for secret in [number,'777444222','token_hash','phone_e164','pass_token_hash']:
        assert secret not in output
    with app.state.engine.begin() as c:
        c.execute(update(event_guests).values(metadata_json={'invitation_id':'forged'}))
        assert inventory(c)['events']['event-demo']['invalid_invitation_links']==1


def test_inventory_reads_old_schema_without_writing_missing_columns(tmp_path):
    engine=create_engine('sqlite:///'+str(tmp_path/'old.sqlite'))
    try:
        with engine.begin() as c:
            c.exec_driver_sql('CREATE TABLE px_event_guests(event_id TEXT, guest_id TEXT)')
            c.exec_driver_sql("INSERT INTO px_event_guests VALUES ('legacy-event','legacy-guest')")
        with engine.connect() as c:
            c.exec_driver_sql('PRAGMA query_only=ON')
            report=inventory(c)
            assert report['events']['legacy-event']['legacy_passes']==1
            assert len(report['migration_missing'])==len(MIGRATION_PATHS)
    finally:engine.dispose()


def test_new_demo_chooses_dates_once_and_does_not_republish_existing(tmp_path):
    app=create_app('sqlite:///'+str(tmp_path/'demo.sqlite'),seed_demo=False)
    with app_client(app):
        seed_demo_data(app.state.engine,demo_day=date(2026,11,10))
        with app.state.engine.connect() as c:
            config=c.execute(select(versions.c.config).where(versions.c.site_id=='event-demo')).scalar_one()
            assert config['start']=='2026-11-10T09:00:00+03:00'
            assert config['end']=='2026-11-14T20:00:00+03:00'
            assert config['records'][0]['start']=='2026-11-10T10:00:00+03:00'
            before=state_fingerprints(c)
        assert seed_demo_data(app.state.engine,demo_day=date(2027,1,1))==[]
        with app.state.engine.connect() as c:assert state_fingerprints(c)==before


def test_sqlite_backup_restore_preserves_ledger_and_detects_post_snapshot_write(admission,tmp_path,monkeypatch):
    app,_,_,scanner,number,_=admission
    assert scan(scanner,number,'before-backup',quantity=1)['status']=='accepted'
    monkeypatch.setenv('DATABASE_URL',app.state.engine.url.render_as_string(hide_password=False))
    monkeypatch.setenv('BACKUP_DIR',str(tmp_path/'snapshots'))
    monkeypatch.setenv('MEDIA_DIR',str(tmp_path/'media'))
    media=tmp_path/'media';media.mkdir();(media/'synthetic.txt').write_text('fixture only')
    with app.state.engine.connect() as c:before=state_fingerprints(c)
    archive=backup_local.backup()
    restored=tmp_path/'restored';restored.mkdir()
    with zipfile.ZipFile(archive) as z:
        member=next(n for n in z.namelist() if n.startswith('data/') and n.endswith('.sqlite'))
        target=restored/'restored.sqlite';target.write_bytes(z.read(member))
        assert z.read('data/media/synthetic.txt')==b'fixture only'
    clone=create_engine('sqlite:///'+str(target))
    try:
        with clone.connect() as c:assert state_fingerprints(c)==before
        assert scan(scanner,number,'after-backup',quantity=1)['status']=='accepted'
        with app.state.engine.connect() as c:assert state_fingerprints(c)!=before
        # No restore operation is offered against the running source.
        with clone.connect() as c:
            assert c.execute(text('SELECT sum(consumed) FROM px_admission_entitlements')).scalar_one()==1
        with app.state.engine.connect() as c:
            assert c.execute(text('SELECT sum(consumed) FROM px_admission_entitlements')).scalar_one()==2
    finally:clone.dispose()
