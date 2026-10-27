"""Rebrand safety: preview is read-only and customer history remains unchanged."""
from copy import deepcopy
import pytest
from sqlalchemy import insert,select
from app.core.build_info import APP_NAME
from app.db import make_engine,metadata,sites,versions,audit
from tools.rebrand_eventna import rebrand

LEGACY='PulseX — Live Experience Platform'
CUSTOM='Customer Conference'

@pytest.fixture
def brand_db(tmp_path):
    engine=make_engine('sqlite:///'+str(tmp_path/'rebrand.sqlite'))
    metadata.create_all(engine)
    try:yield engine
    finally:engine.dispose()

def populate(engine,draft_title,published_title):
    draft={'title':draft_title,'description':'private draft','records':[{'code':'draft-only'}]}
    published={'title':published_title,'description':'public copy','records':[{'code':'public-only'}]}
    with engine.begin() as c:
        c.execute(insert(sites).values(id='platform',kind='platform',slug='platform',draft=draft,draft_rev=7,published_version=1))
        c.execute(insert(versions).values(site_id='platform',version=1,config=published,published_at='2026-10-20T00:00:00Z'))
    return deepcopy(draft),deepcopy(published)

@pytest.mark.parametrize('draft_title,published_title',[(LEGACY,CUSTOM),(CUSTOM,LEGACY),(LEGACY,LEGACY),(CUSTOM,CUSTOM)])
def test_rebrand_preview_and_apply_keep_draft_and_published_content_separate(brand_db,draft_title,published_title):
    engine=brand_db;draft,published=populate(engine,draft_title,published_title)
    wanted=bool(draft_title==LEGACY or published_title==LEGACY)
    preview=rebrand(engine)
    assert preview=={'applied':False,'platforms':['platform'] if wanted else []}
    with engine.connect() as c:
        assert c.execute(select(sites.c.draft)).scalar_one()==draft
        assert c.execute(select(versions.c.config)).scalar_one()==published
        assert c.execute(select(audit)).first() is None
    rebrand(engine,apply=True)
    with engine.connect() as c:
        site=c.execute(select(sites)).mappings().one()
        assert site['draft']=={**draft,'title':APP_NAME if draft_title==LEGACY else draft_title}
        assert site['draft_rev']==7+int(draft_title==LEGACY)
        history=c.execute(select(versions).order_by(versions.c.version)).mappings().all()
        assert history[0]['config']==published
        assert len(history)==1+int(published_title==LEGACY)
        assert history[-1]['config']=={**published,'title':APP_NAME if published_title==LEGACY else published_title}
        assert len(c.execute(select(audit)).all())==int(wanted)
    assert rebrand(engine,apply=True)=={'applied':True,'platforms':[]}

def test_rebrand_does_not_replace_customer_name_that_only_starts_with_legacy_brand(brand_db):
    custom='PulseX Customer Conference'
    draft,published=populate(brand_db,custom,custom)
    assert rebrand(brand_db)=={'applied':False,'platforms':[]},'Prefix matching misclassifies a customer title as the default product name'
    assert rebrand(brand_db,apply=True)=={'applied':True,'platforms':[]}
    with brand_db.connect() as c:
        assert c.execute(select(sites.c.draft)).scalar_one()==draft
        assert c.execute(select(versions.c.config)).scalar_one()==published
