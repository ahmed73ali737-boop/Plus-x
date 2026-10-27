"""Additive self-service certificates; no changes to the legacy register."""
from sqlalchemy import Table, Column, String, Integer, Boolean, JSON, Text, ForeignKey, UniqueConstraint, CheckConstraint, Index, event, DDL, ForeignKeyConstraint, PrimaryKeyConstraint
from app.db import metadata

def ident(): return Column('id', String(64), primary_key=True)
def owner(): return Column('owner_account_id', String(64), ForeignKey('px_users.id'), nullable=False)
def created(): return Column('created_at', String(64), nullable=False)

assets = Table('px_self_certificate_assets', metadata, ident(), owner(),
    Column('kind', String(20), nullable=False), Column('storage_key', String(200), unique=True, nullable=False),
    Column('sha256', String(64), nullable=False), Column('mime', String(80), nullable=False),
    Column('size_bytes', Integer, nullable=False), Column('width', Integer), Column('height', Integer),
    Column('source_kind', String(20), nullable=False), Column('original_size_bytes', Integer, nullable=False),
    Column('source_metadata', JSON, nullable=False), created(),
    CheckConstraint("kind IN ('background','stamp','final','thumbnail','export')", name='ck_self_asset_kind'))

models = Table('px_self_certificate_models', metadata, ident(), owner(),
    Column('name', String(160), nullable=False),
    Column('current_revision_id', String(64), ForeignKey('px_self_certificate_revisions.id', use_alter=True, name='fk_self_model_current_revision')),
    Column('row_version', Integer, nullable=False, default=1), created(), Column('updated_at', String(64), nullable=False))

revisions = Table('px_self_certificate_revisions', metadata, ident(), owner(),
    Column('origin_model_id', String(64), ForeignKey('px_self_certificate_models.id', ondelete='SET NULL')),
    Column('background_asset_id', String(64), ForeignKey(assets.c.id), nullable=False),
    Column('stamp_asset_id', String(64), ForeignKey(assets.c.id)),
    Column('config', JSON, nullable=False), Column('font_manifest', JSON, nullable=False),
    Column('branding_manifest', JSON(none_as_null=True)),
    Column('renderer_version', String(64), nullable=False), Column('schema_version', Integer, nullable=False), created(),
    CheckConstraint('schema_version < 2 OR branding_manifest IS NOT NULL', name='ck_self_revision_branding'))

links = Table('px_self_certificate_links', metadata, ident(), owner(),
    Column('event_id', String(64), ForeignKey('px_sites.id'), nullable=False),
    Column('event_name_snapshot', String(250), nullable=False), Column('model_name_snapshot', String(160), nullable=False),
    Column('revision_id', String(64), ForeignKey(revisions.c.id), nullable=False),
    Column('public_id', String(64), unique=True, nullable=False), Column('key_version', String(40), nullable=False),
    Column('public_token_hash', String(64), unique=True, nullable=False),
    Column('status', String(16), nullable=False), Column('share_text_snapshot', Text, nullable=False),
    Column('config_hash', String(64), nullable=False), Column('input_hash', String(64)), Column('idempotency_key', String(80), nullable=False),
    Column('row_version', Integer, nullable=False, default=1), created(), Column('disabled_at', String(64)),
    UniqueConstraint('owner_account_id', 'idempotency_key', name='uq_self_link_idempotency'),
    CheckConstraint("status IN ('active','paused')", name='ck_self_link_status'))

browser_sessions = Table('px_self_certificate_browser_sessions', metadata, ident(),
    Column('token_hash', String(64), unique=True, nullable=False), created(),
    Column('last_seen_at', String(64), nullable=False))

