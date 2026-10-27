"""Real application HTTP contracts for each admission screen and role.

Synthetic users/sessions only; no route installer or authorization mock is used.
"""
from datetime import datetime, timedelta, timezone
import json
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, select, update, func
from app.server import create_app
from app.db import users, sessions, assignments, sites, guest_checkins
from app.core.security import digest
from app.domain import now, default_config
from app.invitations_db import invitations, guest_lists, entitlements, admission_uses

ALL={'guests.read','guests.register','guests.export','guests.checkin','invitations.manage','invitations.review','policy.manage','committee.manage'}
GRANTS={
    'event_manager':ALL,'platform':ALL,'organizer':ALL,
    'reception':{'guests.read','guests.register','guests.checkin'},
    'scanner':{'guests.read','guests.checkin'},
    'committee_supervisor':{'guests.read','guests.register','guests.checkin','invitations.manage','invitations.review'},
    'analyst':{'guests.read'},'auditor':{'guests.read'},'agency':set(),'anonymous':set(),
}
ROLES=list(GRANTS)
BASE='/api/admin/events/event-demo'
READS=[
    ('guest_directory','/guests','guests.read'),('movement_history','/guest-checkins','guests.read'),
    ('export','/guests/export','guests.export'),('policy','/admission-policy','invitations.manage'),
    ('lists','/guest-lists','invitations.manage'),('invitations','/invitations','invitations.manage'),
    ('committee','/committee','committee.manage'),('reception','/on-site-registration','guests.register'),
    ('permissions','/permissions','guests.read'),
]
ACTIONS=[('invite','invitations.manage'),('list','invitations.manage'),('policy','policy.manage'),
         ('onsite','guests.register'),('review','invitations.review'),('checkin','guests.checkin'),('committee','committee.manage')]


@pytest.fixture(scope='module')
def system(tmp_path_factory):
    tmp=tmp_path_factory.mktemp('functional-roles')
    app=create_app('sqlite:///'+str(tmp/'roles.sqlite'),origin='http://testserver',seed_demo=True)
    clients={}
    with TestClient(app) as admin:
        for role,email in [('platform','admin@pulsex.test'),('organizer','organizer@pulsex.test'),('agency','org01@pulsex.test')]:
            credential=next((x for x in app.state.seed_credentials if x['email']==email),None)
            if credential is None and role=='agency':credential=next(x for x in app.state.seed_credentials if x['role']=='agency')
            client=admin if role=='platform' else TestClient(app)
            auth=client.post('/api/auth/login',json={'email':credential['email'],'password':credential['password']})
            assert auth.status_code==200,auth.text
            client.headers.update({'Origin':'http://testserver','X-CSRF':auth.json()['csrf']})
            clients[role]=client
        clients['anonymous']=TestClient(app)
        with app.state.engine.begin() as conn:
            conn.execute(insert(sites).values(id='functional-other',slug='functional-other',kind='event',event_id='functional-other',draft=default_config('Other synthetic event','event'),draft_rev=1,published_version=0))
            conn.execute(insert(users).values(id='functional-subject',email='functional-subject@example.test',name='Synthetic assignment target',role='member',scope_id='event-demo',password_hash='unused',active=1,must_change_password=0))
            for role in ['event_manager','reception','scanner','committee_supervisor','analyst','auditor']:
                uid='functional-'+role;token='functional-session-'+role
                conn.execute(insert(users).values(id=uid,email=uid+'@example.test',name=uid,role='member',scope_id='event-demo',password_hash='not-a-login-password',active=1,must_change_password=0))
                conn.execute(insert(assignments).values(id='shift-'+role,user_id=uid,site_id='event-demo',role=role,status='active',created_at=now()))
                conn.execute(insert(sessions).values(token_hash=digest(token),user_id=uid,csrf='csrf-'+role,expires_at='2999-01-01T00:00:00+00:00'))
                client=TestClient(app,headers={'Origin':'http://testserver','X-CSRF':'csrf-'+role});client.cookies.set('px_session',token);clients[role]=client
        response=admin.put(BASE+'/admission-policy',json={'enabled':True,'visibility':'private','registration_mode':'manual','max_companions':2})
        assert response.status_code==200,response.text
        yield app,clients
        for client in clients.values():
            if client is not admin:client.close()


