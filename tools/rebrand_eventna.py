"""Update the default platform name without replacing content or old versions."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from sqlalchemy import insert, select, update

from app.application.audit_service import write_audit
from app.core.build_info import APP_NAME
from app.db import make_engine, sites, versions
from app.domain import now


def rebrand(engine, *, apply=False):
    changes = []
    with engine.begin() as conn:
        platforms = conn.execute(select(sites).where(
            sites.c.kind == 'platform').with_for_update()).mappings().all()
        for site in platforms:
            draft = deepcopy(site['draft'])
            updates = {}
            if draft.get('title', '').startswith('PulseX'):
                draft['title'] = APP_NAME
                updates.update(draft=draft, draft_rev=site['draft_rev'] + 1)
            published = conn.execute(select(versions).where(
                versions.c.site_id == site['id'],
                versions.c.version == site['published_version'])).mappings().first()
            if published and published['config'].get('title', '').startswith('PulseX'):
                config = deepcopy(published['config'])
                config['title'] = APP_NAME
                updates['published_version'] = site['published_version'] + 1
                if apply:
                    conn.execute(insert(versions).values(site_id=site['id'],
                        version=updates['published_version'], config=config, published_at=now()))
            if updates:
                changes.append(site['id'])
                if apply:
                    conn.execute(update(sites).where(sites.c.id == site['id']).values(**updates))
                    write_audit(conn, None, site['id'], 'platform_rebrand', {'name': APP_NAME})
    return {'applied': apply, 'platforms': changes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    engine = make_engine()
    try:
        print(json.dumps(rebrand(engine, apply=args.apply), ensure_ascii=False))
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
