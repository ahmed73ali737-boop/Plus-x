import csv
import hashlib
import io
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


def set_access_policy(client, access):
    site=client.get('/api/admin/sites/event-demo').json()
    cfg=site['draft']
    cfg['access_control']=access
    saved=client.put('/api/admin/sites/event-demo',json={'draft_rev':site['draft_rev'],'config':cfg})
    assert saved.status_code==200,saved.text
    return saved.json()


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
    assert normalize_phone('٠٧٧٧ ١٢٣ ٤٥٦','+٩٦٧')=='+967777123456'
    assert normalize_phone('۰۷۷۷ ۱۲۳ ۴۵۶','+۹۶۷')=='+967777123456'
    raw=hashlib.sha256(phone.encode('utf-8')).hexdigest()
    number=guest_number_for_phone(phone)
    assert number==guest_number_for_phone(phone)
    assert number.startswith('G-') and len(number)==21
    assert number!=f"G-{raw[:4]}-{raw[4:8]}-{raw[8:12]}-{raw[12:16]}".upper()
    assert phone_hash(phone)!=raw


def test_same_phone_is_one_guest_and_requires_pass_to_recover_existing_qr(tmp_path):
    app,c=boot(tmp_path)
    first=register(c,'0777 123 456')
    assert first['created'] is True and first['pass_token']
    second=register(c,'+967 777 123 456',name='الاسم المحدث')
    assert second['status']=='verification_required'
    assert 'guest_number' not in second and 'qr_url' not in second
    owner=c.post('/api/public/events/demo/guests/register',json={
        'phone':'+967 777 123 456','country_code':'+967','consent':True,'pass_token':first['pass_token']
    })
    assert owner.status_code==200
    assert owner.json()['guest_number']==first['guest_number']
    assert owner.json()['created'] is False
    with app.state.engine.connect() as db:
        assert len(db.execute(select(guests)).mappings().all())==1
        assert len(db.execute(select(event_guests)).mappings().all())==1


def test_public_reregistration_does_not_disclose_or_overwrite_profile(tmp_path):
    app,c=boot(tmp_path)
    first=register(c,'777151515',name='Original Name',organization='Original Org')
    assert 'phone' not in first and 'name' not in first and 'organization' not in first
    attacker=register(c,'+967777151515',name='Attacker Name',organization='Changed Org')
    assert attacker['status']=='verification_required'
    assert 'guest_number' not in attacker and 'qr_url' not in attacker
    owner=c.post('/api/public/events/demo/guests/register',json={
        'phone':'+967777151515','country_code':'+967','consent':True,
        'pass_token':first['pass_token'],'name':'Attacker Name','organization':'Changed Org'
    })
    assert owner.status_code==200 and owner.json()['guest_number']==first['guest_number']
    login(c,app)
    listed=c.get('/api/admin/events/event-demo/guests').json()['guests']
    found=next(x for x in listed if x['guest_number']==first['guest_number'])
    assert found['name']=='Original Name'
    assert found['organization']=='Original Org'


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
    manifest_guests=manifest.json()['guests']
    assert any(x['guest_number']==guest['guest_number'] for x in manifest_guests)
    assert all('phone' not in x and 'phone_e164' not in x for x in manifest_guests)


def test_guest_csv_export_is_scoped_and_spreadsheet_safe(tmp_path):
    app,c=boot(tmp_path)
    guest=register(c,'777343434',name='=FORMULA()',organization='+Injected')
    login(c,app)
    exported=c.get('/api/admin/events/event-demo/guests/export')
    assert exported.status_code==200
    assert exported.headers['content-type'].startswith('text/csv')
    rows=list(csv.DictReader(io.StringIO(exported.text.lstrip('\ufeff'))))
    row=next(x for x in rows if x['guest_number']==guest['guest_number'])
    assert row['name'].startswith("'=")
    assert row['organization'].startswith("'+")
    assert row['phone']=="'+967777343434"


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


