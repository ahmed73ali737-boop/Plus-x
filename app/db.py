"""Legacy import path kept for tools, ops scripts and tests.

The table metadata lives in app.infrastructure.persistence.tables; this module is
an alias of it (same module object), not a copy.
"""
import sys

from app.infrastructure.persistence import tables as _tables

sys.modules[__name__] = _tables
