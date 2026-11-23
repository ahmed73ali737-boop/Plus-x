"""Collection use cases: accept visitor submissions and build site metrics."""
from __future__ import annotations

from datetime import datetime, timezone

from app.application.access import get_site
from app.application.event_visibility import event_id_for_site, require_public_event
from app.application.ports import persistence
from app.application.publishing import get_site_version
from app.core.security import digest
from app.core.serialization import canonical_json
from app.domain import DomainError, metrics, now, stamp, submissions, survey_answers, text
from app.domain.submissions import (
    ad_payload,
    contact_payload,
    feedback_payload,
    feedback_rating_before_note,
    kind_and_source,
    poll_answer,
    published_version_number,
    require_identifiers,
)


def _feedback(tx, site, version, target, payload):
    scope, _, code = target.partition(':')
    if submissions.feedback_targets_other_site(site, scope):
        submissions.require_feedback_scope(site, get_site(tx, scope))
    if code != 'general':
        submissions.require_feedback_target(get_site_version(tx, get_site(tx, scope))['config'], code)
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
    return metrics.build_metrics(entries, persistence.sites.version_configs(tx), now())


def collect(database, entries) -> list[dict]:
    """Accept an offline batch; each item commits (or is rejected) on its own.

    Exact retries are idempotent: a repeated id with the same body is a
    duplicate, a repeated id with a different body is a conflict, and the
    one-vote dedup key turns a second ballot into a rejection.
    """
    submissions.require_batch(entries)
    transactions = persistence.transactions
    receipts = []
    for body in entries:
        submission_id = body.get('id', '') if isinstance(body, dict) else ''
        try:
            with transactions.write(database) as tx:
                if submissions.is_replay(persistence.submissions.get(tx, submission_id), digest(canonical_json(body))):
                    receipts.append({'id': submission_id, 'status': 'duplicate'})
                    continue
                submissions.require_submission_object(body)
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
            if submissions.same_submission(previous, digest(canonical_json(body))):
                receipts.append({'id': submission_id, 'status': 'duplicate'})
            else:
                receipts.append({'id': submission_id, 'status': 'rejected', 'error': 'ALREADY_VOTED_OR_RECORDED'})
    return receipts