def test_scan_id_cannot_be_reused_for_different_movement(tmp_path):
    app,c=boot(tmp_path)
    guest=register(c,'777434343')
    login(c,app)
    device=c.post('/api/admin/sites/event-demo/devices',json={'name':'Idempotency Gate','device_type':'operator'})
    token=device.json()['device_token']
    c.headers.pop('X-CSRF',None);c.headers.pop('Origin',None)
    headers={'X-PulseX-Device-Token':token}
    scan_id=str(uuid.uuid4())

    first=c.post('/api/device/events/event-demo/guest-checkins',headers=headers,json={'items':[{
        'scan_id':scan_id,'guest_number':guest['guest_number'],'direction':'entry','checkpoint':'main'
    }]}).json()['receipts'][0]
    assert first['status']=='accepted'

    conflict=c.post('/api/device/events/event-demo/guest-checkins',headers=headers,json={'items':[{
        'scan_id':scan_id,'guest_number':guest['guest_number'],'direction':'exit','checkpoint':'main'
    }]}).json()['receipts'][0]
    assert conflict['status']=='rejected' and conflict['error']=='SCAN_ID_CONFLICT'

    with app.state.engine.connect() as db:
        rows=db.execute(select(guest_checkins).where(guest_checkins.c.id==scan_id)).mappings().all()
        assert len(rows)==1 and rows[0]['direction']=='entry'


def test_guest_type_is_admin_controlled(tmp_path):
    app,c=boot(tmp_path)
    public=c.post('/api/public/events/demo/guests/register',json={
        'phone':'777464646','country_code':'+967','consent':True,'guest_type':'vip'
    })
    assert public.status_code==200
    login(c,app)
    listed=c.get('/api/admin/events/event-demo/guests').json()['guests']
    guest=next(x for x in listed if x['guest_number']==public.json()['guest_number'])
    assert guest['guest_type']=='visitor'

    admin=c.post('/api/admin/events/event-demo/guests',json={
        'phone':'777474747','country_code':'+967','consent':True,'guest_type':'vip','name':'VIP Guest'
    })
    assert admin.status_code==200 and admin.json()['guest_type']=='vip'
    listed=c.get('/api/admin/events/event-demo/guests').json()['guests']
    vip=next(x for x in listed if x['guest_number']==admin.json()['guest_number'])
    assert vip['guest_type']=='vip'


def test_gate_validate_and_anti_passback(tmp_path):
    app,c=boot(tmp_path)
    guest=register(c,'777454545')
    login(c,app)
    device=c.post('/api/admin/sites/event-demo/devices',json={'name':'Anti-passback Gate','device_type':'operator'})
    token=device.json()['device_token']
    c.headers.pop('X-CSRF',None); c.headers.pop('Origin',None)
    headers={'X-PulseX-Device-Token':token}

    valid=c.get(f"/api/device/events/event-demo/guests/{guest['guest_number']}/validate",headers=headers)
    assert valid.status_code==200 and valid.json()['status']=='valid' and valid.json()['presence']=='outside'

    entry1={'items':[{'scan_id':str(uuid.uuid4()),'guest_number':guest['guest_number'],'direction':'entry','checkpoint':'main'}]}
    first=c.post('/api/device/events/event-demo/guest-checkins',json=entry1,headers=headers).json()['receipts'][0]
    assert first['status']=='accepted' and first['presence']=='inside'

    entry2={'items':[{'scan_id':str(uuid.uuid4()),'guest_number':guest['guest_number'],'direction':'entry','checkpoint':'main'}]}
    repeated=c.post('/api/device/events/event-demo/guest-checkins',json=entry2,headers=headers).json()['receipts'][0]
    assert repeated['status']=='already_inside' and repeated['presence']=='inside'

    validated_inside=c.get(f"/api/device/events/event-demo/guests/{guest['guest_number']}/validate",headers=headers).json()
    assert validated_inside['status']=='valid' and validated_inside['presence']=='inside'

    exit1={'items':[{'scan_id':str(uuid.uuid4()),'guest_number':guest['guest_number'],'direction':'exit','checkpoint':'main'}]}
    left=c.post('/api/device/events/event-demo/guest-checkins',json=exit1,headers=headers).json()['receipts'][0]
    assert left['status']=='accepted' and left['presence']=='outside'

    exit2={'items':[{'scan_id':str(uuid.uuid4()),'guest_number':guest['guest_number'],'direction':'exit','checkpoint':'main'}]}
    repeated_exit=c.post('/api/device/events/event-demo/guest-checkins',json=exit2,headers=headers).json()['receipts'][0]
    assert repeated_exit['status']=='already_outside' and repeated_exit['presence']=='outside'

    with app.state.engine.connect() as db:
        rows=db.execute(select(guest_checkins).where(guest_checkins.c.guest_number==guest['guest_number'])).mappings().all()
        assert [x['direction'] for x in rows]==['entry','exit']


