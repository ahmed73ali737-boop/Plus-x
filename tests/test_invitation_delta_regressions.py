"""Incremental regression tests for invitation routes added after ced50485.

All records are synthetic. Routes must be installed by the real composition root.
"""
import base64
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select, update

from app.core.security import digest
from app.db import assignments, sessions, users, sites
from app.domain import now
from app.invitations_db import invitations, invitation_imports
from app.server import create_app


BASE = '/api/admin/events/event-demo'


@pytest.fixture
def api(tmp_path):
    app = create_app('sqlite:///' + str(tmp_path / 'delta.sqlite'), origin='http://testserver', seed_demo=True)
    with TestClient(app) as admin, TestClient(app) as public:
        credential = next(x for x in app.state.seed_credentials if x['email'] == 'admin@pulsex.test')
        response = admin.post('/api/auth/login', json={'email': credential['email'], 'password': credential['password']})
        assert response.status_code == 200, response.text
        admin.headers.update({'Origin': 'http://testserver', 'X-CSRF': response.json()['csrf']})
        result = admin.put(BASE + '/admission-policy', json={'enabled': True, 'visibility': 'public', 'registration_mode': 'manual'})
        assert result.status_code == 200, result.text
        yield app, admin, public


def crew(app, role):
    with app.state.engine.begin() as conn:
        conn.execute(insert(users).values(id='delta-crew', email='delta-crew@example.test', name='Synthetic crew', role='member', scope_id='event-demo', active=1, must_change_password=0, password_hash='unused'))
        conn.execute(insert(assignments).values(id='delta-shift', user_id='delta-crew', site_id='event-demo', role=role, status='active', created_at=now()))
        conn.execute(insert(sessions).values(token_hash=digest('delta-session'), user_id='delta-crew', csrf='delta-csrf', expires_at='2999-01-01T00:00:00+00:00'))
    client = TestClient(app, headers={'Origin': 'http://testserver', 'X-CSRF': 'delta-csrf'})
    client.cookies.set('px_session', 'delta-session')
    return client


def preview(admin, csv='name,phone\nSynthetic One,777881001\nSynthetic Two,777881002\n'):
    response = admin.post(BASE + '/invitations/import/preview', json={'filename': 'synthetic.csv', 'content_base64': base64.b64encode(csv.encode()).decode()})
    assert response.status_code == 200, response.text
    return response.json()


def test_import_preview_is_bound_to_creator_even_for_other_event_manager(api):
    app, admin, _ = api
    draft = preview(admin)
    with crew(app, 'event_manager') as other:
        response = other.post(BASE + '/invitations/import/commit', json={'import_id': draft['import_id']})
    assert response.status_code == 404 and response.json()['detail'] == 'IMPORT_PREVIEW_NOT_FOUND'
    with app.state.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(invitations)).scalar_one() == 0
        assert conn.execute(select(invitation_imports.c.state)).scalar_one() == 'preview'


