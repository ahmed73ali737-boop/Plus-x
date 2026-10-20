"""HTTP admission acceptance: invitation policy cannot be bypassed by old routes."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from app.server import create_app
from app.invitations_db import entitlements, admission_uses
from app.db import guest_checkins

@pytest.fixture
def admission(tmp_path,request):
    app=create_app('sqlite:///'+str(tmp_path/'gate.sqlite'),origin='http://testserver',seed_demo=True)
    admin,public=TestClient(app),TestClient(app)
    cred=next(x for x in app.state.seed_credentials if x['email']=='admin@pulsex.test')
    auth=admin.post('/api/auth/login',json={'email':cred['email'],'password':cred['password']}).json()
    admin.headers.update({'Origin':'http://testserver','X-CSRF':auth['csrf']})
    today=datetime.now(ZoneInfo('Asia/Aden')).date().isoformat()
    days=[today]
    if getattr(request,'param',{}).get('two_days'):days.append((datetime.now(ZoneInfo('Asia/Aden')).date()+timedelta(days=1)).isoformat())
    assert admin.put('/api/admin/events/event-demo/admission-policy',json={'enabled':True,'visibility':'private','entry_mode':'daily','max_companions':2,'days':[{'date':day,'capacity':3} for day in days]}).status_code==200
    inv=admin.post('/api/admin/events/event-demo/invitations',json={'name':'Synthetic party','phone':'777444222','max_companions':2}).json()
    issued=public.post('/api/public/invitations/'+inv['token']+'/rsvp',json={'response':'accepted','consent':True,'companions':2,'days':days})
    assert issued.status_code==200,issued.text
    device=admin.post('/api/admin/sites/event-demo/devices',json={'name':'Gate A','device_type':'operator'}).json()
    scanner=TestClient(app,headers={'X-PulseX-Device-Token':device['device_token']})
    yield app,admin,public,scanner,issued.json()['guest_number'],inv
    for c in (admin,public,scanner):c.close()
    app.state.engine.dispose()


def scan(client,number,scan_id,**extra):
    response=client.post('/api/device/events/event-demo/guest-checkins',json={'items':[{'scan_id':scan_id,'guest_number':number,'mode':'entry',**extra}]})
    assert response.status_code==200,response.text
    return response.json()['receipts'][0]


def test_managed_party_split_replay_quantity_conflict_and_overuse(admission):
    app,admin,public,scanner,number,inv=admission
    first=scan(scanner,number,'party-one',quantity=2)
    assert first['status']=='accepted' and first['admission']['remaining']==1
    assert scan(scanner,number,'party-one',quantity=2)['status']=='duplicate'
    assert scan(scanner,number,'party-one',quantity=1)['error']=='SCAN_ID_CONFLICT'
    assert scan(scanner,number,'party-two',quantity=1)['status']=='accepted'
    assert scan(scanner,number,'party-extra')['error']=='ADMISSION_ALREADY_USED'
    with app.state.engine.connect() as c:
        assert c.execute(select(entitlements.c.consumed)).scalar_one()==3
        assert c.execute(select(func.count()).select_from(guest_checkins)).scalar_one()==2
    totals=admin.get('/api/admin/events/event-demo/guest-checkins').json()
    assert totals['admitted_people']==3 and totals['total_checkins']==2


def test_private_registration_bypass_and_private_scanner_context(admission):
    _,admin,public,scanner,number,inv=admission
    assert public.get('/api/public/site/demo').status_code==404
    assert public.get('/api/public/events/demo/registration').status_code in (403,404)
    payload={'name':'Bypass','phone':'777444223','consent':True}
    assert public.post('/api/public/events/demo/guests/register',json=payload).status_code==404
    assert admin.post('/api/admin/events/event-demo/guests',json=payload).status_code==409
    assert public.get('/api/device/events/by-slug/demo/gate-context').status_code in (401,403)
    assert scanner.get('/api/device/events/by-slug/demo/gate-context').json()['event_id']=='event-demo'
    card=public.get('/api/public/events/demo/guests/'+number)
    assert card.status_code==200 and 'phone' not in card.json()
    manifest=scanner.get('/api/device/events/event-demo/guest-manifest').json()
    assert manifest['credential_version']==2 and manifest['requires_online']


def test_offline_managed_denial_and_invalid_batch_sibling_do_not_consume(admission):
    app,_,_,scanner,number,inv=admission
    assert scan(scanner,number,'offline',offline_scan=True)['error']=='ONLINE_ADMISSION_REQUIRED'
    response=scanner.post('/api/device/events/event-demo/guest-checkins',json={'items':[None,{'scan_id':'too-many','guest_number':number,'quantity':4},{'scan_id':'valid-sibling','guest_number':number,'quantity':1}]})
    assert [x['status'] for x in response.json()['receipts']]==['rejected','rejected','accepted']
    with app.state.engine.connect() as c:
        assert c.execute(select(entitlements.c.consumed)).scalar_one()==1
        assert c.execute(select(func.count()).select_from(admission_uses)).scalar_one()==1


def test_revoke_blocks_bearer_qr_and_gate_without_resetting_consumption(admission):
    app,admin,public,scanner,number,inv=admission
    assert scan(scanner,number,'first')['status']=='accepted'
    r=admin.post('/api/admin/events/event-demo/invitations/'+inv['invitation']['id']+'/revoke',json={})
    assert r.status_code==200,r.text
    assert public.get('/api/public/events/demo/guests/'+number+'/qr').status_code==410
    assert scan(scanner,number,'after-revoke')['status']=='rejected'
    with app.state.engine.connect() as c:
        assert c.execute(select(entitlements.c.consumed)).scalar_one()==1


@pytest.mark.parametrize('admission',[{'two_days':True}],indirect=True)
def test_new_event_local_day_restores_only_that_days_entitlement(admission,monkeypatch):
    from app.application import invitation_service
    _,admin,public,scanner,number,inv=admission
    assert scan(scanner,number,'day-one',quantity=3)['status']=='accepted'
    assert scan(scanner,number,'day-one-extra')['error']=='ADMISSION_ALREADY_USED'
    real_datetime=datetime
    class NextDay(real_datetime):
        @classmethod
        def now(cls,tz=None):
            return real_datetime.now(tz)+timedelta(days=1)
    monkeypatch.setattr(invitation_service,'datetime',NextDay)
    assert scan(scanner,number,'day-two',quantity=3)['status']=='accepted'
    assert scan(scanner,number,'day-two-extra')['error']=='ADMISSION_ALREADY_USED'
    totals=admin.get('/api/admin/events/event-demo/guest-checkins').json()
    assert totals['admitted_people']==6 and totals['total_checkins']==2


def test_admin_lost_ack_replay_consumes_exactly_once(admission):
    app,admin,_,_,number,_=admission
    body={'guest_number':number,'scan_id':'lost-admin-ack','mode':'entry','quantity':2}
    first=admin.post('/api/admin/events/event-demo/guest-checkins',json=body)
    assert first.status_code==200 and first.json()['status']=='accepted'
    # The client deliberately discards the first committed response.
    replay=admin.post('/api/admin/events/event-demo/guest-checkins',json=body)
    assert replay.status_code==200 and replay.json()['status']=='duplicate'
    with app.state.engine.connect() as c:
        assert c.execute(select(entitlements.c.consumed)).scalar_one()==2
        assert c.execute(select(func.count()).select_from(admission_uses)).scalar_one()==1
        assert c.execute(select(func.count()).select_from(guest_checkins)).scalar_one()==1


def test_dashboard_counts_more_than_500_history_rows_and_companions(admission):
    from sqlalchemy import insert
    app,admin,_,scanner,number,_=admission
    assert scan(scanner,number,'group-three',quantity=3)['status']=='accepted'
    with app.state.engine.begin() as c:
        template=dict(c.execute(select(guest_checkins)).mappings().one())
        # Historical exit/entry movements are not additional entitlement uses.
        for i in range(502):
            c.execute(insert(guest_checkins).values(**{**template,'id':f'history-{i}','direction':'exit' if i%2==0 else 'entry'}))
    summary=admin.get('/api/admin/events/event-demo/guest-checkins').json()
    assert len(summary['checkins'])==500
    assert summary['total_checkins']==503
    assert summary['admitted_people']==3
    assert summary['inside_count']==1
