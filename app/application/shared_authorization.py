"""Optional canonical authorization AND gate for protected PulseX organizer routes.

This module is an adapter *port*, not an IAM implementation. The caller must
first validate its session and current PulseX organization/event ownership.
Guests, public voting, QR and offline participation do not use this port.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.domain import fail


@dataclass(frozen=True)
class SharedOrganizerDecision:
    actor_id: str
    role: str
    user_scope_id: str
    site_id: str
    event_id: str | None
    action: str


class OrganizerAuthorizationPort(Protocol):
    def allow(self, question: SharedOrganizerDecision) -> bool: ...


def authorize_organizer_action(mode: str, port: OrganizerAuthorizationPort | None,
                               user: dict, site: dict, action: str) -> None:
    """Require canonical Allow in addition to PulseX's already checked local scope.

    Enforce never trusts role/tenant claims from request body/headers. The inputs
    are taken from identify_request and require_scope database lookups.
    """
    if mode == "Off":
        return
    if mode != "Enforce":
        fail("SHARED_AUTHORIZATION_MODE_INVALID", 503)
    if port is None:
        fail("SHARED_AUTHORIZATION_UNAVAILABLE", 503)
    actor = user.get("id")
    site_id = site.get("id")
    if not actor or not site_id or not user.get("role") or not action:
        fail("SHARED_AUTHORIZATION_CONTEXT_MISSING", 403)
    question = SharedOrganizerDecision(
        actor_id=str(actor), role=str(user["role"]),
        user_scope_id=str(user.get("scope_id") or ""),
        site_id=str(site_id),
        event_id=str(site["event_id"]) if site.get("event_id") else None,
        action=action,
    )
    try:
        allowed = port.allow(question)
    except Exception:
        # Never turn an unavailable provider into a permissive fallback.
        fail("SHARED_AUTHORIZATION_UNAVAILABLE", 503)
    if allowed is not True:
        fail("SHARED_AUTHORIZATION_FORBIDDEN", 403)
