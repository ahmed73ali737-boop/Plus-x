"""Database ownership protection, nullable detachment, and migration preflight."""
import hashlib
import pytest
from sqlalchemy import insert, update, select, func
from sqlalchemy.exc import DBAPIError
from tests.test_self_certificate_data import db, model, link
from app.self_certificates_db import models,revisions,links,requests,browser_sessions,assets,certificates,exports,export_snapshot_rows
from app.application.self_certificate_integrity import preflight, require_clean


def owner_fixture(conn):
    a=model(conn)
    revision_a=a['revision']
    revision_b={**revision_a,'id':'revision-b','owner_account_id':'b','origin_model_id':None,'background_asset_id':'bg-b','stamp_asset_id':None}
    conn.execute(insert(revisions).values(**revision_b))
    conn.execute(insert(models).values(id='model-b',owner_account_id='b',name='نموذج ب',current_revision_id='revision-b',row_version=1,created_at='2026-01-01',updated_at='2026-01-01'))
    la=link(conn,revision_a['id'])
    lb={**la,'id':'link-b','owner_account_id':'b','revision_id':'revision-b','public_id':'link-b','public_token_hash':'c'*64,'idempotency_key':'link-b'}
    conn.execute(insert(links).values(**lb))
    conn.execute(insert(browser_sessions).values(id='owner-browser',token_hash='a'*64,created_at='2026-01-01',last_seen_at='2026-01-01'))
    ra=dict(id='request-a',owner_account_id='a',link_id=la['id'],browser_session_id='owner-browser',revision_id=revision_a['id'],participant_name_original='اسم مصطنع',participant_name_normalized='اسم مصطنع',phone_original='0770000000',phone_normalized='0770000000',consent=True,consent_text='إقرار',consent_text_version='1',submitted_at_utc='2026-01-01',status='registered',layout={})
    rb={**ra,'id':'request-b','owner_account_id':'b','link_id':'link-b','revision_id':'revision-b'}
    conn.execute(insert(requests),[ra,rb])
    for ident,kind in [('stamp-b','stamp'),('final-b','final'),('thumb-b','thumbnail'),('export-b','export')]:
        source=dict(conn.execute(select(assets).where(assets.c.id=='bg-b')).mappings().one())
        conn.execute(insert(assets).values(**{**source,'id':ident,'storage_key':ident,'kind':kind}))
    return a,la,lb,ra,rb


def test_database_rejects_every_foreign_owner_edge_and_wrong_asset_kind(db):
    a,la,lb,ra,rb=owner_fixture(db)
    rev=a['revision']
    cert=dict(id='bad-cert',owner_account_id='a',request_id='request-a',link_id=la['id'],serial='CHAIN',name_printed='اسم',layout={},issued_at_utc='2026-01-01',final_asset_id='final',thumbnail_asset_id='thumb',delivery_token_hash='9'*64,key_version='v1',integrity_hash='0'*64,source='self_service',schema_version=2)
    export=dict(id='snapshot-job',owner_account_id='a',cutoff='2026-01-01',format='csv',status='pending',created_at='2026-01-01',attempts=0,snapshot_version=2,snapshot_taken_at='2026-01-01',expected_rows=None)
    db.execute(insert(exports).values(**export))
    snapshot=dict(export_id='snapshot-job',ordinal=1,owner_account_id='a',source_request_id='request-b',participant_name_original='اسم',phone_original='0770000000',model_name_snapshot='نموذج',event_name_snapshot='فعالية',submitted_at_utc='2026-01-01',status='registered')
    cases=[
        (revisions,{**rev,'id':'bad-revision','background_asset_id':'bg-b'}),
        (revisions,{**rev,'id':'bad-revision','stamp_asset_id':'stamp-b'}),
        (revisions,{**rev,'id':'bad-revision','origin_model_id':'model-b'}),
        (revisions,{**rev,'id':'bad-revision','background_asset_id':'stamp'}),
        (models,dict(id='bad-model',owner_account_id='a',name='bad',current_revision_id='revision-b',row_version=1,created_at='now',updated_at='now')),
        (links,{**la,'id':'bad-link','public_id':'bad-link','public_token_hash':'8'*64,'idempotency_key':'bad','revision_id':'revision-b'}),
        (requests,{**ra,'id':'bad-request','link_id':'link-b'}),
        (requests,{**ra,'id':'bad-request','revision_id':'revision-b'}),
        (certificates,{**cert,'owner_account_id':'b','final_asset_id':'final-b','thumbnail_asset_id':'thumb-b'}),
        (certificates,{**cert,'link_id':'link-b'}),
        (certificates,{**cert,'final_asset_id':'final-b'}),
        (certificates,{**cert,'thumbnail_asset_id':'thumb-b'}),
        (certificates,{**cert,'final_asset_id':'thumb'}),
        (exports,{**export,'id':'bad-export','asset_id':'export-b'}),
        (export_snapshot_rows,snapshot),
        (export_snapshot_rows,{**snapshot,'owner_account_id':'b'}),
    ]
    for table,row in cases:
        with pytest.raises(DBAPIError),db.begin_nested():
            db.execute(insert(table).values(**row))
    with pytest.raises(DBAPIError),db.begin_nested():
        db.execute(update(models).where(models.c.id==a['id']).values(current_revision_id='revision-b'))
    assert preflight(db)['ok']


def test_optional_stamp_and_model_detachment_preserve_owner_and_links(db):
    from app.application import self_certificate_repository as repo
    from app.application.self_certificate_rendering import default_config
    a=repo.save_model(db,{'id':'a'},name='بدون ختم',background_asset_id='bg',stamp_asset_id=None,config=default_config(800,600))
    link(db,a['revision']['id'])
    repo.delete_model(db,{'id':'a'},a['id'],1)
    revision=db.execute(select(revisions).where(revisions.c.id==a['revision']['id'])).mappings().one()
    assert revision['origin_model_id'] is None and revision['stamp_asset_id'] is None
    assert revision['owner_account_id']=='a' and preflight(db)['ok']


def test_read_only_preflight_reports_existing_violation_without_reassigning(db):
    # Old SQLite table clone deliberately omits constraints, representing a
    # pre-upgrade witness; never disable guards on the configured database.
    if db.dialect.name!='sqlite':
        pytest.skip('The PostgreSQL legacy upgrade witness is tested separately')
    from app.db import make_engine
    from app.application.self_certificate_integrity import CHECKS
    import app.self_certificates_db as schema
    a,_,_,_,_=owner_fixture(db)
    engine=make_engine('sqlite:///:memory:')
    try:
        with engine.begin() as old:
            for table in dict.fromkeys([t for t,_ in CHECKS]+[assets.name]):
                source=schema.metadata.tables[table]
                columns=', '.join('"'+c.name+'" '+('INTEGER' if c.name=='ordinal' else 'TEXT') for c in source.c)
                old.exec_driver_sql('CREATE TABLE '+table+' ('+columns+')')
            old.exec_driver_sql("INSERT INTO px_self_certificate_revisions(id,owner_account_id,background_asset_id) VALUES ('legacy-bad','a','missing')")
            report=preflight(old)
            assert not report['ok']
            assert 'legacy-bad' in next(p for p in report['problems'] if p['table']==revisions.name)['sample_internal_ids']
            with pytest.raises(RuntimeError,match='PREFLIGHT_FAILED'):
                require_clean(old)
            row=old.exec_driver_sql("SELECT id,owner_account_id,background_asset_id FROM px_self_certificate_revisions").one()
            assert row==('legacy-bad','a','missing')
    finally:
        engine.dispose()
