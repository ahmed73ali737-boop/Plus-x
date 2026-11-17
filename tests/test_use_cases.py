"""Use-case tests against in-memory ports (no database, no HTTP).

The application layer only sees the persistence ports, so these fakes are
enough to exercise the gate, publishing and collection orchestration.
"""
from contextlib import contextmanager

import pytest

from app.application import guest_gate_service as gate
from app.application import publishing
from app.application.ports import persistence
from app.domain import Conflict, Forbidden, NotFound
from app.domain.access_control import AccessPolicy
from app.domain.gate import GuestPresence
from app.domain.site_config import default_config

PASS = 'G-' + 'A' * 30


class FakeTransactions:
    @contextmanager
    def savepoint(self, tx):
        yield

    @contextmanager
    def write(self, database):
        yield database

    read = write

    def is_transient_failure(self, error):
        return False

    def is_conflict(self, error):
        return False


class FakeSites:
    def __init__(self, *sites):
        self.rows = {site['id']: dict(site) for site in sites}
        self.versions = {}
        self.stale = False

    def get(self, tx, site_id):
        return dict(self.rows[site_id]) if site_id in self.rows else None

    def advance_published_version(self, tx, site, version):
        if self.stale:
            return False
        self.rows[site['id']]['published_version'] = version
        return True

    def add_version(self, tx, site_id, version, config, published_at):
        self.versions[(site_id, version)] = {'site_id': site_id, 'version': version, 'config': config,
                                             'published_at': published_at}

    def get_version(self, tx, site_id, version):
        return self.versions.get((site_id, version))


class FakeGuests:
    def __init__(self):
        self.row = {'id': 'guest-1', 'guest_number': 'G-INTERNAL', 'phone_e164': '+967777123456', 'name': 'Guest',
                    'job_title': '', 'organization': '', 'event_guest_id': 'reg-1', 'event_guest_status': 'registered',
                    'guest_type': 'visitor', 'pass_number': PASS, 'metadata_json': {}, 'registered_at': 't0'}

    def by_pass_number(self, tx, event_id, pass_number):
        return dict(self.row) if pass_number == PASS else None

    def for_event(self, tx, event_id):
        return [dict(self.row)]


class FakePresence:
    """Stores aggregates; ``concurrent_entry`` simulates another gate winning the race."""

    def __init__(self):
        self.rows = {}
        self.concurrent_entry = False

    def get(self, tx, event_id, guest_id):
        row = self.rows.get((event_id, guest_id))
        return GuestPresence.from_record(row) if row else None

    def add_if_absent(self, tx, presence):
        self.rows.setdefault((presence.event_id, presence.guest_id), presence.to_record())
        return self.get(tx, presence.event_id, presence.guest_id)

    def lock(self, tx, event_id, guest_id):
        pass

    def save(self, tx, presence, transition):
        key = (presence.event_id, presence.guest_id)
        if self.concurrent_entry:
            self.rows[key] = {**self.rows[key], 'state': 'inside', 'last_scan_id': 'other-gate'}
        if transition.guarded and self.rows[key]['state'] != transition.expected_state:
            return False
        self.rows[key] = presence.to_record()
        return True

    def for_event(self, tx, event_id):
        return {guest: row for (event, guest), row in self.rows.items() if event == event_id}


class FakeCheckins:
    def __init__(self):
        self.rows = {}

    def get(self, tx, scan_id):
        return self.rows.get(scan_id)

    def add_if_absent(self, tx, scan):
        if scan['id'] in self.rows:
            return False
        self.rows[scan['id']] = scan
        return True


class FakeAudit:
    def __init__(self):
        self.rows = []

    def add(self, tx, row):
        self.rows.append(row)


class FakeAdmission:
    """No managed admission policy (legacy public event)."""

    def policy_record(self, tx, event_id):
        return None

    def admission_use(self, tx, scan_id):
        return None


