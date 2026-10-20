"""Certificate register. Additive schema; issued snapshots are never edited."""
from sqlalchemy import Table, Column, String, JSON, ForeignKey, UniqueConstraint, CheckConstraint, Index
from app.db import metadata

certificate_templates = Table('px_certificate_templates', metadata,
    Column('id', String(64), primary_key=True),
    Column('event_id', String(64), ForeignKey('px_sites.id'), nullable=False),
    Column('name', String(160), nullable=False),
    Column('design', JSON, nullable=False),
    Column('created_at', String(64), nullable=False))

certificates = Table('px_certificates', metadata,
    Column('id', String(64), primary_key=True),
    Column('event_id', String(64), ForeignKey('px_sites.id'), nullable=False),
    Column('template_id', String(64), ForeignKey('px_certificate_templates.id'), nullable=False),
    Column('request_key', String(80), nullable=False),
    Column('request_hash', String(64), nullable=False),
    Column('recipient_key', String(160), nullable=False),
    Column('award_key', String(80), nullable=False),
    Column('serial', String(64), unique=True, nullable=False),
    Column('access_hash', String(64), unique=True, nullable=False),
    Column('snapshot', JSON, nullable=False),
    Column('snapshot_hash', String(64), nullable=False),
    Column('status', String(16), nullable=False),
    Column('issued_at', String(64), nullable=False),
    Column('expires_at', String(64)),
    Column('revoked_at', String(64)),
    Column('revoke_reason', String(500)),
    UniqueConstraint('event_id', 'request_key', name='uq_px_certificate_request'),
    UniqueConstraint('event_id', 'recipient_key', 'award_key', name='uq_px_certificate_award'),
    CheckConstraint("status IN ('issued', 'revoked')", name='ck_px_certificate_status'))
Index('px_certificates_event_time', certificates.c.event_id, certificates.c.issued_at)
