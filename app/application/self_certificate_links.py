"""Owner-only immutable request links; library membership is checked independently."""
import hmac
from sqlalchemy import select,insert,update,func
from app.self_certificates_db import links,revisions,assets
from app.application import self_certificate_repository as repo
from app.application.self_certificate_access import require_capability,require_event
from app.application.self_certificate_crypto import fingerprint,token_hash
from app.application.self_certificate_clock import utc_now
from app.application.audit_service import new_id
from app.domain import fail,text

def revision_hash(revision):
    return fingerprint({k:v for k,v in revision.items() if k!='origin_model_id'})

def checked_revision(conn,owner,revision_id):
    row=conn.execute(select(revisions).where(revisions.c.id==revision_id,revisions.c.owner_account_id==owner)).mappings().first()
    if not row:fail('REVISION_UNAVAILABLE',409)
    row=dict(row)
    for ident,kind in ((row['background_asset_id'],'background'),(row['stamp_asset_id'],'stamp')):
        if ident is None:continue
        asset=conn.execute(select(assets).where(assets.c.id==ident,assets.c.owner_account_id==owner,assets.c.kind==kind)).mappings().first()
        if not asset:fail('ASSET_OWNER_MISMATCH',409)
    return row

def projection(row,keys,origin):
    token=keys.token('request-link',row['public_id'],row['key_version'])
    return {k:row[k] for k in ('id','event_id','event_name_snapshot','model_name_snapshot','status','share_text_snapshot','row_version','created_at')}|{'request_url':origin+'/certificates/request/'+token,'qr_url':'/api/self-certificates/links/'+row['id']+'/qr'}

def create(conn,user,keys,origin,body):
    if not isinstance(body,dict) or set(body)-{'event_id','model_id','share_text','idempotency_key','expected_revision_id'} or not {'event_id','model_id','share_text','idempotency_key'}<=set(body):fail('LINK_INPUT_INVALID')
    owner=require_capability(conn,user,'links.manage')
    event_id=text(body['event_id'],64,True);model_id=text(body['model_id'],64,True)
    key=text(body['idempotency_key'],80,True)
    share=text(body['share_text'],4000,True)
    identity=dict(event_id=event_id,model_id=model_id,share_text=share)
    expected_revision_id=body.get('expected_revision_id')
    if 'expected_revision_id' in body:
        identity['expected_revision_id']=text(expected_revision_id,64,True)
    input_hash=fingerprint(identity)
    existing=conn.execute(select(links).where(links.c.owner_account_id==owner['id'],links.c.idempotency_key==key)).mappings().first()
    if existing:
        if existing['input_hash']!=input_hash:fail('IDEMPOTENCY_CONFLICT',409)
        return projection(existing,keys,origin)
    from app.application.self_certificate_participants import lock_authority
    lock_authority(conn,owner["id"],event_id)
    from app.core.certificate_features import certificate_features
    if not certificate_features().link_allowed(owner['id'],event_id):fail('CERTIFICATE_PILOT_UNAVAILABLE',409)
    event=require_event(conn,owner,event_id)
    model=repo.get_model(conn,owner,model_id,lock=True)
    if expected_revision_id is not None and expected_revision_id!=model['current_revision_id']:
        fail('MODEL_REVISION_CHANGED',409)
    revision=checked_revision(conn,owner['id'],model['current_revision_id'])
    if revision['schema_version']!=2:fail('MODEL_UPGRADE_REQUIRED',409)
    public_id=new_id();version=keys.current
    token=keys.token('request-link',public_id,version)
    title=(event.get('draft') or {}).get('title') or event.get('slug') or 'فعالية'
    row=dict(id=new_id(),owner_account_id=owner['id'],event_id=event['id'],
        event_name_snapshot=text(title,250,True),model_name_snapshot=model['name'],revision_id=revision['id'],
        public_id=public_id,key_version=version,public_token_hash=token_hash(token),status='active',
        share_text_snapshot=share,config_hash=revision_hash(revision),input_hash=input_hash,idempotency_key=key,row_version=1,created_at=utc_now())
    conn.execute(insert(links).values(**row))
    return projection(row,keys,origin)

def list_links(conn,user,keys,origin,offset=0,limit=30):
    owner=require_capability(conn,user,'requests.read');repo.page(offset,limit)
    scope=links.c.owner_account_id==owner['id']
    return dict(items=[projection(r,keys,origin) for r in conn.execute(select(links).where(scope)
        .order_by(links.c.created_at.desc(),links.c.id).offset(offset).limit(limit)).mappings()],
        total=conn.execute(select(func.count()).select_from(links).where(scope)).scalar_one())

def get_owned(conn,user,ident,lock=False):
    owner=require_capability(conn,user,'requests.read')
    query=select(links).where(links.c.id==ident,links.c.owner_account_id==owner['id'])
    if lock:query=query.with_for_update()
    row=conn.execute(query).mappings().first()
    if not row:fail('NOT_FOUND',404)
    return dict(row)

def set_state(conn,user,ident,body,keys,origin):
    row=get_owned(conn,user,ident,True)
    if not isinstance(body,dict) or set(body)!={'status','row_version'} or body['status'] not in ('active','paused'):fail('LINK_STATE_INVALID')
    if type(body['row_version']) is not int or body['row_version']!=row['row_version']:fail('VERSION_CONFLICT',409)
    if body['status']=='active':require_event(conn,user,row['event_id'])
    conn.execute(update(links).where(links.c.id==ident,links.c.row_version==row['row_version'])
        .values(status=body['status'],row_version=row['row_version']+1,disabled_at=utc_now() if body['status']=='paused' else None))
    return projection({**row,**body,'row_version':row['row_version']+1},keys,origin)

def get_public(conn,keys,token,lock=False):
    ident,version=keys.verify('request-link',token)
    query=select(links).where(links.c.public_id==ident,links.c.key_version==version)
    if lock:query=query.with_for_update()
    row=conn.execute(query).mappings().first()
    if not row or not hmac.compare_digest(row['public_token_hash'],token_hash(token)):fail('NOT_FOUND',404)
    return dict(row)
