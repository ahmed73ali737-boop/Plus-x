"""Typed existence guards shared by every context.

A use case reads a record through a port and hands the result to one of these
guards; the *rule* (a missing target is NotFound, a duplicate is a Conflict) is
therefore owned by the domain and never re-written next to a repository call.
"""
from __future__ import annotations

from typing import TypeVar

from app.domain.errors import Conflict, DomainError, NotFound, fail

T = TypeVar('T')


def require_found(record: T | None, code: str, kind: type[DomainError] = NotFound) -> T:
    """The target must exist (and be visible to the actor); otherwise raise ``kind(code)``."""
    if not record:
        fail(code, kind)
    return record


def reject_existing(exists: object, code: str, kind: type[DomainError] = Conflict) -> None:
    """The target must not exist yet (unique slug, duplicate participation...)."""
    if exists:
        fail(code, kind)
