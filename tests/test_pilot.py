"""Local SQLite integration/domain tests. These are NOT native PostgreSQL acceptance."""
import base64, copy, csv, io, json, uuid, zipfile
from pathlib import Path
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from app.server import create_app
from app.db import submissions
from app.domain import normalize_record, normalize_config, default_config, answer_value, survey_answers, QTYPES

ROOT=Path(__file__).resolve().parents[1]
@pytest.fixture(scope='module')
def app(tmp_path_factory):
    root=tmp_path_factory.mktemp('db')
    return create_app('sqlite:///'+str(root/'test.sqlite'),origin='http://testserver',seed_demo=True)
@pytest.fixture
def client(app):return TestClient(app,client=('client-'+uuid.uuid4().hex,50000))
def login(c,app,index=0):
    u=app.state.seed_credentials[index];r=c.post('/api/auth/login',json={'email':u['email'],'password':u['password']});assert r.status_code==200
    c.headers['X-CSRF']=r.json()['csrf'];return r.json()
def envelope(sid='agency-01',**kw):
    return {'id':str(uuid.uuid4()),'site_id':sid,'version':1,'kind':'survey','visitor_id':str(uuid.uuid4()),'session_id':str(uuid.uuid4()),'source':'web','target':'main','payload':{'answers':{'q-interest':'o1','q-rate':5}},'client_time':'2026-09-28T12:00:00+03:00',**kw}
def post(c,b):return c.post('/api/collect',json={'items':[b]}).json()['receipts'][0]
def load(c,sid='agency-01'):return c.get('/api/admin/sites/'+sid).json()
def save(c,s):return c.put('/api/admin/sites/'+s['id'],json={'draft_rev':s['draft_rev'],'config':s['draft']})

def test_health_backend_is_explicit(client):
    x=client.get('/api/health').json();assert x['database']=='sqlite' and not x['production_ready']
def test_platform_event_and_ten_agencies(client):
    p=client.get('/api/public/site/platform').json();assert len(p['events'])==1
    e=client.get('/api/public/site/demo').json();assert len(e['agencies'])==10
    a=client.get('/api/public/site/agency-01').json();assert a['event']['id']=='event-demo' and a['config']['welcome']
def test_login_required(client):assert client.get('/api/admin/sites').status_code==401
def test_wrong_password(client):assert client.post('/api/auth/login',json={'email':'no@none.test','password':'wrong'}).status_code==401
def test_hierarchy_visibility(client,app):
    login(client,app,2);assert len(client.get('/api/admin/sites').json()['sites'])==1
    assert client.get('/api/admin/sites/agency-02').status_code==403
    login(client,app,1);assert len(client.get('/api/admin/sites').json()['sites'])==11
    assert client.get('/api/admin/sites/platform').status_code==403
def test_csrf_guard(client,app):
    login(client,app,2);s=load(client);client.headers.pop('X-CSRF');assert save(client,s).status_code==403
def test_cross_origin_block(client,app):
    login(client,app,2);assert client.post('/api/auth/logout',json={},headers={'Origin':'https://evil.example'}).status_code==403
def test_draft_publish_and_version_snapshot(client,app):
    login(client,app,3);s=load(client,'agency-02');old=s['draft']['title'];s['draft']['title']='Draft test';assert save(client,s).status_code==200
    assert client.get('/api/public/site/agency-02').json()['config']['title']==old
    assert save(client,s).status_code==409
    s=load(client,'agency-02');assert client.post('/api/admin/sites/agency-02/publish',json={'draft_rev':s['draft_rev']}).status_code==200
    assert client.get('/api/public/site/agency-02').json()['config']['title']=='Draft test'
    assert post(client,envelope(sid='agency-02'))['status']=='accepted'
def test_preview_no_collection(client,app):
    login(client,app,2);assert client.get('/api/admin/sites/agency-01/preview').json()['preview'] is True
    assert post(client,envelope(preview=True))['error']=='PREVIEW_WRITES_FORBIDDEN'
def test_optional_identity(client):
    assert post(client,envelope())['status']=='accepted'
def test_collection_exact_replay(client):
    b=envelope();assert post(client,b)['status']=='accepted';assert post(client,b)['status']=='duplicate'
    b['payload']['answers']['q-rate']=2;assert post(client,b)['error']=='IDEMPOTENCY_BODY_CONFLICT'
def test_required_question(client):
    assert post(client,envelope(payload={'answers':{'q-rate':2}}))['error'].startswith('ANSWER_REQUIRED')
def test_unknown_question(client):
    assert post(client,envelope(payload={'answers':{'q-interest':'o1','bad':'x'}}))['error']=='UNKNOWN_QUESTION'
