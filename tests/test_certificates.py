"""Certificate journeys on SQLite; PostgreSQL/native provider acceptance remains separate."""
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update, insert, func
from app.server import create_app
from app.db import sites, assignments, users
from app.certificates_db import certificates, certificate_templates
from app.application.certificate_service import default_design, fingerprint


@pytest.fixture
def system(tmp_path):
    url='sqlite:///'+str(tmp_path/'certificates.sqlite')
    app=create_app(url,origin='http://testserver',seed_demo=True)
    client=TestClient(app)
    admin=next(c for c in app.state.seed_credentials if c['role']=='platform')
    r=client.post('/api/auth/login',json={'email':admin['email'],'password':admin['password']})
    assert r.status_code==200,r.text
    headers={'X-CSRF':r.json()['csrf'],'Origin':'http://testserver'}
    with app.state.engine.connect() as conn:
        event=conn.execute(select(sites).where(sites.c.kind=='event')).mappings().first()['id']
    yield app,client,headers,event,url
    app.state.engine.dispose()


def setup(system):
    app,client,headers,event,_=system
    base='/api/admin/events/'+event
    t=client.post(base+'/certificate-templates',json={'name':'قالب رسمي'},headers=headers)
    assert t.status_code==200,t.text
    body={'template_id':t.json()['id'],'request_key':'request-1','recipient_key':'participant-1','award_key':'course-1',
          'data':{'participant_name':'أحمد <script>alert(1)</script>','course_title':'هندسة النظم','issuer_name':'المعهد'}}
    return base,body


def test_issue_verify_download_rotate_revoke_and_persist(system):
    app,client,headers,event,url=system
    base,body=setup(system)
    preview=client.post(base+'/certificates/preview',json={'design':default_design(),'data':body['data']},headers=headers)
    assert preview.status_code==200 and 'PREVIEW-NOT-ISSUED' in preview.json()['svg']
    result=client.post(base+'/certificates',json=body,headers=headers)
    assert result.status_code==200,result.text
    issued=result.json(); cert=issued['certificate'];serial=cert['serial']; cid=cert['id']
    token=issued['access_url'].split('/')[-1]
    public=TestClient(app)
    verify=public.get('/api/public/certificates/verify/'+serial)
    assert verify.json()['status']=='valid'
    assert not {'access_hash','recipient_key','request_key','snapshot','grade','training_hours','revoke_reason'} & verify.json().keys()
    image=public.get('/api/public/certificates/access/'+token+'/image.svg')
    assert image.status_code==200,image.text
    ElementTree.fromstring(image.text)
    assert '<script>' not in image.text and '&lt;script&gt;' in image.text
    assert 'no-store' in image.headers['cache-control']
    assert image.headers['referrer-policy']=='no-referrer'
    assert 'noindex' in image.headers['x-robots-tag']
    landing=public.get('/certificate/'+token)
    assert landing.headers['cache-control']=='no-store'
    assert landing.headers['referrer-policy']=='no-referrer'
    assert token not in image.text
    assert public.get('/api/public/certificates/access/'+serial).status_code==404
    assert public.get('/api/public/certificates/verify/unknown').status_code==404
    # A retry does not create or send a second certificate, nor disclose stored credentials.
    retry=client.post(base+'/certificates',json=body,headers=headers).json()
    assert retry['created'] is False and retry['access_url'] is None
    assert retry['certificate']['id']==cid
    original_snapshot=cert['snapshot']
    duplicate=client.post(base+'/certificates',json={**body,'request_key':'another'},headers=headers)
    assert duplicate.status_code==409
    conflict=client.post(base+'/certificates',json={**body,'data':{**body['data'],'participant_name':'آخر'}},headers=headers)
    assert conflict.status_code==409
    # Another template version never changes an issued certificate.
    client.post(base+'/certificate-templates',json={'name':'نسخة أخرى','design':default_design()},headers=headers)
    assert client.get(base+'/certificates').json()['items'][0]['snapshot']==original_snapshot
    rotated=client.post(base+'/certificates/'+cid+'/access-link',json={},headers=headers).json()['access_url'].split('/')[-1]
    assert public.get('/api/public/certificates/access/'+token).status_code==404
    assert public.get('/api/public/certificates/access/'+rotated+'/image.svg').status_code==200
    revoke=client.post(base+'/certificates/'+cid+'/revoke',json={'reason':'تصحيح الاسم'},headers=headers)
    assert revoke.status_code==200,revoke.text
    assert public.get('/api/public/certificates/verify/'+serial).json()['status']=='revoked'
    assert public.get('/api/public/certificates/access/'+rotated+'/image.svg').status_code==410
    assert client.post(base+'/certificates/'+cid+'/access-link',json={},headers=headers).status_code==410
    assert client.post(base+'/certificates/'+cid+'/revoke',json={'reason':'إعادة المحاولة'},headers=headers).status_code==200
    restarted=create_app(url,origin='http://testserver',seed_demo=False)
    assert TestClient(restarted).get('/api/public/certificates/verify/'+serial).json()['status']=='revoked'
    with app.state.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(certificates)).scalar_one()==1
        row=conn.execute(select(certificates)).mappings().one()
        assert rotated not in str(dict(row)) and token not in str(dict(row))
        assert row['snapshot_hash']==fingerprint(original_snapshot)
    restarted.state.engine.dispose()


