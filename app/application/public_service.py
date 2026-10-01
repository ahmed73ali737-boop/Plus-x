from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import select

from app.db import event_participations, sites, submissions
from app.application.publishing import get_site_version
from app.infrastructure.repository import get_site
from app.domain import now


def build_public_bundle(conn, site, public_origin: str, draft: bool = False):
    current={'config':site['draft'],'version':site['published_version'],'published_at':None} if draft else get_site_version(conn,site)
    event=None; children=[]; events=[]
    if site['event_id'] and site['id']!=site['event_id']:
        e=get_site(conn,site['event_id'])
        if e['published_version']:
            event={'id':e['id'],'slug':e['slug'],'config':get_site_version(conn,e)['config']}
    parent_id=site['event_id'] or site['id']
    for child in conn.execute(select(sites).where(sites.c.parent_id==parent_id)).mappings():
        if child['kind']=='agency' and child['published_version']:
            cfg=get_site_version(conn,child)['config']
            part=conn.execute(select(event_participations).where(event_participations.c.agency_site_id==child['id'])).mappings().first()
            children.append({'id':child['id'],'slug':child['slug'],'title':cfg['title'],'subtitle':cfg['subtitle'],'description':cfg['description'],'logo':cfg['logo'],'primary':cfg['primary'],'rating_criteria':cfg.get('rating_criteria',[]),'participation':dict(part) if part else None})
    if site['kind']=='platform':
        current_time=datetime.now(timezone.utc)
        for e in conn.execute(select(sites).where(sites.c.kind=='event',sites.c.published_version>0)).mappings():
            cfg=get_site_version(conn,e)['config']
            start=datetime.fromisoformat(cfg['start']) if cfg.get('start') else None
            end=datetime.fromisoformat(cfg['end']) if cfg.get('end') else None
            status='upcoming' if start and current_time<start else 'completed' if end and current_time>=end else 'current'
            events.append({'id':e['id'],'slug':e['slug'],'title':cfg['title'],'subtitle':cfg['subtitle'],'start':cfg['start'],'end':cfg['end'],'cover':cfg['cover'],'status':status})
    return {'id':site['id'],'slug':site['slug'],'kind':site['kind'],'event_id':site['event_id'],'version':current['version'],'config':current['config'],'published_at':current['published_at'],'event':event,'agencies':children,'events':events,'preview':draft,'draft':draft,'public_origin':public_origin}


def build_public_poll_results(conn, site):
    cfg=get_site_version(conn,site)['config']; result={}
    for q in cfg['records']:
        if q['kind']!='poll' or not q['enabled'] or not q['show_results']:
            continue
        rows=conn.execute(select(submissions.c.payload).where(submissions.c.site_id==site['id'],submissions.c.kind=='poll',submissions.c.target==q['code'],submissions.c.version==site['published_version'])).scalars()
        counts=Counter(); ballots=0
        for payload in rows:
            ballots+=1; value=payload['answer']
            items=[f'{x} / rank {i+1}' for i,x in enumerate(value)] if q['qtype']=='ranking' else value if isinstance(value,list) else [value]
            for item in items: counts[str(item)]+=1
        result[q['code']]={'counts':dict(counts),'ballots':ballots,'percent_denominator':'ballots; multi-choice can exceed 100%'}
    return {'as_of':now(),'version':site['published_version'],'polls':result}
