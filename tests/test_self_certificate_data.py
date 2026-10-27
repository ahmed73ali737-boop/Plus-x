"""Real DB contracts for snapshots, deletion, uniqueness and immutable participant data."""
import os, hashlib
from app.domain import now
from app.application.self_certificate_rendering import default_config
import pytest
from sqlalchemy import insert, select, update, delete, func
from sqlalchemy.exc import DBAPIError, IntegrityError
from app.db import metadata, make_engine, sites, users
from app.self_certificates_db import assets, models, revisions, links, browser_sessions, requests, jobs, certificates
from app.application import self_certificate_repository as repo

@pytest.fixture
def db():
    if os.environ.get('CERTIFICATE_TEST_POSTGRES')=='true':
        from tools.certificate_test_database import create_test_database, drop_test_database
        url=create_test_database()
        engine=make_engine(url)
        from tools.migrate_postgres import apply_migrations
        first=apply_migrations(engine)
        assert '016_self_certificates.sql' in first['applied']
        assert not apply_migrations(engine)['applied']
    else:
        engine=make_engine('sqlite:///:memory:')
        metadata.create_all(engine)
    with engine.connect() as conn:
        conn.execute(insert(sites).values(id='event',kind='event',slug='event',draft={},draft_rev=1,published_version=0))
        for ident in ('a','b'):
            conn.execute(insert(users).values(id=ident,email=ident+'@example.test',name=ident,role='organizer',scope_id='event',password_hash='unused-synthetic-fixture',active=1,must_change_password=0))
        for ident,owner,kind in [('bg','a','background'),('stamp','a','stamp'),('bg-b','b','background'),('final','a','final'),('thumb','a','thumbnail')]:
            conn.execute(insert(assets).values(id=ident,owner_account_id=owner,kind=kind,storage_key=ident,sha256='0'*64,mime='image/png',size_bytes=10,width=800,height=600,source_kind='png',original_size_bytes=10,source_metadata={},created_at=now()))
        conn.commit()
        yield conn
        conn.rollback()
    engine.dispose()
    if os.environ.get('CERTIFICATE_TEST_POSTGRES')=='true':drop_test_database(url)

def model(conn,**changes):
    return repo.save_model(conn,{'id':'a'},name='نسخة أولى',background_asset_id='bg',stamp_asset_id='stamp',config=default_config(800,600,True),**changes)

def link(conn,revision,ident='link'):
    row=dict(id=ident,owner_account_id='a',event_id='event',event_name_snapshot='فعالية مثبتة',model_name_snapshot='نموذج مثبت',revision_id=revision,public_id=ident,key_version='v1',public_token_hash=hashlib.sha256(ident.encode()).hexdigest(),status='active',share_text_snapshot='نص ثابت',config_hash='0'*64,idempotency_key=ident,row_version=1,created_at='2026-10-22')
    conn.execute(insert(links).values(**row));return row

def test_revisions_stay_fixed_when_library_is_edited_and_really_deleted(db):
    v1=model(db);l1=link(db,v1['revision']['id'])
    v2=model(db,model_id=v1['id'],row_version=1);l2=link(db,v2['revision']['id'],'link2')
    assert l1['revision_id']!=l2['revision_id']
    assert repo.list_models(db,{'id':'b'})['total']==0
    from fastapi import HTTPException
    with pytest.raises(HTTPException):repo.get_model(db,{'id':'b'},v1['id'])
    with pytest.raises(HTTPException) as exc:model(db,model_id=v1['id'],row_version=1)
    assert exc.value.status_code==409
    repo.delete_model(db,{'id':'a'},v1['id'],2)
    assert db.execute(select(func.count()).select_from(models)).scalar_one()==0
    assert db.execute(select(func.count()).select_from(links)).scalar_one()==2
    assert all(r is None for r in db.execute(select(revisions.c.origin_model_id)).scalars())
    assert db.execute(select(func.count()).select_from(assets)).scalar_one()==5

def test_asset_reference_must_belong_to_the_calling_account(db):
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        repo.save_model(db,{'id':'a'},name='bad',background_asset_id='bg-b',stamp_asset_id=None,config={})

