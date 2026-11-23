"""Domain unit tests: business rules with no database, web framework or HTTP."""
from datetime import datetime, timedelta, timezone

import pytest

from app.domain import Conflict, DomainError, Forbidden, InvalidInput, NotFound, Unauthenticated, fail
from app.domain.access_control import AccessPolicy, Checkpoint
from app.domain.account_requests import check_reviewer, granted_assignment_role, request_key
from app.domain.admission import AdmissionPolicy, DEFAULT_POLICY, Entitlement, Invitation, check_window
from app.domain.authorization import EVENT_PERMISSIONS, active_window, event_capabilities
from app.domain.devices import device_changes, heartbeat_values, require_gate_device, require_usable
from app.domain.gate import (
    ALREADY_INSIDE,
    ALREADY_OUTSIDE,
    INSIDE,
    OUTSIDE,
    GuestPresence,
    admission_denial,
    device_checkpoint_allowed,
    offline_scan_time,
)
from app.domain.guests import GuestRegistration, normalize_phone, require_active_pass
from app.domain.organizations import participation_changes
from app.domain.sites import authorize_new_site, publish, require_draft_revision
from app.domain.site_config import default_config
from app.domain.submissions import poll_answer

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


def policy(**access):
    return AccessPolicy.from_site_config({'access_control': access})


def presence(state=OUTSIDE, **values):
    return GuestPresence(event_id='event', guest_id='guest', state=state, **values)


# Errors ---------------------------------------------------------------------

def test_domain_errors_carry_a_category_not_an_http_status():
    with pytest.raises(NotFound) as error:
        fail('SITE_NOT_FOUND', NotFound)
    assert error.value.code == 'SITE_NOT_FOUND' and error.value.kind == 'not_found'
    with pytest.raises(InvalidInput):
        fail('TEXT_LENGTH')
    with pytest.raises(TypeError):
        fail('SITE_NOT_FOUND', 404)


# Access policy and checkpoints -------------------------------------------------

def test_access_policy_defaults_are_defined_once_and_shared_with_new_sites():
    assert default_config(kind='event')['access_control'] == AccessPolicy.defaults().to_dict()
    assert AccessPolicy.from_site_config({}).to_dict() == AccessPolicy.defaults().to_dict()


def test_access_policy_version_changes_with_the_policy():
    assert policy(anti_passback=True).version() != policy(anti_passback=False).version()


def test_access_policy_parse_rejects_unknown_guest_type_at_checkpoint():
    with pytest.raises(InvalidInput, match='CHECKPOINT_GUEST_TYPES_INVALID'):
        AccessPolicy.parse({'checkpoints': [{'key': 'vip-door', 'allowed_guest_types': ['royalty']}]})


def test_checkpoint_window_and_guest_type_rules():
    gate = Checkpoint.from_dict({'key': 'vip', 'allowed_guest_types': ['vip'],
                                 'start': (NOW - timedelta(hours=1)).isoformat(),
                                 'end': (NOW + timedelta(hours=1)).isoformat()})
    assert gate.denial_reason('vip', NOW) is None
    assert gate.denial_reason('visitor', NOW) == 'GUEST_TYPE_NOT_ALLOWED'
    assert gate.denial_reason('vip', NOW + timedelta(hours=2)) == 'CHECKPOINT_WINDOW_CLOSED'
    assert Checkpoint.from_dict({'key': 'x', 'enabled': False}).denial_reason('vip', NOW) == 'CHECKPOINT_DISABLED'
    assert Checkpoint.from_dict({'key': 'x', 'start': 'not-a-date'}).is_open(NOW) is False


def test_admission_denial_order_registration_then_checkpoint():
    assert admission_denial('cancelled', policy(), 'main', 'visitor', NOW) == 'GUEST_STATUS_CANCELLED'
    assert admission_denial('registered', policy(), 'side-door', 'visitor', NOW) == 'CHECKPOINT_NOT_FOUND'
    assert admission_denial('registered', policy(), 'main', None, NOW) is None


# GuestPresence aggregate: anti-passback and re-entry ------------------------------

