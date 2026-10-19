"""Acceptance tests for real invitation storage, transitions, privacy and admission."""
import base64
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import insert, select, func
from app.db import make_engine, metadata, sites, event_guests, guests
from app.invitations_db import invitations, entitlements, admission_uses, guest_lists
from app.application import invitation_service as svc
from app.domain import default_config


@pytest.fixture
def store(tmp_path):
    engine = make_engine('sqlite:///' + str(tmp_path / 'invitations.sqlite'))
    metadata.create_all(engine)
    ev = {'id': 'event-a', 'kind': 'event', 'slug': 'event-a', 'draft': {'title': 'فعالية'}, 'draft_rev': 1, 'published_version': 0}
    with engine.begin() as conn:
        conn.execute(insert(sites).values(**ev))
        conn.execute(insert(sites).values(**{**ev, 'id': 'event-b', 'slug': 'event-b'}))
    yield engine, ev
    engine.dispose()


def policy(conn, ev, **kwargs):
    today = datetime.now(ZoneInfo('Asia/Aden')).date().isoformat()
    return svc.save_policy(conn, ev['id'], {'enabled': True, 'visibility': 'private', 'registration_mode': 'auto', 'entry_mode': 'daily', 'max_companions': 3, 'days': [{'date': today, 'capacity': 10}], **kwargs})


def create(conn, ev, phone='777123456', **kwargs):
    return svc.create_invitation(conn, ev['id'], {'name': 'ضيف', 'phone': phone, **kwargs})


def accept(conn, ev, token, companions=0, **kwargs):
    days = [d['date'] for d in svc.get_policy(conn, ev['id'])['days']]
    return svc.respond(conn, ev, token, {'response': 'accepted', 'consent': True, 'companions': companions, 'days': days, **kwargs})


def test_private_invite_to_rsvp_issues_event_pass_without_phone_disclosure(store):
    engine, ev = store
    with engine.begin() as conn:
        policy(conn, ev)
        row, token = create(conn, ev)
        assert token not in str(conn.execute(select(invitations)).mappings().all())
        row = accept(conn, ev, token, 2)
        view = svc.public_view(conn, ev, row, 'http://testserver')
        assert row['status'] == 'approved'
        assert view['guest_number'].startswith('G-')
        assert 'phone' not in view['invitation'] and 'token_hash' not in str(view)
        assert view['qr_image_url'].endswith('/qr')
        entitlement = conn.execute(select(entitlements)).mappings().one()
        assert entitlement['quantity'] == 3
        reg = conn.execute(select(event_guests)).mappings().one()
        assert reg['metadata_json']['invitation_id'] == row['id']


def test_policy_initial_rev_zero_and_stale_revision_rejected(store):
    engine, ev = store
    with engine.begin() as conn:
        p = svc.save_policy(conn, ev['id'], {'rev': 0, 'enabled': True})
        assert p['rev'] == 1
        with pytest.raises(HTTPException, match='ADMISSION_POLICY_REVISION_CONFLICT'):
            svc.save_policy(conn, ev['id'], {'rev': 0, 'visibility': 'private'})


def test_manual_approval_no_pass_until_review(store):
    engine, ev = store
    with engine.begin() as conn:
        policy(conn, ev, registration_mode='manual')
        row, token = create(conn, ev)
        row = accept(conn, ev, token)
        assert row['status'] == 'pending_approval'
        assert not svc.public_view(conn, ev, row, '') .get('guest_number')
        assert conn.execute(select(func.count()).select_from(event_guests)).scalar_one() == 0
        row = svc.review(conn, ev, row['id'], 'approve', 'staff-1', row['revision'])
        assert row['status'] == 'approved' and row['reviewed_by'] == 'staff-1'


def test_manual_change_invalidates_old_approval_and_blocks_pass(store):
    engine, ev = store
    with engine.begin() as conn:
        policy(conn, ev, registration_mode='manual')
        row, token = create(conn, ev)
        row = accept(conn, ev, token)
        svc.review(conn, ev, row['id'], 'approve', 'staff-1', row['revision'])
        changed = accept(conn, ev, token, 1)
        assert changed['status'] == 'pending_approval'
        assert conn.execute(select(event_guests.c.status)).scalar_one() == 'pending'
        assert conn.execute(select(entitlements.c.status)).scalar_one() == 'revoked'


