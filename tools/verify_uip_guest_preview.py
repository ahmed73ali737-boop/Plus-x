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

if __name__=='__main__': unittest.main()