def counts(app):
    with app.state.engine.connect() as conn:
        return tuple(conn.execute(select(func.count()).select_from(table)).scalar_one() for table in (invitations,guest_lists,guest_checkins,admission_uses,assignments))


def new_invitation(clients,*,approve=False):
    phone='+96777'+str(uuid.uuid4().int)[:7]
    result=clients['platform'].post(BASE+'/invitations',json={'name':'Synthetic functional guest','phone':phone})
    assert result.status_code==200,result.text
    item=result.json()
    response=clients['anonymous'].post('/api/public/invitations/'+item['token']+'/rsvp',json={'response':'accepted','consent':True})
    assert response.status_code==200,response.text
    item['revision']=response.json()['invitation']['revision']
    if approve:
        r=clients['platform'].post(BASE+'/invitations/'+item['invitation']['id']+'/review',json={'decision':'approve','revision':item['revision']})
        assert r.status_code==200,r.text
        item['number']=clients['anonymous'].get('/api/public/invitations/'+item['token']).json()['guest_number']
    return item


@pytest.mark.parametrize('role',ROLES)
@pytest.mark.parametrize('screen,suffix,permission',READS,ids=[r[0] for r in READS])
def test_each_admission_screen_enforces_its_read_capability(system,role,screen,suffix,permission):
    app,clients=system
    before=counts(app);response=clients[role].get(BASE+suffix)
    expected=200 if permission in GRANTS[role] else 401 if role=='anonymous' else 403
    assert response.status_code==expected,(role,screen,response.text)
    assert counts(app)==before
    if expected==200 and suffix=='/guests' and 'guests.export' not in GRANTS[role]:
        assert all('phone' not in row and 'phone_hash' not in row and 'pass_token_hash' not in row for row in response.json()['guests'])


@pytest.mark.parametrize('role',ROLES)
@pytest.mark.parametrize('action,permission',ACTIONS,ids=[r[0] for r in ACTIONS])
def test_screen_commands_commit_only_with_exact_permission(system,role,action,permission):
    app,clients=system;actor=clients[role];unique=uuid.uuid4().hex[:10]
    prepared=new_invitation(clients,approve=action=='checkin') if action in ('review','checkin') else None
    route=BASE;method='POST'
    if action=='invite':route+='/invitations';body={'name':'Synthetic '+unique,'phone':'+96777'+str(uuid.uuid4().int)[:7]}
    elif action=='list':route+='/guest-lists';body={'name':'Synthetic list '+unique}
    elif action=='policy':route+='/admission-policy';method='PUT';body={'visibility':'private'}
    elif action=='onsite':route+='/on-site-registration';body={'name':'Synthetic onsite '+unique,'phone':'+96777'+str(uuid.uuid4().int)[:7],'consent':True}
    elif action=='review':route+='/invitations/'+prepared['invitation']['id']+'/review';body={'decision':'approve','revision':prepared['revision']}
    elif action=='checkin':route+='/guest-checkins';body={'guest_number':prepared['number'],'scan_id':str(uuid.uuid4()),'quantity':1,'mode':'entry'}
    else:route+='/committee';body={'user_id':'functional-subject','role':'scanner'}
    before=counts(app);response=actor.request(method,route,json=body)
    expected=200 if permission in GRANTS[role] else 401 if role=='anonymous' else 403
    assert response.status_code==expected,(role,action,response.text)
    if expected!=200:
        assert counts(app)==before
    elif action in ('invite','list','onsite'):
        assert counts(app)[0 if action!='list' else 1]==before[0 if action!='list' else 1]+1
        if action=='onsite':assert response.json()['invitation']['status']=='pending_approval' and 'guest_number' not in response.json()
    elif action=='review':
        assert response.json()['invitation']['status']=='approved'
        assert clients['anonymous'].get('/api/public/invitations/'+prepared['token']).json()['guest_number']
    elif action=='checkin':
        assert response.json()['status']=='accepted'
        assert counts(app)[2]==before[2]+1 and counts(app)[3]==before[3]+1
    elif action=='committee':
        with app.state.engine.connect() as conn:assert conn.execute(select(users.c.role).where(users.c.id=='functional-subject')).scalar_one()=='member'
    else:assert response.json()['policy']['visibility']=='private'


