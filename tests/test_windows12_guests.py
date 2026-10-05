import hashlib
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.application.guest_service import guest_number_for_phone, normalize_phone, phone_hash
from app.db import event_guests, guest_checkins, guests
from app.server import create_app


def boot(tmp_path):
    app=create_app('sqlite:///'+str(tmp_path/'w12.sqlite'),origin='http://testserver',seed_demo=True)
    return app,TestClient(app)


def login(client, app, email='organizer@pulsex.test'):
    cred=next(x for x in app.state.seed_credentials if x['email']==email)
    r=client.post('/api/auth/login',json={'email':cred['email'],'password':cred['password']})
    assert r.status_code==200, r.text
    client.headers.update({'X-CSRF':r.json()['csrf'],'Origin':'http://testserver'})
    return r.json()['user']


def register(client, phone, **extra):
    body={
        'phone':phone,
        'country_code':'+967',
        'consent':True,
        'name':'زائر تجريبي',
        'organization':'شركة تجريبية',
        **extra,
    }
    r=client.post('/api/public/events/demo/guests/register',json=body)
    assert r.status_code==200, r.text
    return r.json()


def test_phone_normalization_and_public_number_is_keyed_not_raw_phone_hash():
    phone=normalize_phone('0777 123 456','+967')
    assert phone=='+967777123456'
    raw=hashlib.sha256(phone.encode('utf-8')).hexdigest()
    number=guest_number_for_phone(phone)
    assert number==guest_number_for_phone(phone)
    assert number.startswith('G-') and len(number)==21
    assert number!=f"G-{raw[:4]}-{raw[4:8]}-{raw[8:12]}-{raw[12:16]}".upper()
    assert phone_hash(phone)!=raw


def test_same_phone_is_one_guest_and_one_event_registration(tmp_path):
    app,c=boot(tmp_path)
    first=register(c,'0777 123 456')
    second=register(c,'+967 777 123 456',name='الاسم المحدث')
    assert first['guest_number']==second['guest_number']
    assert first['created'] is True
    assert second['created'] is False
    assert second['event_registration_created'] is False
    with app.state.engine.connect() as db:
        assert len(db.execute(select(guests)).mappings().all())==1
        assert len(db.execute(select(event_guests)).mappings().all())==1


def test_public_guest_lookup_does_not_disclose_phone_or_name(tmp_path):
    app,c=boot(tmp_path)
    guest=register(c,'777111222',name='اسم خاص',job_title='مدير')
    r=c.get('/api/public/events/demo/guests/'+guest['guest_number'])
    assert r.status_code==200
    data=r.json()
    assert data['guest_number']==guest['guest_number']
    assert 'phone' not in data and 'phone_e164' not in data and 'name' not in data and 'job_title' not in data


def test_guest_qr_is_png_and_points_to_guest_pass(tmp_path):
    app,c=boot(tmp_path)
    guest=register(c,'777222333')
    r=c.get('/api/public/events/demo/guests/'+guest['guest_number']+'/qr')
    assert r.status_code==200
    assert r.headers['content-type'].startswith('image/png')
    assert r.content.startswith(b'\x89PNG\r\n\x1a\n')


def test_organizer_lists_guests_and_device_manifest_is_scoped(tmp_path):
    app,c=boot(tmp_path)
    guest=register(c,'777333444')
    login(c,app)
    listed=c.get('/api/admin/events/event-demo/guests')
    assert listed.status_code==200
    assert any(x['guest_number']==guest['guest_number'] and x['phone']=='+967777333444' for x in listed.json()['guests'])

    device=c.post('/api/admin/sites/event-demo/devices',json={'name':'بوابة 1','device_type':'operator'})
    assert device.status_code==200, device.text
    token=device.json()['device_token']

    c.headers.pop('X-CSRF',None)
    c.headers.pop('Origin',None)
    manifest=c.get('/api/device/events/event-demo/guest-manifest',headers={'X-PulseX-Device-Token':token})
    assert manifest.status_code==200
    assert any(x['guest_number']==guest['guest_number'] for x in manifest.json()['guests'])


def test_device_checkin_is_idempotent_and_persists_once(tmp_path):
    app,c=boot(tmp_path)
    guest=register(c,'777444555')
    login(c,app)
    device=c.post('/api/admin/sites/event-demo/devices',json={'name':'بوابة رئيسية','device_type':'operator'})
    token=device.json()['device_token']
    scan_id=str(uuid.uuid4())
    body={'items':[{'scan_id':scan_id,'guest_number':guest['guest_number'],'direction':'entry','checkpoint':'main','client_time':'2026-10-06T02:00:00+03:00'}]}

    c.headers.pop('X-CSRF',None)
    c.headers.pop('Origin',None)
    first=c.post('/api/device/events/event-demo/guest-checkins',json=body,headers={'X-PulseX-Device-Token':token})
    second=c.post('/api/device/events/event-demo/guest-checkins',json=body,headers={'X-PulseX-Device-Token':token})
    assert first.status_code==200 and first.json()['receipts'][0]['status']=='accepted'
    assert second.status_code==200 and second.json()['receipts'][0]['status']=='duplicate'
    with app.state.engine.connect() as db:
        rows=db.execute(select(guest_checkins).where(guest_checkins.c.id==scan_id)).mappings().all()
        assert len(rows)==1


def test_device_for_an_agency_cannot_download_event_guest_manifest(tmp_path):
    app,c=boot(tmp_path)
    login(c,app)
    d=c.post('/api/admin/sites/agency-01/devices',json={'name':'جهاز جناح','device_type':'tablet'})
    assert d.status_code==200, d.text
    token=d.json()['device_token']
    c.headers.pop('X-CSRF',None)
    c.headers.pop('Origin',None)
    r=c.get('/api/device/events/event-demo/guest-manifest',headers={'X-PulseX-Device-Token':token})
    assert r.status_code==403
    assert r.json()['detail']=='DEVICE_EVENT_SCOPE'


def test_scanner_route_allows_same_origin_camera_policy(tmp_path):
    app,c=boot(tmp_path)
    r=c.get('/e/demo/scan')
    assert r.status_code==200
    assert 'camera=(self)' in r.headers.get('Permissions-Policy','')
    assert 'microphone=()' in r.headers.get('Permissions-Policy','')
