"""Owner-only immutable request links; library membership is checked independently."""
import hmac
from app.application import self_certificate_repository as repo
from app.application.ports import persistence
from app.application.self_certificate_access import require_capability,require_event
from app.application.self_certificate_crypto import fingerprint,token_hash
from app.application.self_certificate_clock import utc_now
from app.application.audit_service import new_id
from app.domain import text
from app.domain import self_certificates as rules
from app.domain.guards import require_found
from app.domain.self_certificates import LinkRequest, LinkStateChange

def revision_hash(revision):
    return fingerprint({k:v for k,v in revision.items() if k!='origin_model_id'})

def checked_revision(tx,owner,revision_id):
    row=rules.require_revision_available(persistence.self_certificates.revision(tx,owner,revision_id))
    for ident,kind in ((row['background_asset_id'],'background'),(row['stamp_asset_id'],'stamp')):
        if ident is None:continue
        rules.require_asset_owned(persistence.self_certificates.asset(tx,owner,ident,kind))
    return row

def projection(row,keys,origin):
    token=keys.token('request-link',row['public_id'],row['key_version'])
    return {k:row[k] for k in ('id','event_id','event_name_snapshot','model_name_snapshot','status','share_text_snapshot','row_version','created_at')}|{'request_url':origin+'/certificates/request/'+token,'qr_url':'/api/self-certificates/links/'+row['id']+'/qr'}

def create(tx,user,keys,origin,body):
    LinkRequest.check_shape(body)
    owner=require_capability(tx,user,'links.manage')
    link=LinkRequest.parse(body)
    input_hash=fingerprint(link.identity())
    existing=persistence.self_certificates.link_by_idempotency(tx,owner['id'],link.idempotency_key)
    if existing:
        rules.require_same_operation(existing['input_hash'],input_hash)
        return projection(existing,keys,origin)
    from app.application.self_certificate_participants import lock_authority
    lock_authority(tx,owner["id"],link.event_id)
    from app.core.certificate_features import certificate_features
    rules.require_pilot_available(certificate_features().link_allowed(owner['id'],link.event_id))
    event=require_event(tx,owner,link.event_id)
    model=repo.get_model(tx,owner,link.model_id,lock=True)
    rules.require_expected_revision(link.expected_revision_id,model['current_revision_id'])
    revision=checked_revision(tx,owner['id'],model['current_revision_id'])
    rules.require_current_schema(revision)
    public_id=new_id();version=keys.current
    token=keys.token('request-link',public_id,version)
    title=(event.get('draft') or {}).get('title') or event.get('slug') or 'فعالية'
    row=dict(id=new_id(),owner_account_id=owner['id'],event_id=event['id'],
        event_name_snapshot=text(title,250,True),model_name_snapshot=model['name'],revision_id=revision['id'],
        public_id=public_id,key_version=version,public_token_hash=token_hash(token),status='active',
        share_text_snapshot=link.share_text,config_hash=revision_hash(revision),input_hash=input_hash,idempotency_key=link.idempotency_key,row_version=1,created_at=utc_now())
    persistence.self_certificates.add_link(tx,row)
    return projection(row,keys,origin)

def list_links(tx,user,keys,origin,offset=0,limit=30):
    owner=require_capability(tx,user,'requests.read');repo.page(offset,limit)
    rows,total=persistence.self_certificates.links_page(tx,owner['id'],offset,limit)
    return dict(items=[projection(r,keys,origin) for r in rows],total=total)

def get_owned(tx,user,ident,lock=False):
    owner=require_capability(tx,user,'requests.read')
    row=persistence.self_certificates.link(tx,owner['id'],ident,for_update=lock)
    return require_found(row,'NOT_FOUND')

def set_state(tx,user,ident,body,keys,origin):
    row=get_owned(tx,user,ident,True)
    change=LinkStateChange.parse(body,row)
    if change.resumes:require_event(tx,user,row['event_id'])
    persistence.self_certificates.set_link_state(tx,ident,row['row_version'],
        dict(status=change.status,row_version=row['row_version']+1,disabled_at=None if change.resumes else utc_now()))
    return projection({**row,**body,'row_version':row['row_version']+1},keys,origin)

def get_public(tx,keys,token,lock=False):
    ident,version=keys.verify('request-link',token)
    row=persistence.self_certificates.public_link(tx,ident,version,for_update=lock)
    return rules.require_public_link(row,bool(row) and hmac.compare_digest(row['public_token_hash'],token_hash(token)))
