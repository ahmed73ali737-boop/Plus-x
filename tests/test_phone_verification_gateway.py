"""Optional proof of phone ownership through the Channel Gateway, against a stub that follows the gateway's verify contract
(the gateway owns the code, attempts, expiry and per-recipient limits; Pulse X keeps only the opaque verificationId).
Login never requires it; recovery stays administrator-assisted; the phone-account policy tests keep passing unchanged."""
import http.server
import json
import threading
import uuid

import pytest

from account_approval_support import register_approved
from test_phone_account_journey import PASSWORD, PHONE, system  # noqa: F401  (fixture)

KEY = 'cgw_testtenant01_' + 'k' * 32


class Gateway(http.server.ThreadingHTTPServer):
    def __init__(self):
        self.requests, self.code, self.attempts, self.mode = [], '482913', {}, 'ok'
        gw = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(h):
                raw = h.rfile.read(int(h.headers.get('Content-Length', 0))); body = json.loads(raw or b'{}')
                gw.requests.append({'path': h.path, 'headers': {k.lower(): v for k, v in h.headers.items()}, 'body': body})
                if h.headers.get('X-Api-Key') != KEY:
                    return h._send(401, {'error': 'AUTH_REQUIRED'})
                if gw.mode == 'down':
                    return h._send(503, {'error': 'CH_STORE_UNAVAILABLE'})
                if h.path == '/api/channels/v1/verify':
                    if gw.mode == 'rate':
                        return h._send(429, {'error': 'CH_VERIFY_RATE_LIMITED'})
                    vid = 'ver-' + uuid.uuid4().hex[:8]; gw.attempts[vid] = 5
                    return h._send(201, {'verificationId': vid, 'status': 'PENDING', 'expiresAt': '2026-11-23T10:05:00Z', 'attemptsLeft': 5})
                if h.path == '/api/channels/v1/verify/check':
                    vid = body['verificationId']
                    if gw.mode == 'expired':
                        return h._send(410, {'error': 'CH_VERIFY_EXPIRED'})
                    if gw.attempts.get(vid, 0) <= 0:
                        return h._send(429, {'error': 'CH_VERIFY_MAX_ATTEMPTS'})
                    if gw.attempts.get(vid) == -1:
                        return h._send(409, {'error': 'CH_VERIFY_NOT_PENDING'})
                    if body['code'] == gw.code:
                        gw.attempts[vid] = -1
                        return h._send(200, {'verificationId': vid, 'status': 'APPROVED', 'valid': True, 'attemptsLeft': 0})
                    gw.attempts[vid] -= 1
                    return h._send(200, {'verificationId': vid, 'status': 'PENDING', 'valid': False, 'attemptsLeft': gw.attempts[vid]})
                h._send(404, {})

            def _send(h, status, doc):
                data = json.dumps(doc).encode()
                h.send_response(status); h.send_header('Content-Type', 'application/json'); h.send_header('Content-Length', str(len(data))); h.end_headers()
                h.wfile.write(data)

            def log_message(h, *a):
                pass
        super().__init__(('127.0.0.1', 0), H)
        self.url = 'http://127.0.0.1:%d' % self.server_address[1]
        threading.Thread(target=self.serve_forever, daemon=True).start()


@pytest.fixture
def gw(monkeypatch):
    server = Gateway()
    monkeypatch.setenv('PULSEX_CHANNELS_URL', server.url)
    monkeypatch.setenv('PULSEX_CHANNELS_API_KEY', KEY)
    yield server
    server.shutdown(); server.server_close()


def signed_in(system):
    app, client = system
    register_approved(app, client, phone=PHONE, password=PASSWORD)
    return client


def test_disabled_by_default_and_login_never_requires_it(system, monkeypatch):
    monkeypatch.delenv('PULSEX_CHANNELS_URL', raising=False); monkeypatch.delenv('PULSEX_CHANNELS_API_KEY', raising=False)
    client = signed_in(system)
    options = client.get('/api/auth/options').json()
    assert options['phone_verification_available'] is False and options['verification_required'] is False
    assert client.post('/api/auth/phone/verify/start').status_code == 503
    me = client.get('/api/auth/me').json()['user']
    assert me['phone_verified'] is False  # an unverified phone still signs in