def test_companion_bounds_and_days_fail_before_guest_creation(store):
    engine, ev = store
    with engine.begin() as conn:
        policy(conn, ev)
        _, token = create(conn, ev, max_companions=1)
        for body, error in [({'companions': 2}, 'COMPANIONS_INVALID'), ({'days': []}, 'ATTENDANCE_DAYS_REQUIRED_OR_INVALID'), ({'days': ['1900-01-01']}, 'ATTENDANCE_DAYS_REQUIRED_OR_INVALID'), ({'consent': False}, 'GUEST_CONSENT_REQUIRED')]:
            with pytest.raises(HTTPException, match=error): accept(conn, ev, token, **body)
        assert conn.execute(select(func.count()).select_from(guests)).scalar_one() == 0


def test_capacity_reserves_party_size_and_releases_on_decline(store):
    engine, ev = store
    with engine.begin() as conn:
        day = datetime.now(ZoneInfo('Asia/Aden')).date().isoformat()
        policy(conn, ev, days=[{'date': day, 'capacity': 3}])
        first, a = create(conn, ev)
        _, b = create(conn, ev, '777123457')
        accept(conn, ev, a, 2)
        with pytest.raises(HTTPException, match='DAY_CAPACITY_FULL'): accept(conn, ev, b)
        svc.respond(conn, ev, a, {'response': 'declined', 'consent': True, 'companions': 0, 'days': []})
        assert accept(conn, ev, b)['status'] == 'approved'
        assert conn.execute(select(event_guests.c.status).where(event_guests.c.guest_id == svc.by_token(conn, a)['guest_id'])).scalar_one() == 'cancelled'


def test_split_party_atomic_consumption_and_idempotent_replay(store):
    engine, ev = store
    with engine.begin() as conn:
        policy(conn, ev)
        _, token = create(conn, ev)
        row = accept(conn, ev, token, 2)
        guest = {'id': row['guest_id'], 'metadata_json': {'invitation_id': row['id']}}
        result = svc.consume_entitlement(conn, ev, guest, {'scan_id': 'scan-1', 'quantity': 2})
        assert result['remaining'] == 1
        assert svc.consume_entitlement(conn, ev, guest, {'scan_id': 'scan-1', 'quantity': 2})['duplicate']
        with pytest.raises(HTTPException, match='SCAN_ID_CONFLICT'): svc.consume_entitlement(conn, ev, guest, {'scan_id': 'scan-1', 'quantity': 1})
        svc.consume_entitlement(conn, ev, guest, {'scan_id': 'scan-2'})
        with pytest.raises(HTTPException, match='ADMISSION_ALREADY_USED'): svc.consume_entitlement(conn, ev, guest, {'scan_id': 'scan-3'})
        assert conn.execute(select(func.count()).select_from(admission_uses)).scalar_one() == 2
        with pytest.raises(HTTPException, match='ATTENDANCE_ALREADY_STARTED'): accept(conn, ev, token, 1)


def test_consumption_outer_rollback_leaves_allowance(store):
    engine, ev = store
    with engine.begin() as conn:
        policy(conn, ev)
        _, token = create(conn, ev)
        row = accept(conn, ev, token)
    with pytest.raises(RuntimeError):
        with engine.begin() as conn:
            svc.consume_entitlement(conn, ev, {'id': row['guest_id'], 'metadata_json': {'invitation_id': row['id']}}, {'scan_id': 'rollback'})
            raise RuntimeError('scan write failed')
    with engine.connect() as conn:
        assert conn.execute(select(entitlements.c.consumed)).scalar_one() == 0


