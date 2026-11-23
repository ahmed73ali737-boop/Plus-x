"""Collection use cases: accept visitor submissions and build site metrics."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone

from app.application.access import get_site
from app.application.event_visibility import event_id_for_site, require_public_event
from app.application.ports import persistence
from app.application.publishing import get_site_version
from app.core.security import digest
from app.core.serialization import canonical_json
from app.domain import Conflict, DomainError, Forbidden, NotFound, fail, now, stamp, survey_answers, text
from app.domain.submissions import (
    ad_payload,
    contact_payload,
    feedback_payload,
    feedback_rating_before_note,
    has_feedback_target,
    kind_and_source,
    poll_answer,
    published_version_number,
    require_identifiers,
)
from app.domain.surveys import ballot_items


def _feedback(tx, site, version, target, payload):
    scope, _, code = target.partition(':')
    if scope not in (site['id'], site['event_id']):
        target_site = get_site(tx, scope)
        if (target_site['kind'] != 'agency' or target_site['event_id'] != site['event_id']
                or not target_site['published_version']):
            fail('FEEDBACK_SCOPE', Forbidden)
    if code != 'general':
        parent = get_site(tx, scope)
        if not has_feedback_target(get_site_version(tx, parent)['config'], code):
            fail('FEEDBACK_TARGET', NotFound)
    feedback_rating_before_note(payload)
    target_site = get_site(tx, scope)
    # Feedback on the visited page is judged against the version the visitor saw.
    target_config = get_site_version(tx, target_site, version if scope == site['id'] else None)['config']
    return feedback_payload(payload, target_config)


def validate_submission(tx, body: dict) -> dict:
    require_identifiers(body)
    site = get_site(tx, text(body.get('site_id'), 64, True))
    version = published_version_number(body)
    config = get_site_version(tx, site, version)['config']
    kind, source = kind_and_source(body)
    payload = body.get('payload') or {}
    target = text(body.get('target'), 150)
    clean = {}
    dedup = None
    if kind == 'survey':
        clean = {'answers': survey_answers(config, target, payload.get('answers'))}
    elif kind == 'poll':
        live = get_site_version(tx, site)['config']
        clean = poll_answer(config, live, target, payload.get('answer'), datetime.now(timezone.utc))
        dedup = f"poll:{site['id']}:{target}:{body['visitor_id']}"
    elif kind == 'feedback':
        clean = _feedback(tx, site, version, target, payload)
    elif kind in ('profile', 'follow'):
        clean = contact_payload(payload)
    elif kind in ('ad_view', 'ad_click'):
        clean = ad_payload(config, target)
        dedup = f"{kind}:{site['id']}:{version}:{target}:{body['session_id']}"
    return {
        'id': body['id'], 'site_id': site['id'], 'event_id': site['event_id'], 'version': version,
        'kind': kind, 'visitor_id': body['visitor_id'], 'session_id': body['session_id'], 'source': source,
        'target': target, 'payload': clean, 'client_time': stamp(body.get('client_time')),
        'received_at': now(), 'fingerprint': digest(canonical_json(body)), 'dedup_key': dedup,
    }


def build_metrics(tx, site, aggregate=False) -> dict:
    entries = persistence.submissions.for_metrics(tx, site, aggregate)
    counts = Counter(r['kind'] for r in entries)
    visits = [r for r in entries if r['kind'] == 'visit']
    version_map = persistence.sites.version_configs(tx)
    per = Counter(r['site_id'] for r in visits)
    question_counts = defaultdict(Counter)
    ratings = defaultdict(list)
    criteria_ratings = defaultdict(lambda: defaultdict(list))
    text_answers = Counter()
    question_labels = {}

    for record in entries:
        answers = record['payload'].get('answers', {}) if record['kind'] == 'survey' else {record['target']: record['payload'].get('answer')} if record['kind'] == 'poll' else {}
        for key, value in answers.items():
            question_key = f"{record['site_id']} / v{record['version']} / {key}"
            source_config = version_map[(record['site_id'], record['version'])]
            question = next((x for x in source_config['records'] if x['code'] == key), None)
            if question:
                question_labels[question_key] = {'title': question['title'], 'type': question.get('qtype'), 'options': {o['key']: o['label'] for o in question.get('options', [])}}
            if question and question.get('qtype') in ('short_text', 'long_text'):
                text_answers[question_key] += 1
                continue
            values = ballot_items(question.get('qtype') if question else None, value)
            for item in values:
                question_counts[question_key][canonical_json(item) if isinstance(item, dict) else str(item)] += 1
        if record['kind'] == 'feedback':
            if record['payload'].get('rating') is not None:
                ratings[record['target']].append(record['payload']['rating'])
            for criterion, value in (record['payload'].get('criteria') or {}).items():
                criteria_ratings[record['target']][criterion].append(value)

    notes = []
    follow_requests = []
    for record in entries:
        note = text((record['payload'] or {}).get('note'), 2000) if record['kind'] == 'feedback' else ''
        if note:
            notes.append({'target':record['target'],'note':note,'rating':record['payload'].get('rating'),'criteria':record['payload'].get('criteria') or {},'received_at':record['received_at'],'site_id':record['site_id']})
        if record['kind'] == 'follow':
            payload = record['payload'] or {}
            follow_requests.append({
                'name': payload.get('name',''), 'phone': payload.get('phone',''), 'email': payload.get('email',''),
                'job': payload.get('job',''), 'message': payload.get('message',''),
                'preferred_channel': payload.get('preferred_channel','any'), 'marketing': bool(payload.get('marketing')),
                'received_at': record['received_at'], 'site_id': record['site_id']
            })
    notes = sorted(notes, key=lambda x: x['received_at'], reverse=True)[:100]
    follow_requests = sorted(follow_requests, key=lambda x: x['received_at'], reverse=True)[:100]

    return {
        'as_of': now(), 'counts': dict(counts), 'page_sessions': len(visits),
        'browser_ids_estimate': len({r['visitor_id'] for r in visits if r['source'] != 'kiosk'}),
        'kiosk_sessions': len({r['session_id'] for r in visits if r['source'] == 'kiosk'}),
        'verified_people': None, 'site_visits': dict(per),
        'questions': {k: dict(v) for k, v in question_counts.items()}, 'question_labels': question_labels,
        'text_answer_counts': dict(text_answers),
        'ratings': {k: {'count': len(v), 'average': round(sum(v)/len(v), 2)} for k, v in ratings.items()},
        'rating_criteria': {target: {criterion: {'count':len(values),'average':round(sum(values)/len(values),2)} for criterion, values in groups.items()} for target, groups in criteria_ratings.items()},
        'feedback_notes': notes, 'follow_requests': follow_requests,
        'notes': ['زيارات الجهات لا تُجمع باعتبارها أشخاصًا فريدين.','عدد الأجهزة/المتصفحات تقريبي، وبيانات المصدر معلنة من العميل.','المستلم فقط يدخل هذه النتائج؛ الطوابير غير المتصلة غير محسوبة بعد.'],
    }


MAX_BATCH = 50  # items per offline collection batch


def collect(database, entries) -> list[dict]:
    """Accept an offline batch; each item commits (or is rejected) on its own.

    Exact retries are idempotent: a repeated id with the same body is a
    duplicate, a repeated id with a different body is a conflict, and the
    one-vote dedup key turns a second ballot into a rejection.
    """
    if not isinstance(entries, list) or not entries or len(entries) > MAX_BATCH:
        fail('BATCH_1_TO_50_ITEMS')
    transactions = persistence.transactions
    receipts = []
    for body in entries:
        submission_id = body.get('id', '') if isinstance(body, dict) else ''
        try:
            with transactions.write(database) as tx:
                previous = persistence.submissions.get(tx, submission_id)
                if previous:
                    if previous['fingerprint'] != digest(canonical_json(body)):
                        fail('IDEMPOTENCY_BODY_CONFLICT', Conflict)
                    receipts.append({'id': submission_id, 'status': 'duplicate'})
                    continue
                if not isinstance(body, dict):
                    fail('SUBMISSION_OBJECT_REQUIRED')
                target = get_site(tx, body.get('site_id'))
                require_public_event(tx, event_id_for_site(tx, target))
                persistence.submissions.add(tx, validate_submission(tx, body))
                receipts.append({'id': submission_id, 'status': 'accepted'})
        except DomainError as error:
            receipts.append({'id': submission_id, 'status': 'rejected', 'error': error.code})
        except Exception as error:
            if not transactions.is_conflict(error):
                raise
            with transactions.read(database) as tx:
                previous = persistence.submissions.get(tx, submission_id)
            if previous and previous['fingerprint'] == digest(canonical_json(body)):
                receipts.append({'id': submission_id, 'status': 'duplicate'})
            else:
                receipts.append({'id': submission_id, 'status': 'rejected', 'error': 'ALREADY_VOTED_OR_RECORDED'})
    return receipts
