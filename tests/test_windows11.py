import uuid
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.server import create_app
from app.db import organizations, organization_people, memberships, users, event_participations, submissions


def boot(tmp_path):
    app=create_app('sqlite:///'+str(tmp_path/'w11.sqlite'),origin='http://testserver',seed_demo=True)
    return app,TestClient(app)


def login(c,app,email):
    cred=next(x for x in app.state.seed_credentials if x['email']==email)
    r=c.post('/api/auth/login',json={'email':cred['email'],'password':cred['password']})
    assert r.status_code==200
    c.headers.update({'X-CSRF':r.json()['csrf'],'Origin':'http://testserver'})
    return r.json()['user']


def public_envelope(site_id,version,kind='survey',source='web',target='main',payload=None,visitor=None,session=None):
    return {
      'id':str(uuid.uuid4()),'site_id':site_id,'version':version,'kind':kind,
      'visitor_id':visitor or str(uuid.uuid4()),'session_id':session or str(uuid.uuid4()),
      'source':source,'target':target,'payload':payload or {},'client_time':'2026-10-01T19:00:00+03:00'
    }


def test_platform_creates_event_then_organizer_account(tmp_path):
    app,c=boot(tmp_path); login(c,app,'admin@pulsex.test')
    created=c.post('/api/admin/sites',json={'kind':'event','parent_id':'platform','title':'Event Eleven','slug':'event-eleven'})
    assert created.status_code==200
    eid=created.json()['id']
    r=c.post(f'/api/admin/sites/{eid}/users',json={'name':'مدير الفعالية','email':'event11@organizer.test'})
    assert r.status_code==200 and r.json()['role']=='organizer' and r.json()['temporary_password']
    c2=TestClient(app)
    lr=c2.post('/api/auth/login',json={'email':'event11@organizer.test','password':r.json()['temporary_password']})
    assert lr.status_code==200 and lr.json()['user']['scope_id']==eid


def test_organizer_internal_create_org_creates_participation_without_account(tmp_path):
    app,c=boot(tmp_path); login(c,app,'organizer@pulsex.test')
    r=c.post('/api/admin/organizations',json={'name':'Display Only Co','slug':'display-only-co','booth':'D-9','description':'بدون حساب'})
    assert r.status_code==200
    oid=r.json()['id']
    with app.state.engine.connect() as db:
        assert db.execute(select(event_participations).where(event_participations.c.organization_id==oid)).first()
        assert not db.execute(select(memberships).where(memberships.c.organization_id==oid)).first()


def test_non_account_person_can_exist_and_account_can_be_added_later(tmp_path):
    app,c=boot(tmp_path); login(c,app,'organizer@pulsex.test')
    oid=c.post('/api/admin/organizations',json={'name':'People Co','slug':'people-co'}).json()['id']
    p=c.post(f'/api/admin/organizations/{oid}/people',json={'name':'سارة','email':'sara@people.test','phone':'+967777111222','job_title':'مبيعات','person_role':'representative','public_visible':False})
    assert p.status_code==200 and p.json()['has_account'] is False
    pid=p.json()['id']
    listed=c.get(f'/api/admin/organizations/{oid}/people').json()['people']
    assert next(x for x in listed if x['id']==pid)['user_id'] is None
    created=c.post(f'/api/admin/organizations/{oid}/people/{pid}/account',json={'role':'editor'})
    assert created.status_code==200 and created.json()['temporary_password']
    c2=TestClient(app)
    lr=c2.post('/api/auth/login',json={'email':'sara@people.test','password':created.json()['temporary_password']})
    assert lr.status_code==200
    with app.state.engine.connect() as db:
        person=db.execute(select(organization_people).where(organization_people.c.id==pid)).mappings().first()
        assert person['user_id']
        assert db.execute(select(memberships).where(memberships.c.user_id==person['user_id'],memberships.c.organization_id==oid)).first()


def test_non_account_people_do_not_need_login_for_survey_and_rating(tmp_path):
    app,c=boot(tmp_path)
    # Public page already published in demo seed; interaction is public regardless of organization membership/account.
    page=c.get('/api/public/site/agency-01').json(); ver=page['version']
    survey=public_envelope('agency-01',ver,'survey','qr','main',{'answers':{'q-interest':'o1','q-rate':5}})
    feedback=public_envelope('agency-01',ver,'feedback','qr','agency-01:general',{'rating':5,'criteria':{'overall':5},'note':'مشاركة بدون حساب'})
    r=c.post('/api/collect',json={'items':[survey,feedback]})
    assert [x['status'] for x in r.json()['receipts']]==['accepted','accepted']


def test_qr_source_is_preserved_and_metrics_accept_public_visitor(tmp_path):
    app,c=boot(tmp_path)
    page=c.get('/api/public/site/agency-01').json(); ver=page['version']; visitor=str(uuid.uuid4()); session=str(uuid.uuid4())
    visit=public_envelope('agency-01',ver,'visit','qr','',{},visitor,session)
    assert c.post('/api/collect',json={'items':[visit]}).json()['receipts'][0]['status']=='accepted'
    login(c,app,'agency01@pulsex.test')
    metrics=c.get('/api/admin/sites/agency-01/metrics').json()
    assert metrics['counts']['visit']>=1 and metrics['browser_ids_estimate']>=1


