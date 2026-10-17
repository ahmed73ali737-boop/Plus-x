#!/usr/bin/env python3
"""Static design-only PulseX UIP interoperability guard. Not a runtime or privacy test."""
import copy
import json
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / 'reference' / 'integrations' / 'uip-guest-status-preview-v1.json'

def validate(o):
    assert o['schemaVersion']=='1.0'
    assert o['canonicalOwner']['repository']=='Plus-x'
    assert o['capabilityCode']=='engagement.guest.validation.preview'
    assert o['effectType']=='ReadOnlyQuery'
    assert o['dataClassification']=='CONFIDENTIAL'
    assert o['executionPolicy']['mode']=='SIMULATION_ONLY'
    assert o['executionPolicy']['externalEffectsEnabled'] is False
    assert o['events']['emits']==[]
    assert o['acceptance']['verification']=='DESIGN_ONLY'

class TestPulseXUipPreview(unittest.TestCase):
    def setUp(self):
        self.contract=json.loads(PATH.read_text(encoding='utf8'))
    def test_valid_design_only_contract(self):
        validate(self.contract)
    def test_block_non_pulsex_domain_owner(self):
        x=copy.deepcopy(self.contract);x['canonicalOwner']['repository']='UIP'
        with self.assertRaises(AssertionError): validate(x)
    def test_block_live_execution(self):
        x=copy.deepcopy(self.contract);x['executionPolicy']['externalEffectsEnabled']=True
        with self.assertRaises(AssertionError): validate(x)
    def test_block_sensitive_classification_downgrade(self):
        x=copy.deepcopy(self.contract);x['dataClassification']='PUBLIC'
        with self.assertRaises(AssertionError): validate(x)
    def test_block_external_guest_event_emit(self):
        x=copy.deepcopy(self.contract);x['events']['emits']=['guest.full-record.exposed']
        with self.assertRaises(AssertionError): validate(x)


# UIP interoperable envelope v1 local adoption gate (source only; not an E2E/runtime claim).
ADOPTION = Path(__file__).resolve().parents[1] / "reference/integrations/uip-adoption-v1.json"

def validate_adoption(p):
    assert p["protocolVersion"] == "uip.interop.v1"
    assert p["repository"] == "Plus-x"
    assert p["canonicalCapability"] == "engagement.guest.validation.preview"
    assert p["sourceContract"] == "reference/integrations/uip-guest-status-preview-v1.json"
    assert p["mode"] == "READ_ONLY"
    assert p["operation"] == "STATUS_INQUIRY"
    assert p["dataClassification"] == "CONFIDENTIAL"
    assert p["tenantClaimMustMatchPayload"] is True
    assert p["correlationIdRequired"] is True
    assert p["idempotencyKeyRequired"] is True
    assert p["sideEffectsAllowed"] is False
    assert p["providerExecutionEnabled"] is False
    assert p["enabled"] is False
    assert p["nativeVerified"] is False
    assert p["humanApproved"] is False
    assert p["unknownOutcomeDirective"] == "FREEZE_AND_STATUS_INQUIRY"
    assert p["privacyAndOwnership"]["piiExportEnabled"] is False

class TestUipInteropAdoption(unittest.TestCase):
    def setUp(self):
        self.profile = json.loads(ADOPTION.read_text(encoding="utf8"))
    def test_preview_profile_is_fail_closed(self):
        validate_adoption(self.profile)
    def test_reject_live_effects(self):
        x = copy.deepcopy(self.profile); x["sideEffectsAllowed"] = True
        with self.assertRaises(AssertionError): validate_adoption(x)
    def test_reject_tenant_identity_bypass(self):
        x = copy.deepcopy(self.profile); x["tenantClaimMustMatchPayload"] = False
        with self.assertRaises(AssertionError): validate_adoption(x)

if __name__=='__main__': unittest.main()