def test_entry_then_exit_moves_presence_and_records_the_scan():
    guest = presence()
    entry = guest.pass_gate('entry', 'main', 'scan-1', policy(), entitlement_managed=False, at='t1')
    assert entry.accepted and entry.guarded and entry.expected_state == OUTSIDE
    assert (guest.state, guest.last_scan_id, guest.last_direction) == (INSIDE, 'scan-1', 'entry')
    exit_ = guest.pass_gate('exit', 'main', 'scan-2', policy(), entitlement_managed=False, at='t2')
    assert exit_.accepted and exit_.expected_state == INSIDE and guest.state == OUTSIDE


def test_anti_passback_blocks_a_second_entry_without_changing_presence():
    guest = presence(INSIDE, last_scan_id='scan-1', last_direction='entry')
    blocked = guest.pass_gate('entry', 'main', 'scan-2', policy(), entitlement_managed=False, at='t2')
    assert blocked.status == ALREADY_INSIDE and not blocked.accepted
    assert guest.last_scan_id == 'scan-1'
    assert presence().pass_gate('exit', 'main', 's', policy(), entitlement_managed=False, at='t').status == ALREADY_OUTSIDE


def test_without_anti_passback_transitions_are_unguarded():
    guest = presence(INSIDE)
    transition = guest.pass_gate('entry', 'main', 'scan-2', policy(anti_passback=False),
                                 entitlement_managed=False, at='t')
    assert transition.accepted and not transition.guarded


def test_reentry_after_exit_is_refused_when_policy_forbids_it():
    guest = presence(OUTSIDE, last_scan_id='scan-2', last_direction='exit')
    with pytest.raises(Forbidden, match='REENTRY_NOT_ALLOWED'):
        guest.pass_gate('entry', 'main', 'scan-3', policy(allow_reentry=False), entitlement_managed=False, at='t')
    assert presence().pass_gate('entry', 'main', 'first', policy(allow_reentry=False),
                                entitlement_managed=False, at='t').accepted


def test_managed_entitlements_are_counted_by_the_entitlement_not_anti_passback():
    guest = presence(INSIDE, last_scan_id='a', last_direction='exit')
    transition = guest.pass_gate('entry', 'main', 'b', policy(allow_reentry=False), entitlement_managed=True, at='t')
    assert transition.accepted and not transition.guarded


# Offline scans and devices --------------------------------------------------------

def test_offline_scan_requires_current_policy_and_sane_clock():
    current = policy()
    stamp = (NOW - timedelta(minutes=5)).isoformat()
    assert offline_scan_time(current, admission_managed=False, supplied_version=current.version(),
                             client_time=stamp, current=NOW) == NOW - timedelta(minutes=5)
    cases = [
        (dict(admission_managed=True, supplied_version=current.version(), client_time=stamp), 'ONLINE_ADMISSION_REQUIRED'),
        (dict(admission_managed=False, supplied_version='stale', client_time=stamp), 'ACCESS_POLICY_CHANGED'),
        (dict(admission_managed=False, supplied_version=current.version(),
              client_time=(NOW - timedelta(days=30)).isoformat()), 'OFFLINE_SCAN_EXPIRED'),
        (dict(admission_managed=False, supplied_version=current.version(),
              client_time=(NOW + timedelta(hours=1)).isoformat()), 'OFFLINE_SCAN_TIME_FUTURE'),
        (dict(admission_managed=False, supplied_version=current.version(), client_time='garbage'),
         'OFFLINE_SCAN_TIME_INVALID'),
    ]
    for arguments, code in cases:
        with pytest.raises(DomainError, match=code):
            offline_scan_time(current, current=NOW, **arguments)


def test_device_rules_scope_shift_and_telemetry():
    device = {'id': 'd', 'site_id': 'event', 'device_type': 'operator', 'status': 'active',
              'metadata_json': {'checkpoints': ['main'], 'valid_until': '2026-10-19T13:00:00+00:00'},
              'app_version': '1'}
    assert require_usable(device, '2026-10-19T12:00:00+00:00') is device
    with pytest.raises(Unauthenticated, match='DEVICE_SHIFT_INACTIVE'):
        require_usable(device, '2026-10-19T14:00:00+00:00')
    with pytest.raises(Forbidden, match='DEVICE_EVENT_SCOPE'):
        require_gate_device(device, 'other-event')
    with pytest.raises(Forbidden, match='DEVICE_CHECKPOINT_SCOPE'):
        device_checkpoint_allowed(device['metadata_json'], 'vip')
    values = heartbeat_values(device, {'metadata': {'checkpoints': [], 'browser': 'x', 'valid_until': None}}, 'now')
    assert values['metadata_json']['checkpoints'] == ['main'] and values['metadata_json']['browser'] == 'x'
    with pytest.raises(InvalidInput, match='NO_CHANGES'):
        device_changes()


