"""Additive invitation/admission schema. PostgreSQL migration: ops/009_invitations.sql."""
from sqlalchemy import Table, Column, String, Integer, JSON, ForeignKey, UniqueConstraint, CheckConstraint, Index
from app.db import metadata

admission_policies = Table('px_event_admission', metadata,
    Column('event_id', String(64), ForeignKey('px_sites.id'), primary_key=True),
    Column('config', JSON, nullable=False), Column('rev', Integer, nullable=False, default=1),
    Column('updated_at', String(64), nullable=False))
guest_lists = Table('px_guest_lists', metadata,
    Column('id', String(64), primary_key=True), Column('event_id', String(64), ForeignKey('px_sites.id'), nullable=False),
    Column('name', String(160), nullable=False), Column('created_at', String(64), nullable=False),
    UniqueConstraint('event_id', 'name', name='uq_px_guest_list_name'))
invitations = Table('px_invitations', metadata,
    Column('id', String(64), primary_key=True), Column('event_id', String(64), ForeignKey('px_sites.id'), nullable=False),
    Column('list_id', String(64), ForeignKey('px_guest_lists.id')),
    Column('guest_id', String(64), ForeignKey('px_guests.id')),
    Column('name', String(160), nullable=False), Column('phone', String(24), nullable=False),
    Column('token_hash', String(64), unique=True, nullable=False),
    Column('status', String(24), nullable=False), Column('response', String(24), nullable=False),
    Column('max_companions', Integer, nullable=False), Column('companions', Integer, nullable=False, default=0),
    Column('allowed_days', JSON, nullable=False), Column('days', JSON, nullable=False), Column('answers', JSON, nullable=False),
    Column('consent_at', String(64)), Column('reviewed_by', String(64)), Column('reviewed_at', String(64)),
    Column('revision', Integer, nullable=False, default=1), Column('created_at', String(64), nullable=False),
    Column('updated_at', String(64), nullable=False),
    UniqueConstraint('event_id', 'phone', name='uq_px_invitation_event_phone'),
    CheckConstraint('max_companions >= 0 AND companions >= 0 AND companions <= max_companions', name='ck_px_invitation_companions'))
Index('px_invitations_event_status', invitations.c.event_id, invitations.c.status)
entitlements = Table('px_admission_entitlements', metadata,
    Column('id', String(64), primary_key=True), Column('invitation_id', String(64), ForeignKey('px_invitations.id'), nullable=False),
    Column('event_id', String(64), ForeignKey('px_sites.id'), nullable=False),
    Column('guest_id', String(64), ForeignKey('px_guests.id'), nullable=False),
    Column('day', String(10), nullable=False), Column('quantity', Integer, nullable=False),
    Column('consumed', Integer, nullable=False, default=0), Column('status', String(20), nullable=False),
    UniqueConstraint('invitation_id', 'day', name='uq_px_entitlement_day'),
    CheckConstraint('quantity > 0 AND consumed >= 0 AND consumed <= quantity', name='ck_px_entitlement_quantity'))
Index('px_entitlement_event_day', entitlements.c.event_id, entitlements.c.day)
admission_uses = Table('px_admission_uses', metadata,
    Column('scan_id', String(64), primary_key=True), Column('entitlement_id', String(64), ForeignKey('px_admission_entitlements.id'), nullable=False),
    Column('quantity', Integer, nullable=False), Column('used_at', String(64), nullable=False),
    CheckConstraint('quantity > 0', name='ck_px_admission_use_quantity'))
invitation_imports = Table('px_invitation_imports', metadata,
    Column('id', String(64), primary_key=True), Column('event_id', String(64), ForeignKey('px_sites.id'), nullable=False),
    Column('user_id', String(64), ForeignKey('px_users.id'), nullable=False),
    Column('rows', JSON, nullable=False), Column('errors', JSON, nullable=False),
    Column('state', String(20), nullable=False), Column('created_at', String(64), nullable=False))