requests = Table('px_self_certificate_requests', metadata, ident(), owner(),
    Column('link_id', String(64), ForeignKey(links.c.id), nullable=False),
    Column('browser_session_id', String(64), ForeignKey(browser_sessions.c.id), nullable=False),
    Column('revision_id', String(64), ForeignKey(revisions.c.id), nullable=False),
    Column('participant_name_original', String(250), nullable=False),
    Column('participant_name_normalized', String(250), nullable=False),
    Column('phone_original', String(60), nullable=False), Column('phone_normalized', String(60), nullable=False),
    Column('consent', Boolean, nullable=False), Column('consent_text', String(600), nullable=False),
    Column('consent_text_version', String(40), nullable=False),
    Column('submitted_at_utc', String(64), nullable=False), Column('status', String(20), nullable=False),
    Column('error_code', String(80)), Column('layout', JSON, nullable=False),
    UniqueConstraint('link_id', 'browser_session_id', name='uq_self_browser_link'),
    CheckConstraint('consent = true', name='ck_self_consent'),
    CheckConstraint("status IN ('registered','processing','failed','issued')", name='ck_self_request_status'))

jobs = Table('px_self_certificate_generation_jobs', metadata, ident(),
    Column('request_id', String(64), ForeignKey(requests.c.id), unique=True, nullable=False),
    Column('status', String(20), nullable=False), Column('attempts', Integer, nullable=False, default=0),
    Column('available_at', String(64), nullable=False), Column('lease_owner', String(64)),
    Column('lease_until', String(64)), Column('last_error_code', String(80)), created(),
    CheckConstraint("status IN ('pending','leased','retry_wait','failed','done')", name='ck_self_job_status'))

certificates = Table('px_self_certificates', metadata, ident(), owner(),
    Column('request_id', String(64), ForeignKey(requests.c.id), unique=True, nullable=False),
    Column('link_id', String(64), ForeignKey(links.c.id), nullable=False),
    Column('serial', String(64), unique=True, nullable=False), Column('name_printed', String(250), nullable=False),
    Column('layout', JSON, nullable=False), Column('issued_at_utc', String(64), nullable=False),
    Column('final_asset_id', String(64), ForeignKey(assets.c.id), nullable=False),
    Column('thumbnail_asset_id', String(64), ForeignKey(assets.c.id), nullable=False),
    Column('delivery_token_hash', String(64), unique=True, nullable=False),
    Column('key_version', String(40), nullable=False), Column('integrity_hash', String(64), nullable=False),
    Column('source', String(30), nullable=False), Column('schema_version', Integer, nullable=False),
    CheckConstraint("source = 'self_service'", name='ck_self_certificate_source'))

exports = Table('px_self_certificate_export_jobs', metadata, ident(), owner(),
    Column('cutoff', String(64), nullable=False), Column('format', String(8), nullable=False),
    Column('status', String(20), nullable=False), Column('asset_id', String(64), ForeignKey(assets.c.id)),
    Column('error_code', String(80)), Column('row_count', Integer),
    Column('lease_owner', String(64)), Column('lease_until', String(64)),
    Column('attempts', Integer, nullable=False, default=0, server_default='0'), Column('started_at', String(64)), created(),
    Column('snapshot_version', Integer, nullable=False, default=1, server_default='1'),
    Column('snapshot_taken_at', String(64)), Column('expected_rows', Integer),
    Column('idempotency_key', String(80)), Column('input_hash', String(64)),
    UniqueConstraint('owner_account_id','idempotency_key', name='uq_self_export_idempotency'),
    CheckConstraint("format IN ('csv','xlsx')", name='ck_self_export_format'),
    CheckConstraint("status IN ('pending','processing','done','failed')", name='ck_self_export_status'))

model_operations = Table('px_self_certificate_model_operations',metadata,owner(),
    Column('idempotency_key',String(80),nullable=False),Column('input_hash',String(64),nullable=False),
    Column('result',JSON,nullable=False),created(),
    PrimaryKeyConstraint('owner_account_id','idempotency_key',name='pk_self_model_operations'))