# Guests ------------------------------------------------------------------------------

def test_phone_normalization_and_registration_guards():
    assert normalize_phone('0777 123 456') == normalize_phone('+967777123456') == '+967777123456'
    event = {'kind': 'event', 'draft': default_config(kind='event')}
    with pytest.raises(InvalidInput, match='GUEST_CONSENT_REQUIRED'):
        GuestRegistration(event, {'phone': '777123456'}, allow_guest_type=False)
    with pytest.raises(InvalidInput, match='GUEST_TYPE_INVALID'):
        GuestRegistration(event, {'phone': '777123456', 'consent': True, 'guest_type': 'royalty'}, allow_guest_type=True)
    public = GuestRegistration(event, {'phone': '777123456', 'consent': True, 'guest_type': 'vip',
                                       'metadata': {'invitation_id': 'forged', 'note': 'ok'}}, allow_guest_type=False)
    assert public.guest_type == 'visitor' and public.metadata == {'note': 'ok'}
    assert public.profile_updates(allow_profile_update=False) == {}


def test_inactive_pass_is_gone():
    from app.domain import Gone

    with pytest.raises(Gone):
        require_active_pass({'event_guest_status': 'revoked'})


# Managed admission -----------------------------------------------------------------

def stored_policy(**changes):
    return {**DEFAULT_POLICY, 'rev': 1, **changes}


def test_admission_policy_revision_and_validation():
    with pytest.raises(Conflict, match='ADMISSION_POLICY_REVISION_CONFLICT'):
        AdmissionPolicy.revise(stored_policy(), {'rev': 7})
    with pytest.raises(InvalidInput, match='VISIBILITY_INVALID'):
        AdmissionPolicy.revise(stored_policy(), {'visibility': 'secret'})
    revised = AdmissionPolicy.revise(stored_policy(), {'enabled': True, 'days': [{'date': '2026-10-20', 'capacity': '5'}]})
    assert revised['days'] == [{'date': '2026-10-20', 'capacity': 5}]


def test_admission_policy_never_silently_invalidates_admitted_people():
    approved = [{'days': ['2026-10-20'], 'status': 'approved'}]
    with pytest.raises(Conflict, match='ENTRY_MODE_HAS_APPROVALS'):
        AdmissionPolicy.guard_fixed_admissions(stored_policy(), stored_policy(entry_mode='daily'), approved)
    revised = stored_policy(days=[{'date': '2026-10-21', 'capacity': 0}])
    with pytest.raises(Conflict, match='DAY_HAS_APPROVALS'):
        AdmissionPolicy.guard_days(revised, approved, {})
    with pytest.raises(Conflict, match='CAPACITY_BELOW_RESERVED'):
        AdmissionPolicy.guard_days(stored_policy(days=[{'date': '2026-10-20', 'capacity': 2}]), [], {'2026-10-20': 3})


def test_registration_window():
    with pytest.raises(Conflict, match='REGISTRATION_CLOSED'):
        check_window(stored_policy(registration_closes_at='2026-01-01T00:00:00+00:00'), '2026-02-01T00:00:00+00:00')


def invitation(**changes):
    return {'status': 'invited', 'response': 'pending', 'companions': 0, 'days': [], 'answers': {},
            'max_companions': 2, 'allowed_days': [], 'revision': 1, 'guest_id': 'guest', **changes}


def test_invitation_state_machine():
    rsvp = {'response': 'accepted', 'consent': True, 'companions': 1}
    changes = Invitation.rsvp(invitation(), stored_policy(), rsvp)
    assert changes['revision'] == 2 and Invitation.outcome_after_rsvp(changes, stored_policy()) == 'approve'
    assert Invitation.outcome_after_rsvp(changes, stored_policy(registration_mode='manual')) == 'pending_approval'
    assert Invitation.rsvp(invitation(**{key: changes[key] for key in ('response', 'companions', 'days', 'answers')}),
                           stored_policy(), rsvp) is None
    with pytest.raises(Conflict, match='INVITATION_INACTIVE'):
        Invitation.rsvp(invitation(status='revoked'), stored_policy(), rsvp)
    with pytest.raises(Conflict, match='INVITATION_NOT_PENDING_REVIEW'):
        Invitation.check_review(invitation(), 'approve', 1)
    with pytest.raises(Conflict, match='DAY_CAPACITY_FULL'):
        Invitation.check_capacity(invitation(days=['2026-10-20'], companions=1),
                                  stored_policy(days=[{'date': '2026-10-20', 'capacity': 3}]), {'2026-10-20': 2})


