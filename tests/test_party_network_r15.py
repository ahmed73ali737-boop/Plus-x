"""Real SDK import tests: event Party link must be opt-in and provider-authorized."""
import sys
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sdk' / 'python'))
from pulsex_sdk.party_network import (
    PartyNetworkAccessDenied, PartyNetworkContext, EventPartyLinkEvidence,
    require_authorized_event_link, resolve_authorized_event_link,
)


class LinkBoundaryR15(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.ctx = PartyNetworkContext(uuid4(), uuid4(), uuid4(), uuid4(), uuid4(), 2)
        self.event = uuid4()
        self.proof = EventPartyLinkEvidence(
            self.ctx, self.event, "EVENT_PARTICIPATION", "signed-proof",
            True, self.now - timedelta(seconds=5),
            self.now + timedelta(minutes=5), "useas.v1",
        )

    def deny(self, proof):
        with self.assertRaises(PartyNetworkAccessDenied):
            require_authorized_event_link(self.ctx, self.event, proof, self.now)

    def test_rejects_textual_false_consent(self):
        self.deny(replace(self.proof, consent_granted="false"))

    def test_rejects_non_boolean_truthy_consent(self):
        for value in (1, ["agree"], "true"):
            with self.subTest(value=value):
                self.deny(replace(self.proof, consent_granted=value))

    def test_rejects_blank_approval_reference(self):
        self.deny(replace(self.proof, approval_reference=" \t "))

    def test_rejects_blank_source_version(self):
        self.deny(replace(self.proof, source_contract_version=" \t "))

    def test_rejects_membership_version_as_bool(self):
        with self.assertRaises(PartyNetworkAccessDenied):
            replace(self.ctx, membership_version=True).validate()

    def test_rejects_nan_or_text_membership_version(self):
        for invalid in (float("nan"), "1", 1.0):
            with self.subTest(invalid=invalid), self.assertRaises(PartyNetworkAccessDenied):
                replace(self.ctx, membership_version=invalid).validate()

    def test_rejects_invalid_datetime_evidence(self):
        for value in ("2026-10-09", datetime.now().replace(tzinfo=None), None):
            with self.subTest(value=value):
                self.deny(replace(self.proof, expires_at_utc=value))

    def test_positive_provider_resolution(self):
        proof = self.proof
        class Provider:
            calls = 0
            def resolve_event_link(self, context, event_id):
                self.calls += 1
                assert context == proof.context and event_id == proof.event_id
                return proof
        provider = Provider()
        self.assertEqual(proof, resolve_authorized_event_link(provider, self.ctx, self.event, self.now))
        self.assertEqual(provider.calls, 1)

    def test_provider_unavailable_fails_closed(self):
        with self.assertRaises(PartyNetworkAccessDenied):
            resolve_authorized_event_link(None, self.ctx, self.event, self.now)

    def test_provider_exception_denies_and_does_not_leak_secret(self):
        class Provider:
            def resolve_event_link(self, context, event_id):
                raise RuntimeError("SECRET_CLIENT_TOKEN")
        with self.assertRaisesRegex(PartyNetworkAccessDenied, "provider unavailable") as cm:
            resolve_authorized_event_link(Provider(), self.ctx, self.event, self.now)
        self.assertNotIn("SECRET_CLIENT_TOKEN", str(cm.exception))

    def test_invalid_request_not_sent_to_provider(self):
        class Provider:
            def resolve_event_link(self, context, event_id):
                raise AssertionError("Should not call provider")
        with self.assertRaises(PartyNetworkAccessDenied):
            resolve_authorized_event_link(Provider(), replace(self.ctx, membership_version=False), self.event, self.now)

    def test_provider_denied_or_wrong_network_fails_closed(self):
        ctx = self.ctx
        proof = self.proof
        class Provider:
            def resolve_event_link(self, context, event_id):
                return replace(proof, context=replace(ctx, network_id=uuid4()))
        with self.assertRaises(PartyNetworkAccessDenied):
            resolve_authorized_event_link(Provider(), self.ctx, self.event, self.now)

    def test_unresolved_guest_not_auto_promoted(self):
        class Provider:
            def resolve_event_link(self, context, event_id):
                return None
        with self.assertRaises(PartyNetworkAccessDenied):
            resolve_authorized_event_link(Provider(), self.ctx, self.event, self.now)


if __name__ == '__main__':
    unittest.main()