export_snapshot_rows = Table('px_self_certificate_export_snapshot_rows', metadata,
    Column('export_id', String(64), ForeignKey(exports.c.id), primary_key=True),
    Column('ordinal', Integer, primary_key=True), owner(),
    Column('source_request_id', String(64), nullable=False),
    Column('participant_name_original', String(250), nullable=False),
    Column('phone_original', String(60), nullable=False),
    Column('model_name_snapshot', String(160), nullable=False),
    Column('event_name_snapshot', String(250), nullable=False),
    Column('submitted_at_utc', String(64), nullable=False),
    Column('status', String(20), nullable=False),
    UniqueConstraint('export_id','source_request_id',name='uq_self_snapshot_request'),
    CheckConstraint('ordinal > 0',name='ck_self_snapshot_ordinal'),
    CheckConstraint("status IN ('registered','processing','failed','issued')",name='ck_self_snapshot_status'))

rate_buckets = Table('px_self_certificate_rate_buckets', metadata,
    Column('bucket_hash', String(64), primary_key=True), Column('window', Integer, primary_key=True),
    Column('count', Integer, nullable=False))

Index('ix_self_requests_owner_time', requests.c.owner_account_id, requests.c.submitted_at_utc, requests.c.id)
Index('ix_self_links_owner_time', links.c.owner_account_id, links.c.created_at, links.c.id)
Index('ix_self_models_owner_time', models.c.owner_account_id, models.c.updated_at, models.c.id)
Index('ix_self_jobs_pending', jobs.c.status, jobs.c.available_at)
Index('ix_self_exports_pending', exports.c.status, exports.c.created_at)
Index('ix_self_assets_owner_time', assets.c.owner_account_id, assets.c.created_at)

# Guard business records even when a generic SQL update bypasses a service.
GUARDS = {
    'px_self_certificate_requests': ('owner_account_id','link_id','browser_session_id','revision_id',
        'participant_name_original','participant_name_normalized','phone_original','phone_normalized',
        'consent','consent_text','consent_text_version','submitted_at_utc','layout'),
    'px_self_certificate_links': ('owner_account_id','event_id','event_name_snapshot','model_name_snapshot',
        'revision_id','public_id','key_version','public_token_hash','share_text_snapshot','config_hash','input_hash','idempotency_key','created_at'),
    'px_self_certificate_models': ('owner_account_id',),
}
for table_name, fields in GUARDS.items():
    condition = ' OR '.join('NEW.'+f+' IS NOT OLD.'+f for f in ('id',*fields))
    event.listen(metadata, 'after_create', DDL(
        'CREATE TRIGGER IF NOT EXISTS guard_'+table_name+' BEFORE UPDATE ON '+table_name+
        " WHEN "+condition+" BEGIN SELECT RAISE(ABORT, 'SELF_CERTIFICATE_IMMUTABLE'); END;"
    ).execute_if(dialect='sqlite'))
for table_name in ('px_self_certificates','px_self_certificate_assets'):
    event.listen(metadata,'after_create',DDL(
        'CREATE TRIGGER IF NOT EXISTS guard_'+table_name+' BEFORE UPDATE ON '+table_name+
        " BEGIN SELECT RAISE(ABORT, 'SELF_CERTIFICATE_IMMUTABLE'); END;"
    ).execute_if(dialect='sqlite'))
# Only detaching a deleted library record is allowed on a revision.
revision_fields = tuple(c.name for c in revisions.c if c.name != 'origin_model_id')
condition = ' OR '.join('NEW.'+f+' IS NOT OLD.'+f for f in revision_fields)
condition += ' OR (NEW.origin_model_id IS NOT OLD.origin_model_id AND NEW.origin_model_id IS NOT NULL)'
event.listen(metadata,'after_create',DDL(
    'CREATE TRIGGER IF NOT EXISTS guard_self_revision BEFORE UPDATE ON px_self_certificate_revisions WHEN '+
    condition+" BEGIN SELECT RAISE(ABORT, 'SELF_CERTIFICATE_IMMUTABLE'); END;"
).execute_if(dialect='sqlite'))
event.listen(metadata,'after_create',DDL(
    "CREATE TRIGGER IF NOT EXISTS guard_self_issued_delete BEFORE DELETE ON px_self_certificates BEGIN SELECT RAISE(ABORT, 'SELF_CERTIFICATE_IMMUTABLE'); END;"
).execute_if(dialect='sqlite'))

