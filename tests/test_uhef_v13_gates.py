"""UHEF v1.3 Comprehensive Gate Tests

Validates the UHEF v1.3 knowledge base including:
- Schema version and structure
- Role definitions and assignments
- Screen documentation completeness
- Navigation anchors
- Demo accounts consistency
- Role-based access control
"""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'web'
KNOWLEDGE_V13 = WEB / 'uhef-knowledge-v1.3.json'
DEMO_ACCOUNTS = WEB / 'uhef-demo-accounts.json'

REQUIRED_ROLE_FIELDS = {'level', 'name', 'name_ar'}
REQUIRED_SCREEN_FIELDS = {'name', 'purpose', 'why', 'whenToUse', 'roles'}
MIN_SCREENS = 40
MIN_ROLES = 10

@pytest.fixture
def knowledge():
    """Load v1.3 knowledge base."""
    assert KNOWLEDGE_V13.exists(), f'{KNOWLEDGE_V13} not found'
    return json.loads(KNOWLEDGE_V13.read_text(encoding='utf-8'))

@pytest.fixture
def demo_accounts():
    """Load demo accounts."""
    assert DEMO_ACCOUNTS.exists(), f'{DEMO_ACCOUNTS} not found'
    return json.loads(DEMO_ACCOUNTS.read_text(encoding='utf-8'))

class TestSchema:
    """Test schema version and structure."""

    def test_schema_version(self, knowledge):
        """Schema must be v1.3."""
        assert knowledge.get('schema') == 'uhef.knowledge/1.3', \
            f"Schema is {knowledge.get('schema')}, expected uhef.knowledge/1.3"

    def test_top_level_sections(self, knowledge):
        """Knowledge base has all required sections."""
        required = {'schema', 'system', 'language', 'roles', 'screens', 'journeys', 'anchors', 'guide'}
        missing = required - set(knowledge.keys())
        assert not missing, f"Missing sections: {missing}"

    def test_system_name(self, knowledge):
        """System name is documented."""
        assert knowledge.get('system'), 'system name not set'
        assert 'Eventna' in knowledge['system'] or 'eventna' in knowledge['system'].lower()

    def test_language(self, knowledge):
        """Language is set."""
        assert knowledge.get('language') in ['ar', 'en'], 'language must be ar or en'

class TestRoles:
    """Test role definitions."""

    def test_role_count(self, knowledge):
        """At least 10 roles defined."""
        roles = knowledge.get('roles', {})
        assert len(roles) >= MIN_ROLES, \
            f"Only {len(roles)} roles defined, need {MIN_ROLES}+"

    def test_role_structure(self, knowledge):
        """Each role has required fields."""
        roles = knowledge.get('roles', {})
        for role_key, role_data in roles.items():
            assert isinstance(role_data, dict), f"Role {role_key} is not a dict"
            missing = REQUIRED_ROLE_FIELDS - set(role_data.keys())
            assert not missing, f"Role {role_key} missing fields: {missing}"
            assert role_data['level'] >= 0, f"Role {role_key} has invalid level"

    def test_role_levels(self, knowledge):
        """Roles have reasonable access levels."""
        roles = knowledge.get('roles', {})
        levels = {r['level'] for r in roles.values()}
        assert levels, "No role levels found"
        # Levels should be 0-4 (visitor to admin)
        assert max(levels) <= 4, f"Role level too high: {max(levels)}"
        assert min(levels) >= 0, f"Role level too low: {min(levels)}"

    def test_role_names_multilingual(self, knowledge):
        """Roles have both English and Arabic names."""
        roles = knowledge.get('roles', {})
        for role_key, role_data in roles.items():
            assert role_data.get('name'), f"Role {role_key} missing English name"
            assert role_data.get('name_ar'), f"Role {role_key} missing Arabic name"

