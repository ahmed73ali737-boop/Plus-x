"""Phase 1 acceptance on SQLite, or on a disposable native PostgreSQL schema.

Set PX_ACCOUNT_REQUEST_TEST_DATABASE_URL to run the identical cases on PostgreSQL.
No guest/account routes or approval workflow are changed by this phase.
"""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import uuid

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, func, insert, inspect, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from app.account_requests_db import account_requests
from app.core.migrations import MIGRATION_PATHS, expected_migration_checksums
from app.core.security import hash_password, verify_password
from app.db import (make_engine, metadata, sites, users, sessions, memberships,
                    assignments, organizations, organization_people, requests,
                    signup_requests)
from app.domain import default_config, now
from app.infrastructure.account_requests import add_pending_account_request, read_account_request
from app.server import create_app
from tools.migrate_postgres import apply_migrations, execute_script

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / 'ops/013_account_requests.sql'
PASSWORD = 'Pending-Password-2026!'


def snapshot(conn):
    return {table.name: [dict(row) for row in conn.execute(select(table)).mappings()]
            for table in (users, sessions, memberships, assignments, organization_people,
                          requests, signup_requests)}


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv('PULSEX_ENV', 'test')
    monkeypatch.setenv('REQUIRE_POSTGRES', 'false')
    url = 'sqlite:///' + str(tmp_path / 'requests.sqlite')
    native = os.environ.get('PX_ACCOUNT_REQUEST_TEST_DATABASE_URL')
    control = None
    schema = 'px_account_requests_qa_' + uuid.uuid4().hex
    if native:
        assert make_url(native).get_backend_name() == 'postgresql', 'Native acceptance requires PostgreSQL'
        control = create_engine(native)
        with control.begin() as conn:
            conn.exec_driver_sql('CREATE SCHEMA ' + schema)
        parsed = make_url(native)
        url = parsed.set(query={**parsed.query, 'options': '-csearch_path=' + schema}).render_as_string(hide_password=False)
    engine = make_engine(url)
    try:
        # A genuine pre-phase-1 database, containing existing identities and requests.
        metadata.create_all(engine, tables=[t for t in metadata.sorted_tables if t is not account_requests])
        assert 'px_account_requests' not in inspect(engine).get_table_names()
        with engine.begin() as conn:
            for sid, kind in [('platform', 'platform'), ('event-one', 'event'), ('event-two', 'event')]:
                conn.execute(insert(sites).values(id=sid, kind=kind, slug=sid,
                             draft=default_config(sid, kind), draft_rev=1, published_version=0))
            for uid, email in [('supervisor', 'supervisor@example.test'), ('existing', 'Existing@Example.test')]:
                conn.execute(insert(users).values(id=uid, email=email, name=uid, role='platform',
                             scope_id='platform', password_hash=hash_password('Legacy-Password-2026!'), active=1, must_change_password=0))
            conn.execute(insert(sessions).values(token_hash='a' * 64, user_id='existing', csrf='legacy-csrf',
                         expires_at='2099-01-01T00:00:00+00:00'))
            conn.execute(insert(organizations).values(id='org-one', slug='org-one', name='Existing organization',
                         profile={}, status='active', created_at=now()))
            conn.execute(insert(organization_people).values(id='person-one', organization_id='org-one', name='Person without account',
                         person_role='member', public_visible=0, status='active', created_at=now()))
            conn.execute(insert(memberships).values(user_id='existing', organization_id='org-one', role='owner', status='active', created_at=now()))
            conn.execute(insert(assignments).values(id='assignment-one', user_id='existing', site_id='event-one', role='analyst', status='active', created_at=now()))
            conn.execute(insert(requests).values(id='legacy-access', site_id='event-one', email='legacy-access@example.test', name='Legacy access', created_at=now(), status='pending'))
            conn.execute(insert(signup_requests).values(id='legacy-signup', site_id='platform', requested_role='organizer', organization_name='Legacy signup',
                         contact_name='Legacy contact', email='legacy-signup@example.test', wants_account=1, status='pending', details={}, created_at=now()))
            before = snapshot(conn)
            execute_script(conn, MIGRATION.read_text())
            execute_script(conn, MIGRATION.read_text())
            assert snapshot(conn) == before
            assert conn.scalar(select(func.count()).select_from(account_requests)) == 0
        yield engine, url
    finally:
        engine.dispose()
        if control is not None:
            with control.begin() as conn:
                conn.exec_driver_sql('DROP SCHEMA ' + schema + ' CASCADE')
            control.dispose()