def ensure_sqlite_branding_schema(engine):
    """Upgrade only the new register on local SQLite; PostgreSQL uses migration 017."""
    if engine.dialect.name != 'sqlite':
        return
    from sqlalchemy import inspect
    inspector=inspect(engine)
    if revisions.name not in inspector.get_table_names():
        return
    fields={c['name'] for c in inspector.get_columns(revisions.name)}
    with engine.begin() as conn:
        if 'branding_manifest' not in fields:
            conn.exec_driver_sql('ALTER TABLE px_self_certificate_revisions ADD COLUMN branding_manifest JSON')
        # Rebuild the pre-V2 guard after the additive column exists.
        conn.exec_driver_sql('DROP TRIGGER IF EXISTS guard_self_revision')
        conn.exec_driver_sql('CREATE TRIGGER guard_self_revision BEFORE UPDATE ON px_self_certificate_revisions WHEN '+
            condition+" BEGIN SELECT RAISE(ABORT, 'SELF_CERTIFICATE_IMMUTABLE'); END;")
        conn.exec_driver_sql("CREATE TRIGGER IF NOT EXISTS guard_self_revision_brand_insert BEFORE INSERT ON px_self_certificate_revisions WHEN NEW.schema_version >= 2 AND NEW.branding_manifest IS NULL BEGIN SELECT RAISE(ABORT, 'SELF_CERTIFICATE_BRANDING_REQUIRED'); END;")

event.listen(metadata, 'after_create', DDL(
    "CREATE TRIGGER IF NOT EXISTS guard_self_revision_brand_insert BEFORE INSERT ON px_self_certificate_revisions WHEN NEW.schema_version >= 2 AND NEW.branding_manifest IS NULL BEGIN SELECT RAISE(ABORT, 'SELF_CERTIFICATE_BRANDING_REQUIRED'); END;"
).execute_if(dialect='sqlite'))

def _postgres_guard(name, table_name, fields=None, detach=False, deleting=False):
    """The ORM bootstrap installs the same guards as versioned PostgreSQL SQL."""
    if deleting:
        body="BEGIN RAISE EXCEPTION 'SELF_CERTIFICATE_IMMUTABLE' USING ERRCODE = '23514'; END;"
    else:
        expressions=['to_jsonb(NEW.'+field+') IS DISTINCT FROM to_jsonb(OLD.'+field+')' for field in (fields or ())]
        if detach:
            expressions.append('(NEW.origin_model_id IS DISTINCT FROM OLD.origin_model_id AND NEW.origin_model_id IS NOT NULL)')
        predicate=' OR '.join(expressions) if expressions else 'TRUE'
        body="BEGIN IF "+predicate+" THEN RAISE EXCEPTION 'SELF_CERTIFICATE_IMMUTABLE' USING ERRCODE = '23514'; END IF; RETURN NEW; END;"
    sql="CREATE OR REPLACE FUNCTION "+name+"() RETURNS trigger AS '"+body.replace("'","''")+"' LANGUAGE plpgsql"
    for statement in (sql,'DROP TRIGGER IF EXISTS '+name+' ON '+table_name,
        'CREATE TRIGGER '+name+' BEFORE '+('DELETE' if deleting else 'UPDATE')+' ON '+table_name+' FOR EACH ROW EXECUTE FUNCTION '+name+'()'):
        event.listen(metadata,'after_create',DDL(statement).execute_if(dialect='postgresql'))

for _table,_fields in GUARDS.items():
    _postgres_guard('guard_'+_table,_table,('id',*_fields))
for _table in ('px_self_certificates','px_self_certificate_assets'):
    _postgres_guard('guard_'+_table,_table)
_postgres_guard('guard_self_revision',revisions.name,revision_fields,detach=True)
_postgres_guard('guard_self_issued_delete',certificates.name,deleting=True)

