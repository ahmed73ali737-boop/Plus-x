"""Guest desk use cases behind the public registration and staff guest routes."""
from __future__ import annotations

from app.application.access import event_permissions
from app.application.event_visibility import require_public_event
from app.application.guest_gate_service import event_presence_map
from app.application.guest_service import list_event_guests, register_guest
from app.application.invitation_service import get_policy
from app.domain.admission import require_direct_registration_open
from app.domain.sites import require_event_target
from app.domain.guests import guest_qr_payload

SECRET_REGISTRATION_FIELDS = ('pass_token', 'internal_guest_number', 'phone_hash', 'pass_token_hash')


def require_unmanaged_admission(tx, event_id: str) -> None:
    """Direct registration is closed while invitations manage admission."""
    require_direct_registration_open(get_policy(tx, event_id)['enabled'])


def require_open_public_registration(tx, event: dict) -> None:
    """Self-registration is only for public/unlisted events without managed admission."""
    require_public_event(tx, event['id'])
    require_unmanaged_admission(tx, event['id'])


def require_event_kind(event: dict) -> dict:
    return require_event_target(event)


def staff_guest_list(tx, user, event_id: str) -> list[dict]:
    """Guests with live presence; phone numbers only for users allowed to export."""
    presence = event_presence_map(tx, event_id)
    rows = []
    for guest in list_event_guests(tx, event_id):
        guest['presence'] = presence.get(guest['id'], {}).get('state', 'outside')
        if 'guests.export' not in event_permissions(tx, user, event_id):
            guest.pop('phone', None)
        rows.append(guest)
    return rows


def staff_register(tx, event: dict, body: dict, public_origin: str) -> tuple[dict, dict]:
    """Staff registration (profile and guest type may be set); returns (guest, safe view)."""
    require_unmanaged_admission(tx, event['id'])
    guest = register_guest(tx, event, {**body, 'consent': body.get('consent') is True},
                           allow_profile_update=True, allow_guest_type=True)
    view = {key: value for key, value in guest.items() if key not in SECRET_REGISTRATION_FIELDS}
    return guest, {**view, 'qr_url': guest_qr_payload(event['slug'], guest['guest_number'], public_origin)}