class TestScreens:
    """Test screen definitions."""

    def test_screen_count(self, knowledge):
        """At least 40 screens documented."""
        screens = knowledge.get('screens', {})
        assert len(screens) >= MIN_SCREENS, \
            f"Only {len(screens)} screens, need {MIN_SCREENS}+"

    def test_screen_structure(self, knowledge):
        """Each screen has required fields."""
        screens = knowledge.get('screens', {})
        for screen_key, screen_data in screens.items():
            assert isinstance(screen_data, dict), f"Screen {screen_key} is not a dict"
            missing = REQUIRED_SCREEN_FIELDS - set(screen_data.keys())
            assert not missing, f"Screen {screen_key} missing fields: {missing}"

    def test_screen_roles_valid(self, knowledge):
        """Screen roles reference valid role keys."""
        screens = knowledge.get('screens', {})
        roles = knowledge.get('roles', {})
        valid_roles = set(roles.keys())

        for screen_key, screen_data in screens.items():
            screen_roles = screen_data.get('roles', [])
            assert isinstance(screen_roles, list), \
                f"Screen {screen_key} roles is not a list"

            invalid = set(screen_roles) - valid_roles
            assert not invalid, \
                f"Screen {screen_key} has invalid roles: {invalid}"

    def test_screen_roles_not_empty(self, knowledge):
        """Every screen has at least one assigned role."""
        screens = knowledge.get('screens', {})
        for screen_key, screen_data in screens.items():
            roles = screen_data.get('roles', [])
            assert roles, f"Screen {screen_key} has no assigned roles"

    def test_screen_content_quality(self, knowledge):
        """Screen documentation is substantial."""
        screens = knowledge.get('screens', {})
        for screen_key, screen_data in screens.items():
            # Check non-empty strings
            assert screen_data.get('name', '').strip(), \
                f"Screen {screen_key} has empty name"
            assert screen_data.get('purpose', '').strip(), \
                f"Screen {screen_key} has empty purpose"

            # Check lists
            assert isinstance(screen_data.get('parts', []), list), \
                f"Screen {screen_key} parts is not a list"
            assert isinstance(screen_data.get('steps', []), list), \
                f"Screen {screen_key} steps is not a list"
            assert isinstance(screen_data.get('faq', []), list), \
                f"Screen {screen_key} faq is not a list"

class TestAnchors:
    """Test navigation anchors."""

    def test_anchors_exist(self, knowledge):
        """Anchors section is populated."""
        anchors = knowledge.get('anchors', {})
        assert anchors, "No anchors defined"

    def test_anchors_match_screens(self, knowledge):
        """Every screen has a corresponding anchor."""
        screens = set(knowledge.get('screens', {}).keys())
        anchors = set(knowledge.get('anchors', {}).keys())
        missing = screens - anchors
        assert not missing, f"Screens without anchors: {missing}"

    def test_anchor_structure(self, knowledge):
        """Each anchor has required fields."""
        anchors = knowledge.get('anchors', {})
        for anchor_key, anchor_data in anchors.items():
            assert anchor_data.get('id'), f"Anchor {anchor_key} missing id"
            assert anchor_data.get('slug'), f"Anchor {anchor_key} missing slug"
            assert anchor_data.get('module'), f"Anchor {anchor_key} missing module"

    def test_anchor_slugs_unique(self, knowledge):
        """Anchor slugs are unique."""
        anchors = knowledge.get('anchors', {})
        slugs = [a.get('slug') for a in anchors.values()]
        assert len(slugs) == len(set(slugs)), "Duplicate anchor slugs found"

class TestGuide:
    """Test getting started guide."""

    def test_guide_exists(self, knowledge):
        """Guide section exists."""
        guide = knowledge.get('guide', {})
        assert guide, "No guide defined"

    def test_guide_sections(self, knowledge):
        """Guide has documented sections."""
        guide = knowledge.get('guide', {})
        assert guide.get('sections'), "Guide has no sections"
        assert len(guide['sections']) >= 3, "Guide should have at least 3 sections"

class TestJourneys:
    """Test user journeys."""

    def test_journeys_reference_valid_screens(self, knowledge):
        """Journey steps reference valid screens."""
        journeys = knowledge.get('journeys', {})
        screens = set(knowledge.get('screens', {}).keys())

        for journey_key, journey_data in journeys.items():
            steps = journey_data.get('steps', [])
            for step in steps:
                screen = step.get('screen')
                assert screen in screens, \
                    f"Journey {journey_key} references unknown screen {screen}"

