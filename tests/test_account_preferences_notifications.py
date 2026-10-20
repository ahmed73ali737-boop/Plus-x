from fastapi.testclient import TestClient
from app.server import create_app


def test_preferences_and_admin_inbox_journey(tmp_path):
    app = create_app('sqlite:///'+str(tmp_path/'account.sqlite'), origin='http://testserver', seed_demo=True)
    credentials = app.state.seed_credentials
    admin = next(x for x in credentials if x['email']=='admin@pulsex.test')
    other = next(x for x in credentials if x['role'] != 'platform')
    a, b = TestClient(app), TestClient(app)
    def login(client, credential):
        response = client.post('/api/auth/login', json={'email':credential['email'],'password':credential['password']})
        assert response.status_code == 200  # No OTP required.
        return {'X-CSRF':response.json()['csrf'], 'Origin':'http://testserver'}
    ah, bh = login(a,admin), login(b,other)
    prefs = {'theme':'dark','text_size':'large','reduce_motion':True,'notifications_enabled':False}
    assert a.put('/api/account/preferences',json=prefs,headers=ah).json() == prefs
    assert a.get('/api/account/preferences').json() == prefs
    assert b.get('/api/account/preferences').json()['theme'] == 'system'
    assert a.put('/api/account/preferences',json={**prefs,'theme':'wrong'},headers=ah).status_code == 422
    assert a.put('/api/account/preferences',json=prefs,headers={'Origin':'http://testserver'}).status_code == 403
    payload = {'email':other['email'],'title':'تحديث الفعالية','body':'رسالة من الإدارة'}
    assert b.post('/api/admin/notifications',json=payload,headers=bh).status_code == 403
    sent = a.post('/api/admin/notifications',json=payload,headers=ah)
    assert sent.status_code == 200, sent.text
    nid = sent.json()['id']
    assert not a.get('/api/account/notifications').json()['items']
    item = b.get('/api/account/notifications').json()['items'][0]
    assert item['id'] == nid and item['read_at'] is None
    assert a.post('/api/account/notifications/'+nid+'/read',json={},headers=ah).status_code == 404
    assert b.post('/api/account/notifications/'+nid+'/read',json={},headers=bh).status_code == 200
    assert b.get('/api/account/notifications').json()['items'][0]['read_at']
    # Durable settings and inbox across a new application instance.
    app2=create_app('sqlite:///'+str(tmp_path/'account.sqlite'),origin='http://testserver',seed_demo=False)
    fresh=TestClient(app2);login(fresh,other)
    assert fresh.get('/api/account/notifications').json()['items'][0]['id']==nid
    assert TestClient(app2).get('/api/account/notifications').status_code == 401