def test_checkpoint_access_policy_manifest_and_reentry_rules(tmp_path):
    app,c=boot(tmp_path)
    visitor=register(c,'777565656')
    login(c,app)
    access={
        'anti_passback':True,
        'allow_reentry':False,
        'manifest_max_age_minutes':30,
        'guest_types':[{'key':'visitor','label':'زائر'},{'key':'vip','label':'VIP'}],
        'checkpoints':[
            {'key':'main','label':'البوابة الرئيسية','enabled':True,'allowed_guest_types':[],'start':'','end':''},
            {'key':'vip-gate','label':'بوابة VIP','enabled':True,'allowed_guest_types':['vip'],'start':'','end':''},
        ],
    }
    set_access_policy(c,access)
    vip=c.post('/api/admin/events/event-demo/guests',json={
        'phone':'777575757','country_code':'+967','consent':True,'guest_type':'vip','name':'VIP Policy Guest'
    }).json()
    device=c.post('/api/admin/sites/event-demo/devices',json={'name':'Policy Gate','device_type':'operator'})
    token=device.json()['device_token']
    c.headers.pop('X-CSRF',None);c.headers.pop('Origin',None)
    headers={'X-PulseX-Device-Token':token}

    manifest=c.get('/api/device/events/event-demo/guest-manifest',headers=headers)
    assert manifest.status_code==200
    data=manifest.json()
    assert data['guest_count']>=2
    assert len(data['manifest_version'])==20
    assert data['access_control']['manifest_max_age_minutes']==30
    assert any(x['key']=='vip-gate' for x in data['access_control']['checkpoints'])
    assert all('phone' not in x and 'id' not in x for x in data['guests'])

    denied=c.get(f"/api/device/events/event-demo/guests/{visitor['guest_number']}/validate?checkpoint=vip-gate",headers=headers)
    assert denied.status_code==200
    assert denied.json()['status']=='invalid' and denied.json()['reason']=='GUEST_TYPE_NOT_ALLOWED'
    allowed=c.get(f"/api/device/events/event-demo/guests/{vip['guest_number']}/validate?checkpoint=vip-gate",headers=headers)
    assert allowed.status_code==200 and allowed.json()['status']=='valid'

    denied_scan=c.post('/api/device/events/event-demo/guest-checkins',headers=headers,json={'items':[{
        'scan_id':str(uuid.uuid4()),'guest_number':visitor['guest_number'],'mode':'entry','checkpoint':'vip-gate'
    }]}).json()['receipts'][0]
    assert denied_scan['status']=='rejected' and denied_scan['error']=='GUEST_TYPE_NOT_ALLOWED'

    enter=c.post('/api/device/events/event-demo/guest-checkins',headers=headers,json={'items':[{
        'scan_id':str(uuid.uuid4()),'guest_number':visitor['guest_number'],'mode':'entry','checkpoint':'main'
    }]}).json()['receipts'][0]
    assert enter['status']=='accepted' and enter['presence']=='inside'
    leave=c.post('/api/device/events/event-demo/guest-checkins',headers=headers,json={'items':[{
        'scan_id':str(uuid.uuid4()),'guest_number':visitor['guest_number'],'mode':'exit','checkpoint':'main'
    }]}).json()['receipts'][0]
    assert leave['status']=='accepted' and leave['presence']=='outside'
    reentry=c.post('/api/device/events/event-demo/guest-checkins',headers=headers,json={'items':[{
        'scan_id':str(uuid.uuid4()),'guest_number':visitor['guest_number'],'mode':'entry','checkpoint':'main'
    }]}).json()['receipts'][0]
    assert reentry['status']=='rejected' and reentry['error']=='REENTRY_NOT_ALLOWED'


