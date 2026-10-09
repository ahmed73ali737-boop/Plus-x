"""Optional U-SEAS PartyNetwork link for authenticated PulseX event participants.

Unregistered event visitors/QR guests remain guests. This module never converts
a phone, QR token or guest into a Party automatically; U-SEAS owns identity.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID


class PartyNetworkAccessDenied(PermissionError):
    """A requested linkage lacks valid network/consent/role proof."""


@dataclass(frozen=True)
class PartyNetworkContext:
    tenant_id: UUID
    network_id: UUID
    scope_id: UUID
    party_id: UUID
    membership_id: UUID
    membership_version: int

    def validate(self) -> "PartyNetworkContext":
        for value in (self.tenant_id, self.network_id, self.scope_id,
                      self.party_id, self.membership_id):
            if not isinstance(value, UUID) or value.int == 0:
                raise PartyNetworkAccessDenied("Missing scoped U-SEAS Party reference")
        if (type(self.membership_version) is not int or
                self.membership_version < 1):
            raise PartyNetworkAccessDenied("Membership must have a positive revision")
        return self


@dataclass(frozen=True)
class EventPartyLinkEvidence:
    context: PartyNetworkContext
    event_id: UUID
    purpose: str
    approval_reference: str
    consent_granted: bool
    observed_at_utc: datetime
    expires_at_utc: datetime
    source_contract_version: str


class PartyNetworkLookup(Protocol):
    """External authenticated U-SEAS port; no internal U-SEAS tables allowed."""

    def resolve_event_link(self, context: PartyNetworkContext,
                           event_id: UUID) -> EventPartyLinkEvidence: ...


def require_authorized_event_link(
    requested: PartyNetworkContext,
    event_id: UUID,
    proof: EventPartyLinkEvidence | None,
    at_utc: datetime,
) -> EventPartyLinkEvidence:
    """Validate a provider-issued, exact-scope event link; never infer it from a guest.

    The external U-SEAS port is responsible for verifying signed consent,
    membership status, revocation, issuer, IAM and business permissions.
    This local guard deliberately cannot confer those authorities.
    """
    if not isinstance(requested, PartyNetworkContext):
        raise PartyNetworkAccessDenied("Invalid scoped Party reference")
    requested.validate()
    if not isinstance(event_id, UUID) or event_id.int == 0:
        raise PartyNetworkAccessDenied("Missing event reference")
    if (not isinstance(at_utc, datetime) or at_utc.tzinfo is None or
            at_utc.utcoffset() is None):
        raise ValueError("Timezone-aware decision clock required")
    if (not isinstance(proof, EventPartyLinkEvidence) or
            proof.context != requested or proof.event_id != event_id):
        raise PartyNetworkAccessDenied("No authorized event Party linkage")
    if (proof.purpose != "EVENT_PARTICIPATION" or
        type(proof.consent_granted) is not bool or not proof.consent_granted or
        not isinstance(proof.approval_reference, str) or
        not proof.approval_reference.strip() or
        not isinstance(proof.source_contract_version, str) or
        not proof.source_contract_version.strip() or
        not isinstance(proof.observed_at_utc, datetime) or
        not isinstance(proof.expires_at_utc, datetime) or
        proof.observed_at_utc.tzinfo is None or
        proof.expires_at_utc.tzinfo is None or
        proof.observed_at_utc.utcoffset() is None or
        proof.expires_at_utc.utcoffset() is None or
        not (proof.observed_at_utc <= at_utc < proof.expires_at_utc)):
        raise PartyNetworkAccessDenied("Event Party linkage denied, stale or out of scope")
    return proof


def resolve_authorized_event_link(
    provider: PartyNetworkLookup,
    requested: PartyNetworkContext,
    event_id: UUID,
    at_utc: datetime,
) -> EventPartyLinkEvidence:
    """Consumer entry point to an independently authenticated U-SEAS read port.

    Reject malformed requests *before* invoking the provider. A missing or
    failing external provider never grants PulseX a fallback Party link.
    """
    if not isinstance(requested, PartyNetworkContext):
        raise PartyNetworkAccessDenied("Invalid Party context")
    requested.validate()
    if not isinstance(event_id, UUID) or event_id.int == 0:
        raise PartyNetworkAccessDenied("Invalid event")
    if (not isinstance(at_utc, datetime) or at_utc.tzinfo is None or
            at_utc.utcoffset() is None):
        raise ValueError("Timezone-aware decision clock required")
    if provider is None:
        raise PartyNetworkAccessDenied("Canonical Party provider unavailable")
    try:
        proof = provider.resolve_event_link(requested, event_id)
    except Exception:
        raise PartyNetworkAccessDenied("Canonical Party provider unavailable") from None
    return require_authorized_event_link(requested, event_id, proof, at_utc)
