from __future__ import annotations
import os
from pathlib import Path
from sqlalchemy import create_engine, MetaData, Table, Column, String, Integer, Text, JSON, ForeignKey, UniqueConstraint, Index, event
from sqlalchemy.pool import StaticPool
from sqlalchemy.engine import make_url
from app.core.paths import resolve_database_url

metadata=MetaData()
sites=Table('px_sites',metadata,Column('id',String(64),primary_key=True),Column('parent_id',String(64),ForeignKey('px_sites.id')),Column('event_id',String(64)),Column('kind',String(20),nullable=False),Column('slug',String(80),unique=True,nullable=False),Column('draft',JSON,nullable=False),Column('draft_rev',Integer,nullable=False,default=1),Column('published_version',Integer,nullable=False,default=0))
versions=Table('px_site_versions',metadata,Column('site_id',String(64),ForeignKey('px_sites.id'),primary_key=True),Column('version',Integer,primary_key=True),Column('config',JSON,nullable=False),Column('published_at',String(64),nullable=False))
users=Table('px_users',metadata,Column('id',String(64),primary_key=True),Column('email',String(200),unique=True,nullable=False),Column('name',String(200),nullable=False),Column('role',String(20),nullable=False),Column('scope_id',String(64),ForeignKey('px_sites.id')),Column('password_hash',Text,nullable=False),Column('active',Integer,nullable=False,default=1),Column('must_change_password',Integer,nullable=False,default=0))
sessions=Table('px_sessions',metadata,Column('token_hash',String(64),primary_key=True),Column('user_id',String(64),ForeignKey('px_users.id'),nullable=False),Column('csrf',String(100),nullable=False),Column('expires_at',String(64),nullable=False))
imports=Table('px_imports',metadata,Column('id',String(64),primary_key=True),Column('site_id',String(64),ForeignKey('px_sites.id'),nullable=False),Column('user_id',String(64),ForeignKey('px_users.id'),nullable=False),Column('base_rev',Integer,nullable=False),Column('records',JSON,nullable=False),Column('errors',JSON,nullable=False),Column('state',String(30),nullable=False),Column('created_at',String(64),nullable=False))
submissions=Table('px_submissions',metadata,Column('id',String(64),primary_key=True),Column('site_id',String(64),ForeignKey('px_sites.id'),nullable=False),Column('event_id',String(64)),Column('version',Integer,nullable=False),Column('kind',String(30),nullable=False),Column('visitor_id',String(64),nullable=False),Column('session_id',String(64),nullable=False),Column('source',String(20),nullable=False),Column('target',String(150)),Column('payload',JSON,nullable=False),Column('client_time',String(64)),Column('received_at',String(64),nullable=False),Column('fingerprint',String(64),nullable=False),Column('dedup_key',String(240),unique=True))
Index('px_submissions_site_time',submissions.c.site_id,submissions.c.received_at)
Index('px_submissions_event_kind',submissions.c.event_id,submissions.c.kind)
requests=Table('px_access_requests',metadata,Column('id',String(64),primary_key=True),Column('site_id',String(64),ForeignKey('px_sites.id'),nullable=False),Column('email',String(200),nullable=False),Column('name',String(160),nullable=False),Column('created_at',String(64),nullable=False),Column('status',String(20),nullable=False,default='pending'))

organizations=Table('px_organizations',metadata,
    Column('id',String(64),primary_key=True),
    Column('slug',String(80),unique=True,nullable=False),
    Column('name',String(200),nullable=False),
    Column('profile',JSON,nullable=False),
    Column('status',String(20),nullable=False,default='active'),
    Column('created_at',String(64),nullable=False))
organization_people=Table('px_organization_people',metadata,
    Column('id',String(64),primary_key=True),
    Column('organization_id',String(64),ForeignKey('px_organizations.id'),nullable=False),
    Column('user_id',String(64),ForeignKey('px_users.id')),
    Column('name',String(160),nullable=False),
    Column('email',String(200)),
    Column('phone',String(60)),
    Column('job_title',String(160)),
    Column('person_role',String(40),nullable=False,default='member'),
    Column('public_visible',Integer,nullable=False,default=0),
    Column('status',String(20),nullable=False,default='active'),
    Column('created_at',String(64),nullable=False))
Index('px_org_people_org_status',organization_people.c.organization_id,organization_people.c.status)
Index('px_org_people_user',organization_people.c.user_id)

memberships=Table('px_memberships',metadata,
    Column('user_id',String(64),ForeignKey('px_users.id'),primary_key=True),
    Column('organization_id',String(64),ForeignKey('px_organizations.id'),primary_key=True),
    Column('role',String(40),nullable=False),
    Column('status',String(20),nullable=False,default='active'),
    Column('created_at',String(64),nullable=False))
