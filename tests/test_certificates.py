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
    listed=client.get(base+'/certificates').json()['items'][0]['snapshot']
    assert listed['data']==original_snapshot['data'] and 'design' not in listed
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
    overflow=client.post(base+'/certificates',json={**body,'data':{**body['data'],'participant_name':'أحمد '*40}},headers=headers)
    assert overflow.status_code==422 and overflow.json()['detail']=='CERTIFICATE_TEXT_OVERFLOW'
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


def test_server_exports_and_private_image_snapshot(system):
    import base64, io
    from PIL import Image
    app,client,headers,event,_=system
    base,body=setup(system)
    seal=Image.new('RGBA',(90,50),(0,150,120,200));buffer=io.BytesIO();seal.save(buffer,'PNG')
    uri='data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode()
    design=default_design();design['layers'].append({'kind':'image','image_data':uri,'x':800,'y':580,'width':180,'height':90})
    response=client.post(base+'/certificate-templates',json={'name':'قالب مختوم','design':design},headers=headers)
    assert response.status_code==200,response.text
    body['template_id']=response.json()['id'];body['data']['participant_name']='أحمد علي محمد'
    issued=client.post(base+'/certificates',json=body,headers=headers).json()
    token=issued['access_url'].split('/')[-1]
    prefix='/api/public/certificates/access/'+token
    pdf=client.get(prefix+'/download.pdf');assert pdf.status_code==200,pdf.text[:100]
    assert pdf.content.startswith(b'%PDF-') and 'attachment' in pdf.headers['content-disposition']
    png=client.get(prefix+'/download.png');assert png.status_code==200
    im=Image.open(io.BytesIO(png.content));assert im.width==3508 and im.height>2000
    svg=client.get(prefix+'/image.svg')
    assert svg.status_code==200 and uri not in svg.text  # No separately extractable stamp PNG.
    embedded=ElementTree.fromstring(svg.text).find('{http://www.w3.org/2000/svg}image').get('href')
    assert Image.open(io.BytesIO(base64.b64decode(embedded.split(',')[1]))).width==3508
    assert issued['certificate']['snapshot']['font_hash']
    client.post(base+'/certificates/'+issued['certificate']['id']+'/revoke',json={'reason':'مراجعة'},headers=headers)
    assert client.get(prefix+'/download.pdf').status_code==410
    assert client.get(prefix+'/download.png').status_code==410
    design['layers'][-1]['image_data']='https://evil.test/signature.svg'
    assert client.post(base+'/certificate-templates',json={'name':'bad','design':design},headers=headers).status_code==422


def import_body(template_id, rows=None):
    import base64
    content=rows or 'person,course,issuer,identity,award\nأحمد,دورة,المعهد,person-1,course-1\nليلى,دورة,المعهد,person-2,course-1\n'
    return {'filename':'participants.csv','content_base64':base64.b64encode(content.encode()).decode(),
            'template_id':template_id,'mapping':{'participant_name':'person','course_title':'course','issuer_name':'issuer','recipient_key':'identity','award_key':'award'}}


def test_preview_commit_background_issuance_restart_and_schedule(system):
    from app.application.certificate_batches import process_pending
    from app.certificates_db import certificate_jobs
    app,client,headers,event,url=system;base,body=setup(system)
    upload=import_body(body['template_id'])
    inspect=client.post(base+'/certificates/import/preview',json={k:v for k,v in upload.items() if k!='mapping'},headers=headers)
    assert inspect.json()['headers']==['person','course','issuer','identity','award']
    preview=client.post(base+'/certificates/import/preview',json=upload,headers=headers)
    assert preview.status_code==200,preview.text
    assert preview.json()['valid_count']==2 and not preview.json()['errors']
    queue=client.post(base+'/certificates/import/commit',json={'import_id':preview.json()['import_id'],'available_at':'2099-01-01T10:00:00+03:00'},headers=headers)
    assert queue.status_code==200,queue.text
    assert process_pending(app.state.engine)==0
    retry=client.post(base+'/certificates/import/commit',json={'import_id':preview.json()['import_id']},headers=headers)
    assert retry.json()['replayed'] is True
    with app.state.engine.begin() as conn:conn.execute(update(certificate_jobs).values(available_at='2020-01-01T00:00:00+00:00'))
    # A fresh worker resumes the durable pending rows.
    restarted=create_app(url,origin='http://testserver',seed_demo=False)
    assert process_pending(restarted.state.engine)==2
    assert process_pending(restarted.state.engine)==0
    with restarted.state.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(certificates)).scalar_one()==2
        rows=conn.execute(select(certificate_jobs)).mappings().all()
        assert all(r['state']=='done' and r['certificate_id'] for r in rows)
        assert all('access_url' not in r['body'] for r in rows)
    assert client.get(base+'/certificates/batches').json()['items'][0]['count']==2
    restarted.state.engine.dispose()


