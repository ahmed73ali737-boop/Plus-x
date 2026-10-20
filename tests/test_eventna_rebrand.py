from sqlalchemy import insert, select
from app.core.build_info import APP_NAME
from app.db import make_engine, metadata, sites, versions
from tools.rebrand_eventna import rebrand


def test_rebrand_preserves_unpublished_content_history_and_custom_names(tmp_path):
    engine = make_engine('sqlite:///' + str(tmp_path / 'brand.sqlite'))
    metadata.create_all(engine)
    draft = {'title': 'PulseX — draft', 'description': 'Unpublished edit'}
    published = {'title': 'PulseX — Live Experience Platform', 'description': 'Published copy'}
    with engine.begin() as conn:
        conn.execute(insert(sites).values(id='platform', kind='platform', slug='platform',
            draft=draft, draft_rev=4, published_version=1))
        conn.execute(insert(versions).values(site_id='platform', version=1,
            config=published, published_at='2026-10-20T00:00:00Z'))
        conn.execute(insert(sites).values(id='custom', kind='platform', slug='custom',
            draft={'title': 'Customer name'}, draft_rev=1, published_version=0))
    assert rebrand(engine)['platforms'] == ['platform']
    with engine.connect() as conn:
        assert conn.execute(select(sites.c.draft_rev).where(sites.c.id == 'platform')).scalar_one() == 4
    assert rebrand(engine, apply=True)['platforms'] == ['platform']
    assert rebrand(engine, apply=True)['platforms'] == []
    with engine.connect() as conn:
        site = conn.execute(select(sites).where(sites.c.id == 'platform')).mappings().one()
        assert site['draft'] == {**draft, 'title': APP_NAME}
        assert site['draft_rev'] == 5 and site['published_version'] == 2
        history = conn.execute(select(versions).order_by(versions.c.version)).mappings().all()
        assert history[0]['config'] == published
        assert history[1]['config'] == {**published, 'title': APP_NAME}
        assert conn.execute(select(sites.c.draft).where(sites.c.id == 'custom')).scalar_one()['title'] == 'Customer name'
    engine.dispose()
