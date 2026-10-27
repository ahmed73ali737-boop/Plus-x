"""Browser/link deduplication and acceptance. A request and its job commit together."""
from datetime import datetime,timezone
from hashlib import sha256
import hmac,re,unicodedata
from fastapi import HTTPException
from sqlalchemy import select,insert,update
from app.db import users,memberships,organizations,event_participations,assignments
from app.self_certificates_db import browser_sessions,requests,jobs,certificates
from app.application.audit_service import new_id
from app.application.self_certificate_clock import utc_now
from app.application.self_certificate_crypto import token_hash,REMEMBER_SECONDS
from app.application.self_certificate_access import owner_can_accept
from app.application.self_certificate_contracts import parse_participant_input
from app.application.self_certificate_links import checked_revision,revision_hash
from app.application.self_certificate_rendering import fit_name
from app.domain import fail
from app.application.self_certificate_metrics import record

CONSENT_TEXT='أقر بأنني شاركت في هذه الفعالية وأوافق على تزويد الجهة المنظمة باسمي ورقم هاتفي لإصدار الشهادة وإدارة سجلها.'
CONSENT_VERSION='self-declaration-ar-v1'

def browser_expiry(row):
    try:
        created=datetime.fromisoformat(row['created_at'])
        if created.tzinfo is None:raise ValueError()
        return int(created.timestamp()+REMEMBER_SECONDS-datetime.now(timezone.utc).timestamp())
    except (ValueError,TypeError):fail('BROWSER_SESSION_INVALID',403)

def current_browser(conn,keys,cookie):
    ident,version=keys.verify('browser',cookie or '')
    row=conn.execute(select(browser_sessions).where(browser_sessions.c.id==ident)).mappings().first()
    if not row or not hmac.compare_digest(row['token_hash'],token_hash(cookie)):fail('BROWSER_SESSION_INVALID',403)
    if browser_expiry(row)<=0:fail('BROWSER_SESSION_EXPIRED',403)
    return dict(row)

def prepare_browser(conn,keys,seed,cookie):
    if cookie:
        try:return current_browser(conn,keys,cookie),cookie
        except HTTPException as exc:
            if exc.status_code==503:raise
    if not isinstance(seed,str) or not re.fullmatch('[a-f0-9]{64}',seed):fail('BROWSER_STORAGE_REQUIRED',422)
    ident=sha256(('certificate-browser:'+seed).encode()).hexdigest()
    token=keys.token('browser',ident)
    dialect=conn.dialect.name
    if dialect=='postgresql':
        from sqlalchemy.dialects.postgresql import insert as upsert
    else:
        from sqlalchemy.dialects.sqlite import insert as upsert
    conn.execute(upsert(browser_sessions).values(id=ident,token_hash=token_hash(token),created_at=utc_now(),last_seen_at=utc_now())
        .on_conflict_do_nothing(index_elements=[browser_sessions.c.id]))
    row=dict(conn.execute(select(browser_sessions).where(browser_sessions.c.id==ident)).mappings().one())
    if browser_expiry(row)<=0:fail('BROWSER_SESSION_EXPIRED',403)
    for version in keys.keys:
        candidate=keys.token('browser',ident,version)
        if hmac.compare_digest(row['token_hash'],token_hash(candidate)):
            conn.execute(update(browser_sessions).where(browser_sessions.c.id==ident).values(last_seen_at=utc_now()))
            return row,candidate
    fail('CERTIFICATE_KEY_VERSION_UNAVAILABLE',503)

def find_request(conn,link_id,browser_id):
    row=conn.execute(select(requests).where(requests.c.link_id==link_id,requests.c.browser_session_id==browser_id)).mappings().first()
    return dict(row) if row else None