def test_expired_import_cannot_create_any_invitation(api):
    app, admin, _ = api
    draft = preview(admin)
    with app.state.engine.begin() as conn:
        conn.execute(update(invitation_imports).values(created_at=(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()))
    response = admin.post(BASE + '/invitations/import/commit', json={'import_id': draft['import_id']})
    assert response.status_code == 409 and response.json()['detail'] == 'IMPORT_PREVIEW_EXPIRED'
    assert admin.get(BASE + '/invitations').json()['invitations'] == []


def test_import_conflict_after_preview_rolls_back_prior_rows_and_can_retry(api):
    app, admin, _ = api
    draft = preview(admin)
    conflict = admin.post(BASE + '/invitations', json={'name': 'Concurrent synthetic', 'phone': '777881002'})
    assert conflict.status_code == 200, conflict.text
    response = admin.post(BASE + '/invitations/import/commit', json={'import_id': draft['import_id']})
    assert response.status_code == 409 and response.json()['detail'] == 'INVITATION_ALREADY_EXISTS'
    with app.state.engine.begin() as conn:
        assert conn.execute(select(func.count()).select_from(invitations)).scalar_one() == 1
        assert conn.execute(select(invitation_imports.c.state)).scalar_one() == 'preview'
        conn.execute(invitations.delete())
    response = admin.post(BASE + '/invitations/import/commit', json={'import_id': draft['import_id']})
    assert response.status_code == 200 and response.json()['created_count'] == 2


@pytest.mark.parametrize('csv,error', [
    ('name,phone\nOne,777881001\nTwo,+967777881001\n', 'DUPLICATE_PHONE_IN_FILE'),
    ('name,phone\nInvalid,not-a-phone\n', 'PHONE_INVALID'),
])
def test_preview_with_row_errors_cannot_partially_commit(api, csv, error):
    _, admin, _ = api
    draft = preview(admin, csv)
    assert error in [row['error'] for row in draft['errors']]
    response = admin.post(BASE + '/invitations/import/commit', json={'import_id': draft['import_id']})
    assert response.status_code == 409 and response.json()['detail'] == 'IMPORT_ERRORS_MUST_BE_FIXED'
    assert admin.get(BASE + '/invitations').json()['invitations'] == []


def test_reception_cannot_self_approve_and_denied_request_rolls_back(api):
    app, admin, _ = api
    body = {'name': 'Synthetic onsite', 'phone': '777881003', 'consent': True, 'approve': True}
    with crew(app, 'reception') as reception:
        denied = reception.post(BASE + '/on-site-registration', json=body)
        assert denied.status_code == 403 and denied.json()['detail'] == 'FORBIDDEN_EVENT_PERMISSION'
        assert admin.get(BASE + '/invitations').json()['invitations'] == []
        accepted = reception.post(BASE + '/on-site-registration', json={**body, 'approve': False})
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()['invitation']['status'] == 'pending_approval'
        assert 'guest_number' not in accepted.json()


def test_scanner_directory_redacts_phone_and_forbids_export_and_policy_write(api):
    app, admin, public = api
    invite = admin.post(BASE + '/invitations', json={'name': 'Synthetic visitor', 'phone': '777881004'}).json()
    response = public.post('/api/public/invitations/' + invite['token'] + '/rsvp', json={'response': 'accepted', 'consent': True})
    assert response.status_code == 200, response.text
    pending = response.json()['invitation']
    assert admin.post(BASE + '/invitations/' + invite['invitation']['id'] + '/review', json={'decision': 'approve', 'revision': pending['revision']}).status_code == 200
    assert 'phone' in admin.get(BASE + '/guests').json()['guests'][0]
    with crew(app, 'scanner') as scanner:
        listing = scanner.get(BASE + '/guests')
        assert listing.status_code == 200 and listing.json()['guests']
        assert all('phone' not in row and 'phone_hash' not in row and 'pass_token_hash' not in row for row in listing.json()['guests'])
        assert scanner.get(BASE + '/guests/export').status_code == 403
        assert scanner.put(BASE + '/admission-policy', json={'visibility': 'public'}).status_code == 403


def test_invitation_public_projection_uses_published_config_not_secret_draft(api):
    app, admin, public = api
    invite = admin.post(BASE + '/invitations', json={'name': 'Synthetic visitor', 'phone': '777881005'}).json()
    with app.state.engine.begin() as conn:
        event = conn.execute(select(sites).where(sites.c.id == 'event-demo')).mappings().one()
        conn.execute(update(sites).where(sites.c.id == 'event-demo').values(draft={**event['draft'], 'title': 'UNPUBLISHED-SYNTHETIC-SECRET', 'description': 'PRIVATE-DRAFT-DESCRIPTION'}))
    for path in ('/api/public/invitations/' + invite['token'], '/api/public/events/demo/registration'):
        response = public.get(path)
        assert response.status_code == 200, response.text
        assert 'UNPUBLISHED-SYNTHETIC-SECRET' not in response.text and 'PRIVATE-DRAFT-DESCRIPTION' not in response.text
        assert response.json()['event']['title']


@pytest.mark.parametrize('field,offset,expected', [
    ('registration_opens_at', 60, 'REGISTRATION_NOT_OPEN'),
    ('registration_closes_at', -60, 'REGISTRATION_CLOSED'),
    ('rsvp_deadline', -60, 'RSVP_DEADLINE_PASSED'),
])
def test_registration_window_denial_leaves_no_invitation(api, field, offset, expected):
    _, admin, public = api
    timestamp = (datetime.now(timezone.utc) + timedelta(minutes=offset)).isoformat()
    assert admin.put(BASE + '/admission-policy', json={field: timestamp}).status_code == 200
    response = public.post('/api/public/events/demo/registration', json={'name': 'Synthetic visitor', 'phone': '777881006', 'consent': True})
    assert response.status_code == 409 and response.json()['detail'] == expected
    assert admin.get(BASE + '/invitations').json()['invitations'] == []


@pytest.mark.parametrize('site_id', ['event-demo', 'agency-01'])
@pytest.mark.parametrize('path', ['/api/access-request', '/api/signup-request'])
def test_private_event_blocks_public_access_and_signup_requests(api, site_id, path):
    _, admin, public = api
    assert admin.put(BASE + '/admission-policy', json={'visibility': 'private'}).status_code == 200
    response = public.post(path, json={'site_id': site_id, 'email': 'synthetic@example.test', 'name': 'Synthetic', 'requested_role': 'participant'})
    assert response.status_code == 404, response.text


@pytest.mark.parametrize('role', ['analyst', 'auditor'])
def test_analytics_assignment_can_read_metrics_without_site_editing(api, role):
    app, _, _ = api
    with crew(app, role) as reader:
        visible = reader.get('/api/admin/sites')
        assert visible.status_code == 200
        assert 'event-demo' in [s['id'] for s in visible.json()['sites']]
        assert reader.get('/api/admin/sites/event-demo/metrics').status_code == 200
        details = reader.get('/api/admin/sites/event-demo')
        assert details.status_code == 200 and details.json()['can_manage'] is False
        assert reader.put('/api/admin/sites/event-demo', json={'draft_rev': details.json()['draft_rev'], 'config': details.json()['draft']}).status_code == 403
        assert reader.post('/api/admin/sites/event-demo/publish', json={}).status_code == 403


@pytest.mark.parametrize('filename,content,expected', [
    ('bad.txt', b'name,phone\nOne,777881001\n', 'IMPORT_CSV_OR_XLSX_REQUIRED'),
    ('bad.csv', b'name,name,phone\nOne,Two,777881001\n', 'IMPORT_HEADERS_NAME_PHONE'),
    ('bad.csv', b'name,phone,token\nOne,777881001,secret\n', 'IMPORT_UNKNOWN_COLUMN'),
    ('bad.csv', b'name,phone\nOne,777881001,extra\n', 'IMPORT_COLUMN_COUNT'),
    ('bad.csv', b'name,phone\n', 'IMPORT_ROWS_1_TO_1000'),
    ('bad.csv', b'\xff\xfe', 'IMPORT_CSV_INVALID'),
    ('bad.xlsx', b'not-a-workbook', 'IMPORT_XLSX_INVALID'),
    ('bad.csv', b'name,phone\n' + b'One,777881001\n' * 1001, 'IMPORT_ROWS_1_TO_1000'),
])
def test_invitation_parser_rejects_unsafe_or_out_of_contract_files(filename, content, expected):
    from fastapi import HTTPException
    from app.application.invitation_service import parse_guest_file
    with pytest.raises(HTTPException) as exc:
        parse_guest_file(filename, base64.b64encode(content).decode())
    assert exc.value.status_code == 422 and exc.value.detail == expected



@pytest.mark.parametrize('site_id', ['event-demo', 'agency-01'])
def test_private_event_blocks_collection_before_writing_submission(api, site_id):
    import uuid
    from app.db import submissions
    app, admin, public = api
    assert admin.put(BASE + '/admission-policy', json={'visibility': 'private'}).status_code == 200
    item = {'id': str(uuid.uuid4()), 'site_id': site_id, 'version': 1,
            'kind': 'survey', 'source': 'web', 'target': 'main', 'payload': {},
            'visitor_id': str(uuid.uuid4()), 'session_id': str(uuid.uuid4()), 'client_time': now()}
    response = public.post('/api/collect', json={'items': [item]})
    assert response.status_code == 200
    assert response.json()['receipts'] == [{'id': item['id'], 'status': 'rejected', 'error': 'SITE_NOT_FOUND'}]
    with app.state.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(submissions).where(submissions.c.id == item['id'])).scalar_one() == 0


