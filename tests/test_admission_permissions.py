"""Admission authorization regressions; SQLite is not PostgreSQL acceptance."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import insert, select, update

from app.application.access import can_manage, can_read, event_permissions, require_event_permission
from app.application.public_service import build_public_bundle, build_public_poll_results
from app.db import assignments, event_participations, make_engine, memberships, metadata, organizations, sites, users, versions
from app.invitations_db import admission_policies
from app.domain import default_config, now


@pytest.fixture
def db():
    engine = make_engine('sqlite:///:memory:')
    metadata.create_all(engine)
    with engine.begin() as conn:
        for site_id, kind, parent in [('platform', 'platform', None), ('event-a', 'event', 'platform'), ('event-b', 'event', 'platform'), ('agency-a', 'agency', 'event-a')]:
            config = default_config(site_id, kind)
            conn.execute(insert(sites).values(id=site_id, kind=kind, slug=site_id, parent_id=parent,
                event_id=site_id if kind == 'event' else parent if kind == 'agency' else None,
                draft=config, draft_rev=1, published_version=1))
            conn.execute(insert(versions).values(site_id=site_id, version=1, config=config, published_at=now()))
        conn.execute(insert(users).values(id='crew', email='crew@example.test', name='Crew', role='member', scope_id='event-a', password_hash='unused', active=1))
        conn.execute(insert(organizations).values(id='org-a', slug='org-a', name='Org', profile={}, status='active', created_at=now()))
        conn.execute(insert(event_participations).values(id='part-a', organization_id='org-a', event_id='event-a', agency_site_id='agency-a', participation_type='exhibitor', status='active', services=[], created_at=now()))
        yield conn
    engine.dispose()


def crew(db, role=None, **assignment_values):
    if role:
        db.execute(insert(assignments).values(id='assignment-'+role, user_id='crew', site_id='event-a', role=role, status='active', created_at=now(), **assignment_values))
    return dict(db.execute(select(users).where(users.c.id == 'crew')).mappings().one())


@pytest.mark.parametrize('role,allowed,blocked', [
    ('scanner', 'guests.checkin', 'guests.register'),
    ('reception', 'guests.register', 'guests.export'),
    ('committee_supervisor', 'invitations.review', 'committee.manage'),
    ('analyst', 'guests.read', 'guests.checkin'),
    ('auditor', 'guests.read', 'guests.export'),
    ('event_manager', 'policy.manage', 'unknown.action'),
])
def test_admission_roles_enforce_action_and_exact_event(db, role, allowed, blocked):
    user = crew(db, role)
    assert require_event_permission(db, user, 'event-a', allowed)['id'] == 'event-a'
    for eid, action in [('event-a', blocked), ('event-b', allowed)]:
        with pytest.raises(HTTPException) as exc:
            require_event_permission(db, user, eid, action)
        assert exc.value.status_code == 403


@pytest.mark.parametrize('role', ['scanner', 'reception', 'analyst', 'auditor', 'committee_supervisor', 'member', 'unexpected-admin'])
def test_admission_assignment_never_grants_generic_site_editing(db, role):
    user = crew(db, role)
    site = db.execute(select(sites).where(sites.c.id == 'event-a')).mappings().one()
    assert not can_manage(db, user, site)


@pytest.mark.parametrize('assignment_values', [
    {'valid_until': '2000-01-01T00:00:00+00:00'},
    {'valid_from': '2999-01-01T00:00:00+00:00'},
    {'valid_until': 'invalid'},
    {'valid_until': '2999-01-01T00:00:00'},
])
def test_expired_future_and_invalid_shifts_fail_closed(db, assignment_values):
    assert not event_permissions(db, crew(db, 'scanner', **assignment_values), 'event-a')


def test_timezone_offset_shift_compares_instants(db):
    # Local wall time is ahead of UTC, but this start instant is already past.
    start = (datetime.now(timezone.utc) - timedelta(minutes=1)).astimezone(timezone(timedelta(hours=3))).isoformat()
    assert 'guests.checkin' in event_permissions(db, crew(db, 'scanner', valid_from=start), 'event-a')


def test_revoked_assignment_and_disabled_user_fail_closed(db):
    user = crew(db, 'scanner')
    db.execute(update(assignments).values(status='suspended'))
    assert not event_permissions(db, user, 'event-a')
    db.execute(update(assignments).values(status='active'))
    assert not event_permissions(db, {**user, 'active': 0}, 'event-a')


def test_organizer_scope_and_agency_scope_do_not_expand_to_other_events(db):
    user = crew(db)
    organizer = {**user, 'role': 'organizer', 'scope_id': 'event-a'}
    assert 'committee.manage' in event_permissions(db, organizer, 'event-a')
    assert not event_permissions(db, organizer, 'event-b')
    assert not event_permissions(db, {**user, 'role': 'agency', 'scope_id': 'agency-a'}, 'event-a')
    assert 'committee.manage' in event_permissions(db, {**user, 'role': 'platform'}, 'event-b')


@pytest.mark.parametrize('role,status,expected', [
    ('owner', 'active', True), ('admin', 'active', True), ('editor', 'active', True),
    ('analyst', 'active', False), ('member', 'active', False), ('owner', 'suspended', False),
])
def test_direct_agency_scope_cannot_bypass_membership_restrictions(db, role, status, expected):
    user = {**crew(db), 'role': 'agency', 'scope_id': 'agency-a'}
    db.execute(insert(memberships).values(user_id=user['id'], organization_id='org-a', role=role, status=status, created_at=now()))
    site = db.execute(select(sites).where(sites.c.id == 'agency-a')).mappings().one()
    assert can_manage(db, user, site) is expected
    assert can_read(db, user, site) is (expected or (role == 'analyst' and status == 'active'))


def test_organization_owner_is_not_event_admission_manager(db):
    user = crew(db)
    db.execute(insert(memberships).values(user_id=user['id'], organization_id='org-a', role='owner', status='active', created_at=now()))
    assert not event_permissions(db, user, 'event-a')


def test_private_events_and_children_cannot_be_read_or_discovered(db):
    db.execute(insert(admission_policies).values(event_id='event-a', config={'visibility': 'private'}, rev=1, updated_at=now()))
    site = lambda sid: db.execute(select(sites).where(sites.c.id == sid)).mappings().one()
    listing = build_public_bundle(db, site('platform'), 'http://testserver')
    assert [event['id'] for event in listing['events']] == ['event-b']
    for sid in ('event-a', 'agency-a'):
        with pytest.raises(HTTPException) as exc:
            build_public_bundle(db, site(sid), 'http://testserver')
        assert exc.value.status_code == 404
        with pytest.raises(HTTPException) as exc:
            build_public_poll_results(db, site(sid))
        assert exc.value.status_code == 404
    with pytest.raises(HTTPException):
        build_public_bundle(db, site('event-a'), 'http://testserver', authorized_event_id='event-b')
    assert build_public_bundle(db, site('event-a'), 'http://testserver', authorized_event_id='event-a')['id'] == 'event-a'
    assert build_public_bundle(db, site('event-a'), 'http://testserver', draft=True)['preview'] is True


def test_unlisted_event_is_directly_readable_but_not_listed(db):
    db.execute(insert(admission_policies).values(event_id='event-a', config={'visibility': 'unlisted'}, rev=1, updated_at=now()))
    platform = db.execute(select(sites).where(sites.c.id == 'platform')).mappings().one()
    event = db.execute(select(sites).where(sites.c.id == 'event-a')).mappings().one()
    assert build_public_bundle(db, event, 'http://testserver')['id'] == 'event-a'
    assert [row['id'] for row in build_public_bundle(db, platform, 'http://testserver')['events']] == ['event-b']


@pytest.fixture
def committee_api():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.admission_access_routes import install_admission_access_routes
    from app.application.auth_service import identify_request
    from app.core.security import digest
    from app.db import sessions
    engine = make_engine('sqlite:///:memory:')
    metadata.create_all(engine)
    with engine.begin() as conn:
        for eid in ('event-a', 'event-b'):
            conn.execute(insert(sites).values(id=eid, kind='event', slug=eid, event_id=eid, draft=default_config(eid, 'event'), draft_rev=1, published_version=0))
        for uid, role in [('manager', 'organizer'), ('crew', 'member')]:
            conn.execute(insert(users).values(id=uid, name=uid, email=uid+'@example.test', role=role, scope_id='event-a', password_hash='unused', active=1))
            conn.execute(insert(sessions).values(token_hash=digest(uid+'-token'), user_id=uid, csrf='csrf-'+uid, expires_at='2999-01-01T00:00:00+00:00'))
    app = FastAPI()
    install_admission_access_routes(app, engine, identify_request)
    client = TestClient(app)
    client.cookies.set('px_session', 'manager-token')
    client.headers['X-CSRF'] = 'csrf-manager'
    yield client, engine
    engine.dispose()


def test_committee_assignment_capabilities_revocation_and_csrf(committee_api):
    client, engine = committee_api
    route = '/api/admin/events/event-a/committee'
    client.headers.pop('X-CSRF')
    assert client.post(route, json={'email': 'crew@example.test', 'role': 'scanner'}).status_code == 403
    client.headers['X-CSRF'] = 'csrf-manager'
    created = client.post(route, json={'email': 'crew@example.test', 'role': 'scanner'})
    assert created.status_code == 200, created.text
    assignment_id = created.json()['id']
    with engine.connect() as conn:
        assert conn.execute(select(users.c.role).where(users.c.id == 'crew')).scalar_one() == 'member'
    listed = client.get(route).json()['assignments']
    assert listed[0]['id'] == assignment_id
    client.cookies.set('px_session', 'crew-token'); client.headers['X-CSRF'] = 'csrf-crew'
    events = client.get('/api/admin/admission/events').json()['events']
    assert [row['id'] for row in events] == ['event-a']
    assert set(events[0]['permissions']) == {'guests.read', 'guests.checkin'}
    assert client.get('/api/admin/events/event-b/permissions').status_code == 403
    assert client.get(route).status_code == 403
    assert client.post(route, json={'email': 'crew@example.test', 'role': 'event_manager'}).status_code == 403
    client.cookies.set('px_session', 'manager-token'); client.headers['X-CSRF'] = 'csrf-manager'
    assert client.patch(route+'/'+assignment_id, json={'status': 'revoked'}).status_code == 200
    client.cookies.set('px_session', 'crew-token')
    assert client.get('/api/admin/admission/events').json()['events'] == []
    assert client.get('/api/admin/events/event-a/permissions').status_code == 403


@pytest.mark.parametrize('body', [
    {'email': 'crew@example.test', 'role': 'platform'},
    {'email': 'crew@example.test', 'role': 'scanner', 'valid_from': '2026-01-01T10:00:00'},
    {'email': 'crew@example.test', 'role': 'scanner', 'valid_from': '2026-01-02T10:00:00+00:00', 'valid_until': '2026-01-01T10:00:00+00:00'},
])
def test_committee_rejects_privilege_and_shift_input(committee_api, body):
    client, _ = committee_api
    assert client.post('/api/admin/events/event-a/committee', json=body).status_code == 422
    assert client.get('/api/admin/events/event-a/committee').json()['assignments'] == []


def test_committee_manager_cannot_assign_other_event(committee_api):
    client, _ = committee_api
    assert client.post('/api/admin/events/event-b/committee', json={'email': 'crew@example.test', 'role': 'scanner'}).status_code == 403


def test_new_committee_account_is_limited_and_secret_returned_once(committee_api):
    from app.core.security import verify_password
    client, engine = committee_api
    body = {'email': 'new-crew@example.test', 'name': 'Reception', 'role': 'reception',
            'create_account': True, 'global_role': 'platform', 'scope_id': 'event-b'}
    result = client.post('/api/admin/events/event-a/committee', json=body)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data['account_created'] and data['must_change_password'] and data['temporary_password']
    with engine.connect() as conn:
        user = conn.execute(select(users).where(users.c.id == data['user_id'])).mappings().one()
        assert user['role'] == 'member' and user['scope_id'] == 'event-a'
        assert verify_password(data['temporary_password'], user['password_hash'])
        assert not can_manage(conn, user, conn.execute(select(sites).where(sites.c.id == 'event-a')).mappings().one())
        assert 'guests.register' in event_permissions(conn, user, 'event-a')
        assert 'committee.manage' not in event_permissions(conn, user, 'event-a')
    repeat = client.post('/api/admin/events/event-a/committee', json=body).json()
    assert repeat['temporary_password'] is None and repeat['account_created'] is False


def test_limited_crew_cannot_create_more_accounts(committee_api):
    client, engine = committee_api
    assert client.post('/api/admin/events/event-a/committee', json={'email': 'crew@example.test', 'role': 'scanner'}).status_code == 200
    client.cookies.set('px_session', 'crew-token'); client.headers['X-CSRF'] = 'csrf-crew'
    result = client.post('/api/admin/events/event-a/committee', json={
        'email': 'attacker@example.test', 'name': 'Attacker', 'role': 'event_manager', 'create_account': True,
    })
    assert result.status_code == 403
    with engine.connect() as conn:
        assert not conn.execute(select(users).where(users.c.email == 'attacker@example.test')).first()