def test_access_policy_guest_type_and_replay_survive_policy_change(tmp_path):
    app,public=boot(tmp_path)
    visitor=register(public,'777484848')
    admin=TestClient(app)
    login(admin,app)
    vip=admin.post('/api/admin/events/event-demo/guests',json={
        'phone':'777494949','country_code':'+967','consent':True,'guest_type':'vip','name':'VIP Access'
    }).json()
    event=admin.get('/api/admin/sites/event-demo').json()
    config=event['draft']
    config['access_control']={
        'anti_passback':True,'allow_reentry':True,'manifest_max_age_minutes':7200,
        'guest_types':[{'key':'visitor','label':'زائر'},{'key':'vip','label':'VIP'}],
        'checkpoints':[
            {'key':'main','label':'الرئيسية','enabled':True,'allowed_guest_types':[],'start':'','end':''},
            {'key':'vip','label':'VIP Gate','enabled':True,'allowed_guest_types':['vip'],'start':'','end':''},
        ],
    }
    saved=admin.put('/api/admin/sites/event-demo',json={'draft_rev':event['draft_rev'],'config':config})
    assert saved.status_code==200,saved.text
    device=admin.post('/api/admin/sites/event-demo/devices',json={'name':'Policy Gate','device_type':'operator'})
    token=device.json()['device_token']; headers={'X-PulseX-Device-Token':token}
    gate=TestClient(app)

    vip_valid=gate.get(f"/api/device/events/event-demo/guests/{vip['guest_number']}/validate?checkpoint=vip",headers=headers)
    assert vip_valid.status_code==200 and vip_valid.json()['status']=='valid'
    visitor_invalid=gate.get(f"/api/device/events/event-demo/guests/{visitor['guest_number']}/validate?checkpoint=vip",headers=headers)
    assert visitor_invalid.status_code==200 and visitor_invalid.json()['status']=='invalid'
    assert visitor_invalid.json()['reason']=='GUEST_TYPE_NOT_ALLOWED'

    denied=gate.post('/api/device/events/event-demo/guest-checkins',headers=headers,json={'items':[{
        'scan_id':str(uuid.uuid4()),'guest_number':visitor['guest_number'],'direction':'entry','checkpoint':'vip'
    }]}).json()['receipts'][0]
    assert denied['status']=='rejected' and denied['error']=='GUEST_TYPE_NOT_ALLOWED'

    scan_id=str(uuid.uuid4())
    first=gate.post('/api/device/events/event-demo/guest-checkins',headers=headers,json={'items':[{
        'scan_id':scan_id,'guest_number':vip['guest_number'],'direction':'entry','checkpoint':'vip'
    }]}).json()['receipts'][0]
    assert first['status']=='accepted'

    latest=admin.get('/api/admin/sites/event-demo').json()
    changed=latest['draft']; changed['access_control']['checkpoints'][1]['enabled']=False
    assert admin.put('/api/admin/sites/event-demo',json={'draft_rev':latest['draft_rev'],'config':changed}).status_code==200

    replay=gate.post('/api/device/events/event-demo/guest-checkins',headers=headers,json={'items':[{
        'scan_id':scan_id,'guest_number':vip['guest_number'],'direction':'entry','checkpoint':'vip'
    }]}).json()['receipts'][0]
    assert replay['status']=='duplicate'


def test_agency_cannot_access_event_wide_guest_directory_or_export(tmp_path):
    app,c=boot(tmp_path)
    login(c,app,'agency01@pulsex.test')
    assert c.get('/api/admin/events/event-demo/guests').status_code==403
    assert c.get('/api/admin/events/event-demo/guest-checkins').status_code==403
    assert c.get('/api/admin/events/event-demo/guests/export').status_code==403


def test_public_guest_registration_requires_consent_and_valid_phone(tmp_path):
    app,c=boot(tmp_path)
    no_consent=c.post('/api/public/events/demo/guests/register',json={'phone':'777123123','country_code':'+967','consent':False})
    assert no_consent.status_code==422 and no_consent.json()['detail']=='GUEST_CONSENT_REQUIRED'
    bad_phone=c.post('/api/public/events/demo/guests/register',json={'phone':'12','country_code':'+967','consent':True})
    assert bad_phone.status_code==422 and bad_phone.json()['detail']=='PHONE_INVALID'


def test_non_operator_event_device_cannot_access_guest_gate_data(tmp_path):
    app,c=boot(tmp_path)
    login(c,app)
    display=c.post('/api/admin/sites/event-demo/devices',json={'name':'Lobby Display','device_type':'display'})
    assert display.status_code==200,display.text
    token=display.json()['device_token']
    c.headers.pop('X-CSRF',None);c.headers.pop('Origin',None)
    headers={'X-PulseX-Device-Token':token}
    assert c.get('/api/device/events/event-demo/guest-manifest',headers=headers).status_code==403
    guest=register(c,'777414141')
    validation=c.get(f"/api/device/events/event-demo/guests/{guest['guest_number']}/validate",headers=headers)
    assert validation.status_code==403 and validation.json()['detail']=='DEVICE_ROLE_FORBIDDEN'


def test_non_operator_event_device_cannot_use_guest_gate_api(tmp_path):
    app,c=boot(tmp_path)
    login(c,app)
    display=c.post('/api/admin/sites/event-demo/devices',json={'name':'Lobby Display','device_type':'display'})
    assert display.status_code==200
    token=display.json()['device_token']
    c.headers.pop('X-CSRF',None);c.headers.pop('Origin',None)
    r=c.get('/api/device/events/event-demo/guest-manifest',headers={'X-PulseX-Device-Token':token})
    assert r.status_code==403 and r.json()['detail']=='DEVICE_ROLE_FORBIDDEN'


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
