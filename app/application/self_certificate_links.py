"""Owner-only immutable request links; library membership is checked independently."""
import hmac
from app.application import self_certificate_repository as repo
from app.application.ports import persistence
from app.application.self_certificate_access import require_capability,require_event
from app.application.self_certificate_crypto import fingerprint,token_hash
from app.application.self_certificate_clock import utc_now
from app.application.audit_service import new_id
from app.domain import fail, text, NotFound, Conflict

def revision_hash(revision):
    return fingerprint({k:v for k,v in revision.items() if k!='origin_model_id'})

def checked_revision(tx,owner,revision_id):
    row=persistence.self_certificates.revision(tx,owner,revision_id)
    if not row:fail('REVISION_UNAVAILABLE', Conflict)
    for ident,kind in ((row['background_asset_id'],'background'),(row['stamp_asset_id'],'stamp')):
        if ident is None:continue
        if not persistence.self_certificates.asset(tx,owner,ident,kind):fail('ASSET_OWNER_MISMATCH', Conflict)
    return row

def projection(row,keys,origin):
    token=keys.token('request-link',row['public_id'],row['key_version'])
    return {k:row[k] for k in ('id','event_id','event_name_snapshot','model_name_snapshot','status','share_text_snapshot','row_version','created_at')}|{'request_url':origin+'/certificates/request/'+token,'qr_url':'/api/self-certificates/links/'+row['id']+'/qr'}

def create(tx,user,keys,origin,body):
    if not isinstance(body,dict) or set(body)-{'event_id','model_id','share_text','idempotency_key','expected_revision_id'} or not {'event_id','model_id','share_text','idempotency_key'}<=set(body):fail('LINK_INPUT_INVALID')
    owner=require_capability(tx,user,'links.manage')
    event_id=text(body['event_id'],64,True);model_id=text(body['model_id'],64,True)
    key=text(body['idempotency_key'],80,True)
    share=text(body['share_text'],4000,True)
    identity=dict(event_id=event_id,model_id=model_id,share_text=share)
    expected_revision_id=body.get('expected_revision_id')
    if 'expected_revision_id' in body:
        identity['expected_revision_id']=text(expected_revision_id,64,True)
    input_hash=fingerprint(identity)
    existing=persistence.self_certificates.link_by_idempotency(tx,owner['id'],key)
    if existing:
        if existing['input_hash']!=input_hash:fail('IDEMPOTENCY_CONFLICT', Conflict)
        return projection(existing,keys,origin)
    from app.application.self_certificate_participants import lock_authority
    lock_authority(tx,owner["id"],event_id)
    from app.core.certificate_features import certificate_features
    if not certificate_features().link_allowed(owner['id'],event_id):fail('CERTIFICATE_PILOT_UNAVAILABLE', Conflict)
    event=require_event(tx,owner,event_id)
    model=repo.get_model(tx,owner,model_id,lock=True)
    if expected_revision_id is not None and expected_revision_id!=model['current_revision_id']:
        fail('MODEL_REVISION_CHANGED', Conflict)
    revision=checked_revision(tx,owner['id'],model['current_revision_id'])
    if revision['schema_version']!=2:fail('MODEL_UPGRADE_REQUIRED', Conflict)
    public_id=new_id();version=keys.current
    token=keys.token('request-link',public_id,version)
    title=(event.get('draft') or {}).get('title') or event.get('slug') or 'فعالية'
    row=dict(id=new_id(),owner_account_id=owner['id'],event_id=event['id'],
        event_name_snapshot=text(title,250,True),model_name_snapshot=model['name'],revision_id=revision['id'],
        public_id=public_id,key_version=version,public_token_hash=token_hash(token),status='active',
        share_text_snapshot=share,config_hash=revision_hash(revision),input_hash=input_hash,idempotency_key=key,row_version=1,created_at=utc_now())
    persistence.self_certificates.add_link(tx,row)
    return projection(row,keys,origin)

def list_links(tx,user,keys,origin,offset=0,limit=30):
    owner=require_capability(tx,user,'requests.read');repo.page(offset,limit)
    rows,total=persistence.self_certificates.links_page(tx,owner['id'],offset,limit)
    return dict(items=[projection(r,keys,origin) for r in rows],total=total)

def get_owned(tx,user,ident,lock=False):
    owner=require_capability(tx,user,'requests.read')
    row=persistence.self_certificates.link(tx,owner['id'],ident,for_update=lock)
    if not row:fail('NOT_FOUND', NotFound)
    return row

def set_state(tx,user,ident,body,keys,origin):
    row=get_owned(tx,user,ident,True)
    if not isinstance(body,dict) or set(body)!={'status','row_version'} or body['status'] not in ('active','paused'):fail('LINK_STATE_INVALID')
    if type(body['row_version']) is not int or body['row_version']!=row['row_version']:fail('VERSION_CONFLICT', Conflict)
    if body['status']=='active':require_event(tx,user,row['event_id'])
    persistence.self_certificates.set_link_state(tx,ident,row['row_version'],
        dict(status=body['status'],row_version=row['row_version']+1,disabled_at=utc_now() if body['status']=='paused' else None))
    return projection({**row,**body,'row_version':row['row_version']+1},keys,origin)

def get_public(tx,keys,token,lock=False):
    ident,version=keys.verify('request-link',token)
    row=persistence.self_certificates.public_link(tx,ident,version,for_update=lock)
    if not row or not hmac.compare_digest(row['public_token_hash'],token_hash(token)):fail('NOT_FOUND', NotFound)
    return row