def ensure_sqlite_export_schema(engine):
    if engine.dialect.name!='sqlite':return
    from sqlalchemy import inspect
    inspector=inspect(engine)
    if exports.name not in inspector.get_table_names():return
    fields={c['name'] for c in inspector.get_columns(exports.name)}
    with engine.begin() as conn:
        for name,kind in (('snapshot_version','INTEGER NOT NULL DEFAULT 1'),('snapshot_taken_at','VARCHAR(64)'),('expected_rows','INTEGER'),('idempotency_key','VARCHAR(80)'),('input_hash','VARCHAR(64)'),('lease_owner','VARCHAR(64)'),('lease_until','VARCHAR(64)'),('attempts','INTEGER NOT NULL DEFAULT 0'),('started_at','VARCHAR(64)')):
            if name not in fields:conn.exec_driver_sql('ALTER TABLE px_self_certificate_export_jobs ADD COLUMN '+name+' '+kind)
        conn.exec_driver_sql('CREATE UNIQUE INDEX IF NOT EXISTS uq_self_export_idempotency ON px_self_certificate_export_jobs(owner_account_id,idempotency_key)')
        conn.exec_driver_sql("UPDATE px_self_certificate_export_jobs SET status='failed',error_code='EXPORT_SNAPSHOT_LEGACY_REQUIRED',lease_owner=NULL,lease_until=NULL WHERE snapshot_version=1 AND status IN ('pending','processing')")


def ensure_sqlite_link_inputs(engine):
    if engine.dialect.name!='sqlite':return
    from sqlalchemy import inspect
    inspector=inspect(engine)
    if links.name not in inspector.get_table_names():return
    fields={c['name'] for c in inspector.get_columns(links.name)}
    with engine.begin() as conn:
        if 'input_hash' not in fields:conn.exec_driver_sql('ALTER TABLE px_self_certificate_links ADD COLUMN input_hash VARCHAR(64)')
        predicate=' OR '.join('NEW.'+f+' IS NOT OLD.'+f for f in ('id',*GUARDS[links.name]))
        conn.exec_driver_sql('DROP TRIGGER IF EXISTS guard_px_self_certificate_links')
        conn.exec_driver_sql("CREATE TRIGGER guard_px_self_certificate_links BEFORE UPDATE ON px_self_certificate_links WHEN "+predicate+" BEGIN SELECT RAISE(ABORT, 'SELF_CERTIFICATE_IMMUTABLE'); END;")


# Request-time snapshots freeze export membership and values, including status.
for _statement in ["CREATE TRIGGER IF NOT EXISTS guard_self_export_identity BEFORE UPDATE ON px_self_certificate_export_jobs WHEN NEW.id IS NOT OLD.id OR NEW.owner_account_id IS NOT OLD.owner_account_id OR NEW.cutoff IS NOT OLD.cutoff OR NEW.format IS NOT OLD.format OR NEW.snapshot_version IS NOT OLD.snapshot_version OR NEW.snapshot_taken_at IS NOT OLD.snapshot_taken_at OR NEW.idempotency_key IS NOT OLD.idempotency_key OR NEW.input_hash IS NOT OLD.input_hash OR NEW.created_at IS NOT OLD.created_at OR (OLD.expected_rows IS NOT NULL AND NEW.expected_rows IS NOT OLD.expected_rows) BEGIN SELECT RAISE(ABORT,'SELF_CERTIFICATE_IMMUTABLE'); END", "CREATE TRIGGER IF NOT EXISTS guard_self_snapshot_insert BEFORE INSERT ON px_self_certificate_export_snapshot_rows WHEN NOT EXISTS (SELECT 1 FROM px_self_certificate_export_jobs j WHERE j.id=NEW.export_id AND j.owner_account_id=NEW.owner_account_id AND j.snapshot_version=2 AND j.expected_rows IS NULL AND j.status='pending') BEGIN SELECT RAISE(ABORT,'EXPORT_SNAPSHOT_INVALID'); END", "CREATE TRIGGER IF NOT EXISTS guard_self_snapshot_update BEFORE UPDATE ON px_self_certificate_export_snapshot_rows BEGIN SELECT RAISE(ABORT,'SELF_CERTIFICATE_IMMUTABLE'); END", "CREATE TRIGGER IF NOT EXISTS guard_self_snapshot_delete BEFORE DELETE ON px_self_certificate_export_snapshot_rows WHEN NOT EXISTS (SELECT 1 FROM px_self_certificate_export_jobs j WHERE j.id=OLD.export_id AND j.error_code='EXPORT_EXPIRED') BEGIN SELECT RAISE(ABORT,'SELF_CERTIFICATE_IMMUTABLE'); END"]:
    event.listen(metadata,'after_create',DDL(_statement).execute_if(dialect='sqlite'))