def add(conn, **overrides):
    body = dict(email='new@example.test', name='Pending person', requested_role='organizer',
                scope_type='site', scope_id='event-one', supervisor_id='supervisor',
                requested_by='supervisor', request_key=uuid.uuid4().hex,
                expires_at=(datetime.now(timezone.utc) + timedelta(days=3)).isoformat(), password=PASSWORD)
    body.update(overrides)
    return add_pending_account_request(conn, **body)


def test_old_database_upgrade_replays_without_changing_accounts_or_people(store):
    engine, _ = store
    with engine.begin() as conn:
        assert conn.scalar(select(func.count()).select_from(account_requests)) == 0
        assert conn.scalar(select(func.count()).select_from(users)) == 2
        assert conn.execute(select(requests.c.status)).scalar_one() == 'pending'
        assert conn.execute(select(signup_requests.c.status)).scalar_one() == 'pending'
        assert conn.execute(select(organization_people.c.user_id)).scalar_one() is None
        assert verify_password('Legacy-Password-2026!', conn.execute(select(users.c.password_hash).where(users.c.id == 'existing')).scalar_one())
    names = {index['name'] for index in inspect(engine).get_indexes('px_account_requests')}
    assert {'px_ar_pending_identity', 'px_ar_scope_status_time', 'px_ar_supervisor_status_time', 'px_ar_status_expiry'} <= names


def test_pending_record_hashes_password_and_does_not_create_login_or_access(store):
    engine, url = store
    with engine.begin() as conn:
        before = snapshot(conn)
        result = add(conn, email='  New@Example.Test ')
        assert result['email'] == 'new@example.test' and result['status'] == 'pending'
        assert result['supervisor_id'] == 'supervisor'
        assert snapshot(conn) == before
        encoded = conn.scalar(select(account_requests.c.password_hash))
        assert encoded != PASSWORD and verify_password(PASSWORD, encoded)
        public = dict(read_account_request(conn, result['id']))
        assert public == result
        assert not {'password', 'password_hash', 'request_key'} & public.keys()
        assert PASSWORD not in json.dumps(public) and encoded not in json.dumps(public)
    app = create_app(url, origin='http://testserver', seed_demo=False)
    try:
        with TestClient(app) as client:
            response = client.post('/api/auth/login', json={'email': 'new@example.test', 'password': PASSWORD})
            assert response.status_code == 401
            assert client.get('/api/auth/me').status_code == 401
            assert not client.cookies.get('px_session')
        with engine.connect() as conn:
            assert snapshot(conn) == before
    finally:
        app.state.engine.dispose()


def test_pending_duplicates_are_scope_specific_and_recover_outer_transaction(store):
    engine, _ = store
    with engine.begin() as conn:
        first = add(conn)
        for overrides, detail in [({'email': ' NEW@example.test '}, 'ACCOUNT_REQUEST_PENDING'),
                                  ({'email': 'other@example.test', 'request_key': conn.scalar(select(account_requests.c.request_key))}, 'ACCOUNT_REQUEST_KEY_EXISTS')]:
            with pytest.raises(HTTPException) as error:
                add(conn, **overrides)
            assert error.value.status_code == 409 and error.value.detail == detail
        other = add(conn, scope_id='event-two')
        assert other['id'] != first['id']
        assert conn.scalar(select(func.count()).select_from(account_requests)) == 2


def test_existing_legacy_email_is_case_insensitively_rejected(store):
    engine, _ = store
    with engine.begin() as conn:
        with pytest.raises(HTTPException) as error:
            add(conn, email='  EXISTING@example.test ')
        assert error.value.detail == 'ACCOUNT_ALREADY_EXISTS'
        assert conn.scalar(select(func.count()).select_from(account_requests)) == 0


def test_organization_scope_keeps_person_without_login_and_supports_deferred_password(store):
    engine, _ = store
    with engine.begin() as conn:
        result = add(conn, scope_type='organization', scope_id='org-one', requested_role='member',
                     person_id='person-one', membership_role='editor', password=None)
        assert result['organization_id'] == 'org-one' and result['site_id'] is None
        assert conn.scalar(select(account_requests.c.password_hash)) is None
        assert conn.scalar(select(organization_people.c.user_id)) is None
        assert conn.scalar(select(func.count()).select_from(users)) == 2


