"""Negative network/tenant/consent checks for optional U-SEAS PulseX participant link."""
import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from pulsex_sdk.party_network import (
    PartyNetworkContext,
    EventPartyLinkEvidence,
    PartyNetworkAccessDenied,
    require_authorized_event_link,
)


class ScopedPartyLinkTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.event_id = uuid4()
        self.scope = PartyNetworkContext(
            uuid4(), uuid4(), uuid4(), uuid4(), uuid4(), 1,
        )
        self.proof = EventPartyLinkEvidence(
            self.scope, self.event_id, "EVENT_PARTICIPATION",
            "CONSENT-REF-1", True, self.now-timedelta(minutes=1),
            self.now+timedelta(minutes=30), "useas-v1",
        )

    def test_valid_event_link_stays_within_scope(self):
        self.assertEqual(
            self.proof,
            require_authorized_event_link(self.scope, self.event_id, self.proof, self.now),
        )

    def test_unresolved_guest_is_never_promoted_to_party(self):
        with self.assertRaises(PartyNetworkAccessDenied):
            require_authorized_event_link(self.scope, self.event_id, None, self.now)

    def test_cross_network_cannot_use_party_evidence(self):
        wrong = PartyNetworkContext(
            self.scope.tenant_id, uuid4(), self.scope.scope_id,
            self.scope.party_id, self.scope.membership_id, 1,
        )
        with self.assertRaises(PartyNetworkAccessDenied):
            require_authorized_event_link(wrong, self.event_id, self.proof, self.now)

    def test_cross_tenant_and_scope_denied(self):
        for wrong in (
            PartyNetworkContext(uuid4(), self.scope.network_id, self.scope.scope_id,
                self.scope.party_id, self.scope.membership_id, 1),
            PartyNetworkContext(self.scope.tenant_id, self.scope.network_id, uuid4(),
                self.scope.party_id, self.scope.membership_id, 1),
        ):
            with self.subTest(wrong=wrong), self.assertRaises(PartyNetworkAccessDenied):
                require_authorized_event_link(wrong, self.event_id, self.proof, self.now)

    def test_wrong_event_and_purpose_denied(self):
        with self.assertRaises(PartyNetworkAccessDenied):
            require_authorized_event_link(self.scope, uuid4(), self.proof, self.now)
        bad = EventPartyLinkEvidence(
            self.scope, self.event_id, "AD_TARGETING", self.proof.approval_reference,
            True, self.proof.observed_at_utc, self.proof.expires_at_utc, "useas-v1")
        with self.assertRaises(PartyNetworkAccessDenied):
            require_authorized_event_link(self.scope, self.event_id, bad, self.now)

    def test_expired_or_revoked_consent_denied(self):
        for bad in (
            EventPartyLinkEvidence(self.scope, self.event_id, "EVENT_PARTICIPATION",
                "", True, self.proof.observed_at_utc, self.proof.expires_at_utc, "useas-v1"),
            EventPartyLinkEvidence(self.scope, self.event_id, "EVENT_PARTICIPATION",
                "REF", False, self.proof.observed_at_utc, self.proof.expires_at_utc, "useas-v1"),
            EventPartyLinkEvidence(self.scope, self.event_id, "EVENT_PARTICIPATION",
                "REF", True, self.proof.observed_at_utc, self.now, "useas-v1"),
        ):
            with self.subTest(bad=bad), self.assertRaises(PartyNetworkAccessDenied):
                require_authorized_event_link(self.scope, self.event_id, bad, self.now)

    def test_naive_clock_rejected(self):
        with self.assertRaises(ValueError):
            require_authorized_event_link(self.scope, self.event_id, self.proof,
                datetime.now().replace(tzinfo=None))


if __name__ == "__main__":
    unittest.main()
