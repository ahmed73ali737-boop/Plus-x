"""Owner-filtered model persistence; transactions are owned by callers."""
from sqlalchemy import insert, select, update, delete, func, text as sql_text
from app.self_certificates_db import models, revisions, assets, model_operations
from app.application.self_certificate_access import require_capability, require_owner
from app.application.audit_service import new_id
from app.domain import fail, text
from app.application.self_certificate_crypto import fingerprint
import re
from app.application.self_certificate_clock import utc_now
from app.application.self_certificate_branding import system_profile
from app.application.self_certificate_rendering import validate_config, VERSION

def page(offset=0, limit=30):
    if type(offset) is not int or type(limit) is not int or offset < 0 or not 1 <= limit <= 100:
        fail('PAGE_INVALID',422)
    return offset,limit

def get_model(conn,user,model_id,lock=False):
    principal=require_capability(conn,user,'models.manage')
    query=select(models).where(models.c.id==model_id,models.c.owner_account_id==principal['id'])
    if lock: query=query.with_for_update()
    row=conn.execute(query).mappings().first()
    if not row: fail('NOT_FOUND',404)
    return dict(row)

def list_models(conn,user,offset=0,limit=30,q=''):
    principal=require_capability(conn,user,'models.manage')
    offset,limit=page(offset,limit)
    if not isinstance(q,str) or len(q)>160:fail('FILTER_INVALID',422)
    scope=models.c.owner_account_id==principal['id']
    if q.strip():scope=scope & models.c.name.icontains(q.strip(),autoescape=True)
    return {'items':[dict(row) for row in conn.execute(select(models,revisions.c.background_asset_id).join(revisions,(models.c.current_revision_id==revisions.c.id)&(models.c.owner_account_id==revisions.c.owner_account_id)).where(scope).order_by(models.c.updated_at.desc(),models.c.id).offset(offset).limit(limit)).mappings()],
        'total':conn.execute(select(func.count()).select_from(models).where(scope)).scalar_one()}

def owned_asset(conn,user,asset_id,kind=None):
    if not isinstance(asset_id,str) or not 1<=len(asset_id)<=64:fail("NOT_FOUND",404)
    owner=require_owner(conn,user,user['id'])
    row=conn.execute(select(assets).where(assets.c.id==asset_id,assets.c.owner_account_id==owner['id'])).mappings().first()
    if not row or (kind and row['kind']!=kind): fail('NOT_FOUND',404)
    return dict(row)

def get_revision(conn,user,revision_id):
    owner=require_owner(conn,user,user['id'])
    row=conn.execute(select(revisions).where(revisions.c.id==revision_id,revisions.c.owner_account_id==owner['id'])).mappings().first()
    if not row: fail('NOT_FOUND',404)
    return dict(row)

def save_model(conn,user,*,name,background_asset_id,stamp_asset_id,config,model_id=None,row_version=None,idempotency_key=None):
    principal=require_capability(conn,user,'models.manage')
    name=text(name,160,True)
    operation_hash=None
    if idempotency_key is not None:
        if model_id is not None or not isinstance(idempotency_key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',idempotency_key):
            fail('MODEL_INPUT_INVALID',422)
        operation_hash=fingerprint(dict(name=name,background_asset_id=background_asset_id,stamp_asset_id=stamp_asset_id,config=config))
        if conn.dialect.name=='postgresql':
            # Serialize this bounded owner+operation key across processes.
            lock=int(fingerprint(['model-create',principal['id'],idempotency_key])[:16],16)
            if lock>=2**63:lock-=2**64
            conn.execute(sql_text('SELECT pg_advisory_xact_lock(:key)'),{'key':lock})
        existing_operation=conn.execute(select(model_operations).where(
            model_operations.c.owner_account_id==principal['id'],model_operations.c.idempotency_key==idempotency_key)).mappings().first()
        if existing_operation:
            if existing_operation['input_hash']!=operation_hash:fail('IDEMPOTENCY_CONFLICT',409)
            return existing_operation['result']
    background=owned_asset(conn,principal,background_asset_id,'background')
    branding=system_profile(background['width'],background['height'])
    if stamp_asset_id is not None: owned_asset(conn,principal,stamp_asset_id,'stamp')
    config,font_manifest=validate_config(config,background['width'],background['height'],stamp_asset_id is not None,branding)
    if model_id:
        existing=get_model(conn,principal,model_id,lock=True)
        if type(row_version)!=int or existing['row_version']!=row_version:
            fail('VERSION_CONFLICT',409)
    else:
        existing={'id':new_id(),'owner_account_id':principal['id'],'name':name,'current_revision_id':None,'row_version':0,'created_at':utc_now(),'updated_at':utc_now()}
        conn.execute(insert(models).values(**existing))
    revision={'id':new_id(),'owner_account_id':principal['id'],'origin_model_id':existing['id'],
        'background_asset_id':background_asset_id,'stamp_asset_id':stamp_asset_id,'config':config,
        'font_manifest':font_manifest,'renderer_version':VERSION,'schema_version':2,'branding_manifest':branding,'created_at':utc_now()}
    conn.execute(insert(revisions).values(**revision))
    changed=conn.execute(update(models).where(models.c.id==existing['id'],models.c.owner_account_id==principal['id'],
        models.c.row_version==existing['row_version']).values(name=name,current_revision_id=revision['id'],
        row_version=existing['row_version']+1,updated_at=utc_now()))
    if changed.rowcount!=1: fail('VERSION_CONFLICT',409)
    result={**get_model(conn,principal,existing['id']),'revision':revision}
    if idempotency_key is not None:
        conn.execute(insert(model_operations).values(owner_account_id=principal['id'],idempotency_key=idempotency_key,
            input_hash=operation_hash,result=result,created_at=utc_now()))
    return result

def delete_model(conn,user,model_id,row_version):
    row=get_model(conn,user,model_id,lock=True)
    if type(row_version)!=int or row_version!=row['row_version']: fail('VERSION_CONFLICT',409)
    # FK SET NULL detaches revisions; operational copies and assets are retained.
    result=conn.execute(delete(models).where(models.c.id==model_id,models.c.owner_account_id==user['id'],models.c.row_version==row_version))
    if result.rowcount!=1: fail('VERSION_CONFLICT',409)
