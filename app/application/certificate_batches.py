"""Bounded import previews and durable DB-backed issuance, one item/transaction.

No network I/O under a job lock. An interrupted transaction rolls back both its
claim and issue. Tokens are not persisted in job results; links can be rotated
through the scoped administration endpoint after issuance.
"""
import base64
import csv
from datetime import datetime, timedelta, timezone
import io
from app.application.ports import persistence
from app.domain import fail, now, text, stamp, number, NotFound, Conflict, DomainError
from app.xlsx_reader import parse_xlsx, Rejected
from app.application.audit_service import new_id, write_audit
from app.application import certificate_service as svc


def preview(tx, event_id, user_id, body):
    filename = text(body.get('filename'), 200, True).lower()
    encoded = body.get('content_base64')
    if not isinstance(encoded, str) or len(encoded) > 4*1024*1024: fail('IMPORT_FILE_LIMIT')
    try: raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError): fail('IMPORT_BASE64_INVALID')
    if len(raw) > 3*1024*1024: fail('IMPORT_FILE_LIMIT')
    try:
        if filename.endswith('.xlsx'):
            workbook = parse_xlsx(raw)['workbook']
            if len(workbook) != 1: fail('IMPORT_ONE_SHEET_REQUIRED')
            values = next(iter(workbook.values()))
        elif filename.endswith('.csv'): values = list(csv.reader(io.StringIO(raw.decode('utf-8-sig'))))
        else: fail('IMPORT_CSV_OR_XLSX_REQUIRED')
    except (Rejected, ValueError, KeyError, UnicodeDecodeError, csv.Error): fail('CERTIFICATE_IMPORT_INVALID')
    if not 2 <= len(values) <= 1001: fail('IMPORT_ROWS_1_TO_1000')
    headers = [str(v).strip() for v in values[0]]
    if not all(headers) or len(set(headers)) != len(headers) or len(headers) > 32: fail('CERTIFICATE_IMPORT_HEADERS')
    mapping = body.get('mapping')
    if mapping is None:
        return {'headers': headers, 'sample': values[1:4], 'total_count': len(values)-1}
    required = {'recipient_key', 'award_key', *svc.FIELDS[:3]}
    allowed = required | {'grade', 'training_hours'}
    if not isinstance(mapping, dict) or not required.issubset(mapping) or set(mapping) - allowed or any(v not in headers for v in mapping.values()):
        fail('CERTIFICATE_IMPORT_MAPPING')
    zone = svc.issue_timezone(body.get('timezone'))
    template_id = text(body.get('template_id'), 64, True)
    if not persistence.certificates.template(tx, event_id, template_id): fail('CERTIFICATE_TEMPLATE_NOT_FOUND', NotFound)
    rows, errors, seen = [], [], set()
    for index, value in enumerate(values[1:], 2):
        if not any(str(v).strip() for v in value): continue
        try:
            if len(value) > len(headers): fail('IMPORT_COLUMN_COUNT')
            record = dict(zip(headers, [*value, *['']*(len(headers)-len(value))]))
            mapped = {key: text(record[column], 80 if key=='award_key' else 160 if key=='recipient_key' else 250, key in required) for key, column in mapping.items()}
            pair = (mapped['recipient_key'], mapped['award_key'])
            if pair in seen: fail('CERTIFICATE_DUPLICATE_IN_FILE')
            seen.add(pair)
            if mapped.get('training_hours'): number(mapped['training_hours'], low=0, high=100000)
            if persistence.certificates.award_exists(tx, event_id, pair[0], pair[1]): fail('CERTIFICATE_ALREADY_ISSUED')
            rows.append({'template_id': template_id, 'recipient_key': pair[0], 'award_key': pair[1], 'timezone': zone,
                         'data': {key: mapped.get(key, '') for key in svc.FIELDS[:5]}})
        except DomainError as exc: errors.append({'row': index, 'error': exc.detail})
    if not rows and not errors: fail('IMPORT_ROWS_1_TO_1000')
    row = {'id': new_id(), 'event_id': event_id, 'user_id': user_id, 'rows': rows, 'errors': errors, 'created_at': now(), 'committed_at': None}
    persistence.certificates.add_import(tx, row)
    return {'import_id': row['id'], 'rows': rows, 'errors': errors, 'valid_count': len(rows)}


def commit(tx, event_id, user_id, body):
    row = persistence.certificates.lock_import(tx, body.get('import_id'), event_id, user_id)
    if not row: fail('IMPORT_PREVIEW_NOT_FOUND', NotFound)
    if row['committed_at']: return {'import_id': row['id'], 'queued_count': len(row['rows']), 'replayed': True}
    if row['errors'] or not row['rows']: fail('IMPORT_ERRORS_MUST_BE_FIXED', Conflict)
    if datetime.fromisoformat(row['created_at']) < datetime.now(timezone.utc)-timedelta(hours=1): fail('IMPORT_PREVIEW_EXPIRED', Conflict)
    available = stamp(body.get('available_at')) or now()
    # Canonicalize offsets so string ordering remains chronological across workers.
    available = datetime.fromisoformat(available).astimezone(timezone.utc).isoformat()
    if not persistence.certificates.mark_import_committed(tx, row['id'], now()): fail('IMPORT_ALREADY_COMMITTED', Conflict)
    for i, payload in enumerate(row['rows']):
        persistence.certificates.add_job(tx, {'id': new_id(), 'import_id': row['id'], 'event_id': event_id, 'user_id': user_id,
            'body': {**payload, 'request_key': row['id']+':'+str(i)}, 'state': 'pending', 'available_at': available, 'created_at': now()})
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