for _statement in ["CREATE OR REPLACE FUNCTION guard_self_export_identity() RETURNS trigger AS 'BEGIN IF NEW.id IS DISTINCT FROM OLD.id OR NEW.owner_account_id IS DISTINCT FROM OLD.owner_account_id OR NEW.cutoff IS DISTINCT FROM OLD.cutoff OR NEW.format IS DISTINCT FROM OLD.format OR NEW.snapshot_version IS DISTINCT FROM OLD.snapshot_version OR NEW.snapshot_taken_at IS DISTINCT FROM OLD.snapshot_taken_at OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key OR NEW.input_hash IS DISTINCT FROM OLD.input_hash OR NEW.created_at IS DISTINCT FROM OLD.created_at OR (OLD.expected_rows IS NOT NULL AND NEW.expected_rows IS DISTINCT FROM OLD.expected_rows) THEN RAISE EXCEPTION ''SELF_CERTIFICATE_IMMUTABLE'' USING ERRCODE=''23514''; END IF; RETURN NEW; END;' LANGUAGE plpgsql", 'DROP TRIGGER IF EXISTS guard_self_export_identity ON px_self_certificate_export_jobs', 'CREATE TRIGGER guard_self_export_identity BEFORE UPDATE ON px_self_certificate_export_jobs FOR EACH ROW EXECUTE FUNCTION guard_self_export_identity()', "CREATE OR REPLACE FUNCTION guard_self_snapshot_insert() RETURNS trigger AS 'BEGIN IF NOT EXISTS (SELECT 1 FROM px_self_certificate_export_jobs j WHERE j.id=NEW.export_id AND j.owner_account_id=NEW.owner_account_id AND j.snapshot_version=2 AND j.expected_rows IS NULL AND j.status=''pending'') THEN RAISE EXCEPTION ''EXPORT_SNAPSHOT_INVALID'' USING ERRCODE=''23514''; END IF; RETURN NEW; END;' LANGUAGE plpgsql", 'DROP TRIGGER IF EXISTS guard_self_snapshot_insert ON px_self_certificate_export_snapshot_rows', 'CREATE TRIGGER guard_self_snapshot_insert BEFORE INSERT ON px_self_certificate_export_snapshot_rows FOR EACH ROW EXECUTE FUNCTION guard_self_snapshot_insert()', "CREATE OR REPLACE FUNCTION guard_self_snapshot_update() RETURNS trigger AS 'BEGIN RAISE EXCEPTION ''SELF_CERTIFICATE_IMMUTABLE'' USING ERRCODE=''23514''; END;' LANGUAGE plpgsql", 'DROP TRIGGER IF EXISTS guard_self_snapshot_update ON px_self_certificate_export_snapshot_rows', 'CREATE TRIGGER guard_self_snapshot_update BEFORE UPDATE ON px_self_certificate_export_snapshot_rows FOR EACH ROW EXECUTE FUNCTION guard_self_snapshot_update()', "CREATE OR REPLACE FUNCTION guard_self_snapshot_delete() RETURNS trigger AS 'BEGIN IF NOT EXISTS (SELECT 1 FROM px_self_certificate_export_jobs j WHERE j.id=OLD.export_id AND j.error_code=''EXPORT_EXPIRED'') THEN RAISE EXCEPTION ''SELF_CERTIFICATE_IMMUTABLE'' USING ERRCODE=''23514''; END IF; RETURN OLD; END;' LANGUAGE plpgsql", 'DROP TRIGGER IF EXISTS guard_self_snapshot_delete ON px_self_certificate_export_snapshot_rows', 'CREATE TRIGGER guard_self_snapshot_delete BEFORE DELETE ON px_self_certificate_export_snapshot_rows FOR EACH ROW EXECUTE FUNCTION guard_self_snapshot_delete()']:
    event.listen(metadata,'after_create',DDL(_statement).execute_if(dialect='postgresql'))