def test_entitlement_day_slot_and_quantity():
    daily = stored_policy(entry_mode='daily', timezone='UTC')
    day, slot = Entitlement.admission_day(invitation(days=['2026-10-19']), daily, NOW)
    assert (day, slot) == ('2026-10-19', '2026-10-19')
    with pytest.raises(Conflict, match='ATTENDANCE_DAY_NOT_ALLOWED'):
        Entitlement.admission_day(invitation(days=['2026-10-20']), daily, NOW)
    with pytest.raises(Conflict, match='ADMISSION_ALREADY_USED'):
        Entitlement.requested_quantity({'quantity': 2, 'consumed': 2}, {'quantity': 1})


# Sites, authorization, organizations, submissions, account requests -------------------

def test_site_publication_and_draft_revision():
    site = {'id': 's', 'draft': default_config('Expo', 'event'), 'draft_rev': 3, 'published_version': 4}
    publication = publish(site)
    assert publication.version == 5 and publication.config['title'] == 'Expo'
    with pytest.raises(Conflict, match='DRAFT_CHANGED_REFRESH_REQUIRED'):
        require_draft_revision(site, 2)
    with pytest.raises(Forbidden):
        authorize_new_site('organizer', {'kind': 'platform'}, 'event')
    assert authorize_new_site('platform', {'kind': 'platform'}, 'event') == 'event'


def test_event_capabilities_follow_roles_and_shift_windows():
    scanner = {'role': 'member', 'active': 1, 'scope_id': None}
    assignment = {'role': 'scanner', 'status': 'active', 'valid_until': '2026-10-19T13:00:00+00:00'}
    assert event_capabilities(scanner, 'e', [assignment], '2026-10-19T12:00:00+00:00') == {'guests.read', 'guests.checkin'}
    assert event_capabilities(scanner, 'e', [assignment], '2026-10-19T14:00:00+00:00') == frozenset()
    assert event_capabilities({'role': 'platform', 'active': 1}, 'e', []) == EVENT_PERMISSIONS
    assert active_window({'status': 'active', 'valid_from': 'naive-garbage'}) is False


def test_participation_update_requires_a_change():
    with pytest.raises(InvalidInput, match='NO_CHANGES'):
        participation_changes({'status': 'unknown'})


def test_poll_must_match_the_live_version_and_be_open():
    poll = {'code': 'p', 'kind': 'poll', 'enabled': True, 'qtype': 'single_choice', 'required': False,
            'options': [{'key': 'a'}, {'key': 'b'}], 'min': 0, 'max': 10, 'rows': [], 'status': 'open',
            'start': '', 'end': ''}
    config = {'records': [poll]}
    assert poll_answer(config, config, 'p', 'a', NOW) == {'answer': 'a'}
    changed = {'records': [{**poll, 'options': [{'key': 'a'}, {'key': 'c'}]}]}
    with pytest.raises(Conflict, match='POLL_CHANGED_REFRESH_REQUIRED'):
        poll_answer(config, changed, 'p', 'a', NOW)
    with pytest.raises(Conflict, match='POLL_CLOSED'):
        poll_answer(config, {'records': [{**poll, 'status': 'closed'}]}, 'p', 'a', NOW)


def test_account_request_reviewer_independence_and_granted_scope():
    record = {'requested_by': 'alice', 'email': 'bob@example.test', 'requested_role': 'organizer',
              'assignment_role': None}
    with pytest.raises(Forbidden, match='ACCOUNT_REQUEST_SELF_REVIEW'):
        check_reviewer({'id': 'alice', 'email': 'x@example.test'}, record, {'existing_user_id': None}, 'approved')
    assert granted_assignment_role(record, {'purpose': 'site'}, None) == 'event_manager'
    assert granted_assignment_role({**record, 'requested_role': 'agency'}, {'purpose': 'organization'}, 'org') is None
    with pytest.raises(InvalidInput, match='ACCOUNT_REQUEST_KEY_INVALID'):
        request_key('short', 'unused')
