import uuid

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db import guests, event_guests, guest_checkins
from app.server import create_app


def boot(tmp_path):
    app=create_app('sqlite:///'+str(tmp_path/'guest.sqlite'),origin='http://testserver',seed_demo=True)
    return app,TestClient(app)


def login(c,app,email='admin@pulsex.test'):
    cred=next(x for x in app.state.seed_credentials if x['email']==email)
    r=c.post('/api/auth/login',json={'email':cred['email'],'password':cred['password']})
    assert r.status_code==200
    c.headers.update({'X-CSRF':r.json()['csrf'],'Origin':'http://testserver'})
    return r.json()['user']


def event_slug(c):
    platform=c.get('/api/public/site/platform').json()
    assert platform['events']
    return platform['events'][0]['slug']


def register(c,slug,phone,**extra):
    body={
        'phone':phone,'country_code':'+967','consent':True,
        'name':extra.get('name','Guest One'),
        'organization':extra.get('organization','Demo Co'),
        'job_title':extra.get('job_title','Visitor'),
    }
    if extra.get('pass_token'): body['pass_token']=extra['pass_token']
    return c.post(f'/api/public/events/{slug}/guests/register',json=body)


def test_same_phone_is_one_guest_but_qr_recovery_requires_pass_possession(tmp_path):
    app,c=boot(tmp_path);slug=event_slug(c)
    first=register(c,slug,'777123456'); assert first.status_code==200
    a=first.json()
    assert a['created'] is True and a['guest_number'].startswith('G-')
    assert isinstance(a['pass_token'],str) and len(a['pass_token'])>=32

    unknown_device=register(c,slug,'+967777123456'); assert unknown_device.status_code==200
    b=unknown_device.json()
    assert b['status']=='verification_required' and b['verification_required'] is True
    assert 'guest_number' not in b and 'qr_url' not in b and 'pass_token' not in b

    owner_retry=register(c,slug,'+967777123456',pass_token=a['pass_token'])
    assert owner_retry.status_code==200
    owner=owner_retry.json()
    assert owner['guest_number']==a['guest_number']
    assert owner['created'] is False and owner['verification_required'] is False

    with app.state.engine.connect() as db:
        assert db.execute(select(func.count()).select_from(guests)).scalar_one()==1
        assert db.execute(select(func.count()).select_from(event_guests)).scalar_one()==1


def test_lost_registration_ack_can_retry_with_same_pass_token(tmp_path):
    app,c=boot(tmp_path);slug=event_slug(c)
    pass_token='client-owned-pass-token-0123456789abcdef0123456789abcdef'
    body={'client_id':'lost-ack-1','phone':'777321321','country_code':'+967','consent':True,'pass_token':pass_token}
    first=c.post(f'/api/public/events/{slug}/guests/sync',json={'items':[body]})
    assert first.status_code==200
    a=first.json()['receipts'][0]
    assert a['status']=='accepted' and a['guest_number'].startswith('G-')
    retry=c.post(f'/api/public/events/{slug}/guests/sync',json={'items':[body]})
    assert retry.status_code==200
    b=retry.json()['receipts'][0]
    assert b['status']=='accepted' and b['guest_number']==a['guest_number']
    with app.state.engine.connect() as db:
        assert db.execute(select(func.count()).select_from(guests)).scalar_one()==1
        assert db.execute(select(func.count()).select_from(event_guests)).scalar_one()==1


def test_guest_number_qr_and_public_view_do_not_expose_phone(tmp_path):
    app,c=boot(tmp_path);slug=event_slug(c)
    guest=register(c,slug,'777222333',name='Nash').json()
    assert guest['guest_number'].startswith('G-') and len(guest['guest_number'])==21
    public=c.get(f"/api/public/events/{slug}/guests/{guest['guest_number']}")
    assert public.status_code==200
    body=public.json()
    assert body['guest_number']==guest['guest_number']
    assert 'phone' not in body and 'name' not in body
    qr=c.get(f"/api/public/events/{slug}/guests/{guest['guest_number']}/qr")
    assert qr.status_code==200 and qr.headers['content-type']=='image/png' and len(qr.content)>100


def test_admin_manifest_resolves_guest_and_checkin_is_idempotent(tmp_path):
    app,c=boot(tmp_path);slug=event_slug(c)
    guest=register(c,slug,'777555666',name='Gate Guest').json()
    platform=c.get('/api/public/site/platform').json()
    event_id=next(x['id'] for x in platform['events'] if x['slug']==slug)
    login(c,app)
    listing=c.get(f'/api/admin/events/{event_id}/guests')
    assert listing.status_code==200
    found=next(x for x in listing.json()['guests'] if x['guest_number']==guest['guest_number'])
    assert found['phone']=='+967777555666' and found['name']=='Gate Guest'
    scan_id=str(uuid.uuid4())
    payload={'scan_id':scan_id,'guest_number':guest['guest_number'],'direction':'entry','checkpoint':'main','client_time':'2026-10-06T02:00:00+03:00'}
    first=c.post(f'/api/admin/events/{event_id}/guest-checkins',json=payload)
    second=c.post(f'/api/admin/events/{event_id}/guest-checkins',json=payload)
    assert first.status_code==200 and first.json()['status']=='accepted'
    assert second.status_code==200 and second.json()['status']=='duplicate'
    with app.state.engine.connect() as db:
        assert db.execute(select(func.count()).select_from(guest_checkins)).scalar_one()==1


def test_frontend_guest_offline_and_brand_contracts_present():
    from pathlib import Path
    offline=Path('web/offline.mjs').read_text(encoding='utf-8')
    appjs=Path('web/app.mjs').read_text(encoding='utf-8')
    guest=Path('web/guest.mjs').read_text(encoding='utf-8')
    design=Path('web/design.css').read_text(encoding='utf-8')
    domain=Path('app/domain.py').read_text(encoding='utf-8')
    sw=Path('web/sw.js').read_text(encoding='utf-8')
    for token in ["'guests'","'guest_outbox'","'guest_manifests'","'checkin_outbox'"]:
        assert token in offline
    assert "guestPage(parts[1]" in appjs and "scanPage(parts[1])" in appjs
    for token in ['localPhoneFingerprint','newProvisionalNumber','syncGuestRegistrations','BarcodeDetector','loadManifest','syncCheckins']:
        assert token in guest
    for token in ['data-template=rts_tech','data-template=easy_finance','data-template=tharawat_finance']:
        assert token in design
    assert "'tharawat_finance'" in domain
    assert "'/assets/guest.mjs'" in sw
