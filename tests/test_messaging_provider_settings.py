"""Platform admin chooses the messaging provider from settings (provider registry, key by reference, test probe); env stays the fallback."""
from test_phone_account_journey import PASSWORD, PHONE, admin, system  # noqa: F401  (fixture)
from test_phone_verification_gateway import KEY, Gateway, gw, signed_in  # noqa: F401  (fixtures)
import pytest

URL = '/api/admin/integrations/messaging'


def as_admin(system):
    app, client = system
    auth = admin(client, app)
    client.headers['X-CSRF'] = auth['csrf']
    return client


def test_only_the_platform_admin_can_read_or_change_it(system):
    client = signed_in(system)   # an ordinary member
    assert client.get(URL).status_code == 403
    assert client.put(URL, json={'provider': 'none'}).status_code == 403
    assert client.post(URL + '/test').status_code == 403


def test_validation_is_strict_and_secrets_are_never_stored_or_echoed(system, monkeypatch):
    client = as_admin(system)
    bad = [{'provider': 'unknown'}, {'provider': 'channel_gateway', 'url': 'http://example.com', 'key_ref': 'env:CGW_KEY'},
           {'provider': 'channel_gateway', 'url': 'https://u:p@gw.example.com', 'key_ref': 'env:CGW_KEY'},
           {'provider': 'channel_gateway', 'url': 'https://gw.example.com/x?a=1', 'key_ref': 'env:CGW_KEY'},
           {'provider': 'channel_gateway', 'url': 'https://gw.example.com', 'key_ref': 'cgw_realkeyvalue'},
           {'provider': 'channel_gateway', 'url': 'https://gw.example.com', 'key_ref': 'env:CGW_KEY', 'api_key': 'x'}, 'x']
    for body in bad:
        assert client.put(URL, json=body).status_code == 422, body


def test_settings_drive_verification_and_override_the_environment(system, gw, monkeypatch):
    # nothing in the environment: the provider comes only from the stored setting
    monkeypatch.delenv('PULSEX_CHANNELS_URL', raising=False); monkeypatch.delenv('PULSEX_CHANNELS_API_KEY', raising=False)
    monkeypatch.setenv('MY_GATEWAY_KEY', KEY)
    app, client = system
    admin_client = as_admin(system)
    saved = admin_client.put(URL, json={'provider': 'channel_gateway', 'url': gw.url, 'key_ref': 'env:MY_GATEWAY_KEY'})
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body['source'] == 'settings' and body['active'] is True and body['key_ref_resolves'] is True and KEY not in saved.text
    assert admin_client.post(URL + '/test').json() == {'configured': True, 'reachable': True}
    admin_client.post('/api/auth/logout')
    client.headers.pop('X-CSRF', None)
    user = signed_in(system)
    assert user.get('/api/auth/options').json()['phone_verification_available'] is True
    assert user.post('/api/auth/phone/verify/start').json()['sent'] is True
    assert user.post('/api/auth/phone/verify/check', json={'code': gw.code}).json()['verified'] is True


def test_explicit_disable_beats_the_environment_and_unresolved_ref_is_inactive(system, gw):
    client = as_admin(system)   # env points at the working stub (fixture gw)
    assert client.get(URL).json()['source'] == 'environment' and client.get(URL).json()['active'] is True
    assert client.put(URL, json={'provider': 'none'}).json()['active'] is False
    assert client.post(URL + '/test').json() == {'configured': False, 'reachable': False}
    out = client.put(URL, json={'provider': 'channel_gateway', 'url': gw.url, 'key_ref': 'env:NOT_SET_ANYWHERE'}).json()
    assert out['active'] is False and out['key_ref_resolves'] is False