def test_invalid_choice(client):assert post(client,envelope(payload={'answers':{'q-interest':'NOT_AN_OPTION'}}))['error']=='ANSWER_OPTION'
def test_profile_requires_consent(client):
    b=envelope(kind='profile',payload={'phone':'0123'},target='');assert post(client,b)['error']=='CONTACT_CONSENT_REQUIRED'
def test_profile_optional_contact_separate(client):
    b=envelope(kind='profile',payload={'phone':'0123','consent':True},target='');assert post(client,b)['status']=='accepted'
def test_vote_uniqueness_per_pseudonym(client):
    b=envelope(kind='poll',target='p-first',payload={'answer':'o1'});assert post(client,b)['status']=='accepted'
    b['id']=str(uuid.uuid4());assert post(client,b)['error']=='ALREADY_VOTED_OR_RECORDED'
def test_closed_poll_rejects_late_offline_vote(client,app):
    login(client,app,4);s=load(client,'agency-03');q=next(r for r in s['draft']['records'] if r['kind']=='poll');q['status']='closed';assert save(client,s).status_code==200
    s=load(client,'agency-03');client.post('/api/admin/sites/agency-03/publish',json={'draft_rev':s['draft_rev']})
    b=envelope(sid='agency-03',kind='poll',target='p-first',payload={'answer':'o1'});assert post(client,b)['error']=='POLL_CLOSED'
def test_feedback_other_exhibitor_in_event(client):
    b=envelope(sid='event-demo',kind='feedback',target='agency-04:general',payload={'rating':4,'note':'constructive'});assert post(client,b)['status']=='accepted'
def test_feedback_unknown_scope(client):
    r=post(client,envelope(kind='feedback',target='missing:general',payload={'rating':3}));assert r['status']=='rejected'
def test_public_results_no_profiles(client):
    txt=client.get('/api/public/site/agency-01/results').text;assert '0123' not in txt and 'phone' not in txt
def test_metrics_distinguish_people_and_sessions(client,app):
    login(client,app,1);x=client.get('/api/admin/sites/event-demo/metrics').json();assert x['verified_people'] is None and 'browser_ids_estimate' in x and 'kiosk_sessions' in x
def test_cross_scope_metrics_and_export(client,app):
    login(client,app,2);assert client.get('/api/admin/sites/agency-02/metrics').status_code==403;assert client.get('/api/admin/sites/agency-02/export').status_code==403
def test_access_request_does_not_grant_login(client):
    r=client.post('/api/access-request',json={'site_id':'agency-01','email':'pending@sample.test','name':'طلب'});assert r.status_code==200 and not r.json()['grants_access']
def test_subordinate_cannot_create_accounts(client,app):
    login(client,app,2);assert client.post('/api/admin/sites/agency-01/users',json={'email':'bad@sample.test','name':'x','role':'platform'}).status_code==403
def test_organizer_creates_limited_account(client,app):
    login(client,app,1);r=client.post('/api/admin/sites/agency-05/users',json={'email':'new@sample.test','name':'مستخدم','role':'platform'});assert r.status_code==200 and r.json()['role']=='agency'
def test_organizer_cannot_create_platform_event(client,app):
    login(client,app,1);assert client.post('/api/admin/sites',json={'parent_id':'platform','kind':'event','slug':'forbidden','title':'bad'}).status_code==403
def test_create_new_agency_is_draft(client,app):
    login(client,app,1);r=client.post('/api/admin/sites',json={'parent_id':'event-demo','kind':'agency','slug':'agency-new-test','title':'جهة جديدة'});assert r.status_code==200
    assert client.get('/api/public/site/agency-new-test').status_code==404
def test_csv_preview_commit_not_publish(client,app):
    login(client,app,5);sid='agency-04';before=load(client,sid);csv='code,title,body\nCSV-S1,خدمة CSV,تفاصيل\n'
    p=client.post(f'/api/admin/sites/{sid}/imports/preview',json={'kind':'service','csv':csv}).json();assert p['valid'];assert len(load(client,sid)['draft']['records'])==len(before['draft']['records'])
    r=client.post(f"/api/admin/sites/{sid}/imports/{p['id']}/commit",json={});assert r.json()['status']=='committed'
    assert client.post(f"/api/admin/sites/{sid}/imports/{p['id']}/commit",json={}).json()['status']=='already_committed'
    assert all(r['code']!='CSV-S1' for r in client.get('/api/public/site/'+sid).json()['config']['records'])
def test_duplicate_csv_rejected(client,app):
    login(client,app,2);r=client.post('/api/admin/sites/agency-01/imports/preview',json={'kind':'service','csv':'code,title\nservice-1,duplicate\n'}).json();assert not r['valid']