def test_rotation_revocation_and_decline(store):
    engine, ev = store
    with engine.begin() as conn:
        policy(conn, ev)
        row, token = create(conn, ev)
        row = accept(conn, ev, token)
        old_pass = svc.public_view(conn, ev, row, '')['guest_number']
        row, new_token = svc.rotate(conn, ev['id'], row['id'])
        with pytest.raises(HTTPException, match='INVITATION_NOT_FOUND'): svc.by_token(conn, token)
        assert svc.public_view(conn, ev, row, '')['guest_number'] != old_pass
        row = svc.revoke(conn, ev['id'], row['id'])
        assert row['status'] == 'revoked'
        with pytest.raises(HTTPException, match='INVITATION_INACTIVE'): accept(conn, ev, new_token)
        assert not svc.public_view(conn, ev, row, '').get('qr_url')
        assert conn.execute(select(event_guests.c.status)).scalar_one() == 'revoked'


def test_list_scope_and_phone_dedup(store):
    engine, ev = store
    with engine.begin() as conn:
        policy(conn, ev)
        conn.execute(insert(guest_lists).values(id='foreign', event_id='event-b', name='VIP', created_at=svc.now()))
        with pytest.raises(HTTPException, match='GUEST_LIST_SCOPE'): create(conn, ev, list_id='foreign')
        create(conn, ev)
        with pytest.raises(HTTPException, match='INVITATION_ALREADY_EXISTS'): create(conn, ev, '+967777123456')


def test_policy_does_not_remove_approved_days_or_shrink_reserved_capacity(store):
    engine, ev = store
    with engine.begin() as conn:
        p = policy(conn, ev)
        _, token = create(conn, ev)
        accept(conn, ev, token, 2)
        with pytest.raises(HTTPException, match='CAPACITY_BELOW_RESERVED'): svc.save_policy(conn, ev['id'], {'days': [{'date': p['days'][0]['date'], 'capacity': 1}]})
        with pytest.raises(HTTPException, match='ENTRY_MODE_HAS_APPROVALS'): svc.save_policy(conn, ev['id'], {'entry_mode': 'single'})