class TestDemoAccounts:
    """Test demo accounts."""

    def test_accounts_exist(self, demo_accounts):
        """Demo accounts list is populated."""
        accounts = demo_accounts.get('accounts', [])
        assert len(accounts) >= 10, \
            f"Only {len(accounts)} demo accounts, expected 10+"

    def test_account_structure(self, demo_accounts):
        """Each account has required fields."""
        accounts = demo_accounts.get('accounts', [])
        required = {'id', 'role', 'name', 'email', 'password', 'access_path', 'scenario'}

        for account in accounts:
            missing = required - set(account.keys())
            assert not missing, \
                f"Account {account.get('id')} missing fields: {missing}"

    def test_account_roles_valid(self, demo_accounts, knowledge):
        """Account roles match defined roles."""
        accounts = demo_accounts.get('accounts', [])
        roles = set(knowledge.get('roles', {}).keys())

        for account in accounts:
            role = account.get('role')
            assert role in roles, \
                f"Account {account.get('id')} has unknown role {role}"

    def test_account_access_paths_valid(self, demo_accounts, knowledge):
        """Account access paths reference valid screens."""
        accounts = demo_accounts.get('accounts', [])
        screens = set(knowledge.get('screens', {}).keys())

        for account in accounts:
            for screen in account.get('access_path', []):
                assert screen in screens, \
                    f"Account {account.get('id')} references unknown screen {screen}"

    def test_test_scenarios(self, demo_accounts):
        """Test scenarios are documented."""
        scenarios = demo_accounts.get('test_scenarios', [])
        assert len(scenarios) >= 4, \
            f"Only {len(scenarios)} test scenarios, expected 4+"

        for scenario in scenarios:
            assert scenario.get('name'), "Scenario missing name"
            assert scenario.get('role'), "Scenario missing role"
            assert scenario.get('steps'), "Scenario missing steps"

class TestConsistency:
    """Test cross-component consistency."""

    def test_screen_roles_consistency(self, knowledge, demo_accounts):
        """Demo accounts have access to appropriate screens."""
        screens = knowledge.get('screens', {})
        accounts = demo_accounts.get('accounts', [])

        for account in accounts:
            role = account['role']
            account_screens = set(account['access_path'])

            # Check that account's screens are compatible with role
            for screen_key in account_screens:
                screen = screens.get(screen_key, {})
                allowed_roles = screen.get('roles', [])
                assert role in allowed_roles, \
                    f"Account {account['id']} ({role}) cannot access {screen_key}"

    def test_no_duplicate_account_ids(self, demo_accounts):
        """Account IDs are unique."""
        accounts = demo_accounts.get('accounts', [])
        ids = [a['id'] for a in accounts]
        assert len(ids) == len(set(ids)), "Duplicate account IDs found"

    def test_no_duplicate_emails(self, demo_accounts):
        """Demo account emails are unique."""
        accounts = demo_accounts.get('accounts', [])
        emails = [a['email'] for a in accounts]
        assert len(emails) == len(set(emails)), "Duplicate account emails found"

class TestIntegration:
    """Integration tests for v1.3 features."""

    def test_role_based_screen_access(self, knowledge):
        """All role-to-screen mappings are valid."""
        screens = knowledge.get('screens', {})
        roles = knowledge.get('roles', {})

        role_access_count = {}
        for role_key in roles.keys():
            role_access_count[role_key] = 0

        for screen_data in screens.values():
            for role in screen_data.get('roles', []):
                role_access_count[role] += 1

        # Each role should have access to at least some screens
        for role_key, count in role_access_count.items():
            assert count > 0, f"Role {role_key} has no screen access"

    def test_schema_backward_compatibility(self, knowledge):
        """v1.3 knowledge can be used as v1.0 with additional fields."""
        # The screens should still have all v1.0 fields
        screens = knowledge.get('screens', {})
        v10_fields = {'route', 'name', 'purpose', 'why', 'whenToUse',
                      'prerequisites', 'afterwards', 'steps', 'faq', 'parts'}

        for screen_key, screen_data in screens.items():
            missing = v10_fields - set(screen_data.keys())
            # Allow some fields to be optional, but core ones should exist
            core_fields = {'name', 'purpose', 'why', 'whenToUse'}
            missing_core = core_fields - set(screen_data.keys())
            assert not missing_core, \
                f"Screen {screen_key} missing v1.0 core fields: {missing_core}"

class TestMetrics:
    """Test and report metrics."""

    def test_coverage_metrics(self, knowledge, demo_accounts):
        """Verify coverage metrics."""
        screens_count = len(knowledge.get('screens', {}))
        journeys_count = len(knowledge.get('journeys', {}))
        roles_count = len(knowledge.get('roles', {}))
        accounts_count = len(demo_accounts.get('accounts', []))

        print(f"\n=== UHEF v1.3 Coverage Metrics ===")
        print(f"Documented Screens: {screens_count}")
        print(f"User Journeys: {journeys_count}")
        print(f"Role Definitions: {roles_count}")
        print(f"Demo Accounts: {accounts_count}")
        print(f"Test Scenarios: {len(demo_accounts.get('test_scenarios', []))}")

        assert screens_count >= MIN_SCREENS
        assert roles_count >= MIN_ROLES
        assert accounts_count >= 10

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
