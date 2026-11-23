"""Bounded import previews and durable DB-backed issuance, one item/transaction.

No network I/O under a job lock. An interrupted transaction rolls back both its
claim and issue. Tokens are not persisted in job results; links can be rotated
through the scoped administration endpoint after issuance.
"""
import csv
import io
from datetime import datetime, timezone

from app.application import certificate_service as svc
from app.application.audit_service import new_id, write_audit
from app.application.ports import persistence
from app.domain import Conflict, DomainError, NotFound, fail, now, text
from app.domain import certificate_imports as imports
from app.domain.certificate_imports import IssuanceBatch
from app.xlsx_reader import Rejected, parse_xlsx


def _table(body):
    filename = text(body.get('filename'), 200, True).lower()
    raw = imports.decode_upload(body.get('content_base64'))
    try:
        if imports.table_kind(filename) == 'xlsx':
            workbook = parse_xlsx(raw)['workbook']
            if len(workbook) != 1:
                fail('IMPORT_ONE_SHEET_REQUIRED')
            return next(iter(workbook.values()))
        return list(csv.reader(io.StringIO(raw.decode('utf-8-sig'))))
    except (Rejected, ValueError, KeyError, UnicodeDecodeError, csv.Error):
        fail('CERTIFICATE_IMPORT_INVALID')


def preview(tx, event_id, user_id, body):
    values = _table(body)
    headers = imports.headers_of(values)
    mapping = body.get('mapping')
    if mapping is None:
        return {'headers': headers, 'sample': values[1:4], 'total_count': len(values) - 1}
    imports.check_mapping(mapping, headers)
    zone = svc.issue_timezone(body.get('timezone'))
    template_id = text(body.get('template_id'), 64, True)
    if not persistence.certificates.template(tx, event_id, template_id):
        fail('CERTIFICATE_TEMPLATE_NOT_FOUND', NotFound)
    rows, errors = imports.preview_rows(
        values, headers, mapping, template_id=template_id, timezone_name=zone,
        award_exists=lambda recipient, award: persistence.certificates.award_exists(tx, event_id, recipient, award))
    row = {'id': new_id(), 'event_id': event_id, 'user_id': user_id, 'rows': rows, 'errors': errors,
           'created_at': now(), 'committed_at': None}
    persistence.certificates.add_import(tx, row)
    return {'import_id': row['id'], 'rows': rows, 'errors': errors, 'valid_count': len(rows)}


def commit(tx, event_id, user_id, body):
    row = IssuanceBatch.require_found(persistence.certificates.lock_import(tx, body.get('import_id'), event_id, user_id))
    if IssuanceBatch.is_replay(row):
        return {'import_id': row['id'], 'queued_count': len(row['rows']), 'replayed': True}
    IssuanceBatch.require_committable(row, datetime.now(timezone.utc))
    available = IssuanceBatch.available_at(body.get('available_at'), now())
    if not persistence.certificates.mark_import_committed(tx, row['id'], now()):
        fail('IMPORT_ALREADY_COMMITTED', Conflict)
    for index, payload in enumerate(row['rows']):
        persistence.certificates.add_job(tx, {
            'id': new_id(), 'import_id': row['id'], 'event_id': event_id, 'user_id': user_id,
            'body': {**payload, 'request_key': IssuanceBatch.request_key(row['id'], index)},
            'state': 'pending', 'available_at': available, 'created_at': now()})
    return {'import_id': row['id'], 'queued_count': len(row['rows']), 'replayed': False}


def process_pending(engine, limit=25):
    """Issue queued certificates, one job per transaction (claim + issue commit together)."""
    from app.application.access import require_event_permission

    certificates = persistence.certificates
    processed = 0
    for _ in range(limit):
        with persistence.transactions.write(engine) as tx:
            job = certificates.next_pending_job(tx, now())
            if not job:
                break
            if not certificates.claim_job(tx, job['id']):
                continue
            try:
                user = persistence.identity.user(tx, job['user_id'])
                require_event_permission(tx, user, job['event_id'], 'certificates.issue')
                with persistence.transactions.savepoint(tx):
                    row, _, created = svc.issue(tx, job['event_id'], job['body'])
                certificates.finish_job(tx, job['id'], {'state': 'done', 'certificate_id': row['id']})
                if created:
                    write_audit(tx, user, job['event_id'], 'certificate_issued',
                                {'certificate_id': row['id'], 'import_id': job['import_id']})
            except DomainError as error:
                certificates.finish_job(tx, job['id'], {'state': 'failed', 'error': str(error.code)[:160]})
            processed += 1
    return processed


def progress(tx, event_id):
    return persistence.certificates.job_progress(tx, event_id)
