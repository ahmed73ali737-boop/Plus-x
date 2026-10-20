"""P05/P07 synthetic old-schema -> migration/retry -> dump/restore rehearsal.

Requires an explicitly dedicated test connection, CREATE DATABASE permission,
pg_dump and pg_restore. Creates/drops only random px_rehearsal_* databases.
Never restores over the configured database or an existing application database.
"""
from pathlib import Path
import json, os, shutil, subprocess, sys, tempfile, time, uuid
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sqlalchemy import create_engine, insert, inspect, select, text
from sqlalchemy.engine import make_url
from app.db import sites, guests, event_guests, guest_checkins
from app.domain import default_config, now
from app.core.migrations import MIGRATION_PATHS, expected_migration_checksums
from app.application.guest_service import event_guest_by_number
from app.application import invitation_service as svc
from tools import migrate_postgres as runner
from tools.upgrade_inventory import inventory, state_fingerprints


def main():
    output=ROOT/'qa/upgrade-rehearsal.json';output.parent.mkdir(parents=True,exist_ok=True)
    report={'status':'blocked','backend':'PostgreSQL','scope':'synthetic logical restore; not PITR/RPO/field acceptance','checks':[]}
    url=os.environ.get('PX_POSTGRES_TEST_URL','')
    container=os.environ.get('PX_POSTGRES_CONTAINER','')
    tools_available=bool(shutil.which('docker')) if container else all(shutil.which(c) for c in ('pg_dump','pg_restore'))
    if not url.startswith('postgresql+psycopg://') or os.environ.get('PX_ALLOW_POSTGRES_TEST_RESET')!='YES' or not tools_available:
        report['reason']='Dedicated test URL, explicit reset opt-in and pg_dump/pg_restore required'
        output.write_text(json.dumps(report,indent=2)+'\n');return 3
    parsed=make_url(url)
    control=create_engine(url,isolation_level='AUTOCOMMIT')
    names=['px_rehearsal_'+uuid.uuid4().hex for _ in range(2)]
    created=[];engines=[]
    def mark(name,condition=True):
        assert condition,name
        report['checks'].append(name)
    def cli(binary,database,*args,input_bytes=None):
        env={**os.environ,'PGPASSWORD':parsed.password or ''}
        host,port=('127.0.0.1',5432) if container else (parsed.host or 'localhost',parsed.port or 5432)
        cmd=[binary,'--host',host,'--port',str(port),'--username',parsed.username or 'postgres','--dbname',database,*args]
        if container:cmd=['docker','exec','-i','-e','PGPASSWORD',container,*cmd]
        return subprocess.run(cmd,check=True,capture_output=True,timeout=120,env=env,input=input_bytes).stdout
    try:
        for name in names:
            with control.connect() as c:c.exec_driver_sql('CREATE DATABASE "'+name+'"')
            created.append(name)
            engines.append(create_engine(parsed.set(database=name)))
        source,restored=engines
        with source.begin() as c:
            runner.execute_script(c,(ROOT/'ops/001_full_schema_postgres.sql').read_text())
            for path in MIGRATION_PATHS[:6]:runner.execute_script(c,path.read_text())
            ev={'id':'upgrade-event','slug':'upgrade-event','kind':'event','draft':default_config('Synthetic','event'),'draft_rev':1,'published_version':0}
            c.execute(insert(sites).values(**ev))
            c.execute(insert(guests).values(id='old-guest',phone_e164='+967777991234',phone_hash='a'*64,guest_number='G-1111-2222-3333-4444',name='Synthetic',status='active',created_at=now(),updated_at=now()))
            c.execute(insert(event_guests).values(id='old-registration',event_id=ev['id'],guest_id='old-guest',pass_number='G-1111-2222-3333-4444',metadata_json={},status='registered',guest_type='visitor',registered_at=now(),updated_at=now()))
            c.execute(insert(guest_checkins).values(id='historical-scan',event_id=ev['id'],guest_id='old-guest',guest_number='G-1111-2222-3333-4444',source='device',direction='entry',checkpoint='main',scanned_at=now()))
            before=state_fingerprints(c)
        runner.apply_migrations(source)
        with source.connect() as c:
            after=state_fingerprints(c)
            mark('guest_and_history_unchanged',all(before[t]==after[t] for t in ('px_guests','px_guest_checkins')))
            mark('registration_count_preserved',before['px_event_guests']['rows']==after['px_event_guests']['rows'])
            new_pass=c.execute(select(event_guests.c.pass_number)).scalar_one()
            mark('old_pass_rejected',event_guest_by_number(c,ev['id'],'G-1111-2222-3333-4444') is None)
            mark('new_pass_resolves',bool(event_guest_by_number(c,ev['id'],new_pass)))
            mark('eight_exact_migrations',c.execute(text('SELECT count(*) FROM px_schema_migrations')).scalar_one()==8 and not inventory(c)['migration_mismatch'])
        again=runner.apply_migrations(source)
        with source.connect() as c:mark('replay_no_rotation_or_effect',state_fingerprints(c)==after and not again['applied'])
        from fastapi import HTTPException
        try:
            with source.begin() as c:svc.save_policy(c,ev['id'],{'enabled':True})
        except HTTPException as error:mark('legacy_managed_guard_preserved',error.detail=='LEGACY_PASSES_REQUIRE_MIGRATION')
        else:raise AssertionError('Legacy policy guard was bypassed')
        with tempfile.TemporaryDirectory(prefix='px-upgrade-') as folder:
            folder=Path(folder)
            failing=folder/'010_test_failure.sql'
            failing.write_text('CREATE TABLE px_rehearsal_probe(id integer); INSERT INTO px_rehearsal_probe VALUES (1); SELECT 1/0;')
            expected={**expected_migration_checksums(),failing.name:'test-only'}
            try:
                with patch.object(runner,'MIGRATIONS',[*MIGRATION_PATHS,failing]),patch.object(runner,'expected_migration_checksums',lambda:expected):runner.apply_migrations(source)
            except Exception:
                with source.connect() as c:
                    mark('failed_migration_rolls_back_ddl','px_rehearsal_probe' not in inspect(c).get_table_names())
                    mark('failed_migration_not_recorded',c.execute(text('SELECT count(*) FROM px_schema_migrations WHERE migration_id=:id'),{'id':failing.name}).scalar_one()==0)
            else:raise AssertionError('Failure injection did not fail')
            mark('retry_after_failure_idempotent',not runner.apply_migrations(source)['applied'])
            dump=folder/'snapshot.dump'
            dump.write_bytes(cli('pg_dump',names[0],'--format=custom','--no-owner','--no-acl'))
            with source.connect() as c:snapshot=state_fingerprints(c)
            started=time.monotonic()
            cli('pg_restore',names[1],'--exit-on-error','--no-owner','--no-acl',input_bytes=dump.read_bytes())
            report['restore_seconds']=round(time.monotonic()-started,3)
            with restored.connect() as c:mark('restored_all_table_fingerprints_match',state_fingerprints(c)==snapshot)
            with source.begin() as c:
                c.execute(insert(guest_checkins).values(id='post-snapshot-scan',event_id=ev['id'],guest_id='old-guest',guest_number=new_pass,source='device',direction='exit',checkpoint='main',scanned_at=now()))
                mark('post_snapshot_ledger_divergence_detected',state_fingerprints(c)!=snapshot)
            # Deliberately never restore that older snapshot over new movements.
        report['status']='passed'
    except Exception as error:report.update(status='failed',error_type=type(error).__name__)
    finally:
        for engine in engines:engine.dispose()
        for name in reversed(created):
            with control.connect() as c:c.exec_driver_sql('DROP DATABASE "'+name+'" WITH (FORCE)')
        control.dispose()
        output.write_text(json.dumps(report,indent=2)+'\n')
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
