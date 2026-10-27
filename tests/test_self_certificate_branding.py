"""V2 immutable branding snapshots, local upgrade and physical reserved geometry."""
from copy import deepcopy
import re
import pytest
from fastapi import HTTPException
from PIL import Image
from sqlalchemy import insert,select,update,text
from sqlalchemy.exc import DBAPIError
from app.db import make_engine
from app.application import self_certificate_branding as brand
from app.application.self_certificate_clock import utc_now
from app.application.self_certificate_rendering import default_config
from app.application import self_certificate_repository as repo
from app.self_certificates_db import revisions
from tests.test_self_certificate_data import db,model

def test_profile_uses_original_hashed_assets_and_opaque_card():
    p=brand.system_profile(1200,800)
    assert p['logo_sha256']==brand.LOGO_SHA256
    for background in ('#ffffff','#111111','#783ab6'):
        source=Image.new('RGBA',(1200,800),background)
        result=brand.composite_branding(source,p)
        assert result.size==source.size
        r=p['card_rect']
        assert result.getpixel((r['x'],r['y']))==(255,255,255,255)
        assert result.getpixel((r['x']+r['width'],r['y']))==source.getpixel((r['x']+r['width'],r['y']))
    forged=deepcopy(p);forged['label']=''
    with pytest.raises(HTTPException):brand.composite_branding(source,forged)

def test_missing_or_corrupt_branding_fails_closed(monkeypatch,tmp_path):
    monkeypatch.setattr(brand,'LOGO_PATH',tmp_path/'missing.png')
    with pytest.raises(HTTPException) as exc:brand.system_profile(1200,800)
    assert exc.value.detail=='BRANDING_ASSET_UNAVAILABLE'
    (tmp_path/'missing.png').write_bytes(b'fake')
    with pytest.raises(HTTPException):brand.system_profile(1200,800)

def test_entire_name_and_stamp_rectangle_is_reserved_with_clearance():
    p=brand.system_profile(1200,800);r=p['card_rect']
    good=dict(x=300,y=300,width=600,height=120)
    assert brand.validate_reserved_rect(good,p,1200,800)==good
    for bad in [dict(r),dict(x=0,y=r['y']-2,width=300,height=1),
        dict(x=r['x']+.1,y=r['y']+.1,width=1,height=1),
        dict(x=-1,y=1,width=20,height=20),dict(x=0,y=0,width=float('nan'),height=20)]:
        with pytest.raises(HTTPException):brand.validate_reserved_rect(bad,p,1200,800)

def test_new_revisions_freeze_brand_and_legacy_null_is_not_rewritten(db):
    first=model(db)
    assert first['revision']['schema_version']==2
    frozen=deepcopy(first['revision']['branding_manifest'])
    with pytest.raises(DBAPIError),db.begin_nested():
        db.execute(update(revisions).values(branding_manifest={'enabled':False}))
    second=repo.save_model(db,{'id':'a'},name='نسخة مختلفة',background_asset_id='bg',
        stamp_asset_id=None,config={**default_config(800,600),'color':'#000000'},model_id=first['id'],row_version=1)
    assert second['revision']['config']!=first['revision']['config']
    assert db.execute(select(revisions.c.branding_manifest).where(revisions.c.id==first['revision']['id'])).scalar_one()==frozen
    legacy={**first['revision'],'id':'legacy','origin_model_id':None,'schema_version':1,'branding_manifest':None}
    db.execute(insert(revisions).values(**legacy))
    assert db.execute(select(revisions.c.branding_manifest).where(revisions.c.id=='legacy')).scalar_one() is None
    with pytest.raises(DBAPIError),db.begin_nested():
        db.execute(insert(revisions).values(**{**legacy,'id':'invalid-new','schema_version':2}))

def test_sqlite_upgrade_preserves_pre_v2_revision_and_rebuilds_guard():
    from app.self_certificates_db import ensure_sqlite_branding_schema
    engine=make_engine('sqlite:///:memory:')
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE px_self_certificate_revisions (id VARCHAR PRIMARY KEY,owner_account_id VARCHAR,origin_model_id VARCHAR,background_asset_id VARCHAR,stamp_asset_id VARCHAR,config JSON,font_manifest JSON,renderer_version VARCHAR,schema_version INTEGER,created_at VARCHAR)")
        conn.exec_driver_sql("INSERT INTO px_self_certificate_revisions VALUES ('old','a',NULL,'bg',NULL,'{}','{}','legacy',1,'2026-10-22')")
    ensure_sqlite_branding_schema(engine)
    ensure_sqlite_branding_schema(engine)
    with engine.begin() as conn:
        old=dict(conn.execute(text('SELECT * FROM px_self_certificate_revisions')).mappings().one())
        assert old['branding_manifest'] is None and old['renderer_version']=='legacy'
        with pytest.raises(DBAPIError),conn.begin_nested():
            conn.exec_driver_sql("UPDATE px_self_certificate_revisions SET branding_manifest='{}'")
        with pytest.raises(DBAPIError),conn.begin_nested():
            conn.exec_driver_sql("INSERT INTO px_self_certificate_revisions (id,schema_version) VALUES ('bad',2)")
    engine.dispose()

def test_new_utc_strings_have_fixed_precision():
    assert re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}\+00:00',utc_now())