def test_bulk_errors_and_revoked_authority_never_issue(system):
    from app.application.certificate_batches import process_pending
    from app.certificates_db import certificate_jobs
    app,client,headers,event,_=system;base,body=setup(system)
    duplicate=import_body(body['template_id'],'person,course,issuer,identity,award\nأحمد,دورة,المعهد,same,course\nأحمد,دورة,المعهد,same,course\n')
    bad=client.post(base+'/certificates/import/preview',json=duplicate,headers=headers).json()
    assert bad['errors'][0]['row']==3
    assert client.post(base+'/certificates/import/commit',json={'import_id':bad['import_id']},headers=headers).status_code==409
    preview=client.post(base+'/certificates/import/preview',json=import_body(body['template_id']),headers=headers).json()
    assert client.post(base+'/certificates/import/commit',json={'import_id':preview['import_id']},headers=headers).status_code==200
    with app.state.engine.begin() as conn:
        admin_id=conn.execute(select(certificate_jobs.c.user_id).limit(1)).scalar_one()
        conn.execute(update(users).where(users.c.id==admin_id).values(active=0))
    assert process_pending(app.state.engine)==2
    with app.state.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(certificates)).scalar_one()==0
        assert all(r=='failed' for r in conn.execute(select(certificate_jobs.c.state)).scalars())


def test_replacement_is_atomic_new_serial_linked_and_idempotent(system):
    from app.certificates_db import certificate_replacements
    app,client,headers,event,_=system;base,body=setup(system)
    original=client.post(base+'/certificates',json=body,headers=headers).json()['certificate']
    endpoint=base+'/certificates/'+original['id']+'/replace'
    payload={'request_key':'correction-1','reason':'تصحيح الاسم','data':{**body['data'],'participant_name':'الاسم المصحح'}}
    invalid=client.post(endpoint,json={**payload,'data':{}},headers=headers)
    assert invalid.status_code==422
    assert client.get('/api/public/certificates/verify/'+original['serial']).json()['status']=='valid'
    corrected=client.post(endpoint,json=payload,headers=headers)
    assert corrected.status_code==200,corrected.text
    corrected=corrected.json()['certificate']
    assert corrected['serial']!=original['serial']
    check=client.get('/api/public/certificates/verify/'+original['serial']).json()
    assert check['status']=='revoked' and check['superseded'] is True
    assert client.get('/api/public/certificates/verify/'+corrected['serial']).json()['status']=='valid'
    replay=client.post(endpoint,json=payload,headers=headers)
    assert replay.status_code==200 and replay.json()['created'] is False
    with app.state.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(certificate_replacements)).scalar_one()==1
        assert conn.execute(select(func.count()).select_from(certificates)).scalar_one()==2



def test_issuer_timezone_date_and_legacy_idempotency(system, monkeypatch):
    from app.application import certificate_service as svc
    app,client,headers,event,_=system;base,body=setup(system)
    monkeypatch.setattr(svc,'now',lambda:'2026-10-20T23:30:00+00:00')
    issued=client.post(base+'/certificates',json={**body,'timezone':'Asia/Aden'},headers=headers)
    assert issued.status_code==200,issued.text
    row=issued.json()['certificate']
    assert row['snapshot']['data']['issue_date']=='2026-10-21'
    public=client.get('/api/public/certificates/verify/'+row['serial']).json()
    assert public['issue_date']=='2026-10-21' and public['issue_timezone']=='Asia/Aden'
    assert client.post(base+'/certificates',json={**body,'timezone':'UTC'},headers=headers).status_code==409
    assert client.post(base+'/certificates',json={**body,'request_key':'bad-zone','timezone':'no/such-zone'},headers=headers).status_code==422
    # A previously issued UTC request remains replayable after the additive timezone field.
    legacy={**body,'request_key':'legacy','recipient_key':'legacy-person'}
    original=client.post(base+'/certificates',json=legacy,headers=headers).json()['certificate']
    request_data={k:legacy[k] for k in ('template_id','recipient_key','award_key','data')}
    request_data['data']={key:legacy['data'].get(key,'') for key in svc.FIELDS[:5]}
    request_data['expires_at']=None
    with app.state.engine.begin() as conn:
        conn.execute(update(certificates).where(certificates.c.id==original['id']).values(request_hash=svc.fingerprint(request_data)))
    retry=client.post(base+'/certificates',json=legacy,headers=headers)
    assert retry.status_code==200 and retry.json()['created'] is False
