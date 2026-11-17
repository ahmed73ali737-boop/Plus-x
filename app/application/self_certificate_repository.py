"""Owner-filtered model persistence; transactions are owned by callers."""
from app.application.ports import persistence
from app.application.self_certificate_access import require_capability, require_owner
from app.application.audit_service import new_id
from app.domain import fail, text, NotFound, Conflict
from app.application.self_certificate_crypto import fingerprint
import re
from app.application.self_certificate_clock import utc_now
from app.application.self_certificate_branding import system_profile
from app.application.self_certificate_rendering import validate_config, VERSION

def page(offset=0, limit=30):
    if type(offset) is not int or type(limit) is not int or offset < 0 or not 1 <= limit <= 100:
        fail('PAGE_INVALID')
    return offset,limit

def get_model(tx,user,model_id,lock=False):
    principal=require_capability(tx,user,'models.manage')
    row=persistence.self_certificates.model(tx,principal['id'],model_id,for_update=lock)
    if not row: fail('NOT_FOUND', NotFound)
    return row

def list_models(tx,user,offset=0,limit=30,q=''):
    principal=require_capability(tx,user,'models.manage')
    offset,limit=page(offset,limit)
    if not isinstance(q,str) or len(q)>160:fail('FILTER_INVALID')
    items,total=persistence.self_certificates.models_page(tx,principal['id'],q.strip(),offset,limit)
    return {'items':items,'total':total}

def owned_asset(tx,user,asset_id,kind=None):
    if not isinstance(asset_id,str) or not 1<=len(asset_id)<=64:fail("NOT_FOUND", NotFound)
    owner=require_owner(tx,user,user['id'])
    row=persistence.self_certificates.asset(tx,owner['id'],asset_id)
    if not row or (kind and row['kind']!=kind): fail('NOT_FOUND', NotFound)
    return row

def get_revision(tx,user,revision_id):
    owner=require_owner(tx,user,user['id'])
    row=persistence.self_certificates.revision(tx,owner['id'],revision_id)
    if not row: fail('NOT_FOUND', NotFound)
    return row

def save_model(tx,user,*,name,background_asset_id,stamp_asset_id,config,model_id=None,row_version=None,idempotency_key=None):
    principal=require_capability(tx,user,'models.manage')
    name=text(name,160,True)
    operation_hash=None
    if idempotency_key is not None:
        if model_id is not None or not isinstance(idempotency_key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',idempotency_key):
            fail('MODEL_INPUT_INVALID')
        operation_hash=fingerprint(dict(name=name,background_asset_id=background_asset_id,stamp_asset_id=stamp_asset_id,config=config))
        # Serialize this bounded owner+operation key across processes.
        lock=int(fingerprint(['model-create',principal['id'],idempotency_key])[:16],16)
        if lock>=2**63:lock-=2**64
        persistence.self_certificates.serialize_operation(tx,lock)
        existing_operation=persistence.self_certificates.model_operation(tx,principal['id'],idempotency_key)
        if existing_operation:
            if existing_operation['input_hash']!=operation_hash:fail('IDEMPOTENCY_CONFLICT', Conflict)
            return existing_operation['result']
    background=owned_asset(tx,principal,background_asset_id,'background')
    branding=system_profile(background['width'],background['height'])
    if stamp_asset_id is not None: owned_asset(tx,principal,stamp_asset_id,'stamp')
    config,font_manifest=validate_config(config,background['width'],background['height'],stamp_asset_id is not None,branding)
    if model_id:
        existing=get_model(tx,principal,model_id,lock=True)
        if type(row_version)!=int or existing['row_version']!=row_version:
            fail('VERSION_CONFLICT', Conflict)
    else:
        existing={'id':new_id(),'owner_account_id':principal['id'],'name':name,'current_revision_id':None,'row_version':0,'created_at':utc_now(),'updated_at':utc_now()}
        persistence.self_certificates.add_model(tx,existing)
    revision={'id':new_id(),'owner_account_id':principal['id'],'origin_model_id':existing['id'],
        'background_asset_id':background_asset_id,'stamp_asset_id':stamp_asset_id,'config':config,
        'font_manifest':font_manifest,'renderer_version':VERSION,'schema_version':2,'branding_manifest':branding,'created_at':utc_now()}
    persistence.self_certificates.add_revision(tx,revision)
    changed=persistence.self_certificates.advance_model(tx,existing['id'],principal['id'],existing['row_version'],
        dict(name=name,current_revision_id=revision['id'],row_version=existing['row_version']+1,updated_at=utc_now()))
    if not changed: fail('VERSION_CONFLICT', Conflict)
    result={**get_model(tx,principal,existing['id']),'revision':revision}
    if idempotency_key is not None:
        persistence.self_certificates.add_model_operation(tx,dict(owner_account_id=principal['id'],idempotency_key=idempotency_key,
            input_hash=operation_hash,result=result,created_at=utc_now()))
    return result

def delete_model(tx,user,model_id,row_version):
    row=get_model(tx,user,model_id,lock=True)
    if type(row_version)!=int or row_version!=row['row_version']: fail('VERSION_CONFLICT', Conflict)
    # FK SET NULL detaches revisions; operational copies and assets are retained.
    if not persistence.self_certificates.delete_model(tx,model_id,user['id'],row_version): fail('VERSION_CONFLICT', Conflict)
