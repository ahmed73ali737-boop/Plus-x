"""SQL-only schema parity and refuse-to-repair ownership violations on PostgreSQL."""
import os,json
from pathlib import Path
import pytest
from sqlalchemy import inspect,select,insert,func
from sqlalchemy.exc import DBAPIError
from app.db import metadata,make_engine,users,sites
from app.self_certificates_db import assets,revisions,links,requests,browser_sessions
from app.core.migrations import ROOT
from tools.certificate_test_database import create_test_database,drop_test_database
from tools.migrate_postgres import execute_script

pytestmark=pytest.mark.skipif(os.environ.get('CERTIFICATE_TEST_POSTGRES')!='true',reason='SQL-only native PostgreSQL acceptance')

def base(engine):
    for table in metadata.sorted_tables:
        if not table.name.startswith('px_self_'):table.create(engine,checkfirst=True)
    for number in range(16,21):
        path=next((ROOT/'ops').glob(f'{number:03}_*.sql'))
        with engine.begin() as conn:execute_script(conn,path.read_text(encoding='utf-8'))

def test_sql_only_new_schema_matches_metadata_columns_keys_constraints(tmp_path):
    url=create_test_database();engine=make_engine(url)
    try:
        base(engine)
        for number in (21,22):
            path=next((ROOT/'ops').glob(f'{number:03}_*.sql'))
            with engine.begin() as conn:execute_script(conn,path.read_text(encoding='utf-8'))
        inspector=inspect(engine);errors=[]
        for table in [t for t in metadata.sorted_tables if t.name.startswith('px_self_')]:
            actual={c['name']:c for c in inspector.get_columns(table.name)}
            expected={c.name:c for c in table.c}
            if set(actual)!=set(expected):errors.append((table.name,'columns'))
            for name in set(actual)&set(expected):
                column=actual[name];definition=expected[name]
                if column['nullable']!=definition.nullable or column['type']._type_affinity!=definition.type._type_affinity or getattr(column['type'],'length',None)!=getattr(definition.type,'length',None):
                    errors.append((table.name,name,'type/nullability'))
            actual_fk={(tuple(f['constrained_columns']),f['referred_table'],tuple(f['referred_columns']),f.get('options',{}).get('ondelete')) for f in inspector.get_foreign_keys(table.name)}
            expected_fk={(tuple(c.name for c in f.columns),f.referred_table.name,tuple(e.column.name for e in f.elements),f.ondelete) for f in table.foreign_key_constraints}
            if actual_fk!=expected_fk:errors.append((table.name,'foreign_keys',str(actual_fk^expected_fk)))
            actual_unique={tuple(c['column_names']) for c in inspector.get_unique_constraints(table.name)}
            expected_unique={tuple(c.name for c in u.columns) for u in table.constraints if u.__class__.__name__=='UniqueConstraint'}
            if actual_unique!=expected_unique:errors.append((table.name,'unique_constraints',str(actual_unique^expected_unique)))
            if set(inspector.get_pk_constraint(table.name)['constrained_columns'])!={c.name for c in table.primary_key}:errors.append((table.name,'primary_key'))
            actual_checks={c['name'] for c in inspector.get_check_constraints(table.name)}
            expected_checks={c.name for c in table.constraints if c.__class__.__name__=='CheckConstraint'}
            if actual_checks!=expected_checks:errors.append((table.name,'checks',str(actual_checks^expected_checks)))
        from tests.certificate_test_support import evidence_root
        path=evidence_root(tmp_path)/'sql-orm-v3.json'
        path.write_text(json.dumps({'status':'passed' if not errors else 'failed','tables':len([t for t in metadata.tables.values() if t.name.startswith('px_self_')]),'differences':errors},ensure_ascii=False,indent=2),encoding='utf-8')
        assert not errors,errors
    finally:engine.dispose();drop_test_database(url)

def test_ownership_migration_stops_without_reassigning_legacy_bad_row():
    url=create_test_database();engine=make_engine(url)
    try:
        base(engine)
        with engine.begin() as conn:
            conn.execute(insert(sites).values(id='event',kind='event',slug='event',draft={},draft_rev=1,published_version=0))
            for ident in ('a','b'):
                conn.execute(insert(users).values(id=ident,email=ident+'@example.test',name=ident,role='organizer',scope_id='event',password_hash='synthetic-unused',active=1,must_change_password=0))
            conn.execute(insert(assets).values(id='bg',owner_account_id='a',kind='background',storage_key='synthetic',sha256='0'*64,mime='image/png',size_bytes=1,width=800,height=600,source_kind='png',original_size_bytes=1,source_metadata={},created_at='2026-01-01'))
            conn.execute(insert(revisions).values(id='old',owner_account_id='a',origin_model_id=None,background_asset_id='bg',stamp_asset_id=None,config={},font_manifest={},branding_manifest=None,renderer_version='legacy',schema_version=1,created_at='2026-01-01'))
            conn.execute(insert(links).values(id='link',owner_account_id='a',event_id='event',event_name_snapshot='event',model_name_snapshot='model',revision_id='old',public_id='public',key_version='v1',public_token_hash='1'*64,status='active',share_text_snapshot='text',config_hash='2'*64,input_hash=None,idempotency_key='operation',row_version=1,created_at='2026-01-01'))
            conn.execute(insert(browser_sessions).values(id='browser',token_hash='3'*64,created_at='2026-01-01',last_seen_at='2026-01-01'))
            conn.execute(insert(requests).values(id='bad-owner',owner_account_id='b',link_id='link',browser_session_id='browser',revision_id='old',participant_name_original='اسم مصطنع',participant_name_normalized='اسم مصطنع',phone_original='0770000000',phone_normalized='0770000000',consent=True,consent_text='إقرار',consent_text_version='v1',submitted_at_utc='2026-01-01',status='registered',layout={}))
        from app.application.self_certificate_integrity import preflight
        with engine.connect() as conn:
            assert not preflight(conn)['ok']
        with pytest.raises(DBAPIError,match='PREFLIGHT_FAILED'):
            with engine.begin() as conn:execute_script(conn,(ROOT/'ops/021_self_certificate_owner_chain.sql').read_text())
        with engine.connect() as conn:
            row=conn.execute(select(requests.c.owner_account_id,requests.c.link_id).where(requests.c.id=='bad-owner')).one()
            assert row==('b','link')
            assert conn.execute(select(func.count()).select_from(requests)).scalar_one()==1
    finally:engine.dispose();drop_test_database(url)
