"""Real unit tests for the optional canonical AND gate (no provider fixtures disguised as SIT)."""
import pytest
from fastapi import HTTPException

from app.application.shared_authorization import (
    SharedOrganizerDecision, authorize_organizer_action,
)


USER = {"id": "u-123", "role": "organizer", "scope_id": "event-01"}
SITE = {"id": "site-01", "event_id": "event-01"}


class DecisionPort:
    def __init__(self, allow=True, fail=False):
        self.allowed = allow
        self.fail = fail
        self.calls = []

    def allow(self, question: SharedOrganizerDecision) -> bool:
        self.calls.append(question)
        if self.fail:
            raise RuntimeError("upstream provider unavailable")
        return self.allowed


def expect_deny(code, status, action):
    with pytest.raises(HTTPException) as caught:
        action()
    assert caught.value.status_code == status
    assert caught.value.detail == code


def test_off_preserves_original_admin_flow_without_provider():
    authorize_organizer_action("Off", None, USER, SITE, "event.publish")


def test_allow_requires_exact_true_and_passes_trusted_actor_resource():
    provider = DecisionPort(True)
    authorize_organizer_action("Enforce", provider, USER, SITE, "event.publish")
    assert provider.calls == [
        SharedOrganizerDecision("u-123", "organizer", "event-01",
                                "site-01", "event-01", "event.publish")
    ]


@pytest.mark.parametrize("value", [False, None, "allow", 1, [], {}])
def test_false_or_malformed_provider_responses_never_allow(value):
    expect_deny("SHARED_AUTHORIZATION_FORBIDDEN", 403,
                lambda: authorize_organizer_action(
                    "Enforce", DecisionPort(value), USER, SITE, "event.publish"))


def test_missing_provider_denies():
    expect_deny("SHARED_AUTHORIZATION_UNAVAILABLE", 503,
                lambda: authorize_organizer_action("Enforce", None, USER, SITE, "event.publish"))


def test_broken_provider_denies_instead_of_permissive_fallback():
    expect_deny("SHARED_AUTHORIZATION_UNAVAILABLE", 503,
                lambda: authorize_organizer_action(
                    "Enforce", DecisionPort(fail=True), USER, SITE, "event.publish"))


def test_invalid_mode_cannot_be_treated_as_off():
    expect_deny("SHARED_AUTHORIZATION_MODE_INVALID", 503,
                lambda: authorize_organizer_action("AllowAll", DecisionPort(), USER, SITE, "event.publish"))


@pytest.mark.parametrize("user,site", [
    ({**USER, "id": ""}, SITE),
    (USER, {**SITE, "id": ""}),
    ({**USER, "role": ""}, SITE),
])
def test_missing_trusted_actor_or_resource_denies(user, site):
    expect_deny("SHARED_AUTHORIZATION_CONTEXT_MISSING", 403,
                lambda: authorize_organizer_action("Enforce", DecisionPort(), user, site, "event.publish"))


def test_provider_evaluates_site_and_actor_not_untrusted_payload():
    provider = DecisionPort()
    authorize_organizer_action("Enforce", provider, USER, SITE, "event.configure")
    assert provider.calls[0].action == "event.configure"
    assert provider.calls[0].site_id == SITE["id"]