event_participations=Table('px_event_participations',metadata,
    Column('id',String(64),primary_key=True),
    Column('event_id',String(64),ForeignKey('px_sites.id'),nullable=False),
    Column('organization_id',String(64),ForeignKey('px_organizations.id'),nullable=False),
    Column('agency_site_id',String(64),ForeignKey('px_sites.id')),
    Column('participation_type',String(40),nullable=False,default='exhibitor'),
    Column('status',String(20),nullable=False,default='active'),
    Column('booth',String(120)),
    Column('summary',Text),
    Column('services',JSON,nullable=False),
    Column('valid_from',String(64)),
    Column('valid_until',String(64)),
    Column('created_at',String(64),nullable=False),
    UniqueConstraint('event_id','organization_id',name='uq_px_event_org'))
assignments=Table('px_assignments',metadata,
    Column('id',String(64),primary_key=True),
    Column('user_id',String(64),ForeignKey('px_users.id'),nullable=False),
    Column('site_id',String(64),ForeignKey('px_sites.id'),nullable=False),
    Column('role',String(40),nullable=False),
    Column('status',String(20),nullable=False,default='active'),
    Column('valid_from',String(64)),
    Column('valid_until',String(64)),
    Column('created_at',String(64),nullable=False),
    UniqueConstraint('user_id','site_id','role',name='uq_px_assignment'))

devices=Table('px_devices',metadata,
    Column('id',String(64),primary_key=True),
    Column('site_id',String(64),ForeignKey('px_sites.id'),nullable=False),
    Column('name',String(160),nullable=False),
    Column('device_type',String(30),nullable=False),
    Column('token_hash',String(64),unique=True,nullable=False),
    Column('status',String(20),nullable=False,default='active'),
    Column('last_seen_at',String(64)),
    Column('last_sync_at',String(64)),
    Column('pending_count',Integer,nullable=False,default=0),
    Column('app_version',String(40)),
    Column('metadata_json',JSON,nullable=False),
    Column('created_at',String(64),nullable=False))
Index('px_devices_site_status',devices.c.site_id,devices.c.status)
Index('px_devices_last_seen',devices.c.last_seen_at)


signup_requests=Table('px_signup_requests',metadata,
    Column('id',String(64),primary_key=True),
    Column('site_id',String(64),ForeignKey('px_sites.id'),nullable=False),
    Column('event_id',String(64)),
    Column('requested_role',String(30),nullable=False),
    Column('organization_name',String(200),nullable=False),
    Column('contact_name',String(160),nullable=False),
    Column('email',String(200),nullable=False),
    Column('phone',String(60)),
    Column('participation_type',String(40)),
    Column('wants_account',Integer,nullable=False,default=1),
    Column('status',String(20),nullable=False,default='pending'),
    Column('details',JSON,nullable=False),
    Column('created_at',String(64),nullable=False))
Index('px_signup_site_status',signup_requests.c.site_id,signup_requests.c.status)
Index('px_signup_event_status',signup_requests.c.event_id,signup_requests.c.status)

guests=Table('px_guests',metadata,
    Column('id',String(64),primary_key=True),
    Column('phone_e164',String(24),unique=True,nullable=False),
    Column('phone_hash',String(64),unique=True,nullable=False),
    Column('guest_number',String(32),unique=True,nullable=False),
    Column('name',String(160)),
    Column('job_title',String(160)),
    Column('organization',String(200)),
    Column('status',String(20),nullable=False,default='active'),
    Column('created_at',String(64),nullable=False),
    Column('updated_at',String(64),nullable=False))
Index('px_guests_phone_hash',guests.c.phone_hash)
Index('px_guests_guest_number',guests.c.guest_number)

event_guests=Table('px_event_guests',metadata,
    Column('id',String(64),primary_key=True),
    Column('event_id',String(64),ForeignKey('px_sites.id'),nullable=False),
    Column('guest_id',String(64),ForeignKey('px_guests.id'),nullable=False),
    Column('status',String(20),nullable=False,default='registered'),
    Column('guest_type',String(40),nullable=False,default='visitor'),
    Column('pass_number',String(32),unique=True),
    Column('pass_token_hash',String(64)),
    Column('metadata_json',JSON,nullable=False),
    Column('registered_at',String(64),nullable=False),
    Column('updated_at',String(64),nullable=False),
    UniqueConstraint('event_id','guest_id',name='uq_px_event_guest'))
Index('px_event_guests_event_status',event_guests.c.event_id,event_guests.c.status)
Index('px_event_guests_guest',event_guests.c.guest_id)
Index('px_event_guests_pass_number',event_guests.c.pass_number,unique=True)