def invitation_workbook(*, formula=False, external=False, multiple=False):
    import io
    import zipfile
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    rel = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    sheet = f'<worksheet xmlns="{ns}"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>name</t></is></c><c r="B1" t="inlineStr"><is><t>phone</t></is></c></row><row r="2"><c r="A2" t="inlineStr">' + ('<f>1+1</f>' if formula else '') + '<is><t>Synthetic XLSX Guest</t></is></c><c r="B2" t="inlineStr"><is><t>777881007</t></is></c></row></sheetData></worksheet>'
    sheets = '<sheet name="Guests" sheetId="1" r:id="rId1"/>' + ('<sheet name="Extra" sheetId="2" r:id="rId1"/>' if multiple else '')
    target = 'Target="https://external.example.test/file.xml" TargetMode="External"' if external else 'Target="worksheets/sheet1.xml"'
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        z.writestr('_rels/.rels', f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml', f'<workbook xmlns="{ns}" xmlns:r="{rel}"><sheets>{sheets}</sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{rel}/worksheet" {target}/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml', sheet)
    return base64.b64encode(data.getvalue()).decode()


def test_valid_xlsx_invitation_preview_and_commit(api):
    _, admin, _ = api
    response = admin.post(BASE + '/invitations/import/preview', json={'filename': 'synthetic.xlsx', 'content_base64': invitation_workbook()})
    assert response.status_code == 200, response.text
    draft = response.json()
    assert draft['valid_count'] == 1 and draft['errors'] == []
    assert draft['rows'][0]['phone'] == '+967777881007'
    response = admin.post(BASE + '/invitations/import/commit', json={'import_id': draft['import_id']})
    assert response.status_code == 200 and response.json()['created_count'] == 1
    issued = response.json()['invitations'][0]
    assert issued['invitation']['status'] == 'invited' and issued['token']


@pytest.mark.parametrize('options,expected', [
    ({'formula': True}, 'IMPORT_XLSX_INVALID'),
    ({'external': True}, 'IMPORT_XLSX_INVALID'),
    ({'multiple': True}, 'IMPORT_ONE_SHEET_REQUIRED'),
])
def test_invitation_workbook_active_content_and_multiple_sheets_are_rejected(options, expected):
    from fastapi import HTTPException
    from app.application.invitation_service import parse_guest_file
    with pytest.raises(HTTPException) as exc:
        parse_guest_file('synthetic.xlsx', invitation_workbook(**options))
    assert exc.value.status_code == 422 and exc.value.detail == expected
