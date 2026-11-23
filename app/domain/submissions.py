"""Visitor submission rules (visits, surveys, polls, feedback, contact, ads).

Each submission is validated against the exact published version the visitor
saw; polls must still match the live version so a changed ballot cannot be
counted against new options.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime

from app.domain.errors import Conflict, Forbidden, NotFound, fail
from app.domain.site_config import DEFAULT_RATING_CRITERIA
from app.domain.surveys import answer_value
from app.domain.values import boolean, number, text

KINDS = ('visit', 'survey', 'poll', 'feedback', 'profile', 'follow', 'ad_view', 'ad_click')
SOURCES = ('web', 'qr', 'kiosk')
FEEDBACK_TARGET_KINDS = ('participant', 'sponsor', 'session', 'place', 'service')
POLL_SHAPE_FIELDS = ('qtype', 'options', 'min', 'max', 'rows')
CONTACT_CHANNELS = ('any', 'phone', 'email', 'whatsapp')
MAX_BATCH = 50  # items per offline collection batch


def require_batch(entries) -> None:
    """An offline batch is a non-empty list of at most MAX_BATCH items."""
    if not isinstance(entries, list) or not entries or len(entries) > MAX_BATCH:
        fail('BATCH_1_TO_50_ITEMS')


def require_submission_object(body) -> None:
    if not isinstance(body, dict):
        fail('SUBMISSION_OBJECT_REQUIRED')


def is_replay(previous: dict | None, fingerprint: str) -> bool:
    """True for an exact retry of a stored submission; the same id with another body is a conflict."""
    if not previous:
        return False
    if previous['fingerprint'] != fingerprint:
        fail('IDEMPOTENCY_BODY_CONFLICT', Conflict)
    return True


def same_submission(previous: dict | None, fingerprint: str) -> bool:
    """Non-raising variant used after a concurrent insert collided with this id."""
    return bool(previous) and previous['fingerprint'] == fingerprint


def feedback_targets_other_site(site: dict, scope: str) -> bool:
    """Feedback aimed at neither the visited page nor its event needs the target site looked up."""
    return scope not in (site['id'], site['event_id'])


def require_feedback_scope(site: dict, target_site: dict) -> None:
    """Visitors may rate only published agency pages of the same event."""
    if (target_site['kind'] != 'agency' or target_site['event_id'] != site['event_id']
            or not target_site['published_version']):
        fail('FEEDBACK_SCOPE', Forbidden)


def require_feedback_target(config: dict, code: str) -> None:
    """A non-general target code must name a rateable record of the target page."""
    if code != 'general' and not has_feedback_target(config, code):
        fail('FEEDBACK_TARGET', NotFound)


def require_identifiers(body) -> None:
    if not isinstance(body, dict) or body.get('preview'):
        fail('PREVIEW_WRITES_FORBIDDEN')
    for key in ('id', 'visitor_id', 'session_id'):
        try:
            uuid.UUID(body.get(key, ''))
        except (ValueError, TypeError, AttributeError):
            fail('UUID_REQUIRED:' + key)


def published_version_number(body: dict) -> int:
    version = body.get('version')
    if type(version) is not int or version < 1:
        fail('VERSION_REQUIRED')
    return version


def kind_and_source(body: dict) -> tuple[str, str]:
    kind = body.get('kind')
    if kind not in KINDS:
        fail('COLLECTION_KIND')
    source = body.get('source')
    if source not in SOURCES:
        fail('SOURCE_INVALID')
    return kind, source


def _enabled_poll(config: dict, target: str):
    return next((record for record in config['records']
                 if record['code'] == target and record['kind'] == 'poll' and record['enabled']), None)


def poll_answer(seen_config: dict, live_config: dict, target: str, answer, current: datetime) -> dict:
    question = _enabled_poll(seen_config, target)
    live = _enabled_poll(live_config, target)
    if not question or not live:
        fail('POLL_NOT_FOUND', NotFound)
    for key in POLL_SHAPE_FIELDS:
        if question.get(key) != live.get(key):
            fail('POLL_CHANGED_REFRESH_REQUIRED', Conflict)
    if (live['status'] != 'open' or (live['start'] and current < datetime.fromisoformat(live['start']))
            or (live['end'] and current >= datetime.fromisoformat(live['end']))):
        fail('POLL_CLOSED', Conflict)
    return {'answer': answer_value({**question, 'required': True}, answer)}


def has_feedback_target(config: dict, code: str) -> bool:
    return any(record['code'] == code and record['kind'] in FEEDBACK_TARGET_KINDS for record in config['records'])


def _rating(value):
    rating = number(value, 0, 1, 5)
    if int(rating) != rating:
        fail('RATING_INTEGER')
    return rating


def feedback_payload(payload: dict, target_config: dict) -> dict:
    rating = payload.get('rating')
    rating = None if rating in (None, '') else _rating(rating)
    note = text(payload.get('note'), 2000)
    allowed = {item['key']: item for item in target_config.get('rating_criteria', DEFAULT_RATING_CRITERIA)}
    raw_criteria = payload.get('criteria') or {}
    if not isinstance(raw_criteria, dict):
        fail('RATING_CRITERIA_INVALID')
    criteria = {}
    for key, value in raw_criteria.items():
        if key not in allowed:
            fail('RATING_CRITERIA_INVALID')
        criteria[key] = int(_rating(value))
    if rating is None and not note and not criteria:
        fail('FEEDBACK_EMPTY')
    return {'rating': rating, 'note': note, 'criteria': criteria}


def feedback_rating_before_note(payload: dict) -> None:
    """Validate the overall rating first (keeps the historical error precedence)."""
    rating = payload.get('rating')
    if rating not in (None, ''):
        _rating(rating)
    text(payload.get('note'), 2000)


def contact_payload(payload: dict) -> dict:
    if not boolean(payload.get('consent')):
        fail('CONTACT_CONSENT_REQUIRED')
    clean = {
        'name': text(payload.get('name'), 120),
        'phone': text(payload.get('phone'), 40),
        'email': text(payload.get('email'), 200).lower(),
        'job': text(payload.get('job'), 120),
        'message': text(payload.get('message'), 2000),
        'preferred_channel': text(payload.get('preferred_channel') or 'any', 20),
    }
    if clean['email'] and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', clean['email']):
        fail('EMAIL_INVALID')
    if clean['phone'] and not re.fullmatch(r'[+0-9 ()-]{4,40}', clean['phone']):
        fail('PHONE_INVALID')
    if clean['preferred_channel'] not in CONTACT_CHANNELS:
        fail('CONTACT_CHANNEL_INVALID')
    clean.update(consent=True, marketing=boolean(payload.get('marketing')))
    if not any(clean[key] for key in ('name', 'phone', 'email', 'message')):
        fail('CONTACT_EMPTY')
    return clean


def ad_payload(config: dict, target: str) -> dict:
    if not any(record['code'] == target and record['kind'] == 'ad' for record in config['records']):
        fail('AD_NOT_FOUND', NotFound)
    return {'measurement': 'client_reported_not_verified_reach'}
