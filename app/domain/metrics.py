"""Site metrics: the aggregation of collected submissions into reportable figures."""
from __future__ import annotations

import json
from collections import Counter, defaultdict

from app.domain.surveys import ballot_items
from app.domain.values import text

NOTE_LIMIT = 100
METRICS_NOTES = [
    'زيارات الجهات لا تُجمع باعتبارها أشخاصًا فريدين.',
    'عدد الأجهزة/المتصفحات تقريبي، وبيانات المصدر معلنة من العميل.',
    'المستلم فقط يدخل هذه النتائج؛ الطوابير غير المتصلة غير محسوبة بعد.',
]


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _answers_of(record: dict) -> dict:
    if record['kind'] == 'survey':
        return record['payload'].get('answers', {})
    if record['kind'] == 'poll':
        return {record['target']: record['payload'].get('answer')}
    return {}


def _average(values) -> dict:
    return {'count': len(values), 'average': round(sum(values) / len(values), 2)}


def build_metrics(entries: list[dict], version_map: dict, as_of: str) -> dict:
    """Aggregate submissions; ``version_map`` maps (site_id, version) to the config the visitor saw."""
    counts = Counter(r['kind'] for r in entries)
    visits = [r for r in entries if r['kind'] == 'visit']
    per_site = Counter(r['site_id'] for r in visits)
    question_counts = defaultdict(Counter)
    ratings = defaultdict(list)
    criteria_ratings = defaultdict(lambda: defaultdict(list))
    text_answers = Counter()
    question_labels = {}

    for record in entries:
        for key, value in _answers_of(record).items():
            question_key = f"{record['site_id']} / v{record['version']} / {key}"
            source_config = version_map[(record['site_id'], record['version'])]
            question = next((x for x in source_config['records'] if x['code'] == key), None)
            if question:
                question_labels[question_key] = {
                    'title': question['title'], 'type': question.get('qtype'),
                    'options': {o['key']: o['label'] for o in question.get('options', [])}}
            if question and question.get('qtype') in ('short_text', 'long_text'):
                text_answers[question_key] += 1
                continue
            for item in ballot_items(question.get('qtype') if question else None, value):
                question_counts[question_key][_canonical(item) if isinstance(item, dict) else str(item)] += 1
        if record['kind'] == 'feedback':
            if record['payload'].get('rating') is not None:
                ratings[record['target']].append(record['payload']['rating'])
            for criterion, value in (record['payload'].get('criteria') or {}).items():
                criteria_ratings[record['target']][criterion].append(value)

    notes = []
    follow_requests = []
    for record in entries:
        payload = record['payload'] or {}
        note = text(payload.get('note'), 2000) if record['kind'] == 'feedback' else ''
        if note:
            notes.append({'target': record['target'], 'note': note, 'rating': payload.get('rating'),
                          'criteria': payload.get('criteria') or {}, 'received_at': record['received_at'],
                          'site_id': record['site_id']})
        if record['kind'] == 'follow':
            follow_requests.append({
                'name': payload.get('name', ''), 'phone': payload.get('phone', ''), 'email': payload.get('email', ''),
                'job': payload.get('job', ''), 'message': payload.get('message', ''),
                'preferred_channel': payload.get('preferred_channel', 'any'), 'marketing': bool(payload.get('marketing')),
                'received_at': record['received_at'], 'site_id': record['site_id']})
    newest_first = dict(key=lambda x: x['received_at'], reverse=True)
    return {
        'as_of': as_of, 'counts': dict(counts), 'page_sessions': len(visits),
        'browser_ids_estimate': len({r['visitor_id'] for r in visits if r['source'] != 'kiosk'}),
        'kiosk_sessions': len({r['session_id'] for r in visits if r['source'] == 'kiosk'}),
        'verified_people': None, 'site_visits': dict(per_site),
        'questions': {k: dict(v) for k, v in question_counts.items()}, 'question_labels': question_labels,
        'text_answer_counts': dict(text_answers),
        'ratings': {k: _average(v) for k, v in ratings.items()},
        'rating_criteria': {target: {criterion: _average(values) for criterion, values in groups.items()}
                            for target, groups in criteria_ratings.items()},
        'feedback_notes': sorted(notes, **newest_first)[:NOTE_LIMIT],
        'follow_requests': sorted(follow_requests, **newest_first)[:NOTE_LIMIT],
        'notes': list(METRICS_NOTES),
    }