@pytest.fixture
def ports():
    saved = dict(persistence._adapters)
    event = {'id': 'event', 'kind': 'event', 'slug': 'expo', 'event_id': 'event', 'parent_id': 'platform',
             'draft': default_config('Expo', 'event'), 'draft_rev': 1, 'published_version': 0}
    fakes = dict(transactions=FakeTransactions(), sites=FakeSites(event), guests=FakeGuests(),
                 presence=FakePresence(), checkins=FakeCheckins(), admission=FakeAdmission(), audit=FakeAudit())
    persistence.install(**fakes)
    yield fakes
    persistence._adapters.clear()
    persistence._adapters.update(saved)



def scan(mode, scan_id, **extra):
    return gate.record_checkin(None, 'event', PASS, {'mode': mode, 'scan_id': scan_id, **extra},
                               scanner_id='device-1', source='device')


def test_entry_exit_cycle_records_scans_and_presence(ports):
    assert scan('entry', 'scan-1')['status'] == 'accepted'
    assert ports['presence'].rows[('event', 'guest-1')]['state'] == 'inside'
    assert scan('exit', 'scan-2')['presence'] == 'outside'
    assert set(ports['checkins'].rows) == {'scan-1', 'scan-2'}


def test_anti_passback_blocks_second_entry_and_replay_is_idempotent(ports):
    scan('entry', 'scan-1')
    blocked = scan('entry', 'scan-2')
    assert blocked['status'] == 'already_inside' and blocked['last_scan_id'] == 'scan-1'
    assert 'scan-2' not in ports['checkins'].rows
    assert scan('entry', 'scan-1')['status'] == 'duplicate'
    with pytest.raises(Conflict, match='SCAN_ID_CONFLICT'):
        scan('exit', 'scan-1')


def test_conditional_update_defends_against_a_concurrent_gate(ports):
    ports['presence'].concurrent_entry = True
    result = scan('entry', 'scan-1')
    assert result['status'] == 'already_inside' and result['last_scan_id'] == 'other-gate'
    assert ports['checkins'].rows == {}


def test_reentry_policy_is_enforced_by_the_aggregate(ports):
    ports['sites'].rows['event']['draft']['access_control']['allow_reentry'] = False
    scan('entry', 'scan-1')
    scan('exit', 'scan-2')
    with pytest.raises(Forbidden, match='REENTRY_NOT_ALLOWED'):
        scan('entry', 'scan-3')


def test_unknown_pass_and_validate_mode(ports):
    with pytest.raises(NotFound, match='GUEST_NOT_REGISTERED'):
        gate.record_checkin(None, 'event', 'G-' + 'B' * 30, {'mode': 'entry'}, scanner_id=None, source='admin')
    result = gate.record_checkin(None, 'event', PASS, {'mode': 'validate', 'checkpoint': 'side'},
                                 scanner_id=None, source='admin')
    assert result['status'] == 'invalid' and result['reason'] == 'CHECKPOINT_NOT_FOUND'
    assert ports['checkins'].rows == {}


def test_manifest_reports_policy_version_and_presence(ports):
    scan('entry', 'scan-1')
    manifest = gate.build_guest_manifest(None, 'event')
    event = ports['sites'].get(None, 'event')
    assert manifest['guest_count'] == 1 and manifest['guests'][0]['presence'] == 'inside'
    assert manifest['access_policy_version'] == AccessPolicy.from_site_config(event['draft']).version()
    assert manifest['requires_online'] is False


def test_publishing_snapshots_the_draft_and_detects_stale_revisions(ports):
    site = ports['sites'].get(None, 'event')
    assert publishing.publish_site_version(None, site, {'id': 'organizer'}) == 1
    assert ports['sites'].versions[('event', 1)]['config']['title'] == 'Expo'
    assert ports['audit'].rows[-1]['action'] == 'publish'
    ports['sites'].stale = True
    with pytest.raises(Conflict, match='VERSION_CONFLICT'):
        publishing.publish_site_version(None, ports['sites'].get(None, 'event'), {'id': 'organizer'})