def state(conn,row,keys,origin):
    if not row:return dict(status='unregistered',error_code=None,certificate=None,receive_url=None,verification_url=None)
    result=dict(status=row['status'],error_code=row['error_code'],certificate=None,receive_url=None,verification_url=None)
    if row['status']=='issued':
        cert=conn.execute(select(certificates).where(certificates.c.request_id==row['id'],
            certificates.c.owner_account_id==row['owner_account_id'],certificates.c.link_id==row['link_id'])).mappings().first()
        if not cert:fail('CERTIFICATE_STATE_UNAVAILABLE',503)
        result.update(receive_url=origin+'/certificates/receive/'+keys.token('receive',cert['id'],cert['key_version']),
            verification_url=origin+'/certificates/verify/'+cert['serial'])
    return result

def lock_authority(conn,owner_id,event_id):
    # Stable order; revocation/expiry and acceptance have an explicit authorization read point.
    conn.execute(select(users.c.id).where(users.c.id==owner_id).with_for_update()).all()
    rows=conn.execute(select(memberships.c.organization_id).where(memberships.c.user_id==owner_id)
        .order_by(memberships.c.organization_id).with_for_update()).scalars().all()
    if rows:
        conn.execute(select(organizations.c.id).where(organizations.c.id.in_(rows)).order_by(organizations.c.id).with_for_update()).all()
        conn.execute(select(event_participations.c.id).where(event_participations.c.event_id==event_id,
            event_participations.c.organization_id.in_(rows)).order_by(event_participations.c.id).with_for_update()).all()
    conn.execute(select(assignments.c.id).where(assignments.c.user_id==owner_id,assignments.c.site_id==event_id)
        .order_by(assignments.c.id).with_for_update()).all()

def normalize_phone(value):
    value=''.join(str(unicodedata.decimal(c)) if c.isdecimal() else c for c in value)
    value=re.sub(r'[ ()\-]','',value)
    if not re.fullmatch(r'\+?[0-9]{7,20}',value):fail('PHONE_INVALID')
    return value

def accept(conn,link,browser,keys,body,origin,accept_enabled):
    existing=find_request(conn,link['id'],browser['id'])
    if existing:
        record('deduplicated')
        return state(conn,existing,keys,origin),False
    if not accept_enabled:fail('CERTIFICATE_REQUESTS_PAUSED',409)
    if link['status']!='active':fail('CERTIFICATE_LINK_PAUSED',409)
    from app.core.certificate_features import certificate_features
    if not certificate_features().link_allowed(link['owner_account_id'],link['event_id']):fail('CERTIFICATE_PILOT_UNAVAILABLE',409)
    lock_authority(conn,link['owner_account_id'],link['event_id'])
    if not owner_can_accept(conn,link['owner_account_id'],link['event_id']):fail('CERTIFICATE_LINK_UNAVAILABLE',409)
    data=parse_participant_input(body)
    keys.check_nonce(data.request_nonce,browser['id'],link['id'])
    revision=checked_revision(conn,link['owner_account_id'],link['revision_id'])
    if revision_hash(revision)!=link['config_hash']:fail('REVISION_INTEGRITY_ERROR',503)
    layout=fit_name(data.name,revision['config'],revision['font_manifest'],revision['branding_manifest'],renderer_version=revision['renderer_version'])
    phone=normalize_phone(data.phone)
    ident=new_id();at=utc_now()
    row=dict(id=ident,owner_account_id=link['owner_account_id'],link_id=link['id'],
        browser_session_id=browser['id'],revision_id=revision['id'],participant_name_original=data.name,
        participant_name_normalized=layout['normalized_name'],phone_original=data.phone,phone_normalized=phone,
        consent=True,consent_text=CONSENT_TEXT,consent_text_version=CONSENT_VERSION,
        submitted_at_utc=at,status='registered',error_code=None,layout=layout)
    conn.execute(insert(requests).values(**row))
    conn.execute(insert(jobs).values(id=new_id(),request_id=ident,status='pending',attempts=0,available_at=at,created_at=at))
    return state(conn,row,keys,origin),True
