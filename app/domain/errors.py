"""Domain errors carry a business code and a category, never a transport status.

The presentation layer (app.api.errors) maps each category to an HTTP status.
"""
from __future__ import annotations


class DomainError(Exception):
    """A business rule, invariant or lookup failed.

    ``code`` is the stable machine-readable reason shown to clients
    (e.g. ``REENTRY_NOT_ALLOWED``). ``kind`` names the category of failure.
    """

    kind = 'invalid'

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code

    @property
    def detail(self) -> str:
        """Alias kept for callers that collect error codes generically."""
        return self.code

    def __str__(self) -> str:
        return self.code


class InvalidInput(DomainError):
    """Input or requested change violates a validation rule."""

    kind = 'invalid'


class Unauthenticated(DomainError):
    """No valid principal was presented."""

    kind = 'unauthenticated'


class Forbidden(DomainError):
    """The principal is known but not allowed to perform the action."""

    kind = 'forbidden'


class NotFound(DomainError):
    """The target does not exist or is concealed from the actor."""

    kind = 'not_found'


class Conflict(DomainError):
    """The change conflicts with current state (stale revision, duplicate, used)."""

    kind = 'conflict'


class Gone(DomainError):
    """The target existed but is no longer usable (revoked, expired)."""

    kind = 'gone'


class PreconditionRequired(DomainError):
    """A required preceding step has not been completed."""

    kind = 'precondition_required'


class RateLimited(DomainError):
    """The actor exceeded a business rate or quota limit."""

    kind = 'rate_limited'


class Unavailable(DomainError):
    """A required capability or resource is temporarily unavailable."""

    kind = 'unavailable'


def fail(code: str, kind: type[DomainError] = InvalidInput):
    """Raise a domain error of the given category (default: invalid input)."""
    if not (isinstance(kind, type) and issubclass(kind, DomainError)):
        raise TypeError('fail() kind must be a DomainError subclass')
    raise kind(code)
