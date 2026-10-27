"""Shared atomic per-window limits; browser and IP are separate scopes."""
import hashlib,time
from sqlalchemy import delete
from app.self_certificates_db import rate_buckets
from app.domain import fail

def consume(engine,scope,value,limit,seconds=60):
    key=hashlib.sha256((scope+'\0'+value).encode()).hexdigest()
    window=int(time.time())//seconds
    if engine.dialect.name=='postgresql':
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    with engine.begin() as conn:
        statement=insert(rate_buckets).values(bucket_hash=key,window=window,count=1)
        count=conn.execute(statement.on_conflict_do_update(
            index_elements=[rate_buckets.c.bucket_hash,rate_buckets.c.window],
            set_={'count':rate_buckets.c.count+1}).returning(rate_buckets.c.count)).scalar_one()
    if count>limit:fail('RATE_LIMIT',429)

def prune(conn):
    # Bounded cleanup; no participant or certificate data is purged.
    from sqlalchemy import select
    rows=conn.execute(select(rate_buckets.c.bucket_hash,rate_buckets.c.window)
        .where(rate_buckets.c.window<int(time.time())//60-120).limit(1000)).all()
    for key,window in rows:
        conn.execute(delete(rate_buckets).where(rate_buckets.c.bucket_hash==key,rate_buckets.c.window==window))
    return len(rows)