@pytest.mark.parametrize('role',ROLES)
def test_role_cannot_read_another_events_invitation_screen(system,role):
    _,clients=system
    response=clients[role].get('/api/admin/events/functional-other/invitations')
    assert response.status_code==(200 if role=='platform' else 401 if role=='anonymous' else 403),response.text


@pytest.mark.parametrize('role',['analyst','auditor','scanner','reception','committee_supervisor'])
def test_read_only_and_limited_roles_cannot_publish_or_edit(system,role):
    _,clients=system
    site=clients['platform'].get('/api/admin/sites/event-demo').json()
    response=clients[role].put('/api/admin/sites/event-demo',json={'draft_rev':site['draft_rev'],'config':site['draft']})
    assert response.status_code==403
    assert clients[role].post('/api/admin/sites/event-demo/publish',json={'draft_rev':site['draft_rev']}).status_code==403


def test_event_participation_directory_returns_linked_agencies_and_denies_agency(system):
    _,clients=system
    r=clients['organizer'].get(BASE+'/participations')
    assert r.status_code==200,r.text
    assert len(r.json()['participations'])==10
    assert all(row['organization_id'] and row['agency_site_id'] for row in r.json()['participations'])
    assert clients['agency'].get(BASE+'/participations').status_code==403


def test_organization_person_edit_persists_fields_and_status(system):
    _,clients=system;admin=clients['platform']
    created=admin.post('/api/admin/organizations/org-01/people',json={'name':'Synthetic editable person','email':'editable@example.test'})
    assert created.status_code==200,created.text
    pid=created.json()['id']
    r=admin.patch('/api/admin/organizations/org-01/people/'+pid,json={'name':'Edited synthetic person','job_title':'Coordinator','public_visible':True,'status':'inactive'})
    assert r.status_code==200,r.text
    row=next(x for x in admin.get('/api/admin/organizations/org-01/people').json()['people'] if x['id']==pid)
    assert row['name']=='Edited synthetic person' and row['job_title']=='Coordinator'
    assert row['status']=='inactive' and row['public_visible']==1


def test_person_edit_invalid_email_does_not_partially_change_name(system):
    _,clients=system;admin=clients['platform']
    row=admin.post('/api/admin/organizations/org-01/people',json={'name':'Unchanged synthetic person'}).json()
    r=admin.patch('/api/admin/organizations/org-01/people/'+row['id'],json={'name':'Must roll back','email':'invalid'})
    assert r.status_code==422 and r.json()['detail']=='EMAIL_INVALID'
    saved=next(x for x in admin.get('/api/admin/organizations/org-01/people').json()['people'] if x['id']==row['id'])
    assert saved['name']=='Unchanged synthetic person'


def test_person_edit_cannot_move_across_organizations(system):
    _,clients=system;admin=clients['platform']
    row=admin.post('/api/admin/organizations/org-01/people',json={'name':'Scoped synthetic person'}).json()
    r=admin.patch('/api/admin/organizations/org-02/people/'+row['id'],json={'name':'Wrong scope'})
    assert r.status_code==404 and r.json()['detail']=='PERSON_NOT_FOUND'


def test_rotation_http_invalidates_both_invite_token_and_event_pass(system):
    _,clients=system;item=new_invitation(clients,approve=True)
    r=clients['platform'].post(BASE+'/invitations/'+item['invitation']['id']+'/rotate',json={})
    assert r.status_code==200,r.text
    token=r.json()['token'];assert token!=item['token']
    assert clients['anonymous'].get('/api/public/invitations/'+item['token']).status_code==404
    assert clients['anonymous'].get('/api/public/events/demo/guests/'+item['number']+'/qr').status_code==404
    fresh=clients['anonymous'].get('/api/public/invitations/'+token).json()
    assert fresh['guest_number']!=item['number'] and fresh['invitation']['status']=='approved'


