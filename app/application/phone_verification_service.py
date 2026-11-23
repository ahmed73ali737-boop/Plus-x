"""Optional proof of phone ownership through the Channel Gateway. Login never requires it; recovery stays administrator-assisted.

The gateway generates, delivers, hashes, expires and attempt-limits the code; this service keeps only the opaque verification id.
"""
from datetime import datetime, timedelta, timezone

from app.application.audit_service import new_id
from app.application.messaging_settings_service import effective_config
from app.application.ports import persistence
from app.domain import now
from app.domain import phone_verification as rules


def _ago(delta):
    return (datetime.now(timezone.utc) - delta).isoformat()


def available(tx):
    return effective_config(tx) is not None


def start(tx, user):
    cfg = effective_config(tx)
    rules.require_available(cfg is not None)
    phone = rules.require_phone(persistence.identity.phone_of(tx, user['id']))
    if persistence.identity.phone_is_verified(tx, user['id'], phone):
        return {'verified': True, 'phone': phone}
    rules.require_start_allowed(persistence.identity.phone_verifications_since(tx, user['id'], _ago(timedelta(hours=1))))
    out = rules.start_outcome(persistence.phone_verifier.start(cfg, phone))
    persistence.identity.add_phone_verification(tx, {'id': new_id(), 'user_id': user['id'], 'phone': phone,
                                                     'verification_id': out['verificationId'], 'created_at': now(), 'verified_at': None})
    return {'sent': True, 'expires_at': out.get('expiresAt'), 'attempts_left': out.get('attemptsLeft')}


def check(tx, user, body):
    rules.require_code(body.get('code') if isinstance(body, dict) else None)
    cfg = effective_config(tx)
    rules.require_available(cfg is not None)
    phone = rules.require_phone(persistence.identity.phone_of(tx, user['id']))
    pending = rules.require_pending(persistence.identity.pending_phone_verification(
        tx, user['id'], phone, _ago(timedelta(minutes=rules.PENDING_MINUTES))))
    rules.check_outcome(persistence.phone_verifier.check(cfg, pending['verification_id'], body['code']))
    persistence.identity.mark_phone_verified(tx, pending['id'], now())
    return {'verified': True, 'phone': phone}