def test_database_rejects_duplicate_request_job_and_certificate_and_freezes_identity(db):
    v=model(db);link(db,v['revision']['id'])
    db.execute(insert(browser_sessions).values(id='browser',token_hash='b'*64,created_at='2026-10-22',last_seen_at='2026-10-22'))
    request=dict(id='request',owner_account_id='a',link_id='link',browser_session_id='browser',revision_id=v['revision']['id'],
        participant_name_original='محمد أحمد علي حسن العمري',participant_name_normalized='محمد أحمد علي حسن العمري',
        phone_original='0770000000',phone_normalized='0770000000',consent=True,consent_text='إقرار اختبار',
        consent_text_version='1',submitted_at_utc='2026-10-22',status='registered',layout={})
    db.execute(insert(requests).values(**request))
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(insert(requests).values(**{**request,'id':'duplicate'}))
    db.execute(insert(jobs).values(id='job',request_id='request',status='pending',attempts=0,available_at='2026-10-22',created_at='2026-10-22'))
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(insert(jobs).values(id='job2',request_id='request',status='pending',attempts=0,available_at='2026-10-22',created_at='2026-10-22'))
    issued=dict(id='cert',owner_account_id='a',request_id='request',link_id='link',serial='TEST',name_printed='محمد العمري',layout={},
        issued_at_utc='2026-10-22',final_asset_id='final',thumbnail_asset_id='thumb',delivery_token_hash='d'*64,key_version='v1',integrity_hash='h'*64,source='self_service',schema_version=1)
    db.execute(insert(certificates).values(**issued))
    db.execute(update(requests).where(requests.c.id=='request').values(status='issued'))
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(insert(certificates).values(**{**issued,'id':'cert2','serial':'TEST2','delivery_token_hash':'e'*64}))
    for table,values in [(requests,{'phone_original':'CHANGED'}),(requests,{'participant_name_original':'CHANGED'}),(requests,{'consent':False}),(certificates,{'name_printed':'CHANGED'}),(revisions,{'config':{'changed':True}}),(links,{'share_text_snapshot':'CHANGED'}),(assets,{'storage_key':'CHANGED'})]:
        with pytest.raises(DBAPIError), db.begin_nested():
            db.execute(update(table).values(**values))
    with pytest.raises(DBAPIError), db.begin_nested():
        db.execute(delete(certificates))
    assert db.execute(select(requests.c.phone_original)).scalar_one()=='0770000000'
    assert db.execute(select(certificates.c.name_printed)).scalar_one()=='محمد العمري'



def test_postgres_twenty_concurrent_requests_keep_one_request_and_one_job(db):
    if db.dialect.name!='postgresql': pytest.skip('Native PostgreSQL concurrency acceptance')
    import secrets
    from concurrent.futures import ThreadPoolExecutor
    v=model(db);link(db,v['revision']['id'])
    db.execute(insert(browser_sessions).values(id='browser',token_hash='b'*64,created_at='2026-10-22',last_seen_at='2026-10-22'))
    db.commit()
    def attempt(_):
        try:
            with db.engine.begin() as conn:
                rid=secrets.token_hex(16)
                conn.execute(insert(requests).values(id=rid,owner_account_id='a',link_id='link',browser_session_id='browser',revision_id=v['revision']['id'],
                    participant_name_original='اسم اختبار',participant_name_normalized='اسم اختبار',phone_original='0770000000',phone_normalized='0770000000',
                    consent=True,consent_text='إقرار',consent_text_version='1',submitted_at_utc='2026-10-22',status='registered',layout={}))
                conn.execute(insert(jobs).values(id=secrets.token_hex(16),request_id=rid,status='pending',attempts=0,available_at='2026-10-22',created_at='2026-10-22'))
            return 'accepted'
        except IntegrityError:
            return 'duplicate'
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes=list(pool.map(attempt,range(20)))
    assert outcomes.count('accepted')==1 and outcomes.count('duplicate')==19
    assert db.execute(select(func.count()).select_from(requests)).scalar_one()==1
    assert db.execute(select(func.count()).select_from(jobs)).scalar_one()==1


def test_cleanup_keeps_live_and_detached_revision_assets_and_removes_only_stale_orphans(db,tmp_path):
    from app.application.self_certificate_storage import CertificateStore,cleanup_unreferenced
    from datetime import datetime,timezone
    import os,time
    store=CertificateStore(tmp_path/'private')
    def asset(ident,age):
        stored=store.put(('synthetic '+ident).encode())
        db.execute(insert(assets).values(id=ident,owner_account_id='a',kind='background',**stored,mime='image/png',width=800,height=600,source_kind='png',original_size_bytes=stored['size_bytes'],source_metadata={},created_at=age))
        return stored
    live=asset('live','2020-01-01T00:00:00+00:00')
    stale=asset('stale','2020-01-01T00:00:00+00:00')
    fresh=asset('fresh',datetime.now(timezone.utc).isoformat())
    model=repo.save_model(db,{'id':'a'},name='live',background_asset_id='live',stamp_asset_id=None,config=default_config(800,600))
    repo.delete_model(db,{'id':'a'},model['id'],1)
    db.commit()
    result=cleanup_unreferenced(db.engine,store)
    assert result['removed_records']>=1
    assert store.path(live['storage_key']).exists()
    assert store.path(fresh['storage_key']).exists()
    assert not store.path(stale['storage_key']).exists()
    assert db.execute(select(assets.c.id).where(assets.c.id=='live')).scalar_one()=='live'
    assert db.execute(select(assets.c.id).where(assets.c.id=='fresh')).scalar_one()=='fresh'
    assert db.execute(select(assets.c.id).where(assets.c.id=='stale')).first() is None


    # Files from crashes before DB registration, and abandoned temporary writes.
    orphan=store.put(b'orphan without database row')
    orphan_path=store.path(orphan['storage_key'])
    old_tmp=orphan_path.with_name(orphan_path.name+'.'+'a'*16+'.tmp')
    new_tmp=orphan_path.with_name(orphan_path.name+'.'+'b'*16+'.tmp')
    old_tmp.write_bytes(b'old interrupted write');new_tmp.write_bytes(b'live write')
    past=time.time()-48*3600
    os.utime(orphan_path,(past,past));os.utime(old_tmp,(past,past))
    db.commit()
    cleanup_unreferenced(db.engine,store)
    assert not orphan_path.exists() and not old_tmp.exists()
    assert new_tmp.exists() and store.path(live['storage_key']).exists()