# Owner tuples supplement single-column historical FKs without cascading history.
metadata.tables['px_self_certificate_assets'].append_constraint(UniqueConstraint('owner_account_id','id', name='uq_self_asset_owner'))
metadata.tables['px_self_certificate_models'].append_constraint(UniqueConstraint('owner_account_id','id', name='uq_self_model_owner'))
metadata.tables['px_self_certificate_revisions'].append_constraint(UniqueConstraint('owner_account_id','id', name='uq_self_revision_owner'))
metadata.tables['px_self_certificate_links'].append_constraint(UniqueConstraint('owner_account_id','id', name='uq_self_link_owner'))
metadata.tables['px_self_certificate_links'].append_constraint(UniqueConstraint('owner_account_id','id','revision_id', name='uq_self_link_owner_revision'))
metadata.tables['px_self_certificate_requests'].append_constraint(UniqueConstraint('owner_account_id','id', name='uq_self_request_owner'))
metadata.tables['px_self_certificate_requests'].append_constraint(UniqueConstraint('owner_account_id','id','link_id', name='uq_self_request_owner_link'))
metadata.tables['px_self_certificate_export_jobs'].append_constraint(UniqueConstraint('owner_account_id','id', name='uq_self_export_owner'))
metadata.tables['px_self_certificate_models'].append_constraint(ForeignKeyConstraint(['owner_account_id', 'current_revision_id'],['px_self_certificate_revisions.owner_account_id', 'px_self_certificate_revisions.id'],name='fk_self_model_revision_owner',use_alter=True))
metadata.tables['px_self_certificate_revisions'].append_constraint(ForeignKeyConstraint(['owner_account_id', 'background_asset_id'],['px_self_certificate_assets.owner_account_id', 'px_self_certificate_assets.id'],name='fk_self_revision_background_owner',use_alter=True))
metadata.tables['px_self_certificate_revisions'].append_constraint(ForeignKeyConstraint(['owner_account_id', 'stamp_asset_id'],['px_self_certificate_assets.owner_account_id', 'px_self_certificate_assets.id'],name='fk_self_revision_stamp_owner',use_alter=True))
metadata.tables['px_self_certificate_links'].append_constraint(ForeignKeyConstraint(['owner_account_id', 'revision_id'],['px_self_certificate_revisions.owner_account_id', 'px_self_certificate_revisions.id'],name='fk_self_link_revision_owner',use_alter=True))
metadata.tables['px_self_certificate_requests'].append_constraint(ForeignKeyConstraint(['owner_account_id', 'link_id', 'revision_id'],['px_self_certificate_links.owner_account_id', 'px_self_certificate_links.id', 'px_self_certificate_links.revision_id'],name='fk_self_request_link_revision_owner',use_alter=True))
metadata.tables['px_self_certificates'].append_constraint(ForeignKeyConstraint(['owner_account_id', 'request_id', 'link_id'],['px_self_certificate_requests.owner_account_id', 'px_self_certificate_requests.id', 'px_self_certificate_requests.link_id'],name='fk_self_issued_request_link_owner',use_alter=True))
metadata.tables['px_self_certificates'].append_constraint(ForeignKeyConstraint(['owner_account_id', 'final_asset_id'],['px_self_certificate_assets.owner_account_id', 'px_self_certificate_assets.id'],name='fk_self_issued_final_owner',use_alter=True))
metadata.tables['px_self_certificates'].append_constraint(ForeignKeyConstraint(['owner_account_id', 'thumbnail_asset_id'],['px_self_certificate_assets.owner_account_id', 'px_self_certificate_assets.id'],name='fk_self_issued_thumbnail_owner',use_alter=True))
metadata.tables['px_self_certificate_export_jobs'].append_constraint(ForeignKeyConstraint(['owner_account_id', 'asset_id'],['px_self_certificate_assets.owner_account_id', 'px_self_certificate_assets.id'],name='fk_self_export_asset_owner',use_alter=True))
metadata.tables['px_self_certificate_export_snapshot_rows'].append_constraint(ForeignKeyConstraint(['owner_account_id', 'export_id'],['px_self_certificate_export_jobs.owner_account_id', 'px_self_certificate_export_jobs.id'],name='fk_self_snapshot_export_owner',use_alter=True))
metadata.tables['px_self_certificate_export_snapshot_rows'].append_constraint(ForeignKeyConstraint(['owner_account_id', 'source_request_id'],['px_self_certificate_requests.owner_account_id', 'px_self_certificate_requests.id'],name='fk_self_snapshot_source_owner',use_alter=True))

