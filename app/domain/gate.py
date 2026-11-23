"""Gate admission: the GuestPresence aggregate enforces anti-passback and re-entry.

A guest's presence at an event is either ``outside`` or ``inside``. An entry
scan moves outside -> inside and an exit scan inside -> outside. With
anti-passback enabled a scan that does not match the current state is blocked
(``already_inside`` / ``already_outside``). The persistence adapter applies the
resulting transition with a conditional UPDATE on the expected state as an
optimistic-concurrency defence; the rule itself lives here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.domain.access_control import DEFAULT_GUEST_TYPE, AccessPolicy
from app.domain.errors import Conflict, Forbidden, NotFound, fail
from app.domain.values import text

ENTRY = 'entry'
EXIT = 'exit'
VALIDATE = 'validate'
SCAN_MODES = (ENTRY, EXIT, VALIDATE)

OUTSIDE = 'outside'
INSIDE = 'inside'
PRESENCE_STATES = (OUTSIDE, INSIDE)

ACCEPTED = 'accepted'
ALREADY_INSIDE = 'already_inside'
ALREADY_OUTSIDE = 'already_outside'
ADMITTABLE_REGISTRATION_STATUSES = ('registered', 'active')
OFFLINE_FUTURE_TOLERANCE_SECONDS = 300


def scan_mode(raw) -> str:
    mode = raw or ENTRY
    if mode not in SCAN_MODES:
        fail('SCAN_MODE_INVALID')
    return mode


def checkpoint_key(raw) -> str:
    return text(raw or 'main', 40, True)


@dataclass(frozen=True)
class GateTransition:
    """The outcome of presenting a pass at a gate.

    ``expected_state`` is the state the transition was decided against; the
    repository persists ``next_state`` only while the stored state still equals
    it when ``guarded`` is true (anti-passback).
    """

    status: str
    mode: str
    checkpoint: str
    scan_id: str
    expected_state: str
    next_state: str
    guarded: bool

    @property
    def accepted(self) -> bool:
        return self.status == ACCEPTED


@dataclass
class GuestPresence:
    """Aggregate root for one guest's presence at one event."""

    event_id: str
    guest_id: str
    state: str = OUTSIDE
    last_scan_id: str | None = None
    last_direction: str | None = None
    last_checkpoint: str | None = None
    updated_at: str | None = None

    @classmethod
    def new(cls, event_id: str, guest_id: str, at: str) -> 'GuestPresence':
        return cls(event_id=event_id, guest_id=guest_id, updated_at=at)

    @classmethod
    def from_record(cls, record: dict) -> 'GuestPresence':
        return cls(
            event_id=record['event_id'],
            guest_id=record['guest_id'],
            state=record.get('state') or OUTSIDE,
            last_scan_id=record.get('last_scan_id'),
            last_direction=record.get('last_direction'),
            last_checkpoint=record.get('last_checkpoint'),
            updated_at=record.get('updated_at'),
        )

    def to_record(self) -> dict:
        return {
            'event_id': self.event_id,
            'guest_id': self.guest_id,
            'state': self.state,
            'last_scan_id': self.last_scan_id,
            'last_direction': self.last_direction,
            'last_checkpoint': self.last_checkpoint,
            'updated_at': self.updated_at,
        }

    @property
    def has_exited(self) -> bool:
        return self.last_direction == EXIT and bool(self.last_scan_id)

    def pass_gate(self, mode: str, checkpoint: str, scan_id: str, policy: AccessPolicy,
                  *, entitlement_managed: bool, at: str) -> GateTransition:
        """Decide and apply an entry/exit scan.

        Managed admissions (invitation entitlements) are counted by the
        entitlement itself, so presence is then recorded without anti-passback.
        """
        if mode not in (ENTRY, EXIT):
            fail('SCAN_MODE_INVALID')
        expected = OUTSIDE if mode == ENTRY else INSIDE
        next_state = INSIDE if mode == ENTRY else OUTSIDE
        if (not entitlement_managed and mode == ENTRY
                and not policy.allow_reentry and self.has_exited):
            fail('REENTRY_NOT_ALLOWED', Forbidden)
        guarded = policy.anti_passback and not entitlement_managed
        if guarded and self.state != expected:
            return GateTransition(
                status=ALREADY_INSIDE if mode == ENTRY else ALREADY_OUTSIDE,
                mode=mode, checkpoint=checkpoint, scan_id=scan_id,
                expected_state=expected, next_state=self.state, guarded=True,
            )
        self.state = next_state
        self.last_scan_id = scan_id
        self.last_direction = mode
        self.last_checkpoint = checkpoint
        self.updated_at = at
        return GateTransition(
            status=ACCEPTED, mode=mode, checkpoint=checkpoint, scan_id=scan_id,
            expected_state=expected, next_state=next_state, guarded=guarded,
        )


