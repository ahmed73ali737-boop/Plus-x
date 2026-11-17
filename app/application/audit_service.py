"""Audit trail use cases, including denials audited after request rollback."""
from __future__ import annotations

import logging
import time
from collections import OrderedDict, deque
from threading import Lock

from app.application.ports import persistence
from app.domain import DomainError, now
from app.domain.values import new_id

__all__ = ['AuditedDenial', 'DenialAuditWriter', 'new_id', 'write_audit']


def write_audit(tx, user, site_id, action: str, detail=None) -> None:
    persistence.audit.add(tx, {
        'id': new_id(),
        'user_id': user['id'] if user else None,
        'site_id': site_id,
        'action': action,
        'at': now(),
        'details': detail or {},
    })


# Only server-selected, secret-free fields cross the rollback boundary.


class AuditedDenial(DomainError):
    """A denial that is audited after the request transaction rolled back.

    ``kind`` is the denial category (Forbidden or Unauthenticated).
    """
    def __init__(self, code, kind, *, action, user=None, site_id=None):
        super().__init__(code)
        self.kind = kind.kind
        self.audit_id = new_id()
        self.audit_action = action
        self.audit_user = {'id': user['id']} if user else None
        self.audit_site_id = site_id


class DenialAuditWriter:
    """Write after request rollback. Bounded per-process abuse protection.

    Deduplicate the same denial object for 60s, plus a global
    600/min ceiling per worker. Separate HTTP attempts remain separate events. No attacker-supplied request IDs or login
    identifiers are stored. Multi-worker limits multiply by worker count.
    """
    def __init__(self, engine, clock=time.monotonic):
        self.engine, self.clock = engine, clock
        self.lock = Lock()
        self.recent = OrderedDict()
        self.window = deque()
        self.failures = 0
        self.suppressed = 0

    def record(self, denial):
        key = denial.audit_id
        with self.lock:
            current = self.clock()
            while self.recent and current - next(iter(self.recent.values())) >= 60:
                self.recent.popitem(last=False)
            while self.window and current - self.window[0] >= 60:
                self.window.popleft()
            if key in self.recent or len(self.window) >= 600:
                self.suppressed += 1
                return
            # Reserve before attempting I/O: storage failure cannot cause a log storm.
            self.recent[key] = current
            self.window.append(current)
        try:
            with persistence.transactions.write(self.engine) as tx:
                write_audit(tx, denial.audit_user, denial.audit_site_id,
                            denial.audit_action, {'reason': denial.detail})
        except Exception:
            # Never include exception text: drivers may embed SQL parameters.
            with self.lock:
                self.failures += 1
            logging.getLogger(__name__).warning('Denial audit persistence failed')
