"""Explicit setup helpers for tests of already-approved users.

These helpers use real review and password endpoints. They never alter HTTP
responses or auto-approve requests in a transport/middleware fixture.
"""
from fastapi.testclient import TestClient
from sqlalchemy import insert, select
from app.core.security import hash_password
from app.db import users

REVIEWER={'email':'approval-review-admin@tests.example','password':'Independent-Reviewer-2026!'}
PASSWORD='Setup-Account-Password-2026!'


def prepare_review_admin(app):
    with app.state.engine.begin() as c:
        if not c.execute(select(users.c.id).where(users.c.email==REVIEWER['email'])).first():
            c.execute(insert(users).values(id='approval-review-admin',email=REVIEWER['email'],name='Independent test reviewer',role='platform',scope_id='platform',password_hash=hash_password(REVIEWER['password']),active=1,must_change_password=0))


def approve_request(app, pending, *, reset=False, password=PASSWORD):
    assert pending['status']=='pending' and 'temporary_password' not in pending
    with app.state.engine.connect() as c:
        email=c.scalar(select(users.c.email).where(users.c.id==pending['supervisor_id']))
    account=REVIEWER if email==REVIEWER['email'] else next(x for x in app.state.seed_credentials if x['email'].lower()==email.lower())
    staff=TestClient(app)
    try:
        auth=staff.post('/api/auth/login',json=account);assert auth.status_code==200,auth.text
        staff.headers['X-CSRF']=auth.json()['csrf']
        approved=staff.patch('/api/admin/account-requests/'+pending['id'],json={'status':'approved'})
        assert approved.status_code==200,approved.text
        result=approved.json()
        if result['setup_required']:
            setup=staff.post('/api/account-requests/password',json={'tracking_token':pending['tracking_token'],'password':password,'confirmation':password})
            assert setup.status_code==200,setup.text
        if reset:
            reset_result=staff.post('/api/admin/users/'+result['user_id']+'/password/reset',json={})
            # A scoped owner can approve editor memberships but cannot reset login
            # passwords. Use the pre-approved platform authority for that test step.
            if reset_result.status_code==403:
                credentials=next(x for x in app.state.seed_credentials if x['role']=='platform')
                auth=staff.post('/api/auth/login',json=credentials);staff.headers['X-CSRF']=auth.json()['csrf']
                reset_result=staff.post('/api/admin/users/'+result['user_id']+'/password/reset',json={})
            assert reset_result.status_code==200,reset_result.text
            result['temporary_password']=reset_result.json()['temporary_password']
        return result
    finally:staff.close()


def register_approved(app, client, *, phone, password, **extra):
    response=client.post('/api/auth/register',json={'name':'Phone applicant','phone':phone,'password':password,'confirmation':password,**extra})
    assert response.status_code==200,response.text
    assert not response.json()['grants_access']
    assert client.get('/api/auth/me').status_code==401
    approve_request(app,response.json(),password=password)
    auth=client.post('/api/auth/login',json={'phone':phone,'password':password});assert auth.status_code==200,auth.text
    client.headers['X-CSRF']=auth.json()['csrf']
    return auth.json()