def test_guest_config_private_denial_and_managed_public_contract(system):
    _,clients=system;admin=clients['platform'];public=clients['anonymous']
    assert public.get('/api/public/events/demo/guest-config').status_code==404
    assert admin.put(BASE+'/admission-policy',json={'visibility':'unlisted'}).status_code==200
    try:
        r=public.get('/api/public/events/demo/guest-config');assert r.status_code==200,r.text
        assert r.json()['admission_managed'] is True and r.json()['guest_number_strategy']=='event_random_120'
        assert r.json()['registration_url']=='/e/demo/register'
        denied=public.post('/api/public/events/demo/guests/register',json={'name':'No bypass','phone':'777887990','consent':True})
        assert denied.status_code==409 and denied.json()['detail']=='ADMISSION_REGISTRATION_REQUIRED'
    finally:
        assert admin.put(BASE+'/admission-policy',json={'visibility':'private'}).status_code==200


@pytest.mark.parametrize('suffix',['','/live','/ready'],ids=['summary','liveness','readiness'])
def test_public_health_routes_report_local_database_truthfully(system,suffix):
    _,clients=system;r=clients['anonymous'].get('/api/health'+suffix)
    assert r.status_code==200,r.text
    if suffix=='':assert r.json()['database']=='sqlite' and r.json()['production_ready'] is False
    elif suffix=='/live':assert r.json()['status']=='ok'
    else:assert r.json()['status']=='ready' and r.json()['schema_tables_current'] is True


@pytest.mark.parametrize(('payload','detail'),[
    ({'visibility':'hidden'},'VISIBILITY_INVALID'),
    ({'registration_mode':'automatic'},'REGISTRATION_MODE_INVALID'),
    ({'entry_mode':'weekly'},'ENTRY_MODE_INVALID'),
    ({'timezone':'Mars/Olympus'},'TIMEZONE_INVALID'),
    ({'max_companions':-1},'MAX_COMPANIONS_INVALID'),
    ({'max_companions':51},'MAX_COMPANIONS_INVALID'),
    ({'max_companions':True},'MAX_COMPANIONS_INVALID'),
    ({'days':[{'date':'2026-02-30','capacity':1}]},'DAY_INVALID'),
    ({'days':[{'date':'2026-10-20','capacity':-1}]},'CAPACITY_INVALID'),
    ({'days':[{'date':'2026-10-20','capacity':1},{'date':'2026-10-20','capacity':2}]},'DAY_INVALID_OR_DUPLICATE'),
    ({'registration_opens_at':'2026-10-20T10:00:00','registration_closes_at':'2026-10-21T10:00:00Z'},'TIMEZONE_OFFSET_REQUIRED'),
    ({'registration_opens_at':'2026-10-21T10:00:00Z','registration_closes_at':'2026-10-20T10:00:00Z'},'REGISTRATION_WINDOW_INVALID'),
],ids=['visibility','registration-mode','entry-mode','timezone','companions-low','companions-high','bool-is-not-int','invalid-calendar-day','negative-capacity','duplicate-day','timezone-offset-required','reversed-window'])
def test_admission_policy_input_boundaries_are_rejected_atomically(system,payload,detail):
    app,clients=system;admin=clients['platform']
    before=admin.get(BASE+'/admission-policy').json()['policy']
    response=admin.put(BASE+'/admission-policy',json=payload)
    assert response.status_code==422 and response.json()['detail']==detail,(response.status_code,response.text)
    after=admin.get(BASE+'/admission-policy').json()['policy']
    assert after==before


@pytest.mark.parametrize('role',['reception','scanner','committee_supervisor','analyst','auditor','agency','anonymous'])
def test_malformed_policy_cannot_leak_validation_or_mutate_for_unprivileged_roles(system,role):
    app,clients=system;before=counts(app)
    response=clients[role].put(BASE+'/admission-policy',json={'visibility':'not-a-real-mode','max_companions':999})
    assert response.status_code==(401 if role=='anonymous' else 403),(role,response.status_code,response.text)
    assert counts(app)==before
    assert clients['platform'].get(BASE+'/admission-policy').json()['policy']['visibility']=='private'


