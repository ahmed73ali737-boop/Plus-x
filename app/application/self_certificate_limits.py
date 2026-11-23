"""Shared atomic per-window limits; browser and IP are separate scopes."""
import hashlib
import time

from app.application.ports import persistence
from app.domain import RateLimited, fail

PRUNE_AFTER_WINDOWS = 120


def consume(database, scope, value, limit, seconds=60):
    key = hashlib.sha256((scope + '\0' + value).encode()).hexdigest()
    window = int(time.time()) // seconds
    count = persistence.self_certificates.count_in_window(database, key, window)
    if count > limit:
        fail('RATE_LIMIT', RateLimited)


def prune(tx):
    # Bounded cleanup; no participant or certificate data is purged.
    return persistence.self_certificates.prune_windows(tx, int(time.time()) // 60 - PRUNE_AFTER_WINDOWS)