from app.application.self_certificate_integrity import SQLITE_GUARDS, POSTGRES_GUARDS
for _statement in SQLITE_GUARDS:
    event.listen(metadata,'after_create',DDL(_statement).execute_if(dialect='sqlite'))
for _statement in POSTGRES_GUARDS:
    event.listen(metadata,'after_create',DDL(_statement).execute_if(dialect='postgresql'))

for _statement in ["CREATE TRIGGER IF NOT EXISTS guard_self_model_operation BEFORE UPDATE ON px_self_certificate_model_operations BEGIN SELECT RAISE(ABORT,'SELF_CERTIFICATE_IMMUTABLE'); END", "CREATE TRIGGER IF NOT EXISTS guard_self_model_operation_owner BEFORE INSERT ON px_self_certificate_model_operations WHEN json_extract(NEW.result,'$.owner_account_id') IS NOT NEW.owner_account_id OR json_extract(NEW.result,'$.revision.owner_account_id') IS NOT NEW.owner_account_id OR NOT EXISTS (SELECT 1 FROM px_self_certificate_revisions r WHERE r.id=json_extract(NEW.result,'$.revision.id') AND r.owner_account_id=NEW.owner_account_id) BEGIN SELECT RAISE(ABORT,'SELF_CERTIFICATE_OWNER_CHAIN_INVALID'); END"]:
    event.listen(metadata,'after_create',DDL(_statement).execute_if(dialect='sqlite'))
for _statement in ["CREATE OR REPLACE FUNCTION guard_self_model_operation_owner() RETURNS trigger AS 'BEGIN IF NEW.result->>''owner_account_id'' IS DISTINCT FROM NEW.owner_account_id OR NEW.result->''revision''->>''owner_account_id'' IS DISTINCT FROM NEW.owner_account_id OR NOT EXISTS(SELECT 1 FROM px_self_certificate_revisions r WHERE r.id=NEW.result->''revision''->>''id'' AND r.owner_account_id=NEW.owner_account_id) THEN RAISE EXCEPTION ''SELF_CERTIFICATE_OWNER_CHAIN_INVALID'' USING ERRCODE=''23514''; END IF; RETURN NEW; END;' LANGUAGE plpgsql", 'DROP TRIGGER IF EXISTS guard_self_model_operation_owner ON px_self_certificate_model_operations', 'CREATE TRIGGER guard_self_model_operation_owner BEFORE INSERT ON px_self_certificate_model_operations FOR EACH ROW EXECUTE FUNCTION guard_self_model_operation_owner()', "CREATE OR REPLACE FUNCTION guard_self_model_operation() RETURNS trigger AS 'BEGIN RAISE EXCEPTION ''SELF_CERTIFICATE_IMMUTABLE'' USING ERRCODE=''23514''; END;' LANGUAGE plpgsql", 'DROP TRIGGER IF EXISTS guard_self_model_operation ON px_self_certificate_model_operations', 'CREATE TRIGGER guard_self_model_operation BEFORE UPDATE ON px_self_certificate_model_operations FOR EACH ROW EXECUTE FUNCTION guard_self_model_operation()']:
    event.listen(metadata,'after_create',DDL(_statement).execute_if(dialect='postgresql'))
