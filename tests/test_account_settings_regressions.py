"""Settings/inbox acceptance via real HTTP auth, with optional isolated PostgreSQL.

PX_ACCOUNT_TEST_DATABASE_URL is accepted only with PX_ALLOW_POSTGRES_TEST_RESET=YES.
No live application database is used by default.
"""
from contextlib import ExitStack
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
import threading
import itertools
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, event, func, insert, select, update
from app.server import create_app
from app.db import metadata, users, sessions, assignments, preferences, notifications, audit
from app.core.security import digest
from app.domain import now
from harness_support import app_client

DEFAULTS={'theme':'system','text_size':'normal','reduce_motion':False,'notifications_enabled':True}
ROLES=['platform','organizer','agency','event_manager','reception','scanner','committee_supervisor','analyst','auditor']

@pytest.fixture(scope='module')
def account_system(tmp_path_factory):
    url=os.environ.get('PX_ACCOUNT_TEST_DATABASE_URL')
    if url:
        assert url.startswith('postgresql+') and os.environ.get('PX_ALLOW_POSTGRES_TEST_RESET')=='YES'
        engine=create_engine(url)
        metadata.drop_all(engine)
        engine.dispose()
    else:url='sqlite:///'+str(tmp_path_factory.mktemp('account-regressions')/'accounts.sqlite')
    app=create_app(url,origin='http://testserver',seed_demo=True)
    clients={};identities={}
    with ExitStack() as stack:
        primary=stack.enter_context(app_client(app))
        for role in ROLES:
            if role in ('platform','organizer','agency'):
                credential=next(x for x in app.state.seed_credentials if x['role']==role)
                client=primary if role=='platform' else TestClient(app)
                auth=client.post('/api/auth/login',json={'email':credential['email'],'password':credential['password']})
                assert auth.status_code==200,auth.text
                identity=auth.json()['user'];csrf=auth.json()['csrf']
            else:
                uid='account-qa-'+role;token=uuid.uuid4().hex;csrf=uuid.uuid4().hex
                identity={'id':uid,'email':uid+'@example.test','role':role}
                with app.state.engine.begin() as c:
                    c.execute(insert(users).values(id=uid,email=identity['email'],name=role,role='member',scope_id='event-demo',password_hash='synthetic-no-login',active=1,must_change_password=0))
                    c.execute(insert(assignments).values(id='account-assignment-'+role,user_id=uid,site_id='event-demo',role=role,status='active',created_at=now()))
                    c.execute(insert(sessions).values(token_hash=digest(token),user_id=uid,csrf=csrf,expires_at='2999-01-01T00:00:00+00:00'))
                client=TestClient(app);client.cookies.set('px_session',token)
            if client is not primary:stack.callback(client.close)
            client.headers.update({'Origin':'http://testserver','X-CSRF':csrf})
            clients[role]=client;identities[role]=identity
        anonymous=TestClient(app);stack.callback(anonymous.close)
        yield SimpleNamespace(app=app,clients=clients,identities=identities,anonymous=anonymous,url=url)

@pytest.fixture
def account(account_system):
    x=account_system
    with x.app.state.engine.begin() as c:
        c.execute(delete(notifications));c.execute(delete(preferences))
        c.execute(update(users).values(active=1,must_change_password=0))
    return x

def send(account,**changes):
    payload={'email':account.identities['organizer']['email'],'title':'Synthetic notice','body':'Synthetic body'}
    payload.update(changes)
    return account.clients['platform'].post('/api/admin/notifications',json=payload)

@pytest.mark.parametrize('role',ROLES)
def test_each_authenticated_role_can_save_own_preferences_and_read_only_own_inbox(account,role):
    client=account.clients[role]
    assert client.get('/api/account/preferences').json()==DEFAULTS
    wanted={**DEFAULTS,'theme':'dark'}
    response=client.put('/api/account/preferences',json=wanted)
    assert response.status_code==200 and response.json()==wanted
    assert client.get('/api/account/preferences').json()==wanted
    assert client.get('/api/account/notifications').json()=={'items':[],'channel':'in_app'}
    other=account.clients['agency' if role!='agency' else 'platform']
    assert other.get('/api/account/preferences').json()==DEFAULTS

@pytest.mark.parametrize('theme,size,motion,enabled',list(itertools.product(['system','light','dark'],['normal','large'],[False,True],[False,True])))
def test_all_documented_preference_combinations_roundtrip_without_duplicate_owner_rows(account,theme,size,motion,enabled):
    wanted={'theme':theme,'text_size':size,'reduce_motion':motion,'notifications_enabled':enabled}
    client=account.clients['platform']
    for _ in range(2):assert client.put('/api/account/preferences',json=wanted).json()==wanted
    assert client.get('/api/account/preferences').json()==wanted
    with account.app.state.engine.connect() as c:
        assert c.execute(select(func.count()).select_from(preferences)).scalar_one()==1