def test_import_stale_preview_blocked(client,app):
    login(client,app,2);p=client.post('/api/admin/sites/agency-01/imports/preview',json={'kind':'service','csv':'code,title\nNEW-CODE,service\n'}).json();s=load(client);s['draft']['subtitle']='changed';assert save(client,s).status_code==200
    assert client.post(f"/api/admin/sites/agency-01/imports/{p['id']}/commit",json={}).status_code==409
def test_xlsx_template_is_valid(client,app):
    login(client,app,6);data=(ROOT/'templates/PulseX_Windows04_Import.xlsx').read_bytes()
    p=client.post('/api/admin/sites/agency-05/imports/preview',json={'name':'input.xlsx','base64':base64.b64encode(data).decode()});assert p.status_code==200,p.text
    assert p.json()['valid'],p.json()['errors'];assert len(p.json()['records'])>=15
    qs=[r for r in p.json()['records'] if r['kind']=='question'];assert len(qs[0]['options'])==3

def test_formula_xlsx_rejected(client,app):
    login(client,app,2);original=(ROOT/'templates/PulseX_Windows04_Import.xlsx').read_bytes();out=io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original)) as zin,zipfile.ZipFile(out,'w') as zout:
        for item in zin.infolist():
            data=zin.read(item.filename)
            if item.filename=='xl/worksheets/sheet2.xml':data=data.replace(b'</x:c>',b'<x:f>1+1</x:f></x:c>',1)
            zout.writestr(item.filename,data)
    r=client.post('/api/admin/sites/agency-01/imports/preview',json={'name':'bad.xlsx','base64':base64.b64encode(out.getvalue()).decode()});assert r.status_code==422 and 'FORMULA' in r.text
@pytest.mark.parametrize('sheet,kind',[(k,v) for k,v in [('Participants','participant'),('Sponsors','sponsor'),('Sessions','session'),('Places','place'),('Facts','fact'),('Services','service'),('Questions','question'),('Polls','poll'),('Ads','ad'),('Offers','offer'),('Media','media'),('Contacts','contact'),('News','news')]])
def test_each_csv_template_valid(client,app,sheet,kind):
    login(client,app,7);data=(ROOT/'templates'/f'{sheet}.csv').read_text(encoding='utf-8')
    p=client.post('/api/admin/sites/agency-06/imports/preview',json={'kind':kind,'csv':data});assert p.status_code==200,p.text;assert p.json()['valid'],p.text
@pytest.mark.parametrize('kind',['service','fact','ad','participant','sponsor','place','offer','media','news','contact'])
def test_manual_record_normalization(kind):
    assert normalize_record({'kind':kind,'code':'X1','title':'عنوان'})['kind']==kind
@pytest.mark.parametrize('qtype',list(QTYPES))
def test_question_type_supported(qtype):
    q={'kind':'question','code':'Q','title':'سؤال','qtype':qtype,'required':True}
    if qtype in ('single_choice','multiple_choice','dropdown','image_choice','ranking','allocation','quiz'):q['options']=['A','B']
    if qtype=='quiz':q['correct']='o1'
    if qtype=='matrix':q['rows']=['السرعة','الوضوح']
    n=normalize_record(q);assert n['qtype']==qtype

def test_safe_branch_logic():
    c=default_config('Branches');c['records']=[{'kind':'question','code':'Q1','title':'سؤال','options':['A','B'],'qtype':'single_choice','required':True,'order':1},{'kind':'question','code':'Q2','title':'مشروط','qtype':'short_text','required':True,'order':2,'show_if':{'code':'Q1','equals':'o2'}}];c=normalize_config(c)
    assert survey_answers(c,'main',{'Q1':'o1'})=={'Q1':'o1'}
    with pytest.raises(HTTPException):survey_answers(c,'main',{'Q1':'o2'})
def test_branch_cycle_rejected():
    c=default_config('Branches');c['records']=[{'kind':'question','code':'Q1','title':'سؤال','qtype':'short_text','show_if':{'code':'Q1','equals':'x'}}]
    with pytest.raises(HTTPException):normalize_config(c)
def test_script_url_rejected():
    with pytest.raises(HTTPException):normalize_record({'kind':'ad','code':'X','title':'x','url':'javascript:alert(1)'})
def test_media_svg_upload_rejected(client,app):
    login(client,app,2);r=client.post('/api/admin/media',json={'base64':base64.b64encode(b'<svg><script>alert(1)</script></svg>').decode()});assert r.status_code==422
def test_qr_created(client,app):
    login(client,app,2);r=client.get('/api/admin/sites/agency-01/qr');assert r.status_code==200 and r.content.startswith(b'\x89PNG')
def test_password_change_revokes_session(client,app):
    who=app.state.seed_credentials[-1];login(client,app,len(app.state.seed_credentials)-1)
    r=client.post('/api/auth/password',json={'current':who['password'],'password':'A-new-random-password-2026'});assert r.status_code==200
    assert client.get('/api/auth/me').status_code==401
