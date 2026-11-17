"""Legacy import path kept for tools, ops scripts and tests.

The table metadata lives in app.infrastructure.persistence.certificate_tables; this module is
an alias of it (same module object), not a copy.
"""
import sys

from app.infrastructure.persistence import certificate_tables as _tables

sys.modules[__name__] = _tables