def test_successful_business_actions_create_distinct_audit_entries(system):
    _,clients=system;admin=clients['platform'];token=clients['anonymous']
    unique=uuid.uuid4().hex[:10]
    before={row['id'] for row in admin.get('/api/admin/audit',params={'site_id':'event-demo','limit':500}).json()['entries']}
    listed=admin.post(BASE+'/guest-lists',json={'name':'Audit '+unique})
    assert listed.status_code==200,listed.text
    invited=admin.post(BASE+'/invitations',json={'name':'Audit guest '+unique,'phone':'+96777'+str(uuid.uuid4().int)[:7],'list_id':listed.json()['id']})
    assert invited.status_code==200,invited.text
    accepted=token.post('/api/public/invitations/'+invited.json()['token']+'/rsvp',json={'response':'accepted','consent':True})
    assert accepted.status_code==200,accepted.text
    reviewed=admin.post(BASE+'/invitations/'+invited.json()['invitation']['id']+'/review',json={'decision':'approve','revision':accepted.json()['invitation']['revision']})
    assert reviewed.status_code==200,reviewed.text
    after=admin.get('/api/admin/audit',params={'site_id':'event-demo','limit':500}).json()['entries']
    added=[row for row in after if row['id'] not in before]
    actions=[row['action'] for row in added]
    assert actions.count('guest_list_created')==1
    assert actions.count('invitation_created')==1
    assert actions.count('invitation_rsvp')==1
    assert actions.count('invitation_reviewed')==1
    ids=[row['id'] for row in added]
    assert len(ids)==len(set(ids))
    assert all(row['site_id']=='event-demo' for row in added)


def test_audit_filter_scope_and_limit_are_enforced(system):
    _,clients=system;platform=clients['platform'];organizer=clients['organizer']
    other=platform.get('/api/admin/audit',params={'site_id':'functional-other','limit':9999})
    assert other.status_code==200 and len(other.json()['entries'])<=500
    assert organizer.get('/api/admin/audit',params={'site_id':'functional-other'}).status_code==403
    scoped=organizer.get('/api/admin/audit',params={'site_id':'event-demo','limit':-10})
    assert scoped.status_code==200
    assert len(scoped.json()['entries'])<=1
    assert all(row['site_id']=='event-demo' for row in scoped.json()['entries'])


def test_authentication_and_scope_denials_have_separate_secret_free_audit_records(system):
    _,clients=system;platform=clients['platform'];anonymous=clients['anonymous'];agency=clients['agency']
    before={row['id'] for row in platform.get('/api/admin/audit',params={'limit':500}).json()['entries']}
    failed=anonymous.post('/api/auth/login',json={'email':'unknown-audit@example.invalid','password':'NeverStoreThisPassword-42'})
    assert failed.status_code==401
    denied=agency.get(BASE+'/invitations')
    assert denied.status_code==403
    after=platform.get('/api/admin/audit',params={'limit':500}).json()['entries']
    added=[row for row in after if row['id'] not in before]
    serialized=json.dumps(added,ensure_ascii=False)
    assert 'NeverStoreThisPassword-42' not in serialized
    assert 'unknown-audit@example.invalid' not in serialized
    missing=[]
    if not any(row['action']=='login_failed' for row in added):missing.append('login_failed for invalid credentials')
    if not any(row['action']=='scope_denied' and row['site_id']=='event-demo' for row in added):missing.append('scope_denied for cross-event access')
    assert not missing,'missing secret-free failure audit records: '+', '.join(missing)


def test_stale_admission_policy_revision_conflict_does_not_write_another_audit_event(system):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    _,clients=system;admin=clients['platform'];policy=admin.get(BASE+'/admission-policy').json()['policy'];rev=policy['rev']
    barrier=Barrier(2)
    def save(visibility):
        barrier.wait(timeout=5)
        return admin.put(BASE+'/admission-policy',json={'rev':rev,'visibility':visibility})
    before=len(admin.get('/api/admin/audit',params={'site_id':'event-demo','limit':500}).json()['entries'])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(save,['private','unlisted']))
    assert sorted(r.status_code for r in results)==[200,409],[r.text for r in results]
    after=len(admin.get('/api/admin/audit',params={'site_id':'event-demo','limit':500}).json()['entries'])
    assert after==before+1
