"""Owner-filtered model persistence; transactions are owned by callers."""
from app.application.ports import persistence
from app.application.self_certificate_access import require_capability, require_owner
from app.application.audit_service import new_id
from app.domain import text
from app.domain import self_certificates as rules
from app.domain.guards import require_found
from app.application.self_certificate_crypto import fingerprint
from app.application.self_certificate_clock import utc_now
from app.application.self_certificate_branding import system_profile
from app.application.self_certificate_rendering import validate_config, VERSION

def page(offset=0, limit=30):
    return rules.page_window(offset,limit)

def get_model(tx,user,model_id,lock=False):
    principal=require_capability(tx,user,'models.manage')
    return require_found(persistence.self_certificates.model(tx,principal['id'],model_id,for_update=lock),'NOT_FOUND')

def list_models(tx,user,offset=0,limit=30,q=''):
    principal=require_capability(tx,user,'models.manage')
    offset,limit=page(offset,limit)
    items,total=persistence.self_certificates.models_page(tx,principal['id'],rules.search_filter(q),offset,limit)
    return {'items':items,'total':total}

def owned_asset(tx,user,asset_id,kind=None):
    rules.require_asset_reference(asset_id)
    owner=require_owner(tx,user,user['id'])
    return rules.require_asset_of_kind(persistence.self_certificates.asset(tx,owner['id'],asset_id),kind)

def get_revision(tx,user,revision_id):
    owner=require_owner(tx,user,user['id'])
    return require_found(persistence.self_certificates.revision(tx,owner['id'],revision_id),'NOT_FOUND')

def save_model(tx,user,*,name,background_asset_id,stamp_asset_id,config,model_id=None,row_version=None,idempotency_key=None):
    principal=require_capability(tx,user,'models.manage')
    name=text(name,160,True)
    operation_hash=None
    if idempotency_key is not None:
        rules.require_model_operation_key(model_id,idempotency_key)
        operation_hash=fingerprint(dict(name=name,background_asset_id=background_asset_id,stamp_asset_id=stamp_asset_id,config=config))
        # Serialize this bounded owner+operation key across processes.
        lock=int(fingerprint(['model-create',principal['id'],idempotency_key])[:16],16)
        if lock>=2**63:lock-=2**64
        persistence.self_certificates.serialize_operation(tx,lock)
        existing_operation=persistence.self_certificates.model_operation(tx,principal['id'],idempotency_key)
        if existing_operation:
            rules.require_same_operation(existing_operation['input_hash'],operation_hash)
            return existing_operation['result']
    background=owned_asset(tx,principal,background_asset_id,'background')
    branding=system_profile(background['width'],background['height'])
    if stamp_asset_id is not None: owned_asset(tx,principal,stamp_asset_id,'stamp')
    config,font_manifest=validate_config(config,background['width'],background['height'],stamp_asset_id is not None,branding)
    if model_id:
        existing=get_model(tx,principal,model_id,lock=True)
        rules.require_row_version(row_version,existing)
    else:
        existing={'id':new_id(),'owner_account_id':principal['id'],'name':name,'current_revision_id':None,'row_version':0,'created_at':utc_now(),'updated_at':utc_now()}
        persistence.self_certificates.add_model(tx,existing)
    revision={'id':new_id(),'owner_account_id':principal['id'],'origin_model_id':existing['id'],
        'background_asset_id':background_asset_id,'stamp_asset_id':stamp_asset_id,'config':config,
        'font_manifest':font_manifest,'renderer_version':VERSION,'schema_version':2,'branding_manifest':branding,'created_at':utc_now()}
    persistence.self_certificates.add_revision(tx,revision)
    changed=persistence.self_certificates.advance_model(tx,existing['id'],principal['id'],existing['row_version'],
        dict(name=name,current_revision_id=revision['id'],row_version=existing['row_version']+1,updated_at=utc_now()))
    rules.require_changed(changed)
    result={**get_model(tx,principal,existing['id']),'revision':revision}
    if idempotency_key is not None:
        persistence.self_certificates.add_model_operation(tx,dict(owner_account_id=principal['id'],idempotency_key=idempotency_key,
            input_hash=operation_hash,result=result,created_at=utc_now()))
    return result

def delete_model(tx,user,model_id,row_version):
    row=get_model(tx,user,model_id,lock=True)
    rules.require_row_version(row_version,row)
    # FK SET NULL detaches revisions; operational copies and assets are retained.
    rules.require_changed(persistence.self_certificates.delete_model(tx,model_id,user['id'],row_version))
