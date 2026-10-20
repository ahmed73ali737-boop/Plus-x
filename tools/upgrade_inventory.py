"""Read-only upgrade inventory. Never emits phones, public passes or bearer hashes.

No apply mode: existing unmanaged events stay unmanaged until an explicit,
reviewed conversion is implemented. Inventory counts are not a backup.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from sqlalchemy import MetaData, Table, create_engine, func, inspect, select, text
from app.core.migrations import expected_migration_checksums

PASS=re.compile(r'^G-[0-9A-F]{30}$')


def inventory(conn):
    inspector=inspect(conn)
    present=set(inspector.get_table_names())
    tables={name:Table(name,MetaData(),autoload_with=conn) for name in sorted(present) if name.startswith('px_')}
    counts={name:conn.execute(select(func.count()).select_from(table)).scalar_one() for name,table in tables.items()}
    events={}
    regs=tables.get('px_event_guests')
    inv=tables.get('px_invitations')
    invitations={}
    if inv is not None:
        invitations={r['id']:r for r in conn.execute(select(inv.c.id,inv.c.event_id,inv.c.guest_id,inv.c.status)).mappings()}
    if regs is not None:
        columns=[regs.c.event_id,regs.c.guest_id]
        for name in ('pass_number','metadata_json','status'):
            if name in regs.c:columns.append(regs.c[name])
        for row in conn.execute(select(*columns)).mappings():
            ev=events.setdefault(row['event_id'],{'registrations':0,'legacy_passes':0,'unmanaged_registrations':0,'linked_invitations':0,'invalid_invitation_links':0})
            ev['registrations']+=1
            ev['legacy_passes']+=not bool(PASS.fullmatch(row.get('pass_number') or ''))
            meta=row.get('metadata_json') or {}
            if isinstance(meta,str):
                try:meta=json.loads(meta)
                except ValueError:meta={}
            iid=meta.get('invitation_id') if isinstance(meta,dict) else None
            if not iid:ev['unmanaged_registrations']+=1
            else:
                linked=invitations.get(iid)
                valid=linked and linked['event_id']==row['event_id'] and linked['guest_id']==row['guest_id']
                ev['linked_invitations' if valid else 'invalid_invitation_links']+=1
    expected=expected_migration_checksums()
    migration_table=tables.get('px_schema_migrations')
    recorded={} if migration_table is None else dict(conn.execute(select(migration_table.c.migration_id,migration_table.c.checksum)).all())
    devices=tables.get('px_devices')
    device_summary=[]
    if devices is not None:
        for row in conn.execute(select(devices.c.site_id,devices.c.status,devices.c.metadata_json)).mappings():
            meta=row['metadata_json'] or {}
            if isinstance(meta,str):
                try:meta=json.loads(meta)
                except ValueError:meta={}
            device_summary.append({'event_id':row['site_id'],'status':row['status'],
                                   'deny_all_checkpoints':isinstance(meta,dict) and meta.get('checkpoints')==[],
                                   'has_shift':isinstance(meta,dict) and bool(meta.get('valid_from') or meta.get('valid_until'))})
    return {'status':'inventory_only','read_only':True,'database':conn.dialect.name,'table_counts':counts,
            'events':events,'devices':device_summary,
            'migration_missing':sorted(set(expected)-set(recorded)),
            'migration_mismatch':sorted(k for k in expected if k in recorded and expected[k]!=recorded[k]),
            'code_migration_checksums':expected,
            'policy':'Keep unmanaged events unchanged; LEGACY_PASSES_REQUIRE_MIGRATION remains mandatory. No conversion is authorized by this inventory.',
            'client_inventory':'Server cannot enumerate printed cards or disconnected browser caches; reconcile these manually before cutover.'}


def state_fingerprints(conn):
    """Aggregated table hashes for isolated rehearsal/restore comparisons only."""
    result={}
    for name in sorted(inspect(conn).get_table_names()):
        if not name.startswith('px_'):continue
        table=Table(name,MetaData(),autoload_with=conn)
        rows=[json.dumps(dict(r),sort_keys=True,default=str,separators=(',',':')) for r in conn.execute(select(table)).mappings()]
        result[name]={'rows':len(rows),'sha256':hashlib.sha256('\n'.join(sorted(rows)).encode()).hexdigest()}
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    url=os.environ.get('DATABASE_URL','')
    if not url:raise RuntimeError('DATABASE_URL_REQUIRED')
    engine=create_engine(url)
    try:
        with engine.connect() as conn:
            if engine.dialect.name=='postgresql':conn.execute(text('SET TRANSACTION READ ONLY'))
            elif engine.dialect.name=='sqlite':conn.exec_driver_sql('PRAGMA query_only=ON')
            else:raise RuntimeError('UNSUPPORTED_DATABASE')
            report=inventory(conn)
        out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    finally:engine.dispose()
    print('Read-only inventory written; no credentials or pass values included.')


if __name__=='__main__':main()
