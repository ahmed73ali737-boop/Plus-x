"""Browser/link deduplication and acceptance. A request and its job commit together."""
import hmac
from datetime import datetime, timezone
from hashlib import sha256

from app.application.audit_service import new_id
from app.application.ports import persistence
from app.application.self_certificate_access import owner_can_accept
from app.application.self_certificate_clock import utc_now
from app.application.self_certificate_crypto import REMEMBER_SECONDS, token_hash
from app.application.self_certificate_links import checked_revision, revision_hash
from app.application.self_certificate_metrics import record
from app.application.self_certificate_rendering import fit_name
from app.domain import DomainError, Unavailable
from app.domain import self_certificates as rules
from app.domain.self_certificates import (
    CONSENT_TEXT,
    CONSENT_VERSION,
    browser_remaining_seconds,
    declared_phone,
    participant_submission,
    require_accepting,
    require_browser_not_expired,
    require_failed_job,
    require_failed_request,
    require_revision_intact,
)

__all__ = ['CONSENT_TEXT', 'CONSENT_VERSION', 'accept', 'browser_expiry', 'current_browser', 'find_request',
           'history', 'lock_authority', 'normalize_phone', 'prepare_browser', 'retry_failed', 'state']


def browser_expiry(row):
    return browser_remaining_seconds(row['created_at'], REMEMBER_SECONDS, datetime.now(timezone.utc))


def current_browser(tx, keys, cookie):
    ident, _version = keys.verify('browser', cookie or '')
    row = persistence.self_certificates.browser_session(tx, ident)
    rules.require_browser_token(row, bool(row) and hmac.compare_digest(row['token_hash'], token_hash(cookie)))
    require_browser_not_expired(browser_expiry(row))
    return row


def prepare_browser(tx, keys, seed, cookie):
    if cookie:
        try:
            return current_browser(tx, keys, cookie), cookie
        except DomainError as exc:
            if isinstance(exc, Unavailable):
                raise
    rules.require_browser_seed(seed)
    ident = sha256(('certificate-browser:' + seed).encode()).hexdigest()
    token = keys.token('browser', ident)
    row = persistence.self_certificates.ensure_browser_session(
        tx, dict(id=ident, token_hash=token_hash(token), created_at=utc_now(), last_seen_at=utc_now()))
    require_browser_not_expired(browser_expiry(row))
    matching = next((version for version in keys.keys
                     if hmac.compare_digest(row['token_hash'], token_hash(keys.token('browser', ident, version)))), None)
    rules.require_key_version_available(matching)
    persistence.self_certificates.touch_browser_session(tx, ident, utc_now())
    return row, keys.token('browser', ident, matching)


def find_request(tx,link_id,browser_id):
    return persistence.self_certificates.request_for_browser(tx,link_id,browser_id)

def state(tx,row,keys,origin):
    if not row:return dict(status='unregistered',error_code=None,certificate=None,receive_url=None,verification_url=None)
    result=dict(status=row['status'],error_code=row['error_code'],certificate=None,receive_url=None,verification_url=None)
    if row['status']=='issued':
        cert=rules.require_issued_certificate(persistence.self_certificates.certificate_for_request(tx,row))
        result.update(receive_url=origin+'/certificates/receive/'+keys.token('receive',cert['id'],cert['key_version']),
            verification_url=origin+'/certificates/verify/'+cert['serial'])
    return result

def lock_authority(tx,owner_id,event_id):
    # Stable order; revocation/expiry and acceptance have an explicit authorization read point.
    persistence.self_certificates.lock_authority(tx,owner_id,event_id)

normalize_phone = declared_phone

def accept(tx,link,browser,keys,body,origin,accept_enabled):
    existing=find_request(tx,link['id'],browser['id'])
    if existing:
        record('deduplicated')
        return state(tx,existing,keys,origin),False
    require_accepting(accept_enabled, link)
    from app.core.certificate_features import certificate_features
    rules.require_pilot_available(certificate_features().link_allowed(link['owner_account_id'],link['event_id']))
    lock_authority(tx,link['owner_account_id'],link['event_id'])
    rules.require_owner_still_authorised(owner_can_accept(tx,link['owner_account_id'],link['event_id']))
    data=participant_submission(body)
    keys.check_nonce(data.request_nonce,browser['id'],link['id'])
    revision=checked_revision(tx,link['owner_account_id'],link['revision_id'])
    require_revision_intact(link['config_hash'], revision_hash(revision))
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
    require_failed_request(store.owned_request(tx,user['id'],request_id,for_update=True))
    job=store.job_for_request(tx,request_id,for_update=True)
    require_failed_job(job)
    store.requeue(tx,job['id'],request_id,utc_now())