guest_checkins=Table('px_guest_checkins',metadata,
    Column('id',String(64),primary_key=True),
    Column('event_id',String(64),ForeignKey('px_sites.id'),nullable=False),
    Column('guest_id',String(64),ForeignKey('px_guests.id'),nullable=False),
    Column('guest_number',String(32),nullable=False),
    Column('scanner_id',String(64)),
    Column('source',String(20),nullable=False),
    Column('direction',String(12),nullable=False,default='entry'),
    Column('checkpoint',String(80),nullable=False,default='main'),
    Column('client_time',String(64)),
    Column('scanned_at',String(64),nullable=False))
Index('px_guest_checkins_event_time',guest_checkins.c.event_id,guest_checkins.c.scanned_at)
Index('px_guest_checkins_guest_time',guest_checkins.c.guest_id,guest_checkins.c.scanned_at)

guest_presence=Table('px_guest_presence',metadata,
    Column('event_id',String(64),ForeignKey('px_sites.id'),primary_key=True),
    Column('guest_id',String(64),ForeignKey('px_guests.id'),primary_key=True),
    Column('state',String(12),nullable=False,default='outside'),
    Column('last_scan_id',String(64)),
    Column('last_direction',String(12)),
    Column('last_checkpoint',String(80)),
    Column('updated_at',String(64),nullable=False))
Index('px_guest_presence_event_state',guest_presence.c.event_id,guest_presence.c.state)
audit=Table('px_audit',metadata,Column('id',String(64),primary_key=True),Column('user_id',String(64)),Column('site_id',String(64)),Column('action',String(80),nullable=False),Column('at',String(64),nullable=False),Column('details',JSON,nullable=False))

def make_engine(url=None):
    url=resolve_database_url(url if url is not None else os.environ.get('DATABASE_URL','sqlite:///./data/pulsex-pilot.sqlite3'))
    if os.environ.get('REQUIRE_POSTGRES','false').strip().lower() in ('1','true','yes','on') and not url.startswith('postgresql+psycopg://'):
        raise RuntimeError('POSTGRES_REQUIRED')
    parsed=make_url(url)
    if parsed.get_backend_name()=='sqlite' and parsed.database and parsed.database!=':memory:' and parsed.query.get('uri','').lower()!='true':
        Path(parsed.database).parent.mkdir(parents=True,exist_ok=True)
    kw={'pool_pre_ping':True}
    if url.startswith('sqlite'):
        kw['connect_args']={'check_same_thread':False,'timeout':30}
        if ':memory:' in url: kw['poolclass']=StaticPool
    engine=create_engine(url,**kw)
    if url.startswith('sqlite'):
        @event.listens_for(engine,'connect')
        def configure(dbapi,_):
            cur=dbapi.cursor();cur.execute('PRAGMA foreign_keys=ON');cur.execute('PRAGMA journal_mode=WAL');cur.close()
    return engine

# Supporting indexes for scaled administration and audit/event lookups.
Index('px_memberships_org_status',memberships.c.organization_id,memberships.c.status)
Index('px_memberships_user_status',memberships.c.user_id,memberships.c.status)
Index('px_participations_event_status',event_participations.c.event_id,event_participations.c.status)
Index('px_participations_org_status',event_participations.c.organization_id,event_participations.c.status)
Index('px_assignments_site_status',assignments.c.site_id,assignments.c.status)
Index('px_assignments_user_status',assignments.c.user_id,assignments.c.status)
Index('px_audit_site_time',audit.c.site_id,audit.c.at)
Index('px_audit_user_time',audit.c.user_id,audit.c.at)


def ensure_compat_schema(engine):
    """Small additive compatibility migration for local upgrades; production uses versioned SQL migrations."""
    from sqlalchemy import inspect, text as sa_text
    insp=inspect(engine)
    if 'px_users' in insp.get_table_names():
        cols={c['name'] for c in insp.get_columns('px_users')}
        if 'must_change_password' not in cols:
            with engine.begin() as c:
                c.execute(sa_text('ALTER TABLE px_users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0'))
    if 'px_event_guests' in insp.get_table_names():
        cols={c['name'] for c in insp.get_columns('px_event_guests')}
        if 'pass_token_hash' not in cols:
            with engine.begin() as c:
                c.execute(sa_text('ALTER TABLE px_event_guests ADD COLUMN pass_token_hash VARCHAR(64)'))
        if 'pass_number' not in cols:
            with engine.begin() as c:
                c.execute(sa_text('ALTER TABLE px_event_guests ADD COLUMN pass_number VARCHAR(32)'))
                c.execute(sa_text('CREATE UNIQUE INDEX IF NOT EXISTS px_event_guests_pass_number ON px_event_guests(pass_number)'))
