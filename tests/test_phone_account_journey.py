"""Direct phone/password registration and scoped recovery, with no OTP at all."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.engine import make_url

from app.core.security import verify_password
from app.db import audit, metadata, user_phones, users
from app.server import create_app

PASSWORD = 'My-Personal-Password-2026!'
PHONE = '+967777123456'


@pytest.fixture
def system(monkeypatch, tmp_path):
    monkeypatch.setenv('PULSEX_ENV', 'test')
    monkeypatch.setenv('REQUIRE_POSTGRES', 'false')
    # An old environment flag must not restore the superseded OTP behavior.
    monkeypatch.setenv('PULSEX_OTP_MODE', 'mock')
    url = 'sqlite:///' + str(tmp_path / 'phone.sqlite')
    admin_engine = None
    native = os.environ.get('PX_ACCOUNT_TEST_DATABASE_URL')
    if native:
        admin_engine = create_engine(native)
        schema = 'px_phone_qa_' + uuid.uuid4().hex
        with admin_engine.begin() as conn:
            conn.exec_driver_sql('CREATE SCHEMA ' + schema)
        parsed = make_url(native)
        url = parsed.set(query={**parsed.query, 'options': '-csearch_path=' + schema}).render_as_string(hide_password=False)
    try:
        app = create_app(url, origin='http://testserver', seed_demo=True)
        with TestClient(app) as client:
            yield app, client
    finally:
        if admin_engine:
            with admin_engine.begin() as conn:
                conn.exec_driver_sql('DROP SCHEMA ' + schema + ' CASCADE')
            admin_engine.dispose()


def register(client, phone=PHONE, **extra):
    return client.post('/api/auth/register', json={
        'name': 'New Phone User', 'phone': phone, 'password': PASSWORD,
        'confirmation': PASSWORD, **extra})


def login_as(client, account):
    response = client.post('/api/auth/login', json=account)
    assert response.status_code == 200, response.text
    client.headers['X-CSRF'] = response.json()['csrf']
    return response.json()


def admin(client, app):
    return login_as(client, app.state.seed_credentials[0])


def test_register_phone_directly_starts_session_without_granting_admin(system):
    app, client = system
    response = register(client, role='platform', scope_id='platform', active=0, email='attacker@example.test')
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['user']['phone'] == PHONE and data['user']['email'] is None
    assert data['user']['role'] == 'attendee' and data['user']['scope_id'] is None
    assert not data['user']['must_change_password']
    assert client.get('/api/auth/me').status_code == 200
    for path in ('/api/admin/sites', '/api/admin/signup-requests', '/api/admin/organizations', '/api/admin/admission/events'):
        assert client.get(path).status_code == 403, path
    assert client.post('/api/admin/organizations', json={'name': 'Escalation', 'slug': 'escalation'}).status_code == 403
    with app.state.engine.connect() as conn:
        saved = conn.execute(select(users).where(users.c.id == data['user']['id'])).mappings().one()
        assert verify_password(PASSWORD, saved['password_hash']) and saved['password_hash'] != PASSWORD


@pytest.mark.parametrize('phone', ['777123456', '0777123456', '967777123456', '00967777123456', '+967 777 123 456', '٧٧٧١٢٣٤٥٦'])
def test_phone_normalization_prevents_duplicate_accounts(system, phone):
    _, client = system
    assert register(client).status_code == 200
    assert register(client, phone).status_code == 409
    assert client.post('/api/auth/login', json={'phone': phone, 'password': PASSWORD}).status_code == 200


@pytest.mark.parametrize('phone', ['', 'abc777123456', '+967123456789', '+000777123456', '123', '0000'])
def test_invalid_phone_fails_without_creating_a_user(system, phone):
    app, client = system
    with app.state.engine.connect() as conn:
        before = len(conn.execute(select(users)).all())
    assert register(client, phone).status_code == 422
    with app.state.engine.connect() as conn:
        assert len(conn.execute(select(users)).all()) == before


def test_confirmation_short_password_and_wrong_login_are_rejected(system):
    _, client = system
    assert register(client, confirmation='Different-Password-2026!').status_code == 422
    assert register(client, password='0000', confirmation='0000').status_code == 422
    assert register(client).status_code == 200
    assert client.post('/api/auth/login', json={'phone': PHONE, 'password': '0000'}).status_code == 401
    assert client.post('/api/auth/login', json={'email': 'tel:' + PHONE, 'password': PASSWORD}).status_code == 401


def test_no_otp_routes_even_with_old_mock_environment_flag(system):
    _, client = system
    options = client.get('/api/auth/options').json()
    assert options['verification_required'] is False
    for path in ('/api/auth/otp/request', '/api/auth/otp/verify'):
        assert client.post(path, json={'phone': PHONE, 'code': '0000'}).status_code in (404,405)
    assert client.post('/api/auth/password/reset', json={'phone': PHONE, 'password': PASSWORD}).status_code == 403


def test_legacy_account_adds_phone_with_current_password_and_keeps_identity(system):
    app, client = system
    legacy = app.state.seed_credentials[1]
    old = login_as(client, legacy)['user']
    assert client.post('/api/auth/phone', json={'phone': PHONE, 'current': 'wrong'}).status_code == 401
    assert client.post('/api/auth/phone', json={'phone': PHONE, 'current': legacy['password']}).status_code == 200
    assert client.get('/api/auth/me').status_code == 401
    current = login_as(client, {'phone': PHONE, 'password': legacy['password']})['user']
    assert (current['id'], current['role'], current['scope_id']) == (old['id'], old['role'], old['scope_id'])
    assert current['email'] == legacy['email']
    assert client.post('/api/auth/phone', json={'phone': '+967777123457', 'current': legacy['password']}).status_code == 409
    assert client.post('/api/auth/login', json=legacy).status_code == 200


def test_phone_cannot_be_taken_from_an_existing_account(system):
    app, client = system
    assert register(client).status_code == 200
    admin(client, app)
    assert client.post('/api/auth/phone', json={'phone': PHONE, 'current': app.state.seed_credentials[0]['password']}).status_code == 409


def test_self_password_change_revokes_every_session(system):
    app, client = system
    registered = register(client).json()
    client.headers['X-CSRF'] = registered['csrf']
    with TestClient(app) as other:
        login_as(other, {'phone': PHONE, 'password': PASSWORD})
        response = client.post('/api/auth/password', json={'current': PASSWORD, 'password': 'Changed-By-Me-2026!', 'confirmation': 'Changed-By-Me-2026!'})
        assert response.status_code == 200
        assert other.get('/api/auth/me').status_code == 401
        assert client.get('/api/auth/me').status_code == 401
        assert client.post('/api/auth/login', json={'phone': PHONE, 'password': PASSWORD}).status_code == 401
        assert client.post('/api/auth/login', json={'phone': PHONE, 'password': 'Changed-By-Me-2026!'}).status_code == 200


def test_administrator_recovery_revokes_sessions_forces_change_and_never_uses_otp(system):
    app, client = system
    data = register(client).json()
    target = data['user']['id']
    with TestClient(app) as staff:
        assert staff.post('/api/admin/users/' + target + '/password/reset', json={}).status_code == 401
        admin(staff, app)
        lookup = staff.get('/api/admin/users', params={'phone': '777123456'}).json()
        assert lookup['users'][0]['id'] == target
        reset = staff.post('/api/admin/users/' + target + '/password/reset', json={})
        assert reset.status_code == 200, reset.text
        temporary = reset.json()['temporary_password']
    assert client.get('/api/auth/me').status_code == 401
    auth = login_as(client, {'phone': PHONE, 'password': temporary})
    assert auth['user']['must_change_password'] is True
    assert client.post('/api/auth/password', json={'current': temporary, 'password': PASSWORD, 'confirmation': PASSWORD}).status_code == 200
    assert client.get('/api/auth/me').status_code == 401
    with app.state.engine.connect() as conn:
        record = conn.execute(select(audit).where(audit.c.action == 'admin_password_reset')).mappings().one()
        assert record['details'] == {'target_user_id': target}
        assert temporary not in str(record)


def test_suspended_user_cannot_login_or_reset(system):
    app, client = system
    target = register(client).json()['user']['id']
    with app.state.engine.begin() as conn:
        conn.execute(update(users).where(users.c.id == target).values(active=0))
    assert client.get('/api/auth/me').status_code == 401
    assert client.post('/api/auth/login', json={'phone': PHONE, 'password': PASSWORD}).status_code == 401
    admin(client, app)
    assert client.post('/api/admin/users/' + target + '/password/reset', json={}).status_code == 409


def test_phone_only_business_request_is_pending_and_approval_is_not_replayed(system):
    app, client = system
    registered = register(client).json()['user']
    payload = {'site_id': 'event-demo', 'requested_role': 'participant', 'organization_name': 'Phone Org', 'contact_name': 'Owner', 'phone': PHONE}
    response = client.post('/api/signup-request', json=payload)
    assert response.status_code == 200, response.text
    request_id = response.json()['id']
    assert response.json()['grants_access'] is False
    assert client.get('/api/admin/signup-requests').status_code == 403
    admin(client, app)
    reviewed = client.patch('/api/admin/signup-requests/' + request_id, json={'status': 'approved', 'organization_slug': 'phone-org'})
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()['temporary_password'] is None
    assert client.patch('/api/admin/signup-requests/' + request_id, json={'status': 'approved'}).status_code == 409
    signed_in = login_as(client, {'phone': PHONE, 'password': PASSWORD})['user']
    assert signed_in['id'] == registered['id'] and signed_in['role'] == 'member'
    assert client.get('/api/admin/sites/' + reviewed.json()['agency_site_id']).status_code == 200
    assert client.get('/api/admin/signup-requests').status_code == 403


def test_operator_can_create_phone_staff_and_reset_only_in_scope(system):
    app, client = system
    platform_user = admin(client, app)['user']['id']
    created = client.post('/api/admin/sites/agency-01/users', json={'name': 'Phone Staff', 'phone': PHONE})
    assert created.status_code == 200, created.text
    user = next(row for row in client.get('/api/admin/sites/agency-01/users').json()['users'] if row['phone'] == PHONE)
    assert user['email'] is None
    login_as(client, app.state.seed_credentials[1])
    assert client.post('/api/admin/users/' + user['id'] + '/password/reset', json={}).status_code == 200
    assert client.post('/api/admin/users/' + platform_user + '/password/reset', json={}).status_code == 403


def test_concurrent_registration_creates_exactly_one_phone_account(system):
    app, _ = system
    def attempt(_):
        with TestClient(app) as client:
            return register(client).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, range(2))) == [200, 409]
    with app.state.engine.connect() as conn:
        assert len(conn.execute(select(user_phones)).all()) == 1


def test_additive_phone_migration_replays_and_preserves_legacy_users(system):
    from tools.migrate_postgres import execute_script
    app, _ = system
    source = (Path(__file__).resolve().parents[1] / 'ops/011_phone_accounts.sql').read_text()
    with app.state.engine.begin() as conn:
        before = list(conn.execute(select(users)).mappings())
        user_phones.drop(conn)
        execute_script(conn, source)
        execute_script(conn, source)
        assert list(conn.execute(select(users)).mappings()) == before


def test_cross_origin_registration_rejected(system):
    _, client = system
    response = client.post('/api/auth/register', headers={'Origin': 'https://other.example'}, json={'phone': PHONE})
    assert response.status_code == 403


def test_platform_can_suspend_and_reactivate_phone_account(system):
    app, client = system
    target = register(client).json()['user']['id']
    client.headers['X-CSRF'] = client.get('/api/auth/me').json()['csrf']
    assert client.patch('/api/admin/users/' + target, json={'active': False}).status_code == 403
    platform = admin(client, app)['user']['id']
    assert client.patch('/api/admin/users/' + platform, json={'active': False}).status_code == 409
    assert client.patch('/api/admin/users/' + target, json={'active': 'false'}).status_code == 422
    assert client.patch('/api/admin/users/' + target, json={'active': False}).status_code == 200
    with TestClient(app) as other:
        assert other.post('/api/auth/login', json={'phone': PHONE, 'password': PASSWORD}).status_code == 401
        assert client.patch('/api/admin/users/' + target, json={'active': True}).status_code == 200
        assert other.post('/api/auth/login', json={'phone': PHONE, 'password': PASSWORD}).status_code == 200


def test_phone_committee_account_and_registered_attendee_keep_scoped_roles(system):
    app, client = system
    target = register(client).json()['user']['id']
    admin(client, app)
    assigned = client.post('/api/admin/events/event-demo/committee', json={'phone': PHONE, 'role': 'scanner'})
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()['user_id'] == target
    login_as(client, {'phone': PHONE, 'password': PASSWORD})
    permissions = client.get('/api/admin/events/event-demo/permissions').json()['permissions']
    assert 'guests.checkin' in permissions and 'committee.manage' not in permissions
    assert client.get('/api/admin/sites/event-demo').status_code == 403
    assert client.get('/api/admin/signup-requests').status_code == 403
    admin(client, app)
    created = client.post('/api/admin/events/event-demo/committee', json={'phone': '+967777123458', 'role': 'reception', 'name': 'Phone Crew', 'create_account': True})
    assert created.status_code == 200, created.text
    assert created.json()['phone'] == '+967777123458' and created.json()['email'] is None
    rows = client.get('/api/admin/events/event-demo/committee').json()['assignments']
    assert any(row['phone'] == '+967777123458' and row['email'] is None for row in rows)


def test_real_http_registration_and_login_need_no_verification(tmp_path):
    from test_admission_http_ack import running_server
    with running_server(tmp_path) as (_, client):
        response = register(client)
        assert response.status_code == 200, response.text
        assert client.get('/api/auth/me').json()['user']['phone'] == PHONE
        assert client.get('/api/admin/sites').status_code == 403
        client.headers['X-CSRF'] = response.json()['csrf']
        assert client.post('/api/auth/logout', json={}).status_code == 200
        assert client.get('/api/auth/me').status_code == 401
        assert client.post('/api/auth/login', json={'phone': '777123456', 'password': PASSWORD}).status_code == 200


def test_organization_user_creation_and_existing_phone_membership(system):
    app, client = system
    registered = register(client).json()['user']['id']
    admin(client, app)
    linked = client.post('/api/admin/organizations/org-01/users', json={'name': 'Existing owner', 'phone': PHONE, 'role': 'editor'})
    assert linked.status_code == 200, linked.text
    assert linked.json()['temporary_password'] is None
    signed = login_as(client, {'phone': PHONE, 'password': PASSWORD})['user']
    assert signed['id'] == registered and signed['role'] == 'member'
    assert client.get('/api/admin/sites/agency-01').status_code == 200
    admin(client, app)
    created = client.post('/api/admin/organizations/org-01/users', json={'name': 'New owner', 'phone': '+967777123459', 'role': 'editor'})
    assert created.status_code == 200, created.text
    assert created.json()['email'] is None
    signed = login_as(client, {'phone': '+967777123459', 'password': created.json()['temporary_password']})
    assert signed['user']['must_change_password'] is True


def test_organization_person_can_get_phone_account_without_email(system):
    app, client = system
    admin(client, app)
    person = client.post('/api/admin/organizations/org-01/people', json={'name': 'Phone Person', 'phone': PHONE})
    assert person.status_code == 200, person.text
    result = client.post('/api/admin/organizations/org-01/people/' + person.json()['id'] + '/account', json={'role': 'editor'})
    assert result.status_code == 200, result.text
    assert result.json()['phone'] == PHONE and result.json()['email'] is None
    state = login_as(client, {'phone': PHONE, 'password': result.json()['temporary_password']})
    assert state['user']['must_change_password'] is True


def test_registered_phone_user_receives_private_admin_notifications_and_saves_preferences(system):
    app, client = system
    registered = register(client).json()
    client.headers['X-CSRF'] = registered['csrf']
    preferences = {'theme':'dark','text_size':'large','reduce_motion':True,'notifications_enabled':True}
    assert client.put('/api/account/preferences',json=preferences).status_code == 200
    with TestClient(app) as staff:
        admin(staff, app)
        sent = staff.post('/api/admin/notifications',json={'phone':PHONE,'title':'Welcome','body':'Private phone account message'})
        assert sent.status_code == 200, sent.text
        assert staff.get('/api/account/notifications').json()['items'] == []
    assert client.get('/api/account/preferences').json() == preferences
    message = client.get('/api/account/notifications').json()['items'][0]
    assert message['body'] == 'Private phone account message'
    assert client.post('/api/account/notifications/'+message['id']+'/read',json={}).status_code == 200
