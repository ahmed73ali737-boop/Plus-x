"""Fail-closed public vote disclosure even for legacy or malformed revisions."""
from __future__ import annotations
import copy
import pytest
from sqlalchemy import select,update
from fastapi.testclient import TestClient
from app.server import create_app
from app.db import sites,versions

@pytest.mark.parametrize('style,show,enabled,allowed',[
    ('secret',True,True,False),
    ('quick','false',True,False),
    ('quick',True,'false',False),
    ('quick',True,True,True),
])
def test_only_explicitly_public_published_poll_returns_results(tmp_path,style,show,enabled,allowed):
    app=create_app('sqlite:///'+str(tmp_path/'secret.sqlite'),origin='http://testserver',seed_demo=True)
    with app.state.engine.begin() as connection:
        site=connection.execute(select(sites).where(sites.c.id=='agency-01')).mappings().one()
        revision=connection.execute(select(versions).where(versions.c.site_id=='agency-01',versions.c.version==site['published_version'])).mappings().one()
        cfg=copy.deepcopy(revision['config'])
        poll=next(r for r in cfg['records'] if r['kind']=='poll')
        poll.update(poll_style=style,show_results=show,enabled=enabled)
        connection.execute(update(versions).where(versions.c.site_id=='agency-01',versions.c.version==site['published_version']).values(config=cfg))
    response=TestClient(app).get('/api/public/site/agency-01/results')
    assert response.status_code==200
    assert (poll['code'] in response.json()['polls']) is allowed
    assert 'guest_number' not in response.text and 'visitor_id' not in response.text