def test_full_journey_sends_the_code_through_the_gateway_and_records_the_proof(system, gw):
    client = signed_in(system)
    assert client.get('/api/auth/options').json()['phone_verification_available'] is True
    started = client.post('/api/auth/phone/verify/start')
    assert started.status_code == 200, started.text
    assert started.json()['sent'] is True and 'verificationId' not in started.text  # the opaque id never reaches the browser
    sent = gw.requests[0]
    assert sent['headers']['x-api-key'] == KEY and sent['headers']['idempotency-key'].startswith('pulsex-')
    assert (sent['body']['to'], sent['body']['channel'], sent['body']['originSystem']) == (PHONE, 'SMS', 'pulsex')
    wrong = client.post('/api/auth/phone/verify/check', json={'code': '000000'})
    assert (wrong.status_code, wrong.json()['detail']) == (422, 'INVALID_CODE')
    assert client.get('/api/auth/me').json()['user']['phone_verified'] is False
    ok = client.post('/api/auth/phone/verify/check', json={'code': gw.code})
    assert ok.status_code == 200 and ok.json() == {'verified': True, 'phone': PHONE}
    assert client.get('/api/auth/me').json()['user']['phone_verified'] is True
    assert client.post('/api/auth/phone/verify/start').json() == {'verified': True, 'phone': PHONE}  # already proven: nothing sent
    assert len([r for r in gw.requests if r['path'].endswith('/verify')]) == 1
    again = client.post('/api/auth/phone/verify/check', json={'code': gw.code})
    assert again.status_code == 409  # nothing pending any more


def test_input_and_state_rules(system, gw):
    client = signed_in(system)
    assert client.post('/api/auth/phone/verify/check', json={'code': '123456'}).status_code == 409   # nothing started
    client.post('/api/auth/phone/verify/start')
    for bad in ('', 'abcdef', '12', '1' * 11, None, 123456):
        assert client.post('/api/auth/phone/verify/check', json={'code': bad}).status_code == 422
    client.headers.pop('X-CSRF')
    assert client.post('/api/auth/phone/verify/start').status_code in (401, 403)   # CSRF-protected like every state change


def test_unauthenticated_callers_cannot_trigger_sms(system, gw):
    _, client = system
    assert client.post('/api/auth/phone/verify/start').status_code in (401, 403)
    assert client.post('/api/auth/phone/verify/check', json={'code': '123456'}).status_code in (401, 403)
    assert gw.requests == []   # no anonymous path can make the gateway send a message


def test_attempts_are_limited_by_the_gateway_and_surface_clearly(system, gw):
    client = signed_in(system)
    client.post('/api/auth/phone/verify/start')
    for _ in range(5):
        assert client.post('/api/auth/phone/verify/check', json={'code': '000000'}).status_code == 422
    spent = client.post('/api/auth/phone/verify/check', json={'code': gw.code})   # even the right code is refused once attempts are gone
    assert (spent.status_code, spent.json()['detail']) == (429, 'VERIFICATION_ATTEMPTS_EXHAUSTED')
    assert client.get('/api/auth/me').json()['user']['phone_verified'] is False


def test_expired_code_and_local_start_limit(system, gw):
    client = signed_in(system)
    client.post('/api/auth/phone/verify/start')
    gw.mode = 'expired'
    expired = client.post('/api/auth/phone/verify/check', json={'code': gw.code})
    assert (expired.status_code, expired.json()['detail']) == (410, 'VERIFICATION_EXPIRED')
    gw.mode = 'ok'
    client.post('/api/auth/phone/verify/start'); client.post('/api/auth/phone/verify/start')
    limited = client.post('/api/auth/phone/verify/start')
    assert (limited.status_code, limited.json()['detail']) == (429, 'VERIFICATION_RATE_LIMITED')  # at most 3 sends per hour per user
    assert len([r for r in gw.requests if r['path'].endswith('/verify')]) == 3


def test_gateway_outage_and_refusal_are_reported_without_recording_anything(system, gw):
    client = signed_in(system)
    gw.mode = 'down'
    down = client.post('/api/auth/phone/verify/start')
    assert (down.status_code, down.json()['detail']) == (503, 'PHONE_VERIFICATION_UNAVAILABLE')
    gw.mode = 'rate'
    rate = client.post('/api/auth/phone/verify/start')
    assert (rate.status_code, rate.json()['detail']) == (429, 'VERIFICATION_RATE_LIMITED')
    gw.mode = 'ok'
    assert client.post('/api/auth/phone/verify/check', json={'code': gw.code}).status_code == 409  # a failed start left nothing pending


def test_a_wrong_gateway_key_is_a_clean_error_and_never_leaks_the_key(system, gw, monkeypatch):
    client = signed_in(system)
    monkeypatch.setenv('PULSEX_CHANNELS_API_KEY', 'cgw_wrongtenant1_' + 'x' * 32)
    r = client.post('/api/auth/phone/verify/start')
    assert r.status_code == 503 and 'cgw_' not in r.text and 'wrongtenant' not in r.text


def test_recovery_stays_administrator_assisted(system, gw):
    client = signed_in(system)
    client.post('/api/auth/phone/verify/start'); client.post('/api/auth/phone/verify/check', json={'code': gw.code})
    reset = client.post('/api/auth/password/reset', json={'phone': PHONE, 'password': PASSWORD})
    assert reset.status_code == 403   # a verified phone still does not allow self-service password reset (product decision)
