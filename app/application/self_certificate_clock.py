"""Uniform UTC strings for new self-service records; existing data is not rewritten."""
from datetime import datetime, timezone

def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def lease_now(conn):
    """One server clock for leases across processes; timings use monotonic elsewhere."""
    if conn.dialect.name=='postgresql':
        from sqlalchemy import select,func
        value=conn.execute(select(func.clock_timestamp())).scalar_one()
        return value.astimezone(timezone.utc).isoformat(timespec='microseconds')
    return utc_now()
