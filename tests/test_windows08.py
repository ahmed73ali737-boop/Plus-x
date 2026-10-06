from app.domain import normalize_record, normalize_config, answer_value, default_config
from fastapi import HTTPException


def test_time_question_is_native_type_and_validated():
    q=normalize_record({'kind':'question','code':'visit-time','title':'وقت الزيارة','qtype':'time','form_id':'main','required':True})
    assert q['qtype']=='time'
    assert answer_value(q,'14:35')=='14:35'
    try:
        answer_value(q,'29:99')
        assert False
    except HTTPException as e:
        assert e.detail=='TIME_INVALID'


def test_datetime_question_type():
    q=normalize_record({'kind':'question','code':'meeting-at','title':'موعد اللقاء','qtype':'datetime','form_id':'main','required':True})
    assert answer_value(q,'2026-09-30T14:35')=='2026-09-30T14:35'


def test_survey_metadata_is_normalized_and_legacy_forms_are_discovered():
    cfg=default_config('Demo')
    cfg['surveys']=[{'id':'main','title':'رأي الزوار','description':'قصير','completion':'شكرًا'}]
    cfg['records']=[
        {'kind':'question','code':'q1','title':'س1','qtype':'short_text','form_id':'main'},
        {'kind':'question','code':'q2','title':'س2','qtype':'short_text','form_id':'legacy-form'},
    ]
    out=normalize_config(cfg)
    surveys={s['id']:s for s in out['surveys']}
    assert surveys['main']['title']=='رأي الزوار'
    assert 'legacy-form' in surveys


def test_default_config_has_readable_survey():
    c=default_config('Demo')
    assert c['surveys'][0]['id']=='main'
    assert c['surveys'][0]['title']

import uuid
from fastapi.testclient import TestClient
from app.server import create_app
from app.core.build_info import BUILD_LABEL


def test_windows08_version_and_ui_contract(tmp_path):
    app=create_app('sqlite:///'+str(tmp_path/'w08.sqlite'),origin='http://testserver',seed_demo=True)
    c=TestClient(app)
    assert c.get('/api/health').json()['build']==BUILD_LABEL  # build label kept for backward compatibility in this candidate
    assert app.openapi()['info']['version']=='0.9.0'
    admin=(__import__('pathlib').Path(__file__).resolve().parents[1]/'web/admin.mjs').read_text(encoding='utf-8')
    public=(__import__('pathlib').Path(__file__).resolve().parents[1]/'web/public.mjs').read_text(encoding='utf-8')
    questions=(__import__('pathlib').Path(__file__).resolve().parents[1]/'web/questions.mjs').read_text(encoding='utf-8')
    assert 'استبيان جديد' in admin and 'question-type-config' in admin
    assert "'datetime-local'" in admin and "time:'time'" in questions
    assert 'star-picker' in public and 'طلبات التواصل' in admin


def test_contact_request_is_actionable_in_admin_metrics(tmp_path):
    app=create_app('sqlite:///'+str(tmp_path/'contact.sqlite'),origin='http://testserver',seed_demo=True)
    c=TestClient(app)
    public=c.get('/api/public/site/agency-01').json()
    env={'id':str(uuid.uuid4()),'site_id':'agency-01','version':public['version'],'kind':'follow','visitor_id':str(uuid.uuid4()),'session_id':str(uuid.uuid4()),'source':'web','target':'','payload':{'name':'زائر','phone':'+967777000000','email':'visitor@example.com','job':'مدير','message':'أريد معرفة المزيد','preferred_channel':'whatsapp','consent':True,'marketing':False},'client_time':'2026-09-30T10:00:00+03:00'}
    receipt=c.post('/api/collect',json={'items':[env]}).json()['receipts'][0]
    assert receipt['status']=='accepted'
    user=app.state.seed_credentials[1]
    login=c.post('/api/auth/login',json={'email':user['email'],'password':user['password']})
    c.headers['X-CSRF']=login.json()['csrf']
    metrics=c.get('/api/admin/sites/agency-01/metrics').json()
    req=metrics['follow_requests'][0]
    assert req['email']=='visitor@example.com' and req['preferred_channel']=='whatsapp'


def test_time_question_end_to_end_api(tmp_path):
    app=create_app('sqlite:///'+str(tmp_path/'time-e2e.sqlite'),origin='http://testserver',seed_demo=True)
    c=TestClient(app)
    u=app.state.seed_credentials[2]
    login=c.post('/api/auth/login',json={'email':u['email'],'password':u['password']}); c.headers['X-CSRF']=login.json()['csrf']
    site=c.get('/api/admin/sites/agency-01').json()
    site['draft']['records'].append({'kind':'question','code':'visit-time','title':'ما الوقت الأنسب لزيارتك؟','qtype':'time','form_id':'main','required':True,'order':99,'enabled':True})
    saved=c.put('/api/admin/sites/agency-01',json={'draft_rev':site['draft_rev'],'config':site['draft']})
    assert saved.status_code==200,saved.text
    pub=c.post('/api/admin/sites/agency-01/publish',json={'draft_rev':saved.json()['draft_rev']}); assert pub.status_code==200
    page=c.get('/api/public/site/agency-01').json(); version=page['version']
    env={'id':str(uuid.uuid4()),'site_id':'agency-01','version':version,'kind':'survey','visitor_id':str(uuid.uuid4()),'session_id':str(uuid.uuid4()),'source':'web','target':'main','payload':{'answers':{'q-interest':'o1','q-rate':5,'visit-time':'16:30'}},'client_time':'2026-09-30T10:00:00+03:00'}
    receipt=c.post('/api/collect',json={'items':[env]}).json()['receipts'][0]
    assert receipt['status']=='accepted'


def test_rating_note_end_to_end_api(tmp_path):
    app=create_app('sqlite:///'+str(tmp_path/'rating-e2e.sqlite'),origin='http://testserver',seed_demo=True)
    c=TestClient(app)
    page=c.get('/api/public/site/agency-01').json()
    env={'id':str(uuid.uuid4()),'site_id':'agency-01','version':page['version'],'kind':'feedback','visitor_id':str(uuid.uuid4()),'session_id':str(uuid.uuid4()),'source':'web','target':'agency-01:general','payload':{'rating':5,'criteria':{'overall':5},'note':'تجربة واضحة ومفيدة'},'client_time':'2026-09-30T10:00:00+03:00'}
    assert c.post('/api/collect',json={'items':[env]}).json()['receipts'][0]['status']=='accepted'
