"""Phone/password accounts without OTP. Phone input never proves ownership.

Legacy px_users.email is a required unique login identifier. Phone-only accounts
use a reserved `tel:` principal in it, never a made-up deliverable email address.
The additive mapping avoids rebuilding the existing users table and foreign keys.
Public responses expose phone and null email for these principals.
"""
from app.application.access import active_window, can_read, event_permissions
from app.application.ports import persistence
from app.domain import contacts
from app.domain.authorization import committee_roles
from app.domain.contacts import account_phone, contact_identity, principal

__all__ = ['account_phone', 'bind_phone', 'can_review_accounts', 'contact_identity', 'find_by_phone',
           'find_contact_user', 'management_access', 'principal', 'public_user']


def find_contact_user(tx, email, phone):
    by_phone = find_by_phone(tx, phone) if phone else None
    matches = persistence.identity.users_with_email(tx, email) if contacts.looks_up_by_email(email) else []
    return contacts.resolve_contact_user(by_phone, matches)


def find_by_phone(tx, raw):
    return persistence.identity.user_by_phone(tx, account_phone(raw))


def bind_phone(tx, user_id, phone):
    existing = persistence.identity.phone_binding(tx, phone)
    owned = persistence.identity.phone_binding_of(tx, user_id)
    if contacts.phone_binding_action(existing, owned, user_id, phone) == 'bind':
        persistence.identity.bind_phone(tx, phone, user_id)


def public_user(tx, user):
    result = {key: user[key] for key in ('id', 'name', 'role', 'scope_id')}
    result['email'] = contacts.public_email(user['email'])
    result['phone'] = persistence.identity.phone_of(tx, user['id'])
    result['phone_verified'] = bool(result['phone']) and persistence.identity.phone_is_verified(tx, user['id'], result['phone'])
    result['must_change_password'] = bool(user.get('must_change_password'))
    result['management_access'] = bool(management_access(tx, user))
    result['can_review_account_requests'] = can_review_accounts(tx, user)
    return result


def management_access(tx, user):
    if persistence.access.has_active_membership(tx, user['id']):
        return True
    return any(can_read(tx, user, site) or (site['kind'] == 'event' and event_permissions(tx, user, site['id']))
               for site in persistence.sites.list_all(tx))


def can_review_accounts(tx, user):
    def owns_an_organization():
        return persistence.access.has_active_membership(tx, user['id'], role='owner')

    def has_committee_role():
        rows = persistence.access.user_assignments_with_roles(tx, user['id'], committee_roles())
        return any(active_window(row) for row in rows)

    return contacts.may_review_accounts(user['role'], owns_an_organization, has_committee_role)
