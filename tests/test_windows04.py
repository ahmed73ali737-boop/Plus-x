import uuid
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.server import create_app
from app.domain import normalize_config, normalize_record, answer_value

@pytest.fixture
def env(tmp_path):
    app=create_app('sqlite:///'+str(tmp_path/'v04.sqlite'),origin='http://testserver',seed_demo=True)
    return app,TestClient(app)

def login(c,app,index=0):
    u=app.state.seed_credentials[index]
    r=c.post('/api/auth/login',json={'email':u['email'],'password':u['password']})
    assert r.status_code==200
    c.headers['X-CSRF']=r.json()['csrf']
    return r.json()['user']

def test_health_v04(env):
    _,c=env
    x=c.get('/api/health').json(); assert x['build']=='windows-08'

def test_seed_permanent_organizations_and_participations(env):
    app,c=env; login(c,app,0)
    data=c.get('/api/admin/organizations').json()['organizations']
    assert len(data)==11
    exhib=[x for x in data if x['id']=='org-01'][0]
    assert exhib['participations'][0]['agency_site_id']=='agency-01'

def test_organizer_can_create_permanent_org_and_event_participation(env):
    app,c=env; login(c,app,1)
    r=c.post('/api/admin/organizations',json={'name':'جهة جديدة','slug':'new-org','booth':'B-12','description':'جهة دائمة'})
    assert r.status_code==200
    orgs=c.get('/api/admin/organizations').json()['organizations']
    created=[x for x in orgs if x['slug']=='new-org'][0]
    assert len(created['participations'])==1 and created['participations'][0]['booth']=='B-12'

def test_membership_grants_same_user_access_in_second_event(env):
    app,c=env; login(c,app,0)
    r=c.post('/api/admin/sites',json={'kind':'event','parent_id':'platform','title':'فعالية ثانية','slug':'second-event'})
    assert r.status_code==200; event_id=r.json()['id']
    p=c.post(f'/api/admin/events/{event_id}/participations',json={'organization_id':'org-01','participation_type':'exhibitor','booth':'C-01'})
    assert p.status_code==200; second_agency=p.json()['agency_site_id']
    # new client as the original organization account
    c2=TestClient(app); login(c2,app,2)
    sites=c2.get('/api/admin/sites').json()['sites']
    assert {'agency-01',second_agency}.issubset({x['id'] for x in sites})

def test_platform_access_request_is_public_signup_request(env):
    _,c=env
    r=c.post('/api/access-request',json={'site_id':'platform','name':'مؤسسة ترغب بالاشتراك','email':'join@example.test'})
    assert r.status_code==200 and r.json()['status']=='pending_approval' and not r.json()['grants_access']

def test_theme_and_section_templates_normalize():
    raw={'title':'Test','template':'technology','primary':'#112233','secondary':'#223344','accent':'#334455','background':'#F1F2F3','surface':'#FFFFFF','text_color':'#111111','card_style':'bordered','hero_style':'cover','radius':28,
         'rating_criteria':[{'key':'innovation','label':'الابتكار','weight':60},{'key':'service','label':'الخدمة','weight':40}],
         'sections':[{'key':'services','title':'حلولنا','enabled':True,'order':1,'layout':'featured','preview_count':5}], 'records':[]}
    c=normalize_config(raw)
    assert c['template']=='technology' and c['card_style']=='bordered' and c['radius']==28
    assert c['sections'][0]['layout']=='featured' and c['sections'][0]['preview_count']==5
    assert sum(x['weight'] for x in c['rating_criteria'])==100

@pytest.mark.parametrize('typ,value,extra',[('date','2026-09-29',{}),('email','A@Example.com',{}),('phone','+967 777 123 456',{}),('url','https://example.com',{}),('consent',True,{})])
def test_new_question_types_simple(typ,value,extra):
    q=normalize_record({'kind':'question','code':'q1','title':'س','qtype':typ,'required':True,**extra})
    assert answer_value(q,value) is not None

def test_allocation_question_sums_to_100():
    q=normalize_record({'kind':'question','code':'alloc','title':'وزع النقاط','qtype':'allocation','required':True,'options':['أ','ب']})
    assert answer_value(q,{'o1':70,'o2':30})=={'o1':70,'o2':30}
    with pytest.raises(Exception):answer_value(q,{'o1':70,'o2':20})

def test_quiz_requires_and_accepts_correct_option():
    q=normalize_record({'kind':'question','code':'quiz','title':'اختبار','qtype':'quiz','required':True,'options':['أ','ب'],'correct':'o1','score':5})
    assert q['correct']=='o1' and q['score']==5 and answer_value(q,'o1')=='o1'

def test_secret_poll_forces_results_hidden():
    q=normalize_record({'kind':'poll','code':'p1','title':'سري','qtype':'single_choice','options':['أ','ب'],'poll_style':'secret','show_results':True})
    assert q['poll_style']=='secret' and q['show_results'] is False

