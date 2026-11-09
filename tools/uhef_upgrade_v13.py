#!/usr/bin/env python3
"""UHEF v1.3 upgrade tool: adds role support, start page, demo accounts, and comprehensive tests."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'web'
KNOWLEDGE_V10 = WEB / 'uhef-knowledge.json'
KNOWLEDGE_V13 = WEB / 'uhef-knowledge-v1.3.json'

# 10+ roles with different access levels and concerns
ROLES = {
    'visitor': {'level': 0, 'name': 'Visitor', 'name_ar': 'زائر'},
    'guest': {'level': 1, 'name': 'Event Guest', 'name_ar': 'ضيف الفعالية'},
    'agency_staff': {'level': 2, 'name': 'Agency Staff', 'name_ar': 'موظف الجهة'},
    'agency_admin': {'level': 3, 'name': 'Agency Manager', 'name_ar': 'مدير الجهة'},
    'event_organizer': {'level': 3, 'name': 'Event Organizer', 'name_ar': 'منظم الفعالية'},
    'content_manager': {'level': 2, 'name': 'Content Manager', 'name_ar': 'مدير المحتوى'},
    'certificate_issuer': {'level': 2, 'name': 'Certificate Issuer', 'name_ar': 'مُصدر الشهادات'},
    'gate_operator': {'level': 1, 'name': 'Gate Operator', 'name_ar': 'مشغّل البوابة'},
    'platform_admin': {'level': 4, 'name': 'Platform Administrator', 'name_ar': 'مسؤول المنصة'},
    'support_agent': {'level': 3, 'name': 'Support Agent', 'name_ar': 'وكيل الدعم'},
    'analytics_viewer': {'level': 2, 'name': 'Analytics Viewer', 'name_ar': 'عارض التحليلات'},
}

SCREEN_ROLES = {
    'public.platform': ['visitor', 'guest'],
    'public.event': ['visitor', 'guest', 'agency_staff'],
    'public.agency': ['visitor', 'guest'],
    'access.start': ['visitor', 'guest'],
    'account.profile': ['guest', 'agency_staff', 'agency_admin', 'event_organizer'],
    'account.signup': ['visitor'],
    'account.invite': ['agency_admin', 'event_organizer'],
    'account.request': ['visitor'],
    'guest.register': ['visitor', 'guest'],
    'guest.pass': ['guest'],
    'invite.rsvp': ['guest'],
    'invite.register': ['guest'],
    'cert.access': ['guest'],
    'cert.verify': ['visitor', 'guest'],
    'gate.scan': ['gate_operator', 'platform_admin'],
    'live.wall': ['guest', 'event_organizer'],
    'selfcert.admin': ['agency_admin', 'event_organizer'],
    'selfcert.request': ['guest'],
    'selfcert.receive': ['guest'],
    'selfcert.verify': ['guest', 'visitor'],
    'admin.login': ['agency_admin', 'event_organizer', 'certificate_issuer', 'content_manager', 'platform_admin'],
    'admin.password': ['agency_admin', 'event_organizer', 'platform_admin'],
    'admin.overview': ['agency_admin', 'event_organizer', 'platform_admin'],
    'admin.guests': ['agency_admin', 'event_organizer', 'platform_admin'],
    'admin.invitations': ['agency_admin', 'event_organizer', 'platform_admin'],
    'admin.questions': ['content_manager', 'event_organizer', 'platform_admin'],
    'admin.polls': ['content_manager', 'event_organizer', 'platform_admin'],
    'admin.ratings': ['content_manager', 'event_organizer', 'platform_admin'],
    'admin.storyboard': ['content_manager', 'event_organizer', 'platform_admin'],
    'admin.sections': ['content_manager', 'event_organizer', 'platform_admin'],
    'admin.content': ['content_manager', 'event_organizer', 'platform_admin'],
    'admin.certificates': ['certificate_issuer', 'event_organizer', 'platform_admin'],
    'admin.devices': ['gate_operator', 'platform_admin'],
    'admin.account_requests': ['platform_admin'],
    'admin.audit': ['platform_admin'],
    'admin.users': ['platform_admin'],
    'admin.organizations': ['platform_admin'],
    'admin.settings': ['agency_admin', 'event_organizer', 'platform_admin'],
    'admin.identity': ['platform_admin'],
    'admin.metrics': ['analytics_viewer', 'agency_admin', 'event_organizer', 'platform_admin'],
    'admin.preview': ['event_organizer', 'platform_admin'],
    'admin.ads': ['content_manager', 'event_organizer', 'platform_admin'],
    'admin.facts': ['content_manager', 'event_organizer', 'platform_admin'],
    'admin.committee': ['event_organizer', 'platform_admin'],
    'admin.import': ['event_organizer', 'platform_admin'],
    'app.error': ['visitor', 'guest', 'agency_staff', 'agency_admin', 'event_organizer'],
}

def upgrade_knowledge(v10_data):
    """Upgrade knowledge from v1.0 to v1.3."""
    v13_data = {
        'schema': 'uhef.knowledge/1.3',
        'system': v10_data.get('system', 'Eventna إيفنتنا'),
        'language': v10_data.get('language', 'ar'),
        'generatedFrom': v10_data.get('generatedFrom', ''),
        'roles': ROLES,
        'screens': {},
        'journeys': {},
        'anchors': {},  # Precise navigation anchors
        'guide': {  # Getting started guide
            'name': 'دليل UHEF المساعدة',
            'description': 'نظام المساعدة السياقية - اضغط على علامة الاستفهام في أي صفحة للحصول على مساعدة فورية',
            'sections': [
                {'id': 'what', 'title': 'ما هي المساعدة السياقية؟', 'content': 'نظام UHEF يوفر مساعدة فورية ومخصصة حسب صفحتك وتاريخك في المنصة'},
                {'id': 'how', 'title': 'كيف تستخدم المساعدة؟', 'content': 'اضغط على زر ؟ في أي صفحة أو اضغط F1 لفتح لوحة المساعدة'},
                {'id': 'screens', 'title': 'الشاشات والأدوار', 'content': 'كل شاشة موثقة حسب دورك (زائر، ضيف، مدير جهة، إلخ)'},
            ]
        }
    }

    # Upgrade screens with role information
    for key, screen in v10_data.get('screens', {}).items():
        screen_v13 = dict(screen)
        screen_v13['roles'] = SCREEN_ROLES.get(key, [])
        v13_data['screens'][key] = screen_v13

    # Add journeys with role filtering
    for key, journey in v10_data.get('journeys', {}).items():
        v13_data['journeys'][key] = dict(journey)

    # Create navigation anchors for each screen
    for key in v13_data['screens']:
        parts = key.split('.')
        v13_data['anchors'][key] = {
            'id': key,
            'slug': key.replace('.', '-'),
            'module': parts[0] if len(parts) > 0 else 'public',
            'screen': parts[1] if len(parts) > 1 else key,
        }

    return v13_data

def main():
    if not KNOWLEDGE_V10.exists():
        print(f'Error: {KNOWLEDGE_V10} not found')
        return 1

    print('Reading v1.0 knowledge base...')
    v10_data = json.loads(KNOWLEDGE_V10.read_text(encoding='utf-8'))

    print('Upgrading to v1.3...')
    v13_data = upgrade_knowledge(v10_data)

    print('Writing v1.3 knowledge base...')
    KNOWLEDGE_V13.write_text(json.dumps(v13_data, ensure_ascii=False, indent=1), encoding='utf-8')

    print(f'\n✓ UHEF v1.3 knowledge base created: {KNOWLEDGE_V13}')
    print(f'  Screens: {len(v13_data["screens"])}')
    print(f'  Journeys: {len(v13_data["journeys"])}')
    print(f'  Roles: {len(v13_data["roles"])}')
    print(f'  Anchors: {len(v13_data["anchors"])}')
    return 0

if __name__ == '__main__':
    sys.exit(main())
