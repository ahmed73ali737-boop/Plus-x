from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
import re

from sqlalchemy import and_, or_, select

from app.core.security import digest
from app.core.serialization import canonical_json
from app.db import submissions, versions
from app.domain import answer_value, boolean, fail, now, number, stamp, survey_answers, text
from app.infrastructure.repository import get_site
from app.application.publishing import get_site_version


def validate_submission(conn, body: dict) -> dict:
    if not isinstance(body, dict) or body.get('preview'):
        fail('PREVIEW_WRITES_FORBIDDEN')
    for key in ('id', 'visitor_id', 'session_id'):
        try:
            uuid.UUID(body.get(key, ''))
        except (ValueError, TypeError, AttributeError):
            fail('UUID_REQUIRED:' + key)

    site = get_site(conn, text(body.get('site_id'), 64, True))
    version = body.get('version')
    if type(version) is not int or version < 1:
        fail('VERSION_REQUIRED')
    config = get_site_version(conn, site, version)['config']
    kind = body.get('kind')
    payload = body.get('payload') or {}
    target = text(body.get('target'), 150)
    if kind not in ('visit','survey','poll','feedback','profile','follow','ad_view','ad_click'):
        fail('COLLECTION_KIND')
    source = body.get('source')
    if source not in ('web','qr','kiosk'):
        fail('SOURCE_INVALID')

    clean = {}
    dedup = None
    if kind == 'survey':
        clean = {'answers': survey_answers(config, target, payload.get('answers'))}
    elif kind == 'poll':
        question = next((q for q in config['records'] if q['code'] == target and q['kind'] == 'poll' and q['enabled']), None)
        current = get_site_version(conn, site)['config']
        live = next((x for x in current['records'] if x['code'] == target and x['kind'] == 'poll' and x['enabled']), None)
        if not question or not live:
            fail('POLL_NOT_FOUND', 404)
        for key in ('qtype', 'options', 'min', 'max', 'rows'):
            if question.get(key) != live.get(key):
                fail('POLL_CHANGED_REFRESH_REQUIRED', 409)
        current_time = datetime.now(timezone.utc)
        if live['status'] != 'open' or (live['start'] and current_time < datetime.fromisoformat(live['start'])) or (live['end'] and current_time >= datetime.fromisoformat(live['end'])):
            fail('POLL_CLOSED', 409)
        value = answer_value({**question, 'required': True}, payload.get('answer'))
        clean = {'answer': value}
        dedup = f"poll:{site['id']}:{target}:{body['visitor_id']}"
    elif kind == 'feedback':
        scope, _, code = target.partition(':')
        if scope not in (site['id'], site['event_id']):
            target_site = get_site(conn, scope)
            if target_site['kind'] != 'agency' or target_site['event_id'] != site['event_id'] or not target_site['published_version']:
                fail('FEEDBACK_SCOPE', 403)
        if code != 'general':
            parent = get_site(conn, scope)
            target_version = get_site_version(conn, parent)['config']
            if not any(x['code'] == code and x['kind'] in ('participant','sponsor','session','place','service') for x in target_version['records']):
                fail('FEEDBACK_TARGET', 404)
        rating = payload.get('rating')
        if rating in (None, ''):
            rating = None
        else:
            rating = number(rating, 0, 1, 5)
            if int(rating) != rating:
                fail('RATING_INTEGER')
        note = text(payload.get('note'), 2000)
        target_site = get_site(conn, scope)
        target_config = get_site_version(conn, target_site, version if scope == site['id'] else None)['config'] if scope == site['id'] else get_site_version(conn, target_site)['config']
        allowed = {x['key']: x for x in target_config.get('rating_criteria', [{'key':'overall','label':'التقييم العام','weight':100}])}
        raw_criteria = payload.get('criteria') or {}
        if not isinstance(raw_criteria, dict):
            fail('RATING_CRITERIA_INVALID')
        criteria = {}
        for key, value in raw_criteria.items():
            if key not in allowed:
                fail('RATING_CRITERIA_INVALID')
            numeric = number(value, 0, 1, 5)
            if int(numeric) != numeric:
                fail('RATING_INTEGER')
            criteria[key] = int(numeric)
        if rating is None and not note and not criteria:
            fail('FEEDBACK_EMPTY')
        clean = {'rating': rating, 'note': note, 'criteria': criteria}
    elif kind in ('profile', 'follow'):
        if not boolean(payload.get('consent')):
            fail('CONTACT_CONSENT_REQUIRED')
        clean = {
            'name': text(payload.get('name'),120),
            'phone': text(payload.get('phone'),40),
            'email': text(payload.get('email'),200).lower(),
            'job': text(payload.get('job'),120),
            'message': text(payload.get('message'),2000),
            'preferred_channel': text(payload.get('preferred_channel') or 'any',20),
        }
        if clean['email'] and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',clean['email']): fail('EMAIL_INVALID')
        if clean['phone'] and not re.fullmatch(r'[+0-9 ()-]{4,40}',clean['phone']): fail('PHONE_INVALID')
        if clean['preferred_channel'] not in ('any','phone','email','whatsapp'): fail('CONTACT_CHANNEL_INVALID')
        clean.update(consent=True, marketing=boolean(payload.get('marketing')))
        if not any(clean[key] for key in ('name','phone','email','message')):
            fail('CONTACT_EMPTY')
    elif kind in ('ad_view', 'ad_click'):
        if not any(x['code'] == target and x['kind'] == 'ad' for x in config['records']):
            fail('AD_NOT_FOUND', 404)
        clean = {'measurement': 'client_reported_not_verified_reach'}
        dedup = f"{kind}:{site['id']}:{version}:{target}:{body['session_id']}"

    return {
        'id': body['id'], 'site_id': site['id'], 'event_id': site['event_id'], 'version': version,
        'kind': kind, 'visitor_id': body['visitor_id'], 'session_id': body['session_id'], 'source': source,
        'target': target, 'payload': clean, 'client_time': stamp(body.get('client_time')),
        'received_at': now(), 'fingerprint': digest(canonical_json(body)), 'dedup_key': dedup,
    }


def build_metrics(conn, site, aggregate=False) -> dict:
    stmt = select(submissions)
    if aggregate and site['kind'] == 'event':
        stmt = stmt.where(submissions.c.event_id == site['id'])
    elif aggregate and site['kind'] == 'platform':
        pass
    else:
        stmt = stmt.where(or_(submissions.c.site_id == site['id'], and_(submissions.c.kind == 'feedback', submissions.c.target.like(site['id'] + ':%'))))
    entries = conn.execute(stmt).mappings().all()
    counts = Counter(r['kind'] for r in entries)
    visits = [r for r in entries if r['kind'] == 'visit']
    version_map = {(r['site_id'], r['version']): r['config'] for r in conn.execute(select(versions)).mappings()}
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
            values = [f'{x} / rank {i+1}' for i, x in enumerate(value)] if question and question.get('qtype') == 'ranking' else value if isinstance(value, list) else [value]
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
