from account_approval_support import prepare_review_admin, approve_request
from fastapi.testclient import TestClient
from app.server import create_app
from app.db import signup_requests, organizations, event_participations
from sqlalchemy import select


def test_templates_accept_rts_and_easy(tmp_path):
    app=create_app('sqlite:///'+str(tmp_path/'x.sqlite'),origin='http://testserver',seed_demo=True)
    c=TestClient(app)
    creds=app.state.seed_credentials
    admin=next(x for x in creds if x['email']=='admin@pulsex.test')
    r=c.post('/api/auth/login',json={'email':admin['email'],'password':admin['password']}); csrf=r.json()['csrf']; h={'X-CSRF':csrf,'Origin':'http://testserver'}
    sites=c.get('/api/admin/sites').json()['sites']; agency=next(x for x in sites if x['kind']=='agency')
    d=c.get('/api/admin/sites/'+agency['id']).json(); cfg=d['draft']; cfg['template']='rts_tech'
    assert c.put('/api/admin/sites/'+agency['id'],json={'draft_rev':d['draft_rev'],'config':cfg},headers=h).status_code==200
    d=c.get('/api/admin/sites/'+agency['id']).json(); cfg=d['draft']; cfg['template']='easy_finance'
    assert c.put('/api/admin/sites/'+agency['id'],json={'draft_rev':d['draft_rev'],'config':cfg},headers=h).status_code==200


def test_public_participant_signup_approval_creates_org_participation_account(tmp_path):
    app=create_app('sqlite:///'+str(tmp_path/'x.sqlite'),origin='http://testserver',seed_demo=True)
    c=TestClient(app); creds=app.state.seed_credentials
    admin=next(x for x in creds if x['email']=='admin@pulsex.test')
    login=c.post('/api/auth/login',json={'email':admin['email'],'password':admin['password']}); csrf=login.json()['csrf']; h={'X-CSRF':csrf,'Origin':'http://testserver'}
    sites=c.get('/api/admin/sites').json()['sites']; event=next(x for x in sites if x['kind']=='event')
    req=c.post('/api/signup-request',json={'site_id':event['id'],'requested_role':'participant','organization_name':'New Pay Co','contact_name':'Owner','email':'owner@newpay.test','phone':'+967700000000','participation_type':'exhibitor','wants_account':True,'message':'payments'})
    assert req.status_code==200
    assert req.json()['status']=='pending'
    data=approve_request(app,req.json())
    assert data['result_site_id'] and data['result_organization_id'] and 'temporary_password' not in data


def test_public_organizer_signup_does_not_grant_platform_scope(tmp_path):
    app=create_app('sqlite:///'+str(tmp_path/'x.sqlite'),origin='http://testserver',seed_demo=True)
    c=TestClient(app); creds=app.state.seed_credentials
    admin=next(x for x in creds if x['email']=='admin@pulsex.test')
    login=c.post('/api/auth/login',json={'email':admin['email'],'password':admin['password']}); csrf=login.json()['csrf']; h={'X-CSRF':csrf,'Origin':'http://testserver'}
    platform=next(x for x in c.get('/api/admin/sites').json()['sites'] if x['kind']=='platform')
    req=c.post('/api/signup-request',json={'site_id':platform['id'],'requested_role':'organizer','organization_name':'Organizer X','contact_name':'Manager','email':'manager@organizerx.test','wants_account':True})
    assert req.status_code==200
    approved=approve_request(app,req.json())
    assert approved['result_site_id']!='platform'
    from app.db import users
    with app.state.engine.connect() as conn:
        user=conn.execute(select(users).where(users.c.id==approved['user_id'])).mappings().one()
        assert user['role']=='organizer' and user['scope_id']==approved['result_site_id']