INVALID=[{},[],None,{**DEFAULTS,'theme':'sepia'},{**DEFAULTS,'theme':{}},{**DEFAULTS,'theme':None},
         {**DEFAULTS,'text_size':'huge'},{**DEFAULTS,'reduce_motion':1},{**DEFAULTS,'reduce_motion':'false'},
         {**DEFAULTS,'notifications_enabled':0},{**DEFAULTS,'notifications_enabled':'true'},
         {**DEFAULTS,'notifications_enabled':None},{**DEFAULTS,'user_id':'another-account'}]
@pytest.mark.parametrize('payload',INVALID)
def test_invalid_preferences_are_rejected_without_partial_write(account,payload):
    client=account.clients['platform']
    assert client.put('/api/account/preferences',json=DEFAULTS).status_code==200
    response=client.put('/api/account/preferences',json=payload)
    assert response.status_code==422,response.text
    assert client.get('/api/account/preferences').json()==DEFAULTS

@pytest.mark.parametrize('method,path,body',[
    ('GET','/api/account/preferences',None),('PUT','/api/account/preferences',DEFAULTS),
    ('GET','/api/account/notifications',None),('POST','/api/account/notifications/missing/read',{}),
    ('POST','/api/admin/notifications',{'email':'nobody@example.test','title':'x','body':'y'})])
def test_account_endpoints_require_authentication(account,method,path,body):
    assert account.anonymous.request(method,path,json=body).status_code==401

@pytest.mark.parametrize('path,payload',[
    ('/api/account/preferences',DEFAULTS),('/api/account/notifications/missing/read',{}),
    ('/api/admin/notifications',{'email':'nobody@example.test','title':'x','body':'y'})])
@pytest.mark.parametrize('failure',['missing_csrf','wrong_csrf','foreign_origin'])
def test_each_account_mutation_enforces_csrf_and_origin(account,path,payload,failure):
    original=account.clients['platform'];headers=dict(original.headers)
    headers.update({'origin':'http://testserver'})
    if failure=='missing_csrf':headers.pop('x-csrf',None)
    elif failure=='wrong_csrf':headers['x-csrf']='synthetic-invalid'
    else:headers['origin']='https://untrusted.example'
    with TestClient(account.app,headers=headers) as client:
        client.cookies.update(original.cookies)
        response=client.request('PUT' if path.endswith('preferences') else 'POST',path,json=payload)
        assert response.status_code==403,response.text

@pytest.mark.parametrize('role',[r for r in ROLES if r!='platform'])
def test_non_platform_roles_cannot_send_notifications(account,role):
    response=account.clients[role].post('/api/admin/notifications',json={'email':account.identities['platform']['email'],'title':'x','body':'y'})
    assert response.status_code==403
    with account.app.state.engine.connect() as c:assert c.execute(select(func.count()).select_from(notifications)).scalar_one()==0

@pytest.mark.parametrize('field,value',[('title',''),('title','x'*161),('title',{}),('body',''),('body','x'*2001),('body',True),('email',''),('email','missing@example.test'),('title','bad\x00title')])
def test_invalid_notification_is_atomic_and_does_not_record_success(account,field,value):
    with account.app.state.engine.connect() as c:before=c.execute(select(func.count()).select_from(audit).where(audit.c.action=='notification_sent')).scalar_one()
    response=send(account,**{field:value})
    assert response.status_code in (404,422),response.text
    with account.app.state.engine.connect() as c:
        assert c.execute(select(func.count()).select_from(notifications)).scalar_one()==0
        assert c.execute(select(func.count()).select_from(audit).where(audit.c.action=='notification_sent')).scalar_one()==before

