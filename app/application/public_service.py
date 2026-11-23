"""Anonymous read models: the public site bundle and public poll results."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from app.application.access import get_site
from app.application.event_visibility import event_id_for_site, is_public_event, require_public_event
from app.application.ports import persistence
from app.application.publishing import get_site_version
from app.domain import now
from app.domain.site_config import public_config_without_answer_keys
from app.domain.sites import event_status, require_published_config
from app.domain.surveys import ballot_items


def _child_card(child: dict, participation) -> dict:
    config = require_published_config(child['published_config'])
    return {
        'id': child['id'], 'slug': child['slug'], 'title': config['title'], 'subtitle': config['subtitle'],
        'description': config['description'], 'logo': config['logo'], 'primary': config['primary'],
        'rating_criteria': config.get('rating_criteria', []), 'participation': participation,
    }


def _public_events(tx) -> list[dict]:
    current_time = datetime.now(timezone.utc)
    events = []
    for event in persistence.sites.published_events(tx):
        if not is_public_event(tx, event['id']):
            continue
        config = get_site_version(tx, event)['config']
        events.append({
            'id': event['id'], 'slug': event['slug'], 'title': config['title'], 'subtitle': config['subtitle'],
            'start': config['start'], 'end': config['end'], 'cover': config['cover'],
            'status': event_status(config, current_time),
        })
    return events


def build_public_bundle(tx, site, public_origin: str, draft: bool = False, *, authorized_event_id: str | None = None):
    event_id = event_id_for_site(tx, site)
    # The internal invitation endpoint may pass this only after validating the
    # invitation credential. Public routes must never forward a client parameter.
    if not draft and (not event_id or authorized_event_id != event_id):
        require_public_event(tx, event_id)
    if draft:
        current = {'config': site['draft'], 'version': site['published_version'], 'published_at': None}
    else:
        current = get_site_version(tx, site)
    event = None
    if site['event_id'] and site['id'] != site['event_id']:
        parent = get_site(tx, site['event_id'])
        if parent['published_version']:
            event = {'id': parent['id'], 'slug': parent['slug'],
                     'config': public_config_without_answer_keys(get_site_version(tx, parent)['config'])}
    parent_id = site['event_id'] or site['id']
    # Two set-based reads replace 2N child queries.
    participations = {}
    for participation in persistence.sites.participations_of_children(tx, parent_id):
        participations.setdefault(participation['agency_site_id'], participation)
    children = [_child_card(child, participations.get(child['id']))
                for child in persistence.sites.published_agency_children(tx, parent_id)]
    events = _public_events(tx) if site['kind'] == 'platform' else []
    return {
        'id': site['id'], 'slug': site['slug'], 'kind': site['kind'], 'event_id': site['event_id'],
        'version': current['version'],
        'config': current['config'] if draft else public_config_without_answer_keys(current['config']),
        'published_at': current['published_at'], 'event': event, 'agencies': children, 'events': events,
        'preview': draft, 'draft': draft, 'public_origin': public_origin,
    }


def _shows_public_results(question: dict) -> bool:
    return (question.get('kind') == 'poll' and question.get('enabled') is True
            and question.get('show_results') is True and question.get('poll_style') != 'secret')


def build_public_poll_results(tx, site):
    require_public_event(tx, event_id_for_site(tx, site))
    config = get_site_version(tx, site)['config']
    result = {}
    for question in config['records']:
        if not _shows_public_results(question):
            continue
        counts, ballots = Counter(), 0
        for payload in persistence.submissions.poll_payloads(tx, site['id'], question['code'], site['published_version']):
            ballots += 1
            for item in ballot_items(question.get('qtype'), payload['answer']):
                counts[str(item)] += 1
        result[question['code']] = {'counts': dict(counts), 'ballots': ballots,
                                    'percent_denominator': 'ballots; multi-choice can exceed 100%'}
    return {'as_of': now(), 'version': site['published_version'], 'polls': result}