def test_rating_criteria_and_note_are_stored_and_aggregated(env):
    app,c=env; login(c,app,2)
    site=c.get('/api/admin/sites/agency-01').json()
    site['draft']['rating_criteria']=[{'key':'overall','label':'العام','weight':40},{'key':'innovation','label':'الابتكار','weight':60}]
    s=c.put('/api/admin/sites/agency-01',json={'draft_rev':site['draft_rev'],'config':site['draft']}); assert s.status_code==200
    rev=s.json()['draft_rev']; pub=c.post('/api/admin/sites/agency-01/publish',json={'draft_rev':rev}); assert pub.status_code==200
    ver=pub.json()['published_version']
    item={'id':str(uuid.uuid4()),'site_id':'agency-01','version':ver,'kind':'feedback','visitor_id':str(uuid.uuid4()),'session_id':str(uuid.uuid4()),'source':'web','target':'agency-01:general','payload':{'rating':4,'criteria':{'overall':4,'innovation':5},'note':'ملاحظة مفيدة'},'client_time':'2026-09-29T12:00:00+03:00'}
    r=c.post('/api/collect',json={'items':[item]}); assert r.json()['receipts'][0]['status']=='accepted'
    m=c.get('/api/admin/sites/agency-01/metrics').json()
    assert m['ratings']['agency-01:general']['average']==4
    assert m['rating_criteria']['agency-01:general']['innovation']['average']==5
    assert m['feedback_notes'][0]['note']=='ملاحظة مفيدة'

def test_audit_log_visible_for_scope(env):
    app,c=env; login(c,app,2)
    x=c.get('/api/admin/audit?site_id=agency-01').json()['entries']
    assert any(e['action']=='login' for e in x)

def test_public_platform_catalog_marks_event_status(env):
    _,c=env
    x=c.get('/api/public/site/platform').json()
    assert x['events'][0]['status'] in ('upcoming','current','completed')

def test_public_event_agencies_expose_participation_metadata(env):
    _,c=env
    e=c.get('/api/public/site/demo').json(); a=e['agencies'][0]
    assert a['participation']['booth'] and a['rating_criteria']


def test_platform_can_add_permanent_user_to_org(env):
    app,c=env; login(c,app,0)
    r=c.post('/api/admin/organizations/org-01/users',json={'name':'عضو جديد','email':'member@example.test','role':'analyst'})
    assert r.status_code==200 and r.json()['permanent_membership'] is True and r.json()['temporary_password']
    c2=TestClient(app)
    l=c2.post('/api/auth/login',json={'email':'member@example.test','password':r.json()['temporary_password']})
    assert l.status_code==200 and l.json()['user']['must_change_password'] is True
    csrf=l.json()['csrf']; c2.headers.update({'X-CSRF':csrf,'Origin':'http://testserver'})
    assert c2.get('/api/admin/sites').status_code==428
    changed=c2.post('/api/auth/password',json={'current':r.json()['temporary_password'],'password':'NewSecurePass123!'})
    assert changed.status_code==200
    l2=c2.post('/api/auth/login',json={'email':'member@example.test','password':'NewSecurePass123!'})
    assert l2.status_code==200 and l2.json()['user']['must_change_password'] is False
    c2.headers.update({'X-CSRF':l2.json()['csrf'],'Origin':'http://testserver'})
    sites=c2.get('/api/admin/sites').json()['sites']
    assert any(x['id']=='agency-01' for x in sites)

def test_public_ui_contains_signup_and_section_layout_support():
    public=Path('web/public.mjs').read_text()
    css=Path('web/design.css').read_text()
    assert 'طلب اشتراك / حساب' in public and 'ما تم إنجازه' in public and 'القادمة' in public
    assert 'previewLimit' in public and 'layout-featured' in css and 'layout-list' in css

def test_admin_ui_exposes_templates_audit_orgs_quiz_score_and_notes():
    admin=Path('web/admin.mjs').read_text()
    for token in ['الهوية والقالب','المؤسسات والمشاركات','السجل والتدقيق','الإجابة الصحيحة للاختبار','أحدث الملاحظات المكتوبة','إضافة مستخدم']:
        assert token in admin

def test_membership_and_participation_lifecycle_controls(env):
    app,c=env; login(c,app,0)
    created=c.post('/api/admin/organizations/org-01/users',json={'name':'محرر','email':'editor@example.test','role':'editor'}).json()
    members=c.get('/api/admin/organizations/org-01/members').json()['members']
    member=next(x for x in members if x['email']=='editor@example.test')
    r=c.patch(f"/api/admin/organizations/org-01/members/{member['user_id']}",json={'status':'suspended','role':'analyst'})
    assert r.status_code==200 and r.json()['status']=='suspended'
    orgs=c.get('/api/admin/organizations').json()['organizations']; part=next(x for x in orgs if x['id']=='org-01')['participations'][0]
    r=c.patch('/api/admin/participations/'+part['id'],json={'status':'suspended','booth':'TEMP-1'})
    assert r.status_code==200 and r.json()['status']=='suspended'
    # Restore to avoid surprising later tests if fixture ever changes scope.
    assert c.patch('/api/admin/participations/'+part['id'],json={'status':'active','booth':'A-01'}).status_code==200
