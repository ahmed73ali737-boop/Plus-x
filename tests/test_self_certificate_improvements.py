"""V3 acceptance: an export owns immutable request-time values, never a live query."""
import csv
from io import StringIO
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select, update, delete, insert, func
from sqlalchemy.exc import DBAPIError
from tests.test_self_certificate_http import system, A, new_link, prepare, submit
from app.self_certificates_db import exports, requests, assets, browser_sessions
from app.application import self_certificate_exports as exporter


def rows(staff, ident):
    response = staff.get(A+'/exports/'+ident+'/download')
    assert response.status_code == 200, response.text
    return list(csv.reader(StringIO(response.content.decode('utf-8-sig'))))


def accepted(app, link, name='اسم قبل اللقطة'):
    browser, token, prepared = prepare(app, link)
    assert submit(browser, token, prepared, name=name).status_code == 202
    return browser, token


def test_export_freezes_membership_and_status_at_acceptance_before_worker(system):
    app, client = system
    staff = client()
    link, _ = new_link(staff)
    accepted(app, link)
    job = staff.post(A+'/exports', json={'format':'csv'}).json()
    assert app.state.self_certificate_runtime.generate()
    accepted(app, link, 'اسم بعد اللقطة')
    assert app.state.self_certificate_runtime.export()
    data = rows(staff, job['id'])
    assert len(data) == 2
    assert data[1][1] == 'اسم قبل اللقطة'
    assert data[1][6] == 'مسجل'
    listing = staff.get(A+'/exports').json()['items'][0]
    assert listing['expected_rows'] == 1
    assert listing['snapshot_taken_at'] == listing['cutoff']


def test_export_idempotency_returns_same_snapshot_and_rejects_changed_input(system):
    app, client = system
    staff = client()
    link, _ = new_link(staff)
    accepted(app, link)
    body = {'format':'csv', 'idempotency_key':'export-operation-00000001'}
    first = staff.post(A+'/exports', json=body)
    assert first.status_code == 200, first.text
    accepted(app, link, 'طلب أحدث')
    second = staff.post(A+'/exports', json=body)
    assert second.status_code == 200 and second.json()['id'] == first.json()['id']
    assert second.json()['expected_rows'] == 1
    changed = staff.post(A+'/exports', json={**body,'format':'xlsx'})
    assert changed.status_code == 409
    other = client('self-b').post(A+'/exports', json=body)
    assert other.status_code == 200 and other.json()['id'] != first.json()['id']
    assert other.json()['expected_rows'] == 0


def test_export_retry_does_not_recapture_rows_or_updated_statuses(system, monkeypatch):
    app, client = system
    staff = client()
    link, _ = new_link(staff)
    accepted(app, link)
    job = staff.post(A+'/exports', json={'format':'csv'}).json()
    store = app.state.self_certificate_runtime.store
    original = store.put_file
    def unavailable(*_):
        raise OSError('synthetic temporary storage failure')
    monkeypatch.setattr(store, 'put_file', unavailable)
    assert app.state.self_certificate_runtime.export()
    accepted(app, link, 'بعد محاولة فاشلة')
    assert app.state.self_certificate_runtime.generate()
    with app.state.engine.begin() as conn:
        conn.execute(update(exports).where(exports.c.id==job['id']).values(lease_until='2000-01-01T00:00:00+00:00'))
    monkeypatch.setattr(store, 'put_file', original)
    assert app.state.self_certificate_runtime.export()
    data = rows(staff, job['id'])
    assert len(data) == 2 and data[1][6] == 'مسجل'
    with app.state.engine.connect() as conn:
        row = conn.execute(select(exports).where(exports.c.id==job['id'])).mappings().one()
    assert row['attempts'] == 2 and row['cutoff'] == job['snapshot_taken_at']


def test_export_membership_ignores_later_request_with_older_utc(system, monkeypatch):
    app, client = system
    staff = client()
    link, _ = new_link(staff)
    accepted(app, link)
    job = staff.post(A+'/exports', json={'format':'csv'}).json()
    from app.application import self_certificate_participants as people
    browser, token, prepared = prepare(app, link)
    monkeypatch.setattr(people, 'utc_now', lambda:'2020-01-01T00:00:00+00:00')
    assert submit(browser, token, prepared, name='طلب لاحق بتوقيت أقدم').status_code == 202
    assert app.state.self_certificate_runtime.export()
    assert len(rows(staff, job['id'])) == 2


def test_snapshot_rows_are_immutable_and_expire_without_originals(system, monkeypatch):
    app, client = system
    staff = client()
    link, _ = new_link(staff)
    accepted(app, link)
    job = staff.post(A+'/exports', json={'format':'csv'}).json()
    from app.self_certificates_db import export_snapshot_rows
    with app.state.engine.begin() as conn:
        with pytest.raises(DBAPIError), conn.begin_nested():
            conn.execute(update(export_snapshot_rows).where(export_snapshot_rows.c.export_id==job['id']).values(phone_original='changed'))
    assert app.state.self_certificate_runtime.export()
    real_datetime = exporter.datetime
    class Future(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return real_datetime.now(tz)+timedelta(days=8)
    monkeypatch.setattr(exporter, 'datetime', Future)
    assert app.state.self_certificate_runtime.expire_exports()['expired'] == 1
    with app.state.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(export_snapshot_rows)).scalar_one() == 0
        assert conn.execute(select(func.count()).select_from(requests)).scalar_one() == 1
    assert staff.get(A+'/exports/'+job['id']+'/download').status_code == 410


def test_uncommitted_older_transaction_is_outside_export_snapshot(system):
    app, client = system
    if app.state.engine.dialect.name != 'postgresql':
        pytest.skip('Requires independent PostgreSQL MVCC transactions')
    staff = client()
    link, _ = new_link(staff)
    accepted(app, link)
    with app.state.engine.begin() as conn:
        source = dict(conn.execute(select(requests)).mappings().one())
        conn.execute(insert(browser_sessions).values(id='late-browser',token_hash='f'*64,created_at=source['submitted_at_utc'],last_seen_at=source['submitted_at_utc']))
    with app.state.engine.connect() as pending:
        transaction = pending.begin()
        pending.execute(insert(requests).values(**{**source,'id':'older-uncommitted-request','browser_session_id':'late-browser','submitted_at_utc':'2000-01-01T00:00:00+00:00'}))
        job = staff.post(A+'/exports', json={'format':'csv'}).json()
        transaction.commit()
    assert app.state.self_certificate_runtime.export()
    assert len(rows(staff, job['id'])) == 2