def test_offline_queue_contract_server_ack_and_duplicate(tmp_path):
    app,c=boot(tmp_path)
    page=c.get('/api/public/site/agency-01').json(); ver=page['version']
    item=public_envelope('agency-01',ver,'survey','kiosk','main',{'answers':{'q-interest':'o1','q-rate':4}})
    first=c.post('/api/collect',json={'items':[item]}).json()['receipts'][0]
    second=c.post('/api/collect',json={'items':[item]}).json()['receipts'][0]
    assert first['status']=='accepted' and second['status']=='duplicate'
    with app.state.engine.connect() as db:
        assert db.execute(select(submissions).where(submissions.c.id==item['id'])).fetchall().__len__()==1


def test_kiosk_two_visitors_use_separate_sessions_and_count_as_kiosk_sessions(tmp_path):
    app,c=boot(tmp_path)
    page=c.get('/api/public/site/agency-01').json(); ver=page['version']
    a=public_envelope('agency-01',ver,'visit','kiosk','',{})
    b=public_envelope('agency-01',ver,'visit','kiosk','',{})
    assert all(x['status']=='accepted' for x in c.post('/api/collect',json={'items':[a,b]}).json()['receipts'])
    login(c,app,'agency01@pulsex.test')
    m=c.get('/api/admin/sites/agency-01/metrics').json()
    assert m['kiosk_sessions']>=2


def test_suspended_participation_revokes_member_site_management_but_not_public_interaction(tmp_path):
    app,c=boot(tmp_path); login(c,app,'admin@pulsex.test')
    user=c.post('/api/admin/organizations/org-01/users',json={'name':'محرر تجريبي','email':'suspend@org.test','role':'editor'}).json()
    org=next(x for x in c.get('/api/admin/organizations').json()['organizations'] if x['id']=='org-01')
    part=org['participations'][0]
    assert c.patch('/api/admin/participations/'+part['id'],json={'status':'suspended'}).status_code==200
    c2=TestClient(app); lr=c2.post('/api/auth/login',json={'email':'suspend@org.test','password':user['temporary_password']}); assert lr.status_code==200
    c2.headers.update({'X-CSRF':lr.json()['csrf'],'Origin':'http://testserver'})
    assert c2.get('/api/admin/sites/agency-01').status_code==428
    assert c2.post('/api/auth/password',json={'current':user['temporary_password'],'password':'SuspendPass123!'}).status_code==200
    lr2=c2.post('/api/auth/login',json={'email':'suspend@org.test','password':'SuspendPass123!'}); assert lr2.status_code==200
    c2.headers.update({'X-CSRF':lr2.json()['csrf'],'Origin':'http://testserver'})
    assert c2.get('/api/admin/sites/agency-01').status_code==403
    page=c2.get('/api/public/site/agency-01').json(); assert page['version']>=1
    # restore not needed because isolated DB


def test_offline_frontend_has_indexeddb_outbox_receipts_online_retry_qr_and_kiosk_contract():
    from pathlib import Path
    offline=Path('web/offline.mjs').read_text(encoding='utf-8')
    public=Path('web/public.mjs').read_text(encoding='utf-8')
    admin=Path('web/admin.mjs').read_text(encoding='utf-8')
    for token in ["indexedDB.open", "'outbox'", "'receipts'", "slice(0,50)", "window.addEventListener('online',sync)", 'deviceHeartbeat', 'navigator.storage?.persist']:
        assert token in offline
    assert "params.get('source')==='qr'?'qr':'web'" in public
    assert "params.get('kiosk')==='1'" in public
    assert "?source=qr" in admin
    assert 'زائر جديد' in public and 'تجهيز دون إنترنت' in public


def test_admin_ui_exposes_people_without_account_and_later_account_creation():
    from pathlib import Path
    admin=Path('web/admin.mjs').read_text(encoding='utf-8')
    for token in ['الفريق / أعضاء بدون حساب','إضافة عضو بدون حساب','إنشاء حساب إدارة لهذا العضو','يمكنه المشاركة كزائر في الاستبيان والتقييم دون حساب']:
        assert token in admin

def test_additive_compat_migration_adds_password_change_flag_to_old_sqlite(tmp_path):
    import sqlite3
    db=tmp_path/'old.sqlite'
    con=sqlite3.connect(db)
    con.execute("CREATE TABLE px_users (id VARCHAR(64) PRIMARY KEY, email VARCHAR(200) UNIQUE NOT NULL, name VARCHAR(200) NOT NULL, role VARCHAR(20) NOT NULL, scope_id VARCHAR(64), password_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1)")
    con.commit();con.close()
    app=create_app('sqlite:///'+str(db),origin='http://testserver',seed_demo=False)
    with sqlite3.connect(db) as con:
        cols={r[1] for r in con.execute('PRAGMA table_info(px_users)').fetchall()}
    assert 'must_change_password' in cols
