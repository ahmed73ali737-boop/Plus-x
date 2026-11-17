"""Browser/link deduplication and acceptance. A request and its job commit together."""
from datetime import datetime,timezone
from hashlib import sha256
import hmac,re,unicodedata
from app.application.audit_service import new_id
from app.application.ports import persistence
from app.application.self_certificate_clock import utc_now
from app.application.self_certificate_crypto import token_hash,REMEMBER_SECONDS
from app.application.self_certificate_access import owner_can_accept
from app.domain.self_certificates import participant_submission
from app.application.self_certificate_links import checked_revision,revision_hash
from app.application.self_certificate_rendering import fit_name
from app.domain import fail, Forbidden, Conflict, NotFound, Unavailable, DomainError
from app.application.self_certificate_metrics import record

CONSENT_TEXT='أقر بأنني شاركت في هذه الفعالية وأوافق على تزويد الجهة المنظمة باسمي ورقم هاتفي لإصدار الشهادة وإدارة سجلها.'
CONSENT_VERSION='self-declaration-ar-v1'

def browser_expiry(row):
    try:
        created=datetime.fromisoformat(row['created_at'])
        if created.tzinfo is None:raise ValueError()
        return int(created.timestamp()+REMEMBER_SECONDS-datetime.now(timezone.utc).timestamp())
    except (ValueError,TypeError):fail('BROWSER_SESSION_INVALID', Forbidden)

def current_browser(tx,keys,cookie):
    ident,version=keys.verify('browser',cookie or '')
    row=persistence.self_certificates.browser_session(tx,ident)
    if not row or not hmac.compare_digest(row['token_hash'],token_hash(cookie)):fail('BROWSER_SESSION_INVALID', Forbidden)
    if browser_expiry(row)<=0:fail('BROWSER_SESSION_EXPIRED', Forbidden)
    return row

def prepare_browser(tx,keys,seed,cookie):
    if cookie:
        try:return current_browser(tx,keys,cookie),cookie
        except DomainError as exc:
            if isinstance(exc,Unavailable):raise
    if not isinstance(seed,str) or not re.fullmatch('[a-f0-9]{64}',seed):fail('BROWSER_STORAGE_REQUIRED')
    ident=sha256(('certificate-browser:'+seed).encode()).hexdigest()
    token=keys.token('browser',ident)
    row=persistence.self_certificates.ensure_browser_session(tx,dict(id=ident,token_hash=token_hash(token),
        created_at=utc_now(),last_seen_at=utc_now()))
    if browser_expiry(row)<=0:fail('BROWSER_SESSION_EXPIRED', Forbidden)
    for version in keys.keys:
        candidate=keys.token('browser',ident,version)
        if hmac.compare_digest(row['token_hash'],token_hash(candidate)):
            persistence.self_certificates.touch_browser_session(tx,ident,utc_now())
            return row,candidate
    fail('CERTIFICATE_KEY_VERSION_UNAVAILABLE', Unavailable)

def find_request(tx,link_id,browser_id):
    return persistence.self_certificates.request_for_browser(tx,link_id,browser_id)

def state(tx,row,keys,origin):
    if not row:return dict(status='unregistered',error_code=None,certificate=None,receive_url=None,verification_url=None)
    result=dict(status=row['status'],error_code=row['error_code'],certificate=None,receive_url=None,verification_url=None)
    if row['status']=='issued':
        cert=persistence.self_certificates.certificate_for_request(tx,row)
        if not cert:fail('CERTIFICATE_STATE_UNAVAILABLE', Unavailable)
        result.update(receive_url=origin+'/certificates/receive/'+keys.token('receive',cert['id'],cert['key_version']),
            verification_url=origin+'/certificates/verify/'+cert['serial'])
    return result

def lock_authority(tx,owner_id,event_id):
    # Stable order; revocation/expiry and acceptance have an explicit authorization read point.
    persistence.self_certificates.lock_authority(tx,owner_id,event_id)

def normalize_phone(value):
    value=''.join(str(unicodedata.decimal(c)) if c.isdecimal() else c for c in value)
    value=re.sub(r'[ ()\-]','',value)
    if not re.fullmatch(r'\+?[0-9]{7,20}',value):fail('PHONE_INVALID')
    return value

def accept(tx,link,browser,keys,body,origin,accept_enabled):
    existing=find_request(tx,link['id'],browser['id'])
    if existing:
        record('deduplicated')
        return state(tx,existing,keys,origin),False
    if not accept_enabled:fail('CERTIFICATE_REQUESTS_PAUSED', Conflict)
    if link['status']!='active':fail('CERTIFICATE_LINK_PAUSED', Conflict)
    from app.core.certificate_features import certificate_features
    if not certificate_features().link_allowed(link['owner_account_id'],link['event_id']):fail('CERTIFICATE_PILOT_UNAVAILABLE', Conflict)
    lock_authority(tx,link['owner_account_id'],link['event_id'])
    if not owner_can_accept(tx,link['owner_account_id'],link['event_id']):fail('CERTIFICATE_LINK_UNAVAILABLE', Conflict)
    data=participant_submission(body)
    keys.check_nonce(data.request_nonce,browser['id'],link['id'])
    revision=checked_revision(tx,link['owner_account_id'],link['revision_id'])
    if revision_hash(revision)!=link['config_hash']:fail('REVISION_INTEGRITY_ERROR', Unavailable)
    layout=fit_name(data.name,revision['config'],revision['font_manifest'],revision['branding_manifest'],renderer_version=revision['renderer_version'])
    phone=normalize_phone(data.phone)
    ident=new_id();at=utc_now()
    row=dict(id=ident,owner_account_id=link['owner_account_id'],link_id=link['id'],
        browser_session_id=browser['id'],revision_id=revision['id'],participant_name_original=data.name,
        participant_name_normalized=layout['normalized_name'],phone_original=data.phone,phone_normalized=phone,
        consent=True,consent_text=CONSENT_TEXT,consent_text_version=CONSENT_VERSION,
        submitted_at_utc=at,status='registered',error_code=None,layout=layout)
    persistence.self_certificates.add_request_with_job(tx,row,dict(id=new_id(),request_id=ident,status='pending',attempts=0,available_at=at,created_at=at))
    return state(tx,row,keys,origin),True


def history(tx,user,keys_factory,origin,*,search,status,event_id,offset,limit):
    """The owner's participant requests with private receive links for issued ones."""
    rows,total=persistence.self_certificates.request_history(tx,user['id'],search,status,event_id,offset,limit)
    keyring=keys_factory() if any(row['certificate_id'] for row in rows) else None
    for row in rows:
        row['name_printed']=(row.pop('layout') or {}).get('name_printed',row['participant_name_original'])
        certificate_id=row.pop('certificate_id');version=row.pop('certificate_key_version')
        row['receive_url']=origin+'/certificates/receive/'+keyring.token('receive',certificate_id,version) if certificate_id else None
    return dict(items=rows,total=total)

def retry_failed(tx,user,request_id):
    """Requeue a failed generation; only failed requests with a failed job qualify."""
    store=persistence.self_certificates
    row=store.owned_request(tx,user['id'],request_id,for_update=True)
    if not row:fail('NOT_FOUND', NotFound)
    if row['status']!='failed':fail('REQUEST_NOT_FAILED', Conflict)
    job=store.job_for_request(tx,request_id,for_update=True)
    if job['status']!='failed':fail('REQUEST_NOT_FAILED', Conflict)
    store.requeue(tx,job['id'],request_id,utc_now())
