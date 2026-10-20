"""Native PostgreSQL invitation acceptance in a disposable, isolated schema.

Requires PX_POSTGRES_TEST_URL and PX_ALLOW_POSTGRES_TEST_RESET=YES, matching the
existing dedicated test-DB contract. Never touches application/public tables.
No SQLite fallback: an unavailable PostgreSQL server blocks this acceptance.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from threading import Barrier
from zoneinfo import ZoneInfo
import json
import os
import sys
import traceback
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fastapi import HTTPException
from sqlalchemy import insert, select, update, func, inspect
from sqlalchemy.engine import make_url
from app.db import make_engine, sites, guests, event_guests, guest_checkins
from app.domain import default_config, now
from app.application import invitation_service as svc
from app.application.guest_service import event_guest_by_number
from app.application.guest_gate_service import record_checkin
from app.invitations_db import invitations, entitlements, admission_uses
from app.core.migrations import MIGRATION_PATHS
from tools.migrate_postgres import execute_script, apply_migrations


def main():
    qa = ROOT / 'qa' / 'postgres-invitations-acceptance.json'
    qa.parent.mkdir(parents=True, exist_ok=True)
    checks = []
    report = {'status': 'blocked', 'database': 'PostgreSQL', 'checks': checks,
              'test_data': 'synthetic isolated schema', 'sqlite_fallback': False}
    def mark(name, condition=True):
        assert condition, name
        checks.append(name)
        print('PASS', name, flush=True)
    raw_url = os.environ.get('PX_POSTGRES_TEST_URL', '')
    if not raw_url.startswith('postgresql+psycopg://') or os.environ.get('PX_ALLOW_POSTGRES_TEST_RESET') != 'YES':
        report['reason'] = 'Dedicated PX_POSTGRES_TEST_URL and PX_ALLOW_POSTGRES_TEST_RESET=YES are required.'
        qa.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2))
        return 3
    schema = 'px_invitation_qa_' + uuid.uuid4().hex
    control = make_engine(raw_url)
    engine = None
    created = False
    try:
        with control.begin() as conn:
            # Identifier consists only of a fixed prefix and generated hexadecimal.
            conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        created = True
        parsed = make_url(raw_url)
        isolated_url = parsed.set(query={**parsed.query, 'options': f'-csearch_path={schema}'}).render_as_string(hide_password=False)
        engine = make_engine(isolated_url)
        with engine.connect() as conn:
            mark('isolated_postgresql_schema', conn.exec_driver_sql('select current_schema()').scalar_one() == schema)
        with engine.begin() as conn:
            execute_script(conn, (ROOT / 'ops/001_full_schema_postgres.sql').read_text())
            for path in MIGRATION_PATHS:
                if path.name[:3] in ('008', '009'): continue
                execute_script(conn, path.read_text())
            ev_old = {'id': 'migration-event', 'kind': 'event', 'slug': 'migration-event', 'draft': default_config('Migration event', 'event'), 'draft_rev': 1, 'published_version': 0}
            conn.execute(insert(sites).values(**ev_old))
            conn.execute(insert(guests).values(id='legacy-guest', phone_e164='+967777990000', phone_hash='a' * 64, guest_number='G-1111-2222-3333-4444', name='Synthetic legacy', status='active', created_at=now(), updated_at=now()))
            conn.execute(insert(event_guests).values(id='legacy-registration', event_id=ev_old['id'], guest_id='legacy-guest', status='registered', guest_type='visitor', pass_number='G-1111-2222-3333-4444', metadata_json={}, registered_at=now(), updated_at=now()))
            execute_script(conn, (ROOT / 'ops/008_event_pass_isolation.sql').read_text())
            execute_script(conn, (ROOT / 'ops/009_invitations.sql').read_text())
            upgraded = conn.execute(select(event_guests.c.pass_number).where(event_guests.c.id == 'legacy-registration')).scalar_one()
            mark('migration_008_rotates_legacy_global_pass', upgraded != 'G-1111-2222-3333-4444' and len(upgraded) == 32)
            mark('legacy_global_credential_not_accepted', event_guest_by_number(conn, ev_old['id'], 'G-1111-2222-3333-4444') is None)
            mark('upgraded_event_credential_resolves', bool(event_guest_by_number(conn, ev_old['id'], upgraded)))
        mark('migration_009_creates_invitation_tables', {'px_event_admission', 'px_invitations', 'px_admission_entitlements', 'px_admission_uses', 'px_invitation_imports'}.issubset(inspect(engine).get_table_names()))
        applied = apply_migrations(engine)
        repeated = apply_migrations(engine)
        mark('versioned_runner_records_008_and_009', {'008_event_pass_isolation.sql', '009_invitations.sql'}.issubset(applied['applied']))
        mark('versioned_runner_replay_idempotent', not repeated['applied'] and len(repeated['skipped']) == len(MIGRATION_PATHS))

        today = datetime.now(ZoneInfo('Asia/Aden')).date().isoformat()
        def create_event(identifier, capacity=10):
            ev = {'id': identifier, 'kind': 'event', 'slug': identifier, 'draft': default_config(identifier, 'event'), 'draft_rev': 1, 'published_version': 0}
            with engine.begin() as conn:
                conn.execute(insert(sites).values(**ev))
                svc.save_policy(conn, identifier, {'enabled': True, 'visibility': 'private', 'registration_mode': 'auto', 'entry_mode': 'daily', 'max_companions': 2, 'days': [{'date': today, 'capacity': capacity}]})
            return ev
        def invite(ev, phone):
            with engine.begin() as conn:
                return svc.create_invitation(conn, ev['id'], {'name': 'Synthetic guest', 'phone': phone})
        def respond(ev, token, companions=0):
            with engine.begin() as conn:
                return svc.respond(conn, ev, token, {'response': 'accepted', 'companions': companions, 'days': [today], 'consent': True})
        def parallel(callables):
            barrier = Barrier(len(callables))
            def run(fn):
                barrier.wait(timeout=15)
                try: return {'ok': True, 'value': fn()}
                except HTTPException as exc: return {'ok': False, 'status': exc.status_code, 'error': exc.detail}
            with ThreadPoolExecutor(max_workers=len(callables)) as pool:
                futures = [pool.submit(run, fn) for fn in callables]
                return [f.result(timeout=45) for f in futures]

        ev = create_event('capacity-last-seat', 1)
        candidates = [invite(ev, f'+96777799100{i}') for i in range(8)]
        outcomes = parallel([lambda tok=token: respond(ev, tok) for _, token in candidates])
        winners = [item['value'] for item in outcomes if item['ok']]
        losers = [item for item in outcomes if not item['ok']]
        mark('simultaneous_last_seat_has_one_approval', len(winners) == 1 and len(losers) == 7)
        mark('capacity_losers_are_conflicts_not_server_errors', all(item['status'] == 409 and item['error'] == 'DAY_CAPACITY_FULL' for item in losers))
        winner = winners[0]
        with engine.connect() as conn:
            pass_number = svc.public_view(conn, ev, winner, '')['guest_number']
        shared_scan = str(uuid.uuid4())
        def checkin(event, credential, scan_id, quantity=1):
            with engine.begin() as conn:
                return record_checkin(conn, event, credential, {'scan_id': scan_id, 'direction': 'entry', 'checkpoint': 'main', 'quantity': quantity}, scanner_id='synthetic-gate', source='device')
        scans = parallel([lambda: checkin(ev, pass_number, shared_scan) for _ in range(8)])
        mark('same_scan_concurrent_retries_do_not_error', all(item['ok'] for item in scans))
        statuses = [item['value']['status'] for item in scans]
        mark('same_scan_one_accept_seven_replays', statuses.count('accepted') == 1 and statuses.count('duplicate') == 7)
        with engine.connect() as conn:
            mark('same_scan_one_ledger_row', conn.execute(select(func.count()).select_from(guest_checkins).where(guest_checkins.c.id == shared_scan)).scalar_one() == 1)
            mark('same_scan_one_entitlement_consumption', conn.execute(select(entitlements.c.consumed).where(entitlements.c.invitation_id == winner['id'])).scalar_one() == 1)
            mark('same_scan_one_admission_use', conn.execute(select(func.count()).select_from(admission_uses).where(admission_uses.c.scan_id == shared_scan)).scalar_one() == 1)
        duplicate_entries = parallel([lambda: checkin(ev, pass_number, str(uuid.uuid4())) for _ in range(4)])
        mark('distinct_scans_cannot_reuse_consumed_ticket', all(not r['ok'] and r['error'] == 'ADMISSION_ALREADY_USED' for r in duplicate_entries))

        second = create_event('cross-event-isolation')
        _, other_token = invite(second, winner['phone'])
        other = respond(second, other_token)
        with engine.connect() as conn:
            other_pass = svc.public_view(conn, second, other, '')['guest_number']
        mark('same_phone_has_distinct_event_passes', other_pass != pass_number)
        cross = parallel([lambda: checkin(second, pass_number, str(uuid.uuid4()))])
        mark('cross_event_pass_rejected', not cross[0]['ok'] and cross[0]['error'] == 'GUEST_NOT_REGISTERED')

        race_ev = create_event('scan-rsvp-race')
        _, race_token = invite(race_ev, '+967777992001')
        party = respond(race_ev, race_token, 1)
        with engine.connect() as conn:
            race_pass = svc.public_view(conn, race_ev, party, '')['guest_number']
        races = parallel([lambda: checkin(race_ev, race_pass, str(uuid.uuid4())), lambda: respond(race_ev, race_token, 2)])
        mark('scan_rsvp_race_no_integrity_or_server_error', all(r['ok'] or r['error'] == 'ATTENDANCE_ALREADY_STARTED' for r in races))
        with engine.connect() as conn:
            entitlement = conn.execute(select(entitlements).where(entitlements.c.invitation_id == party['id'])).mappings().one()
            mark('scan_rsvp_race_consistent_consumption', entitlement['consumed'] == 1 and entitlement['quantity'] in (2, 3))

        revoke_ev = create_event('scan-revoke-race')
        rev, rev_token = invite(revoke_ev, '+967777992002')
        rev = respond(revoke_ev, rev_token)
        with engine.connect() as conn:
            rev_pass = svc.public_view(conn, revoke_ev, rev, '')['guest_number']
        def do_revoke():
            with engine.begin() as conn: return svc.revoke(conn, revoke_ev['id'], rev['id'])
        rev_race = parallel([lambda: checkin(revoke_ev, rev_pass, str(uuid.uuid4())), do_revoke])
        mark('scan_revoke_race_no_integrity_or_server_error', all(r['ok'] or r['error'] in ('INVITATION_INACTIVE', 'GUEST_STATUS_REVOKED') for r in rev_race))
        with engine.connect() as conn:
            row = conn.execute(select(entitlements).where(entitlements.c.invitation_id == rev['id'])).mappings().one()
            mark('revoked_race_final_state_consistent', row['status'] == 'revoked' and row['consumed'] in (0, 1))

        report['status'] = 'passed'
        report['warning'] = 'This verifies native PostgreSQL migrations and transaction races, not physical scanners, load SLA, or production deployment.'
        return 0
    except Exception as exc:
        report['status'] = 'failed'
        report['error'] = str(exc)
        report['traceback'] = traceback.format_exc()
        return 1
    finally:
        if engine is not None: engine.dispose()
        if created:
            with control.begin() as conn:
                conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        control.dispose()
        report['passed'] = len(checks)
        qa.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    raise SystemExit(main())
