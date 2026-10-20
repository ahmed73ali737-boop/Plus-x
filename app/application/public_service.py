from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone

from sqlalchemy import and_, select

from app.db import event_participations, sites, submissions, versions
from app.application.publishing import get_site_version
from app.infrastructure.repository import get_site
from app.domain import fail, now
from app.application.event_visibility import event_id_for_site, is_public_event, require_public_event


def public_config_without_answer_keys(config):
    """Build an anonymous-safe copy while preserving canonical scoring data.

    Server-side validation and privileged drafts retain correct answers; public
    site and parent-event bundles must never transmit those keys.
    """
    result = deepcopy(config)
    for item in result.get('records', []):
        if isinstance(item, dict) and item.get('kind') == 'question':
            item.pop('correct', None)
    return result


def build_public_bundle(conn, site, public_origin: str, draft: bool = False, *, authorized_event_id: str | None = None):
    event_id = event_id_for_site(conn, site)
    # The internal invitation endpoint may pass this only after validating the
    # invitation credential. Public routes must never forward a client parameter.
    if not draft and (not event_id or authorized_event_id != event_id):
        require_public_event(conn, event_id)
    current={'config':site['draft'],'version':site['published_version'],'published_at':None} if draft else get_site_version(conn,site)
    event=None; children=[]; events=[]
    if site['event_id'] and site['id']!=site['event_id']:
        e=get_site(conn,site['event_id'])
        if e['published_version']:
            event={'id':e['id'],'slug':e['slug'],'config':public_config_without_answer_keys(get_site_version(conn,e)['config'])}
    parent_id=site['event_id'] or site['id']
    # Two set-based reads replace 2N child queries. Keep publication authority
    # and the existing transaction/locking policy; no cache or schema change.
    parts={}
    for part in conn.execute(select(event_participations).join(sites,event_participations.c.agency_site_id==sites.c.id).where(sites.c.parent_id==parent_id)).mappings():
        parts.setdefault(part['agency_site_id'],dict(part))
    child_query=select(sites,versions.c.config.label('published_config')).select_from(
        sites.outerjoin(versions,and_(versions.c.site_id==sites.c.id,versions.c.version==sites.c.published_version))
    ).where(sites.c.parent_id==parent_id,sites.c.kind=='agency',sites.c.published_version>0)
    for child in conn.execute(child_query).mappings():
        cfg=child['published_config']
        if cfg is None:fail('NOT_PUBLISHED',404)
        children.append({'id':child['id'],'slug':child['slug'],'title':cfg['title'],'subtitle':cfg['subtitle'],'description':cfg['description'],'logo':cfg['logo'],'primary':cfg['primary'],'rating_criteria':cfg.get('rating_criteria',[]),'participation':parts.get(child['id'])})
    if site['kind']=='platform':
        current_time=datetime.now(timezone.utc)
        for e in conn.execute(select(sites).where(sites.c.kind=='event',sites.c.published_version>0)).mappings():
            if not is_public_event(conn, e['id']):
                continue
            cfg=get_site_version(conn,e)['config']
            start=datetime.fromisoformat(cfg['start']) if cfg.get('start') else None
            end=datetime.fromisoformat(cfg['end']) if cfg.get('end') else None
            status='upcoming' if start and current_time<start else 'completed' if end and current_time>=end else 'current'
            events.append({'id':e['id'],'slug':e['slug'],'title':cfg['title'],'subtitle':cfg['subtitle'],'start':cfg['start'],'end':cfg['end'],'cover':cfg['cover'],'status':status})
    return {'id':site['id'],'slug':site['slug'],'kind':site['kind'],'event_id':site['event_id'],'version':current['version'],'config':current['config'] if draft else public_config_without_answer_keys(current['config']),'published_at':current['published_at'],'event':event,'agencies':children,'events':events,'preview':draft,'draft':draft,'public_origin':public_origin}


def build_public_poll_results(conn, site):
    require_public_event(conn, event_id_for_site(conn, site))
    cfg=get_site_version(conn,site)['config']; result={}
    for q in cfg['records']:
        if (q.get('kind') != 'poll' or q.get('enabled') is not True or
                q.get('show_results') is not True or q.get('poll_style') == 'secret'):
            continue
        rows=conn.execute(select(submissions.c.payload).where(submissions.c.site_id==site['id'],submissions.c.kind=='poll',submissions.c.target==q['code'],submissions.c.version==site['published_version'])).scalars()
        counts=Counter(); ballots=0
        for payload in rows:
            ballots+=1; value=payload['answer']
            items=[f'{x} / rank {i+1}' for i,x in enumerate(value)] if q['qtype']=='ranking' else value if isinstance(value,list) else [value]
            for item in items: counts[str(item)]+=1
        result[q['code']]={'counts':dict(counts),'ballots':ballots,'percent_denominator':'ballots; multi-choice can exceed 100%'}
    return {'as_of':now(),'version':site['published_version'],'polls':result}
