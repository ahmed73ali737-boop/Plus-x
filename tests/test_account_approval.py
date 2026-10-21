"""End-to-end account gate: real HTTP, independent actors, transaction rollback.

The same cases execute on a disposable PostgreSQL schema when the phase-1
native database URL is set. Existing fixture identities are pre-approved.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import ast
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, insert, update, func

from test_account_requests_model import store
from app.server import create_app
from app.db import users, sessions, memberships, assignments, organization_people, event_participations, sites, audit
from app.account_requests_db import account_requests as ar, request_workflows as wf
from app.core.security import hash_password, verify_password
from app.application import account_requests as service

PASSWORD='Approved-Password-2026!'
LEGACY='Legacy-Password-2026!'


@pytest.fixture
def env(store):
    engine,url=store
    with engine.begin() as c:
        for uid,role,scope in [('organizer','organizer','event-one'),('outsider','organizer','event-two'),('owner','agency',None),('scanner','member','event-one')]:
            c.execute(insert(users).values(id=uid,email=uid+'@example.test',name=uid,role=role,scope_id=scope,password_hash=hash_password(LEGACY),active=1,must_change_password=0))
        c.execute(insert(memberships).values(user_id='owner',organization_id='org-one',role='owner',status='active',created_at=service.now()))
        c.execute(insert(event_participations).values(id='part-one',event_id='event-one',organization_id='org-one',participation_type='exhibitor',status='active',services=[],created_at=service.now()))
        c.execute(insert(assignments).values(id='scanner-assignment',user_id='scanner',site_id='event-one',role='scanner',status='active',created_at=service.now()))
    app=create_app(url,origin='http://testserver',seed_demo=False)
    with TestClient(app,raise_server_exceptions=False) as anonymous:
        clients=[]
        def login(uid):
            client=TestClient(app,raise_server_exceptions=False)
            email={'existing':'Existing@Example.test'}.get(uid,uid+'@example.test')
            response=client.post('/api/auth/login',json={'email':email.lower(),'password':LEGACY})
            # Existing mixed-case addresses are legacy data; authenticating that
            # fixture uses its exact address until the separate login path normalizes it.
            if response.status_code!=200:response=client.post('/api/auth/login',json={'email':email,'password':LEGACY})
            assert response.status_code==200,response.text
            client.headers['X-CSRF']=response.json()['csrf'];clients.append(client);return client
        yield app,engine,anonymous,login
        for client in clients:client.close()
    app.state.engine.dispose()


def submit_public(client,**extra):
    return client.post('/api/auth/register',json={'name':'Applicant','phone':'+967777880001','password':PASSWORD,'confirmation':PASSWORD,**extra})


def decide(login,request,**extra):
    reviewer=login(request['supervisor_id'])
    return reviewer.patch('/api/admin/account-requests/'+request['id'],json={'status':'approved',**extra})


def test_personal_request_has_no_user_session_or_access_before_approval(env):
    app,engine,client,login=env
    response=submit_public(client,role='platform',active=True,scope_id='platform')
    assert response.status_code==200,response.text
    request=response.json();assert request['scope_name']
    assert request['status']=='pending' and not request['grants_access']
    assert 'csrf' not in request and 'password_hash' not in request and not client.cookies.get('px_session')
    assert client.post('/api/auth/login',json={'phone':'+967777880001','password':PASSWORD}).status_code==401
    with engine.connect() as c:
        assert not c.execute(select(users.c.id).where(users.c.email=='tel:+967777880001')).first()
        assert verify_password(PASSWORD,c.scalar(select(ar.c.password_hash).where(ar.c.id==request['id'])))
    assert decide(login,request).status_code==200
    assert client.post('/api/auth/login',json={'phone':'+967777880001','password':PASSWORD}).status_code==200
    assert client.get('/api/auth/me').json()['user']['role']=='attendee'
    assert client.get('/api/admin/sites').status_code==403
    with engine.connect() as c:assert c.scalar(select(ar.c.password_hash).where(ar.c.id==request['id'])) is None


@pytest.mark.parametrize('path,body',[
    ('/api/admin/sites/event-one/users',{'name':'New organizer','email':'organizer-new@example.test'}),
    ('/api/admin/organizations/org-one/users',{'name':'Employee','email':'employee@example.test','role':'editor'}),
    ('/api/admin/organizations/org-one/people/person-one/account',{'email':'person@example.test'}),
    ('/api/admin/events/event-one/committee',{'name':'Crew','email':'crew@example.test','role':'scanner','create_account':True}),
])
def test_every_admin_creation_path_waits_for_independent_approval_and_setup(env,path,body):
    app,engine,client,login=env
    creator=login('supervisor')
    with engine.connect() as c:before={t.name:c.scalar(select(func.count()).select_from(t)) for t in (users,memberships,assignments)}
    response=creator.post(path,json=body);assert response.status_code==200,response.text
    request=response.json();assert request['status']=='pending' and 'temporary_password' not in request
    with engine.connect() as c:
        assert {t.name:c.scalar(select(func.count()).select_from(t)) for t in (users,memberships,assignments)}==before
        assert c.scalar(select(organization_people.c.user_id)) is None
    assert creator.patch('/api/admin/account-requests/'+request['id'],json={'status':'approved'}).status_code in (403,404)
    approved=decide(login,request);assert approved.status_code==200,approved.text
    assert approved.json()['setup_required']
    if '/sites/' in path:
        row=next(u for u in creator.get(path).json()['users'] if u['id']==approved.json()['user_id'])
        assert row['setup_required'] and not row['active']
    token=request['tracking_token']
    assert client.post('/api/account-requests/password',json={'tracking_token':token,'password':PASSWORD,'confirmation':PASSWORD}).status_code==200
    assert client.post('/api/account-requests/password',json={'tracking_token':token,'password':PASSWORD,'confirmation':PASSWORD}).status_code==409
    logged=client.post('/api/auth/login',json={'email':body['email'],'password':PASSWORD});assert logged.status_code==200,logged.text
    again=decide(login,request);assert again.status_code==200 and again.json()['already_reviewed']
    with engine.connect() as c:
        assert c.scalar(select(func.count()).select_from(users).where(users.c.email==body['email']))==1
        if '/people/' in path:assert c.scalar(select(organization_people.c.user_id))==approved.json()['user_id']
        if '/committee' in path:
            user=c.execute(select(users).where(users.c.id==approved.json()['user_id'])).mappings().one()
            assert user['role']=='member'
            assert c.scalar(select(func.count()).select_from(assignments).where(assignments.c.user_id==user['id'],assignments.c.role=='scanner'))==1


@pytest.mark.parametrize('role,site',[('organizer','platform'),('participant','event-one')])
def test_signup_approval_atomically_creates_organization_site_and_account(env,role,site):
    app,engine,client,login=env
    response=client.post('/api/signup-request',json={'site_id':site,'requested_role':role,'organization_name':'Applied organization','contact_name':'Applicant','email':'signup@example.test','password':PASSWORD,'confirmation':PASSWORD})
    assert response.status_code==200,response.text
    request=response.json()
    assert request['organization_name']=='Applied organization' and request['scope_name']
    with engine.connect() as c:assert not c.execute(select(users.c.id).where(users.c.email=='signup@example.test')).first()
    result=decide(login,request);assert result.status_code==200,result.text
    result=result.json();assert result['result_site_id'] and result['result_organization_id']
    assert client.post('/api/auth/login',json={'email':'signup@example.test','password':PASSWORD}).status_code==200
    assert client.get('/api/admin/sites').status_code==200
    with engine.connect() as c:assert c.scalar(select(func.count()).select_from(memberships).where(memberships.c.organization_id==result['result_organization_id']))==1


def test_existing_account_link_preserves_password_role_and_prior_scope(env):
    app,engine,client,login=env
    creator=login('supervisor')
    response=creator.post('/api/admin/events/event-one/committee',json={'user_id':'outsider','role':'analyst'})
    assert response.status_code==200,response.text
    request=response.json()
    with engine.connect() as c:before=dict(c.execute(select(users).where(users.c.id=='outsider')).mappings().one())
    assert decide(login,request).status_code==200
    with engine.connect() as c:
        assert dict(c.execute(select(users).where(users.c.id=='outsider')).mappings().one())==before
        assert c.scalar(select(func.count()).select_from(assignments).where(assignments.c.user_id=='outsider',assignments.c.site_id=='event-one'))==1


def test_scope_isolation_self_review_and_secret_free_audit(env):
    app,engine,client,login=env
    request=login('organizer').post('/api/admin/organizations/org-one/users',json={'name':'New Owner','email':'new-owner@example.test','role':'owner'}).json()
    outsider=login('outsider');assert outsider.get('/api/admin/account-requests').json()['requests']==[]
    assert outsider.patch('/api/admin/account-requests/'+request['id'],json={'status':'approved'}).status_code==404
    assert login('scanner').get('/api/admin/account-requests').json()['requests']==[]
    # Changing a designation in the database simulates a self-designated old row:
    # the service must recheck maker/checker independently of the UI.
    with engine.begin() as c:c.execute(update(ar).where(ar.c.id==request['id']).values(supervisor_id='organizer'))
    denied=login('organizer').patch('/api/admin/account-requests/'+request['id'],json={'status':'approved'})
    assert denied.status_code==403
    with engine.connect() as c:
        encoded=json.dumps([dict(r) for r in c.execute(select(audit)).mappings()])
        assert 'account_request_review_denied' in encoded
        assert PASSWORD not in encoded and 'password_hash' not in encoded


@pytest.mark.parametrize('action',['rejected','cancelled','expired'])
def test_rejected_cancelled_expired_cannot_login_and_clear_secret(env,action):
    app,engine,client,login=env
    request=submit_public(client).json();token=request['tracking_token']
    if action=='rejected':
        reviewer=login(request['supervisor_id'])
        assert reviewer.patch('/api/admin/account-requests/'+request['id'],json={'status':'rejected'}).status_code==422
        result=reviewer.patch('/api/admin/account-requests/'+request['id'],json={'status':'rejected','reason':'يرجى مراجعة الجهة المختصة.'})
        assert result.status_code==200
    elif action=='cancelled':assert client.post('/api/account-requests/cancel',json={'tracking_token':token}).status_code==200
    else:
        with engine.begin() as c:c.execute(update(ar).where(ar.c.id==request['id']).values(expires_at=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),created_at='2000-01-01T00:00:00+00:00'))
    result=client.post('/api/account-requests/status',json={'tracking_token':token}).json();assert result['status']==action
    assert client.post('/api/auth/login',json={'phone':'+967777880001','password':PASSWORD}).status_code==401
    with engine.connect() as c:assert c.scalar(select(ar.c.password_hash).where(ar.c.id==request['id'])) is None


def test_approval_failure_rolls_back_user_links_and_status(env,monkeypatch):
    app,engine,client,login=env
    request=submit_public(client).json()
    with engine.connect() as c:before=c.scalar(select(func.count()).select_from(users))
    def broken(*args,**kwargs):raise RuntimeError('synthetic link failure')
    monkeypatch.setattr(service,'approve_links',broken)
    assert decide(login,request).status_code==500
    with engine.connect() as c:
        assert c.scalar(select(func.count()).select_from(users))==before
        row=c.execute(select(ar).where(ar.c.id==request['id'])).mappings().one()
        assert row['status']=='pending' and row['password_hash']
        assert c.scalar(select(func.count()).select_from(audit).where(audit.c.action=='account_request_approved'))==0


def test_request_retry_is_idempotent_without_persisting_capability(env):
    app,engine,client,login=env
    key='a1'*32
    first=submit_public(client,request_key=key).json()
    second=submit_public(client,request_key=key).json()
    assert first['id']==second['id'] and second['already_pending']
    with engine.connect() as c:
        assert c.scalar(select(func.count()).select_from(ar))==1
        assert c.scalar(select(ar.c.request_key))!=key
        assert c.scalar(select(wf.c.tracking_hash))!=key
    assert client.post('/api/account-requests/status',json={'tracking_token':'b2'*32}).status_code==404


def test_concurrent_approvals_create_exactly_one_account(env):
    app,engine,client,login=env
    request=submit_public(client).json()
    def approve(_):
        with engine.begin() as c:
            actor=c.execute(select(users).where(users.c.id==request['supervisor_id'])).mappings().one()
            return service.review(c,actor,request['id'],'approved')['status']
    with ThreadPoolExecutor(max_workers=2) as pool:assert list(pool.map(approve,range(2)))==['approved','approved']
    with engine.connect() as c:assert c.scalar(select(func.count()).select_from(users).where(users.c.email=='tel:+967777880001'))==1


def test_creation_route_inventory_has_one_authority():
    root=Path(__file__).resolve().parents[1]
    offenders=[]
    for file in (root/'app').rglob('*.py'):
        tree=ast.parse(file.read_text())
        for node in ast.walk(tree):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='insert' and node.args and isinstance(node.args[0],ast.Name) and node.args[0].id in ('users','memberships','assignments'):
                if file.relative_to(root).as_posix() not in ('app/application/account_requests.py','app/infrastructure/seed.py'):offenders.append(str(file))
    assert not offenders


def test_platform_admin_request_requires_distinct_designated_platform_reviewer(env):
    app,engine,client,login=env
    creator=login('supervisor')
    response=creator.post('/api/admin/platform-account-requests',json={'name':'Platform candidate','email':'platform-candidate@example.test','role':'agency'})
    assert response.status_code==200,response.text
    pending=response.json();assert pending['requested_role']=='platform' and pending['supervisor_id']!='supervisor'
    assert creator.patch('/api/admin/account-requests/'+pending['id'],json={'status':'approved'}).status_code==404
    result=decide(login,pending);assert result.status_code==200,result.text
    with engine.connect() as c:
        record=c.execute(select(users).where(users.c.id==result.json()['user_id'])).mappings().one()
        assert record['role']=='platform' and not record['active']


def test_display_only_signup_approval_never_creates_account_or_membership(env):
    app,engine,client,login=env
    with engine.connect() as c:before=[c.scalar(select(func.count()).select_from(t)) for t in (users,memberships,assignments)]
    response=client.post('/api/signup-request',json={'site_id':'event-one','requested_role':'participant','organization_name':'Display only','contact_name':'Representative','email':'display@example.test','wants_account':False})
    assert response.status_code==200,response.text
    result=decide(login,response.json());assert result.status_code==200,result.text
    assert not result.json()['account_requested'] and result.json()['user_id'] is None
    with engine.connect() as c:assert [c.scalar(select(func.count()).select_from(t)) for t in (users,memberships,assignments)]==before


def test_expired_setup_is_denied_then_explicitly_renewed_and_consumed_once(env):
    app,engine,client,login=env
    response=login('supervisor').post('/api/admin/organizations/org-one/users',json={'name':'Employee','email':'setup@example.test','role':'editor'})
    pending=response.json();approved=decide(login,pending);assert approved.status_code==200,approved.text
    with engine.begin() as c:c.execute(update(wf).where(wf.c.request_id==pending['id']).values(setup_expires_at='2000-01-01T00:00:00+00:00'))
    body={'tracking_token':pending['tracking_token'],'password':PASSWORD,'confirmation':PASSWORD}
    assert client.post('/api/account-requests/password',json=body).status_code==409
    assert login('outsider').post('/api/admin/account-requests/'+pending['id']+'/setup-link',json={}).status_code==404
    assert login(pending['supervisor_id']).post('/api/admin/account-requests/'+pending['id']+'/setup-link',json={}).status_code==200
    assert client.post('/api/account-requests/password',json=body).status_code==200
    assert client.post('/api/account-requests/password',json=body).status_code==409


def test_suspension_invalidates_unconsumed_password_setup_capability(env):
    app,engine,client,login=env
    pending=login('supervisor').post('/api/admin/organizations/org-one/users',json={'name':'Employee','email':'suspended-setup@example.test'}).json()
    approved=decide(login,pending).json()
    assert login('supervisor').patch('/api/admin/users/'+approved['user_id'],json={'active':False}).status_code==200
    assert client.post('/api/account-requests/password',json={'tracking_token':pending['tracking_token'],'password':PASSWORD,'confirmation':PASSWORD}).status_code==409
    assert login(pending['supervisor_id']).post('/api/admin/account-requests/'+pending['id']+'/setup-link',json={}).status_code==409


def test_reviewer_membership_revocation_removes_visibility_and_review_authority(env):
    app,engine,client,login=env
    pending=login('supervisor').post('/api/admin/organizations/org-one/users',json={'name':'Employee','email':'scope-recheck@example.test','role':'editor'}).json()
    assert pending['supervisor_id']=='owner'
    owner=login('owner')
    with engine.begin() as c:c.execute(update(memberships).where(memberships.c.user_id=='owner').values(status='suspended'))
    assert not owner.get('/api/admin/account-requests').json()['requests']
    assert owner.patch('/api/admin/account-requests/'+pending['id'],json={'status':'approved'}).status_code==404
    with engine.connect() as c:assert c.scalar(select(ar.c.status).where(ar.c.id==pending['id']))=='pending'


def test_signup_entity_creation_rolls_back_on_account_link_failure(env,monkeypatch):
    app,engine,client,login=env
    pending=client.post('/api/signup-request',json={'site_id':'event-one','requested_role':'participant','organization_name':'Rollback org','contact_name':'Owner','email':'rollback-org@example.test'}).json()
    with engine.connect() as c:before=[c.scalar(select(func.count()).select_from(t)) for t in (users,sites,memberships,event_participations)]
    def broken(*args,**kwargs):raise RuntimeError('synthetic membership failure')
    monkeypatch.setattr(service,'approve_links',broken)
    assert decide(login,pending).status_code==500
    with engine.connect() as c:
        assert [c.scalar(select(func.count()).select_from(t)) for t in (users,sites,memberships,event_participations)]==before
        assert c.scalar(select(ar.c.status).where(ar.c.id==pending['id']))=='pending'


def test_two_scopes_concurrently_approve_one_identity_without_changing_credential(env):
    app,engine,client,login=env
    requests=[]
    for site in ('event-one','event-two'):
        response=client.post('/api/access-request',json={'site_id':site,'name':'One identity','email':'cross-scope@example.test','password':PASSWORD,'confirmation':PASSWORD})
        assert response.status_code==200,response.text
        requests.append(response.json())
    with engine.begin() as c:c.execute(update(ar).where(ar.c.id==requests[1]['id']).values(supervisor_id='supervisor'))
    requests[1]['supervisor_id']='supervisor'
    def run(pending):
        with engine.begin() as c:
            actor=c.execute(select(users).where(users.c.id==pending['supervisor_id'])).mappings().one()
            return service.review(c,actor,pending['id'],'approved')
    with ThreadPoolExecutor(max_workers=2) as pool:result=list(pool.map(run,requests))
    assert result[0]['user_id']==result[1]['user_id']
    with engine.connect() as c:
        records=c.execute(select(users).where(users.c.email=='cross-scope@example.test')).mappings().all()
        assert len(records)==1 and verify_password(PASSWORD,records[0]['password_hash'])


def test_pausing_submission_never_restores_direct_user_creation(env,monkeypatch):
    app,engine,client,login=env
    monkeypatch.setenv('ACCOUNT_REQUESTS_ACCEPTING','false')
    with engine.connect() as c:before=c.scalar(select(func.count()).select_from(users))
    assert submit_public(client).status_code==503
    with engine.connect() as c:assert c.scalar(select(func.count()).select_from(users))==before


def test_additive_runtime_upgrade_creates_workflow_and_pending_phone_index(store):
    from app.db import ensure_compat_schema
    from test_account_requests_model import add, ROOT
    from tools.migrate_postgres import execute_script
    from sqlalchemy import inspect
    engine,_=store
    with engine.begin() as c:
        wf.drop(c)
        c.exec_driver_sql('DROP INDEX px_ar_pending_phone')
        pending=add(c)
    if engine.dialect.name=='sqlite':ensure_compat_schema(engine)
    else:
        with engine.begin() as c:execute_script(c,(ROOT/'ops/014_account_request_workflows.sql').read_text())
    assert 'px_account_request_workflows' in inspect(engine).get_table_names()
    assert 'px_ar_pending_phone' in {i['name'] for i in inspect(engine).get_indexes('px_account_requests')}
    with engine.connect() as c:
        row=c.execute(select(ar).where(ar.c.id==pending['id'])).mappings().one()
        assert row['status']=='pending' and row['password_hash']


def test_platform_invitation_is_not_an_account_and_candidate_must_apply_then_be_reviewed(env):
    app,engine,client,login=env
    admin=login('supervisor')
    with engine.connect() as c:before=c.scalar(select(func.count()).select_from(users))
    invite=admin.post('/api/admin/platform-account-invites',json={'name':'Invited platform candidate','email':'invited-admin@example.test'}).json()
    assert invite['status']=='invited' and not invite['grants_access']
    with engine.connect() as c:
        assert c.scalar(select(func.count()).select_from(users))==before
        assert c.scalar(select(func.count()).select_from(ar))==0
    response=client.post('/api/account-invites/accept',json={'invitation_token':invite['invitation_token'],'password':PASSWORD,'confirmation':PASSWORD,'email':'override@example.test','role':'organizer'})
    assert response.status_code==200,response.text
    pending=response.json();assert pending['requested_role']=='platform' and pending['email']=='invited-admin@example.test'
    with engine.connect() as c:assert c.scalar(select(func.count()).select_from(users))==before
    assert client.post('/api/auth/login',json={'email':'invited-admin@example.test','password':PASSWORD}).status_code==401
    assert decide(login,pending).status_code==200
    assert client.post('/api/auth/login',json={'email':'invited-admin@example.test','password':PASSWORD}).json()['user']['role']=='platform'
    again=client.post('/api/account-invites/accept',json={'invitation_token':invite['invitation_token'],'password':'Different-Password-2026!','confirmation':'Different-Password-2026!'})
    assert again.status_code==200 and again.json()['already_pending']
    with engine.connect() as c:
        user=c.execute(select(users).where(users.c.email=='invited-admin@example.test')).mappings().one()
        assert verify_password(PASSWORD,user['password_hash'])
        assert not c.execute(select(assignments.c.id).where(assignments.c.user_id==user['id'])).first()


def test_expired_platform_invitation_and_nonplatform_issuer_are_denied(env):
    from app.account_requests_db import platform_account_invites
    app,engine,client,login=env
    assert login('organizer').post('/api/admin/platform-account-invites',json={'name':'Denied','email':'denied@example.test'}).status_code==403
    invite=login('supervisor').post('/api/admin/platform-account-invites',json={'name':'Expired','email':'expired-invite@example.test'}).json()
    with engine.begin() as c:c.execute(update(platform_account_invites).values(expires_at='2000-01-01T00:00:00+00:00'))
    assert client.post('/api/account-invites/accept',json={'invitation_token':invite['invitation_token'],'password':PASSWORD,'confirmation':PASSWORD}).status_code==409
    with engine.connect() as c:assert c.scalar(select(func.count()).select_from(ar))==0


def test_status_polling_does_not_consume_signup_submission_budget(env):
    app,engine,client,login=env
    pending=submit_public(client).json()
    for _ in range(12):assert client.post('/api/account-requests/status',json={'tracking_token':pending['tracking_token']}).status_code==200
    signup={'site_id':'event-one','requested_role':'participant','organization_name':'New organization','contact_name':'Owner','email':'rate-status@example.test','request_key':'a9'*32}
    for _ in range(10):assert client.post('/api/signup-request',json=signup).status_code==200
    assert client.post('/api/signup-request',json=signup).status_code==429