def test_auth_scope_csrf_and_no_admission_role_escalation(system):
    app,client,headers,event,_=system
    base,body=setup(system)
    assert TestClient(app).get(base+'/certificates').status_code==401
    assert client.post(base+'/certificates',json=body).status_code==403
    assert client.post(base+'/certificates',json=body,headers={**headers,'Origin':'https://evil.test'}).status_code==403
    other=next(c for c in app.state.seed_credentials if c['role']=='agency')
    agency=TestClient(app)
    r=agency.post('/api/auth/login',json={'email':other['email'],'password':other['password']})
    ah={'X-CSRF':r.json()['csrf'],'Origin':'http://testserver'}
    assert agency.get(base+'/certificates').status_code==403
    assert agency.post(base+'/certificates',json=body,headers=ah).status_code==403
    with app.state.engine.begin() as conn:
        user=conn.execute(select(users).where(users.c.email==other['email'])).mappings().one()
        for role in ('scanner','committee_supervisor','reception','analyst'):
            conn.execute(insert(assignments).values(id='certificate-test-'+role,user_id=user['id'],site_id=event,
                role=role,status='active',created_at=datetime.now(timezone.utc).isoformat()))
    assert agency.get(base+'/certificates').status_code==403
    with app.state.engine.begin() as conn:
        ev=dict(conn.execute(select(sites).where(sites.c.id==event)).mappings().one())
        ev.update(id='event-isolation',slug='event-isolation');conn.execute(insert(sites).values(**ev))
    bad=client.post('/api/admin/events/event-isolation/certificates',json=body,headers=headers)
    assert bad.status_code==404  # Template scope, even for platform admin.


def test_validation_expiry_and_integrity_fail_closed(system):
    app,client,headers,event,_=system
    base,body=setup(system)
    for design in ({'layers':[]},{**default_design(),'qr':{'x':1110,'y':0,'size':130}},
                   {**default_design(),'layers':[{'text':'{{unknown}}'}]},
                   {**default_design(),'background':'url(https://evil.test)'}):
        assert client.post(base+'/certificate-templates',json={'name':'bad','design':design},headers=headers).status_code==422
    for payload in ({**body,'data':{'participant_name':'x'}},{**body,'expires_at':'2020-01-01T00:00:00Z'},
                    {**body,'expires_at':'2099-01-01T00:00:00'},{**body,'data':{**body['data'],'serial':'fake'}}):
        assert client.post(base+'/certificates',json=payload,headers=headers).status_code==422
    result=client.post(base+'/certificates',json=body,headers=headers).json()
    cid=result['certificate']['id'];serial=result['certificate']['serial'];token=result['access_url'].split('/')[-1]
    with app.state.engine.begin() as conn:
        conn.execute(update(certificates).where(certificates.c.id==cid).values(expires_at='2020-01-01T00:00:00+00:00'))
    assert client.get('/api/public/certificates/verify/'+serial).json()['status']=='expired'
    assert client.get('/api/public/certificates/access/'+token+'/image.svg').status_code==410
    with app.state.engine.begin() as conn:
        conn.execute(update(certificates).where(certificates.c.id==cid).values(expires_at=None,snapshot_hash='0'*64))
    assert client.get('/api/public/certificates/verify/'+serial).json()['status']=='integrity_error'
    assert client.get('/api/public/certificates/access/'+token+'/image.svg').status_code==410