def test_delivery_read_receipt_audit_and_disabled_alerts_do_not_break_owner_isolation(account):
    target=account.clients['organizer'];owner=account.identities['organizer']['id']
    target.put('/api/account/preferences',json={**DEFAULTS,'notifications_enabled':False})
    result=send(account,email='  '+account.identities['organizer']['email'].upper()+'  ',title='ع'*160,body='<img src=x onerror=alert(1)>'+'ب'*1950)
    assert result.status_code==200,result.text
    nid=result.json()['id']
    assert result.json()=={'id':nid,'status':'delivered_to_inbox','channel':'in_app'}
    for role in ('platform','agency','scanner'):
        client=account.clients[role]
        assert client.get('/api/account/notifications').json()['items']==[]
        assert client.post('/api/account/notifications/'+nid+'/read',json={}).status_code==404
    item=target.get('/api/account/notifications').json()['items'][0]
    assert set(item)=={'id','title','body','created_at','read_at'} and item['read_at'] is None
    assert item['body'].startswith('<img')
    for _ in range(2):assert target.post('/api/account/notifications/'+nid+'/read',json={}).status_code==200
    assert target.get('/api/account/notifications').json()['items'][0]['read_at']
    with account.app.state.engine.connect() as c:
        entry=c.execute(select(audit).where(audit.c.action=='notification_sent').order_by(audit.c.at.desc())).mappings().first()
        assert entry is not None
        assert entry['user_id']==account.identities['platform']['id']
        assert entry['details']=={'notification_id':nid,'recipient_id':owner}
        assert c.execute(select(notifications.c.user_id).where(notifications.c.id==nid)).scalar_one()==owner

def test_disabled_account_cannot_receive_or_use_existing_session(account):
    uid=account.identities['organizer']['id']
    with account.app.state.engine.begin() as c:c.execute(update(users).where(users.c.id==uid).values(active=0))
    assert send(account).status_code==404
    assert account.clients['organizer'].get('/api/account/notifications').status_code==401
    assert account.clients['organizer'].put('/api/account/preferences',json=DEFAULTS).status_code==401

def test_forced_password_change_blocks_settings_inbox_and_send(account):
    uid=account.identities['platform']['id']
    with account.app.state.engine.begin() as c:c.execute(update(users).where(users.c.id==uid).values(must_change_password=1))
    client=account.clients['platform']
    for method,path,body in [('GET','/api/account/preferences',None),('PUT','/api/account/preferences',DEFAULTS),('GET','/api/account/notifications',None),('POST','/api/admin/notifications',{'title':'x','body':'y','email':'x@example.test'})]:
        assert client.request(method,path,json=body).status_code==428

def test_inbox_is_bounded_newest_first_and_still_excludes_other_owners(account):
    owner=account.identities['organizer']['id'];sender=account.identities['platform']['id']
    with account.app.state.engine.begin() as c:
        c.execute(insert(notifications),[{'id':f'synthetic-{i:03}','user_id':owner,'sender_id':sender,'title':str(i),'body':'safe','created_at':f'2026-10-20T00:{i//60:02}:{i%60:02}+00:00'} for i in range(105)])
    items=account.clients['organizer'].get('/api/account/notifications').json()['items']
    assert len(items)==100 and items[0]['id']=='synthetic-104' and items[-1]['id']=='synthetic-005'
    assert account.clients['agency'].get('/api/account/notifications').json()['items']==[]

def test_preferences_and_read_inbox_survive_new_application_instance(account):
    wanted={**DEFAULTS,'theme':'dark','reduce_motion':True}
    target=account.clients['organizer'];assert target.put('/api/account/preferences',json=wanted).status_code==200
    nid=send(account).json()['id'];target.post('/api/account/notifications/'+nid+'/read',json={})
    app2=create_app(account.url,origin='http://testserver',seed_demo=False)
    with app_client(app2) as fresh:
        fresh.cookies.update(target.cookies)
        assert fresh.get('/api/account/preferences').json()==wanted
        item=fresh.get('/api/account/notifications').json()['items'][0]
        assert item['id']==nid and item['read_at']

def test_concurrent_first_preference_saves_do_not_return_internal_server_error(account):
    """Exercise real SQLite serialization and PostgreSQL's concurrent first insert."""
    barrier=threading.Barrier(2)
    def before_insert(conn,cursor,statement,parameters,context,executemany):
        if statement.lstrip().upper().startswith('INSERT INTO PX_PREFERENCES'):
            barrier.wait(timeout=15)
    engine=account.app.state.engine
    coordinated=engine.dialect.name=='postgresql'
    if coordinated:event.listen(engine,'before_cursor_execute',before_insert)
    def save(theme):
        owner=account.clients['platform']
        with TestClient(account.app,raise_server_exceptions=False,headers=dict(owner.headers)) as client:
            client.cookies.update(owner.cookies)
            return client.put('/api/account/preferences',json={**DEFAULTS,'theme':theme}).status_code
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses=list(pool.map(save,['light','dark']))
    finally:
        if coordinated:event.remove(engine,'before_cursor_execute',before_insert)
    assert statuses==[200,200],f'Concurrent valid first saves must both succeed; received {statuses}'
    assert account.clients['platform'].get('/api/account/preferences').json()['theme'] in ('light','dark')
