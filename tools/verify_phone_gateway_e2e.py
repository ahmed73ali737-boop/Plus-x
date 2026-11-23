#!/usr/bin/env python3
"""End-to-end: Pulse X proves phone ownership through a RUNNING Channel Gateway (sandbox provider, no real SMS vendor).

    GATEWAY_URL=http://127.0.0.1:5080 GATEWAY_ADMIN_KEY=cgw_... PYTHONPATH=.:tests python3 tools/verify_phone_gateway_e2e.py

Creates its own gateway tenant and operator key, runs the real Pulse X app with PULSEX_CHANNELS_URL/KEY pointing at it, registers and signs in a
phone user, sends the code, reads it from the gateway's sandbox outbox (test-only endpoint), and checks wrong code / right code / single use.
Exit 0 = every check passed."""
import json, os, re, sys, tempfile, time, urllib.request, urllib.error, uuid
from unittest import mock
GW, ADMIN = os.environ.get('GATEWAY_URL', 'http://127.0.0.1:5080').rstrip('/'), os.environ['GATEWAY_ADMIN_KEY']
R = []
def check(n, ok, d=''):
    ok = bool(ok); R.append(ok); print(('PASS ' if ok else 'FAIL ') + n + ('' if ok else '  <- ' + str(d)[:300]))
def gw(method, path, key, body=None):
    req = urllib.request.Request(GW + path, data=json.dumps(body).encode() if body is not None else None, method=method, headers={'X-Api-Key': key, 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=20) as r: return r.status, json.loads(r.read() or b'null')
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b'null')
tenant = 'pulsex-' + uuid.uuid4().hex[:6]
s, _ = gw('PUT', f'/api/admin/v1/tenants/{tenant}', ADMIN, {'name': 'Pulse X e2e', 'timeZone': 'Asia/Aden'}); check('gateway: tenant created', s == 201, s)
s, c = gw('POST', '/api/admin/v1/clients', ADMIN, {'tenantId': tenant, 'role': 'operator', 'name': 'pulsex'}); KEY = c.get('apiKey'); check('gateway: operator key issued', s == 201 and KEY, (s, c))
def sandbox_code(timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        _, out = gw('GET', '/api/channels/v1/sandbox/outbox?limit=200', KEY)
        for item in out if isinstance(out, list) else []:
            m = re.search(r'verification code is (\d+)', item.get('wire', ''))
            if m: return m.group(1)
        time.sleep(0.5)
tmp = tempfile.mkdtemp(prefix='pulsex-e2e-')
env = {'PULSEX_ENV': 'test', 'REQUIRE_POSTGRES': 'false', 'PULSEX_CHANNELS_URL': GW, 'PULSEX_CHANNELS_API_KEY': KEY}
with mock.patch.dict(os.environ, env):
    from fastapi.testclient import TestClient
    from app.server import create_app
    from account_approval_support import prepare_review_admin, register_approved
    app = create_app('sqlite:///' + tmp + '/e2e.sqlite', origin='http://testserver', seed_demo=True)
    PHONE, PW = '+967777' + str(uuid.uuid4().int)[:6], 'My-Personal-Password-2026!'
    with TestClient(app) as client:
        prepare_review_admin(app); register_approved(app, client, phone=PHONE, password=PW)
        check('pulsex: verification advertised as available', client.get('/api/auth/options').json()['phone_verification_available'] is True)
        r = client.post('/api/auth/phone/verify/start'); check('pulsex: code requested through the gateway', r.status_code == 200 and r.json().get('sent') is True, (r.status_code, r.text))
        code = sandbox_code(); check('gateway: the SMS reached the recipient (sandbox) with a 6-digit code', code and len(code) == 6, code)
        wrong = ''.join(str((int(ch) + 1) % 10) for ch in (code or '000000'))
        r = client.post('/api/auth/phone/verify/check', json={'code': wrong}); check('pulsex: wrong code rejected (422)', r.status_code == 422, (r.status_code, r.text))
        check('pulsex: still unverified after a wrong code', client.get('/api/auth/me').json()['user']['phone_verified'] is False)
        r = client.post('/api/auth/phone/verify/check', json={'code': code}); check('pulsex: right code verifies the phone', r.status_code == 200 and r.json().get('verified') is True, (r.status_code, r.text))
        check('pulsex: phone_verified is now true', client.get('/api/auth/me').json()['user']['phone_verified'] is True)
        r = client.post('/api/auth/phone/verify/check', json={'code': code}); check('pulsex: the code is single-use', r.status_code == 409, (r.status_code, r.text))
        r = client.post('/api/auth/phone/verify/start'); check('pulsex: already verified -> nothing is sent again', r.status_code == 200 and r.json().get('verified') is True, (r.status_code, r.text))
        _, msgs = gw('GET', '/api/channels/v1/messages?limit=50', KEY); items = msgs if isinstance(msgs, list) else (msgs or {}).get('items', [])
        check('gateway: exactly one OTP message was sent for this journey', len([m for m in items if m.get('category') == 'OTP']) == 1, len(items))
print(f'\n{sum(R)}/{len(R)} checks passed'); sys.exit(0 if all(R) else 1)