def blocked_status(mode: str) -> str:
    """Status reported when a concurrent scan changed the presence first."""
    return ALREADY_INSIDE if mode == ENTRY else ALREADY_OUTSIDE


def admission_denial(registration_status: str, policy: AccessPolicy, checkpoint: str,
                     guest_type: str | None, at: datetime | None = None) -> str | None:
    """First reason a registered guest may not pass this checkpoint now, else None."""
    if registration_status not in ADMITTABLE_REGISTRATION_STATUSES:
        return 'GUEST_STATUS_' + str(registration_status).upper()
    rule = policy.checkpoint(checkpoint)
    if rule is None:
        return 'CHECKPOINT_NOT_FOUND'
    return rule.denial_reason(guest_type or DEFAULT_GUEST_TYPE, at)


def offline_scan_time(policy: AccessPolicy, *, admission_managed: bool, supplied_version,
                      client_time, current: datetime | None = None) -> datetime:
    """Accept an offline scan only against the current policy and a sane clock."""
    if admission_managed:
        fail('ONLINE_ADMISSION_REQUIRED', Conflict)
    supplied = text(supplied_version, 40, True)
    if supplied != policy.version():
        fail('ACCESS_POLICY_CHANGED', Conflict)
    at_time = _scan_time(client_time)
    current = current or datetime.now(timezone.utc)
    if (current - at_time).total_seconds() > policy.manifest_max_age_minutes * 60:
        fail('OFFLINE_SCAN_EXPIRED', Conflict)
    if at_time > current.replace(microsecond=0):
        # Small clock differences are handled at field setup; future scans are never trusted.
        if (at_time - current).total_seconds() > OFFLINE_FUTURE_TOLERANCE_SECONDS:
            fail('OFFLINE_SCAN_TIME_FUTURE')
    return at_time


def _scan_time(raw) -> datetime:
    try:
        value = datetime.fromisoformat(str(raw or ''))
    except (TypeError, ValueError):
        fail('OFFLINE_SCAN_TIME_INVALID')
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def device_checkpoint_allowed(device_metadata, checkpoint: str) -> None:
    """A gate device restricted to checkpoints may only scan at those checkpoints."""
    allowed = (device_metadata or {}).get('checkpoints')
    if allowed is not None and (not isinstance(allowed, list) or checkpoint not in allowed):
        fail('DEVICE_CHECKPOINT_SCOPE', Forbidden)


def require_scan_replay(existing: dict, use: dict | None, *, event_id: str, guest_number: str, mode: str,
                        checkpoint: str, quantity) -> None:
    """A scan id is idempotent only for the exact same scan; any difference is a conflict."""
    if use and use['quantity'] != quantity:
        fail('SCAN_ID_CONFLICT', Conflict)
    if (existing['event_id'] != event_id or existing['guest_number'] != guest_number.upper()
            or existing['direction'] != mode or existing['checkpoint'] != checkpoint):
        fail('SCAN_ID_CONFLICT', Conflict)


def require_invitation_when_managed(policy_enabled: bool, admission: dict) -> None:
    """When managed admission is on, only an invited guest's entitlement admits."""
    if policy_enabled and not admission['managed']:
        fail('INVITATION_REQUIRED', Forbidden)


def require_valid_admission(validated: dict) -> None:
    if validated['status'] != 'valid':
        fail(validated.get('reason') or 'ACCESS_DENIED', Forbidden)


def require_unmanaged_quantity(quantity) -> None:
    """Without an entitlement a scan admits exactly one person."""
    if quantity != 1:
        fail('ADMISSION_QUANTITY_INVALID')


def require_registered_guest(guest: dict | None) -> dict:
    """A pass number must belong to a guest registered for this event."""
    if not guest:
        fail('GUEST_NOT_REGISTERED', NotFound)
    return guest
