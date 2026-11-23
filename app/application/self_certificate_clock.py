"""Uniform UTC strings for new self-service records; existing data is not rewritten."""
from app.application.ports import persistence
from app.domain.values import utc_timestamp


def utc_now():
    return utc_timestamp()


def lease_now(tx):
    """One server clock for leases across processes; timings use monotonic elsewhere."""
    return persistence.self_certificates.lease_now(tx)