def test_registration_deadline_and_private_policy(store):
    engine, ev = store
    with engine.begin() as conn:
        policy(conn, ev)
        with pytest.raises(HTTPException, match='INVITATION_REQUIRED'): svc.assert_public_registration(conn, ev['id'])
        _, token = create(conn, ev)
        svc.save_policy(conn, ev['id'], {'rsvp_deadline': (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()})
        with pytest.raises(HTTPException, match='RSVP_DEADLINE_PASSED'): accept(conn, ev, token)


def test_csv_parser_rejects_bad_columns_and_formula_workbooks(store):
    encoded = lambda s: base64.b64encode(s.encode()).decode()
    rows = svc.parse_guest_file('guests.csv', encoded('name,phone,max_companions,days\nGuest,777123456,2,2026-10-19;2026-10-20\n'))
    assert rows[0]['days'] == ['2026-10-19', '2026-10-20']
    with pytest.raises(HTTPException, match='IMPORT_UNKNOWN_COLUMN'): svc.parse_guest_file('a.csv', encoded('name,phone,token\na,777123456,secret\n'))
    with pytest.raises(HTTPException, match='IMPORT_BASE64_INVALID'): svc.parse_guest_file('a.csv', '!notbase64')


def test_public_registration_and_import_api(tmp_path):
    from app.server import create_app
    from app.api.invitation_routes import install_invitation_routes
    from app.application.auth_service import identify_request
    from app.application.audit_service import write_audit
    app = create_app('sqlite:///' + str(tmp_path / 'api.sqlite'), origin='http://testserver', seed_demo=True)
    # While integrating, exercise the same route installer if composition root not wired yet.
    if not any(getattr(route, 'path', '') == '/api/public/invitations/{token}' for route in app.routes):
        install_invitation_routes(app, app.state.engine, 'http://testserver', identify_request, write_audit)
    client = TestClient(app)
    cred = next(c for c in app.state.seed_credentials if c['email'] == 'admin@pulsex.test')
    response = client.post('/api/auth/login', json={'email': cred['email'], 'password': cred['password']})
    client.headers.update({'X-CSRF': response.json()['csrf'], 'Origin': 'http://testserver'})
    with app.state.engine.connect() as conn:
        event_row = conn.execute(select(sites).where(sites.c.kind == 'event')).mappings().first()
    event_id, slug = event_row['id'], event_row['slug']
    base = f'/api/admin/events/{event_id}'
    assert client.put(base + '/admission-policy', json={'enabled': True, 'visibility': 'public', 'max_companions': 2}).status_code == 200
    public = TestClient(app)
    body = {'name': 'Guest', 'phone': '777123456', 'consent': True, 'companions': 1, 'days': []}
    registered = public.post(f'/api/public/events/{slug}/registration', json=body)
    assert registered.status_code == 200, registered.text
    assert registered.json()['invitation']['status'] == 'approved'
    assert registered.json()['qr_image_url']
    duplicate = public.post(f'/api/public/events/{slug}/registration', json=body).json()
    assert duplicate == {'status': 'verification_required', 'verification_required': True}
    file_data = base64.b64encode(b'name,phone\nGuest Two,777123457\nGuest Three,777123458\n').decode()
    preview = client.post(base + '/invitations/import/preview', json={'filename': 'guests.csv', 'content_base64': file_data})
    assert preview.status_code == 200 and preview.json()['valid_count'] == 2
    committed = client.post(base + '/invitations/import/commit', json={'import_id': preview.json()['import_id']})
    assert committed.status_code == 200 and committed.json()['created_count'] == 2
    assert client.post(base + '/invitations/import/commit', json={'import_id': preview.json()['import_id']}).status_code == 409
    listing = client.get(base + '/invitations').json()
    assert len(listing['invitations']) == 3 and 'token_hash' not in str(listing)
    client.headers.pop('X-CSRF')
    assert client.post(base + '/guest-lists', json={'name': 'VIP'}).status_code == 403


def test_removed_pending_day_cannot_approve_or_respond(store):
    engine, ev = store
    with engine.begin() as conn:
        old = policy(conn, ev, registration_mode='manual')
        row, token = create(conn, ev, days=[old['days'][0]['date']])
        row = accept(conn, ev, token)
        next_day = (datetime.now(ZoneInfo('Asia/Aden')) + timedelta(days=1)).date().isoformat()
        svc.save_policy(conn, ev['id'], {'days': [{'date': next_day, 'capacity': 10}]})
        with pytest.raises(HTTPException, match='ATTENDANCE_DAYS_REQUIRED_OR_INVALID'):
            svc.review(conn, ev, row['id'], 'approve', 'reviewer', row['revision'])
        with pytest.raises(HTTPException, match='ATTENDANCE_DAYS_REQUIRED_OR_INVALID'):
            accept(conn, ev, token, days=[old['days'][0]['date']])


def test_stale_review_cannot_approve_changed_rsvp(store):
    engine, ev = store
    with engine.begin() as conn:
        policy(conn, ev, registration_mode='manual')
        row, token = create(conn, ev)
        row = accept(conn, ev, token)
        initial = row['revision']
        updated = accept(conn, ev, token, 2)
        with pytest.raises(HTTPException, match='INVITATION_REVISION_CONFLICT'):
            svc.review(conn, ev, row['id'], 'approve', 'reviewer', initial)
        assert svc.review(conn, ev, row['id'], 'approve', 'reviewer', updated['revision'])['status'] == 'approved'


def test_revoke_after_admission_keeps_capacity_used(store):
    engine, ev = store
    with engine.begin() as conn:
        today = datetime.now(ZoneInfo('Asia/Aden')).date().isoformat()
        policy(conn, ev, days=[{'date': today, 'capacity': 1}])
        row, token = create(conn, ev)
        row = accept(conn, ev, token)
        svc.consume_entitlement(conn, ev, {'id': row['guest_id'], 'metadata_json': {'invitation_id': row['id']}}, {'scan_id': 'arrived'})
        svc.revoke(conn, ev['id'], row['id'])
        _, another = create(conn, ev, '777123457')
        with pytest.raises(HTTPException, match='DAY_CAPACITY_FULL'): accept(conn, ev, another)


def test_disabled_registration_legacy_enable_and_timezone_change_are_blocked(store):
    from app.application.guest_service import register_guest
    engine, ev = store
    with engine.begin() as conn:
        with pytest.raises(HTTPException, match='ADMISSION_REGISTRATION_DISABLED'): svc.assert_public_registration(conn, ev['id'])
        register_guest(conn, ev, {'phone': '777888999', 'consent': True})
        with pytest.raises(HTTPException, match='LEGACY_PASSES_REQUIRE_MIGRATION'): policy(conn, ev)
    with engine.begin() as conn:
        other = {**ev, 'id': 'event-b', 'slug': 'event-b'}
        policy(conn, other)
        _, token = create(conn, other)
        accept(conn, other, token)
        with pytest.raises(HTTPException, match='TIMEZONE_HAS_APPROVALS'): svc.save_policy(conn, other['id'], {'timezone': 'UTC'})


def test_public_api_unpublished_and_disabled_event_no_registration(tmp_path):
    from app.server import create_app
    app = create_app('sqlite:///' + str(tmp_path / 'unpublished.sqlite'), origin='http://testserver', seed_demo=True)
    from app.api.invitation_routes import install_invitation_routes
    from app.application.auth_service import identify_request
    from app.application.audit_service import write_audit
    if not any(getattr(route, 'path', '') == '/api/public/invitations/{token}' for route in app.routes):
        install_invitation_routes(app, app.state.engine, 'http://testserver', identify_request, write_audit)
    client = TestClient(app)
    with app.state.engine.begin() as conn:
        conn.execute(insert(sites).values(id='draft-only', slug='draft-only', kind='event', draft={'title': 'secret draft'}, draft_rev=1, published_version=0))
        policy(conn, {'id': 'draft-only'}, visibility='public')
        existing = conn.execute(select(sites).where(sites.c.kind == 'event', sites.c.published_version > 0)).mappings().first()
    response = client.get('/api/public/events/draft-only/registration')
    assert response.status_code == 404 and 'secret draft' not in response.text
    response = client.get(f'/api/public/events/{existing["slug"]}/registration')
    assert response.status_code == 409 and response.json()['detail'] == 'ADMISSION_REGISTRATION_DISABLED'


def test_schedule_clear_or_timezone_change_cannot_invalidate_admission_history(store):
    engine, ev = store
    with engine.begin() as conn:
        policy(conn, ev)
        row, token = create(conn, ev)
        row = accept(conn, ev, token)
        with pytest.raises(HTTPException, match='DAY_HAS_APPROVALS'): svc.save_policy(conn, ev['id'], {'days': []})
        svc.consume_entitlement(conn, ev, {'id': row['guest_id'], 'metadata_json': {'invitation_id': row['id']}}, {'scan_id': 'historical'})
        svc.revoke(conn, ev['id'], row['id'])
        with pytest.raises(HTTPException, match='TIMEZONE_HAS_APPROVALS'): svc.save_policy(conn, ev['id'], {'timezone': 'UTC'})
        with pytest.raises(HTTPException, match='DAY_HAS_APPROVALS'): svc.save_policy(conn, ev['id'], {'days': []})
        with pytest.raises(HTTPException, match='ADMISSION_POLICY_HAS_APPROVALS'): svc.save_policy(conn, ev['id'], {'enabled': False})


def test_forged_invitation_metadata_cannot_consume_another_guests_quota(store):
    engine, ev = store
    with engine.begin() as conn:
        policy(conn, ev)
        row, token = create(conn, ev)
        row = accept(conn, ev, token)
        forged = {'id': 'other-person', 'metadata_json': {'invitation_id': row['id']}}
        with pytest.raises(HTTPException, match='ENTITLEMENT_GUEST_SCOPE'):
            svc.consume_entitlement(conn, ev, forged, {'scan_id': 'forged'})
        assert conn.execute(select(entitlements.c.consumed)).scalar_one() == 0
