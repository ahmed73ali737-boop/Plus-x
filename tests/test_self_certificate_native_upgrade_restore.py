"""Full synthetic pre-016 legacy data -> V3 -> native restore -> disabled-new delivery."""
import os,json,time,hashlib,shutil
from pathlib import Path
import pytest
from sqlalchemy import select,insert,func,text
from fastapi.testclient import TestClient
from app.db import metadata,make_engine,sites,users
from app.server import create_app
from app.domain import default_config,now
from app.core.migrations import MIGRATION_PATHS,expected_migration_checksums
from tools.migrate_postgres import execute_script,apply_migrations
from tools.certificate_test_database import create_test_database,drop_test_database
from app.core.security import hash_password
from app.application import certificate_service as legacy,certificate_batches
from app.application.certificate_rendering import render as legacy_render
from app.certificates_db import certificates as legacy_certificates,certificate_jobs
from app.self_certificates_db import certificates,requests
from tests.test_self_certificate_http import new_model,new_link,prepare,submit,A,P,PASSWORD
from tests.test_certificates import import_body

@pytest.mark.skipif(os.environ.get('CERTIFICATE_TEST_POSTGRES')!='true' or os.environ.get('PX_CERTIFICATE_NATIVE_RESTORE_COORDINATED')!='YES',reason='Dedicated native PostgreSQL with host dump/restore coordination required')
def test_historical_upgrade_then_native_backup_restore_and_rollback(monkeypatch,tmp_path):
    from tests.certificate_test_support import evidence_root
    area=evidence_root(tmp_path)/os.environ.get('CERTIFICATE_NATIVE_JOURNEY_NAME','native-journey')
    area.mkdir(exist_ok=True)
    source_url=create_test_database();restored_url=create_test_database()
    source=make_engine(source_url)
    app=restored=None
    report={'status':'running','checks':[],'fixture':'synthetic full pre-016 schema and actual legacy certificate/batch records; not a production historical customer backup'}
    try:
        # Create only legacy tables; metadata.after_create self-service guards
        # are not invoked by individual Table.create calls.
        for table in metadata.sorted_tables:
            if not table.name.startswith('px_self_'):table.create(source,checkfirst=True)
        with source.begin() as conn:
            conn.exec_driver_sql("CREATE TABLE px_schema_migrations(migration_id VARCHAR(160) PRIMARY KEY,checksum VARCHAR(64) NOT NULL,applied_at VARCHAR(64) NOT NULL)")
            for path in MIGRATION_PATHS:
                if int(path.name.split('_')[0])>=16:continue
                execute_script(conn,path.read_text(encoding='utf-8'))
                conn.execute(text('INSERT INTO px_schema_migrations VALUES(:id,:hash,:at)'),{'id':path.name,'hash':expected_migration_checksums()[path.name],'at':now()})
            conn.execute(insert(sites).values(id='self-event',kind='event',slug='self-event',draft=default_config('فعالية تاريخية مصطنعة','event'),draft_rev=1,published_version=0))
            conn.execute(insert(users).values(id='self-a',email='self-a@example.test',name='Synthetic owner',role='organizer',scope_id='self-event',password_hash=hash_password(PASSWORD),active=1,must_change_password=0))
            template=legacy.create_template(conn,'self-event',{'name':'قالب تاريخي'})
            old,old_token,_=legacy.issue(conn,'self-event',{'template_id':template['id'],'request_key':'legacy-request','recipient_key':'legacy-person','award_key':'legacy-award','data':{'participant_name':'اسم تاريخي مصطنع','course_title':'دورة قديمة','issuer_name':'جهة اختبار'}})
            preview=certificate_batches.preview(conn,'self-event','self-a',import_body(template['id']))
            certificate_batches.commit(conn,'self-event','self-a',{'import_id':preview['import_id']})
        old_png=legacy_render(old,'http://testserver/verify/certificate/'+old['serial'],'PNG')
        assert not any(t.startswith('px_self_') for t in __import__('sqlalchemy').inspect(source).get_table_names())
        report['checks'].append('Pre-016 database has actual legacy issued certificate and two pending batch rows; no self-service tables')
        migration=apply_migrations(source)
        assert '020_self_certificate_export_snapshots.sql' in migration['applied']
        assert '021_self_certificate_owner_chain.sql' in migration['applied']
        assert not apply_migrations(source)['applied']
        assert certificate_batches.process_pending(source)==2
        with source.connect() as conn:
            assert conn.execute(select(func.count()).select_from(legacy_certificates)).scalar_one()==3
            assert dict(conn.execute(select(legacy_certificates).where(legacy_certificates.c.id==old['id'])).mappings().one())==old
        report['checks'].append('Additive migration and old batch processing preserve historical certificate snapshot and identifiers')
        monkeypatch.setenv('DATA_DIR',str(area/'source-data'))
        monkeypatch.setenv('PX_SELF_CERTIFICATES_ADMIN','true');monkeypatch.setenv('PX_SELF_CERTIFICATES_ACCEPT_NEW','true')
        app=create_app(source_url,origin='http://testserver',seed_demo=False)
        staff=TestClient(app);login=staff.post('/api/auth/login',json={'email':'self-a@example.test','password':PASSWORD})
        assert login.status_code==200
        staff.headers.update({'X-CSRF':login.json()['csrf'],'Origin':'http://testserver'})
        assert staff.get('/api/public/certificates/access/'+old_token+'/download.png').content==old_png
        model=new_model(staff);link,_=new_link(staff,model)
        first,token,prepared=prepare(app,link)
        assert submit(first,token,prepared).status_code==202
        assert app.state.self_certificate_runtime.generate()
        cap=first.get(P+'/request/'+token+'/mine').json()['receive_url'].rsplit('/',1)[-1]
        value=first.get(P+'/receive/'+cap).json();raw=first.get(value['download_url']).content
        qr=staff.get(A+'/links/'+link['id']+'/qr').content
        queued,_,prepared2=prepare(app,link);assert submit(queued,token,prepared2).status_code==202
        assert staff.delete(A+'/models/'+model['id'],params={'row_version':1}).status_code==200
        assert staff.post(A+'/links/'+link['id']+'/state',json={'status':'paused','row_version':1}).status_code==200
        # No ASGI lifespan was started; the only workers used above were
        # synchronous and are finished. No writers run during the backup.
        app.state.engine.dispose();source.dispose()
        from app.application.self_certificate_executor import shutdown
        for _ in range(30):
            if shutdown(app.state.self_certificate_runtime.store.root):break
            time.sleep(.1)
        else:raise RuntimeError('SYNTHETIC_RENDERER_SHUTDOWN_TIMEOUT')
        time.sleep(.2)
        ready={'source_database':source_url.rsplit('/',1)[-1],'restore_database':restored_url.rsplit('/',1)[-1]}
        (area/'ready.json').write_text(json.dumps(ready),encoding='utf-8')
        for _ in range(600):
            if (area/'restored.json').exists():break
            time.sleep(.2)
        else:raise RuntimeError('NATIVE_RESTORE_COORDINATION_TIMEOUT')
        result=json.loads((area/'restored.json').read_text())
        assert result['status']=='restored',result
        old_store=area/'source-data'
        assert old_store.resolve().is_relative_to(area.resolve())
        old_store.rename(area/'original-data-disabled')
        restored_data=area/'restored-data'
        resource_root=restored_data/'restore-resources'
        monkeypatch.setenv('DATA_DIR',str(restored_data));monkeypatch.setenv('PX_SELF_CERTIFICATE_RESOURCE_ROOT',str(resource_root))
        monkeypatch.setenv('PX_SELF_CERTIFICATES_ADMIN','false');monkeypatch.setenv('PX_SELF_CERTIFICATES_ACCEPT_NEW','false')
        from app.application import self_certificate_fonts as fonts,self_certificate_branding as brand
        monkeypatch.setattr(fonts,'ROOT',resource_root/'fonts')
        monkeypatch.setattr(brand,'RESOURCE_ROOT',resource_root)
        monkeypatch.setattr(brand,'LOGO_PATH',resource_root/'branding/rts'/(brand.LOGO_SHA256+'.png'))
        monkeypatch.setattr(brand,'FONT_PATH',resource_root/'fonts'/(brand.FONT_SHA256+'.ttf'))
        from app.application import certificate_rendering as legacy_renderer
        monkeypatch.setattr(legacy_renderer,'FONT',resource_root/'legacy/CertificateSans.ttf')
        legacy_renderer.font_bytes.cache_clear()
        assert legacy_renderer.FONT.is_file()
        restored=create_app(restored_url,origin='http://testserver',seed_demo=False)
        rb=TestClient(restored)
        assert rb.get(P+'/receive/'+cap).json()['status']=='valid'
        assert rb.get(value['download_url']).content==raw
        assert rb.get('/api/public/certificates/access/'+old_token+'/download.png').content==old_png
        login=rb.post('/api/auth/login',json={'email':'self-a@example.test','password':PASSWORD})
        rb.headers.update({'X-CSRF':login.json()['csrf'],'Origin':'http://testserver'})
        assert rb.get(A+'/links/'+link['id']+'/qr').content==qr
        assert rb.get(A+'/links').json()['items'][0]['status']=='paused'
        assert restored.state.self_certificate_runtime.generate()
        with restored.state.engine.connect() as conn:
            assert conn.execute(select(func.count()).select_from(certificates)).scalar_one()==2
            assert conn.execute(select(func.count()).select_from(legacy_certificates)).scalar_one()==3
        report['checks'].append('Native restore uses independent DB, private data, versioned keys and restored public resources while original data path is disabled')
        report['checks'].append('Old PNG, new issued PNG and QR are byte-identical; queued request completes with both flags off and link paused')
        report.update(status='passed',new_certificate_sha256=hashlib.sha256(raw).hexdigest(),legacy_certificate_sha256=hashlib.sha256(old_png).hexdigest(),restored_legacy=3,restored_new=2,backup=result['backup'],restore=result['restore'],
            limitations=['Synthetic complete historical schema witness, not a copy of a historical production deployment','Measured local logical restore does not certify production scheduling or production 8-hour RTO'])
    except BaseException as error:
        report.update(status='failed',failure_kind=type(error).__name__)
        raise
    finally:
        if app:app.state.engine.dispose()
        if restored:restored.state.engine.dispose()
        source.dispose()
        from app.application import certificate_rendering as legacy_renderer
        legacy_renderer.font_bytes.cache_clear()
        drop_test_database(source_url);drop_test_database(restored_url)
        (area/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