@pytest.mark.parametrize('status', ['approved', 'rejected', 'expired', 'cancelled'])
def test_terminal_states_require_secret_cleanup_and_allow_new_request(store, status):
    engine, _ = store
    with engine.begin() as conn:
        first = add(conn)
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(update(account_requests).where(account_requests.c.id == first['id']).values(
                status=status, reviewed_by='supervisor', reviewed_at=now(), decision_reason='Suitable public reason'))
        conn.execute(update(account_requests).where(account_requests.c.id == first['id']).values(
            status=status, password_hash=None, reviewed_by='supervisor', reviewed_at=now(), decision_reason='Suitable public reason'))
        add(conn)
        assert conn.scalar(select(func.count()).select_from(account_requests)) == 2


@pytest.mark.parametrize('changes', [
    {'status': 'active'}, {'requested_role': 'root'}, {'email': 'UPPER@example.test'},
    {'password_hash': 'plaintext-password'}, {'scope_id': 'different-key'},
    {'site_id': 'missing-site', 'scope_id': 'missing-site'}, {'supervisor_id': 'missing-supervisor'},
    {'scope_type': 'organization'}, {'source': 'guest'}, {'expires_at': '2000-01-01'},
    {'status': 'approved', 'password_hash': None},
    {'status': 'rejected', 'password_hash': None, 'reviewed_by': 'supervisor', 'reviewed_at': '2030-01-01', 'decision_reason': ' '},
    {'reviewed_by': 'supervisor'}, {'assignment_role': 'superadmin'}, {'membership_role': 'platform'},
])
def test_database_constraints_reject_invalid_records(store, changes):
    engine, _ = store
    with engine.begin() as conn:
        add(conn)
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(update(account_requests).values(**changes))


@pytest.mark.parametrize('changes,detail', [
    ({'email': 'invalid'}, 'EMAIL_INVALID'), ({'requested_role': 'scanner'}, 'ACCOUNT_REQUEST_ROLE_INVALID'),
    ({'scope_type': 'guest'}, 'ACCOUNT_REQUEST_SCOPE_INVALID'), ({'password': 'short'}, 'PASSWORD_12_TO_256_CHARACTERS'),
    ({'expires_at': '2000-01-01T00:00:00+00:00'}, 'ACCOUNT_REQUEST_EXPIRY_INVALID'),
    ({'expires_at': '2099-01-01T00:00:00'}, 'ACCOUNT_REQUEST_EXPIRY_INVALID'),
    ({'expires_at': 'invalid'}, 'ACCOUNT_REQUEST_EXPIRY_INVALID'),
])
def test_input_validation_never_persists_raw_credentials(store, changes, detail):
    engine, _ = store
    with engine.begin() as conn:
        with pytest.raises(HTTPException) as error:
            add(conn, **changes)
        assert error.value.detail == detail
        assert conn.scalar(select(func.count()).select_from(account_requests)) == 0


def test_versioned_sql_and_orm_schema_have_matching_columns_checks_and_indexes(store):
    engine, _ = store
    # Compare the migration-created table against a fresh ORM-created instance.
    migrated = inspect(engine)
    fresh = make_engine('sqlite:///:memory:')
    try:
        metadata.create_all(fresh)
        orm = inspect(fresh)
        table = 'px_account_requests'
        assert {c['name'] for c in migrated.get_columns(table)} == {c['name'] for c in orm.get_columns(table)}
        assert {c['name'] for c in migrated.get_check_constraints(table)} == {c['name'] for c in orm.get_check_constraints(table)}
        assert {i['name'] for i in migrated.get_indexes(table) if not i.get('duplicates_constraint')} == {i['name'] for i in orm.get_indexes(table) if not i.get('duplicates_constraint')}
    finally:
        fresh.dispose()


def test_versioned_migration_checksum_and_postgres_replay(store):
    engine, _ = store
    assert MIGRATION_PATHS[-1] == MIGRATION
    from app.core.migrations import migration_checksum
    assert expected_migration_checksums()[MIGRATION.name] == migration_checksum(MIGRATION)
    if engine.dialect.name == 'postgresql':
        applied = apply_migrations(engine)
        assert MIGRATION.name in applied['applied']
        repeated = apply_migrations(engine)
        assert not repeated['applied'] and MIGRATION.name in repeated['skipped']
        with engine.begin() as conn:
            recorded = conn.execute(text('SELECT checksum FROM px_schema_migrations WHERE migration_id=:id'), {'id': MIGRATION.name}).scalar_one()
            assert recorded == migration_checksum(MIGRATION)
            conn.execute(text('UPDATE px_schema_migrations SET checksum=:checksum WHERE migration_id=:id'), {'checksum': '0' * 64, 'id': MIGRATION.name})
        with pytest.raises(RuntimeError, match='MIGRATION_CHECKSUM_MISMATCH:' + MIGRATION.name):
            apply_migrations(engine)
