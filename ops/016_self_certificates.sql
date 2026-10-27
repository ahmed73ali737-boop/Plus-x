-- Additive account-owned self-service certificates. Legacy tables remain untouched.


CREATE TABLE IF NOT EXISTS px_self_certificate_browser_sessions (
	id VARCHAR(64) NOT NULL, 
	token_hash VARCHAR(64) NOT NULL, 
	created_at VARCHAR(64) NOT NULL, 
	last_seen_at VARCHAR(64) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (token_hash)
)

;


CREATE TABLE IF NOT EXISTS px_self_certificate_rate_buckets (
	bucket_hash VARCHAR(64) NOT NULL, 
	"window" INTEGER NOT NULL, 
	count INTEGER NOT NULL, 
	PRIMARY KEY (bucket_hash, "window")
)

;


CREATE TABLE IF NOT EXISTS px_self_certificate_assets (
	id VARCHAR(64) NOT NULL, 
	owner_account_id VARCHAR(64) NOT NULL, 
	kind VARCHAR(20) NOT NULL, 
	storage_key VARCHAR(200) NOT NULL, 
	sha256 VARCHAR(64) NOT NULL, 
	mime VARCHAR(80) NOT NULL, 
	size_bytes INTEGER NOT NULL, 
	width INTEGER, 
	height INTEGER, 
	source_kind VARCHAR(20) NOT NULL, 
	original_size_bytes INTEGER NOT NULL, 
	source_metadata JSON NOT NULL, 
	created_at VARCHAR(64) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_self_asset_kind CHECK (kind IN ('background','stamp','final','thumbnail','export')), 
	FOREIGN KEY(owner_account_id) REFERENCES px_users (id), 
	UNIQUE (storage_key)
)

;

CREATE INDEX IF NOT EXISTS ix_self_assets_owner_time ON px_self_certificate_assets (owner_account_id, created_at);


CREATE TABLE IF NOT EXISTS px_self_certificate_models (
	id VARCHAR(64) NOT NULL, 
	owner_account_id VARCHAR(64) NOT NULL, 
	name VARCHAR(160) NOT NULL, 
	current_revision_id VARCHAR(64), 
	row_version INTEGER NOT NULL, 
	created_at VARCHAR(64) NOT NULL, 
	updated_at VARCHAR(64) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_account_id) REFERENCES px_users (id)
)

;

CREATE INDEX IF NOT EXISTS ix_self_models_owner_time ON px_self_certificate_models (owner_account_id, updated_at, id);


CREATE TABLE IF NOT EXISTS px_self_certificate_export_jobs (
	id VARCHAR(64) NOT NULL, 
	owner_account_id VARCHAR(64) NOT NULL, 
	cutoff VARCHAR(64) NOT NULL, 
	format VARCHAR(8) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	asset_id VARCHAR(64), 
	error_code VARCHAR(80), 
	row_count INTEGER, 
	created_at VARCHAR(64) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_self_export_format CHECK (format IN ('csv','xlsx')), 
	CONSTRAINT ck_self_export_status CHECK (status IN ('pending','processing','done','failed')), 
	FOREIGN KEY(owner_account_id) REFERENCES px_users (id), 
	FOREIGN KEY(asset_id) REFERENCES px_self_certificate_assets (id)
)

;

CREATE INDEX IF NOT EXISTS ix_self_exports_pending ON px_self_certificate_export_jobs (status, created_at);


CREATE TABLE IF NOT EXISTS px_self_certificate_revisions (
	id VARCHAR(64) NOT NULL, 
	owner_account_id VARCHAR(64) NOT NULL, 
	origin_model_id VARCHAR(64), 
	background_asset_id VARCHAR(64) NOT NULL, 
	stamp_asset_id VARCHAR(64), 
	config JSON NOT NULL, 
	font_manifest JSON NOT NULL, 
	renderer_version VARCHAR(64) NOT NULL, 
	schema_version INTEGER NOT NULL, 
	created_at VARCHAR(64) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_account_id) REFERENCES px_users (id), 
	FOREIGN KEY(origin_model_id) REFERENCES px_self_certificate_models (id) ON DELETE SET NULL, 
	FOREIGN KEY(background_asset_id) REFERENCES px_self_certificate_assets (id), 
	FOREIGN KEY(stamp_asset_id) REFERENCES px_self_certificate_assets (id)
)

;


CREATE TABLE IF NOT EXISTS px_self_certificate_links (
	id VARCHAR(64) NOT NULL, 
	owner_account_id VARCHAR(64) NOT NULL, 
	event_id VARCHAR(64) NOT NULL, 
	event_name_snapshot VARCHAR(250) NOT NULL, 
	model_name_snapshot VARCHAR(160) NOT NULL, 
	revision_id VARCHAR(64) NOT NULL, 
	public_id VARCHAR(64) NOT NULL, 
	key_version VARCHAR(40) NOT NULL, 
	public_token_hash VARCHAR(64) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	share_text_snapshot TEXT NOT NULL, 
	config_hash VARCHAR(64) NOT NULL, 
	idempotency_key VARCHAR(80) NOT NULL, 
	row_version INTEGER NOT NULL, 
	created_at VARCHAR(64) NOT NULL, 
	disabled_at VARCHAR(64), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_self_link_idempotency UNIQUE (owner_account_id, idempotency_key), 
	CONSTRAINT ck_self_link_status CHECK (status IN ('active','paused')), 
	FOREIGN KEY(owner_account_id) REFERENCES px_users (id), 
	FOREIGN KEY(event_id) REFERENCES px_sites (id), 
	FOREIGN KEY(revision_id) REFERENCES px_self_certificate_revisions (id), 
	UNIQUE (public_id), 
	UNIQUE (public_token_hash)
)

;

CREATE INDEX IF NOT EXISTS ix_self_links_owner_time ON px_self_certificate_links (owner_account_id, created_at, id);


CREATE TABLE IF NOT EXISTS px_self_certificate_requests (
	id VARCHAR(64) NOT NULL, 
	owner_account_id VARCHAR(64) NOT NULL, 
	link_id VARCHAR(64) NOT NULL, 
	browser_session_id VARCHAR(64) NOT NULL, 
	revision_id VARCHAR(64) NOT NULL, 
	participant_name_original VARCHAR(250) NOT NULL, 
	participant_name_normalized VARCHAR(250) NOT NULL, 
	phone_original VARCHAR(60) NOT NULL, 
	phone_normalized VARCHAR(60) NOT NULL, 
	consent BOOLEAN NOT NULL, 
	consent_text VARCHAR(600) NOT NULL, 
	consent_text_version VARCHAR(40) NOT NULL, 
	submitted_at_utc VARCHAR(64) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	error_code VARCHAR(80), 
	layout JSON NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_self_browser_link UNIQUE (link_id, browser_session_id), 
	CONSTRAINT ck_self_consent CHECK (consent = true), 
	CONSTRAINT ck_self_request_status CHECK (status IN ('registered','processing','failed','issued')), 
	FOREIGN KEY(owner_account_id) REFERENCES px_users (id), 
	FOREIGN KEY(link_id) REFERENCES px_self_certificate_links (id), 
	FOREIGN KEY(browser_session_id) REFERENCES px_self_certificate_browser_sessions (id), 
	FOREIGN KEY(revision_id) REFERENCES px_self_certificate_revisions (id)
)

;

CREATE INDEX IF NOT EXISTS ix_self_requests_owner_time ON px_self_certificate_requests (owner_account_id, submitted_at_utc, id);


CREATE TABLE IF NOT EXISTS px_self_certificate_generation_jobs (
	id VARCHAR(64) NOT NULL, 
	request_id VARCHAR(64) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	attempts INTEGER NOT NULL, 
	available_at VARCHAR(64) NOT NULL, 
	lease_owner VARCHAR(64), 
	lease_until VARCHAR(64), 
	last_error_code VARCHAR(80), 
	created_at VARCHAR(64) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_self_job_status CHECK (status IN ('pending','leased','retry_wait','failed','done')), 
	UNIQUE (request_id), 
	FOREIGN KEY(request_id) REFERENCES px_self_certificate_requests (id)
)

;

CREATE INDEX IF NOT EXISTS ix_self_jobs_pending ON px_self_certificate_generation_jobs (status, available_at);


CREATE TABLE IF NOT EXISTS px_self_certificates (
	id VARCHAR(64) NOT NULL, 
	owner_account_id VARCHAR(64) NOT NULL, 
	request_id VARCHAR(64) NOT NULL, 
	link_id VARCHAR(64) NOT NULL, 
	serial VARCHAR(64) NOT NULL, 
	name_printed VARCHAR(250) NOT NULL, 
	layout JSON NOT NULL, 
	issued_at_utc VARCHAR(64) NOT NULL, 
	final_asset_id VARCHAR(64) NOT NULL, 
	thumbnail_asset_id VARCHAR(64) NOT NULL, 
	delivery_token_hash VARCHAR(64) NOT NULL, 
	key_version VARCHAR(40) NOT NULL, 
	integrity_hash VARCHAR(64) NOT NULL, 
	source VARCHAR(30) NOT NULL, 
	schema_version INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_self_certificate_source CHECK (source = 'self_service'), 
	FOREIGN KEY(owner_account_id) REFERENCES px_users (id), 
	UNIQUE (request_id), 
	FOREIGN KEY(request_id) REFERENCES px_self_certificate_requests (id), 
	FOREIGN KEY(link_id) REFERENCES px_self_certificate_links (id), 
	UNIQUE (serial), 
	FOREIGN KEY(final_asset_id) REFERENCES px_self_certificate_assets (id), 
	FOREIGN KEY(thumbnail_asset_id) REFERENCES px_self_certificate_assets (id), 
	UNIQUE (delivery_token_hash)
)

;

ALTER TABLE px_self_certificate_models DROP CONSTRAINT IF EXISTS fk_self_model_current_revision;

ALTER TABLE px_self_certificate_models ADD CONSTRAINT fk_self_model_current_revision FOREIGN KEY (current_revision_id) REFERENCES px_self_certificate_revisions(id);

CREATE OR REPLACE FUNCTION guard_px_self_certificate_requests() RETURNS trigger AS 'BEGIN IF to_jsonb(NEW.id) IS DISTINCT FROM to_jsonb(OLD.id) OR to_jsonb(NEW.owner_account_id) IS DISTINCT FROM to_jsonb(OLD.owner_account_id) OR to_jsonb(NEW.link_id) IS DISTINCT FROM to_jsonb(OLD.link_id) OR to_jsonb(NEW.browser_session_id) IS DISTINCT FROM to_jsonb(OLD.browser_session_id) OR to_jsonb(NEW.revision_id) IS DISTINCT FROM to_jsonb(OLD.revision_id) OR to_jsonb(NEW.participant_name_original) IS DISTINCT FROM to_jsonb(OLD.participant_name_original) OR to_jsonb(NEW.participant_name_normalized) IS DISTINCT FROM to_jsonb(OLD.participant_name_normalized) OR to_jsonb(NEW.phone_original) IS DISTINCT FROM to_jsonb(OLD.phone_original) OR to_jsonb(NEW.phone_normalized) IS DISTINCT FROM to_jsonb(OLD.phone_normalized) OR to_jsonb(NEW.consent) IS DISTINCT FROM to_jsonb(OLD.consent) OR to_jsonb(NEW.consent_text) IS DISTINCT FROM to_jsonb(OLD.consent_text) OR to_jsonb(NEW.consent_text_version) IS DISTINCT FROM to_jsonb(OLD.consent_text_version) OR to_jsonb(NEW.submitted_at_utc) IS DISTINCT FROM to_jsonb(OLD.submitted_at_utc) OR to_jsonb(NEW.layout) IS DISTINCT FROM to_jsonb(OLD.layout) THEN RAISE EXCEPTION ''SELF_CERTIFICATE_IMMUTABLE'' USING ERRCODE = ''23514''; END IF; RETURN NEW; END;' LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS guard_px_self_certificate_requests ON px_self_certificate_requests;

CREATE TRIGGER guard_px_self_certificate_requests BEFORE UPDATE ON px_self_certificate_requests FOR EACH ROW EXECUTE FUNCTION guard_px_self_certificate_requests();

CREATE OR REPLACE FUNCTION guard_px_self_certificate_links() RETURNS trigger AS 'BEGIN IF to_jsonb(NEW.id) IS DISTINCT FROM to_jsonb(OLD.id) OR to_jsonb(NEW.owner_account_id) IS DISTINCT FROM to_jsonb(OLD.owner_account_id) OR to_jsonb(NEW.event_id) IS DISTINCT FROM to_jsonb(OLD.event_id) OR to_jsonb(NEW.event_name_snapshot) IS DISTINCT FROM to_jsonb(OLD.event_name_snapshot) OR to_jsonb(NEW.model_name_snapshot) IS DISTINCT FROM to_jsonb(OLD.model_name_snapshot) OR to_jsonb(NEW.revision_id) IS DISTINCT FROM to_jsonb(OLD.revision_id) OR to_jsonb(NEW.public_id) IS DISTINCT FROM to_jsonb(OLD.public_id) OR to_jsonb(NEW.key_version) IS DISTINCT FROM to_jsonb(OLD.key_version) OR to_jsonb(NEW.public_token_hash) IS DISTINCT FROM to_jsonb(OLD.public_token_hash) OR to_jsonb(NEW.share_text_snapshot) IS DISTINCT FROM to_jsonb(OLD.share_text_snapshot) OR to_jsonb(NEW.config_hash) IS DISTINCT FROM to_jsonb(OLD.config_hash) OR to_jsonb(NEW.idempotency_key) IS DISTINCT FROM to_jsonb(OLD.idempotency_key) OR to_jsonb(NEW.created_at) IS DISTINCT FROM to_jsonb(OLD.created_at) THEN RAISE EXCEPTION ''SELF_CERTIFICATE_IMMUTABLE'' USING ERRCODE = ''23514''; END IF; RETURN NEW; END;' LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS guard_px_self_certificate_links ON px_self_certificate_links;

CREATE TRIGGER guard_px_self_certificate_links BEFORE UPDATE ON px_self_certificate_links FOR EACH ROW EXECUTE FUNCTION guard_px_self_certificate_links();

CREATE OR REPLACE FUNCTION guard_px_self_certificate_models() RETURNS trigger AS 'BEGIN IF to_jsonb(NEW.id) IS DISTINCT FROM to_jsonb(OLD.id) OR to_jsonb(NEW.owner_account_id) IS DISTINCT FROM to_jsonb(OLD.owner_account_id) THEN RAISE EXCEPTION ''SELF_CERTIFICATE_IMMUTABLE'' USING ERRCODE = ''23514''; END IF; RETURN NEW; END;' LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS guard_px_self_certificate_models ON px_self_certificate_models;

CREATE TRIGGER guard_px_self_certificate_models BEFORE UPDATE ON px_self_certificate_models FOR EACH ROW EXECUTE FUNCTION guard_px_self_certificate_models();

CREATE OR REPLACE FUNCTION guard_px_self_certificates() RETURNS trigger AS 'BEGIN IF TRUE THEN RAISE EXCEPTION ''SELF_CERTIFICATE_IMMUTABLE'' USING ERRCODE = ''23514''; END IF; RETURN NEW; END;' LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS guard_px_self_certificates ON px_self_certificates;

CREATE TRIGGER guard_px_self_certificates BEFORE UPDATE ON px_self_certificates FOR EACH ROW EXECUTE FUNCTION guard_px_self_certificates();

CREATE OR REPLACE FUNCTION guard_px_self_certificate_assets() RETURNS trigger AS 'BEGIN IF TRUE THEN RAISE EXCEPTION ''SELF_CERTIFICATE_IMMUTABLE'' USING ERRCODE = ''23514''; END IF; RETURN NEW; END;' LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS guard_px_self_certificate_assets ON px_self_certificate_assets;

CREATE TRIGGER guard_px_self_certificate_assets BEFORE UPDATE ON px_self_certificate_assets FOR EACH ROW EXECUTE FUNCTION guard_px_self_certificate_assets();

CREATE OR REPLACE FUNCTION guard_self_revision() RETURNS trigger AS 'BEGIN IF to_jsonb(NEW.id) IS DISTINCT FROM to_jsonb(OLD.id) OR to_jsonb(NEW.owner_account_id) IS DISTINCT FROM to_jsonb(OLD.owner_account_id) OR to_jsonb(NEW.background_asset_id) IS DISTINCT FROM to_jsonb(OLD.background_asset_id) OR to_jsonb(NEW.stamp_asset_id) IS DISTINCT FROM to_jsonb(OLD.stamp_asset_id) OR to_jsonb(NEW.config) IS DISTINCT FROM to_jsonb(OLD.config) OR to_jsonb(NEW.font_manifest) IS DISTINCT FROM to_jsonb(OLD.font_manifest) OR to_jsonb(NEW.renderer_version) IS DISTINCT FROM to_jsonb(OLD.renderer_version) OR to_jsonb(NEW.schema_version) IS DISTINCT FROM to_jsonb(OLD.schema_version) OR to_jsonb(NEW.created_at) IS DISTINCT FROM to_jsonb(OLD.created_at) OR (NEW.origin_model_id IS DISTINCT FROM OLD.origin_model_id AND NEW.origin_model_id IS NOT NULL) THEN RAISE EXCEPTION ''SELF_CERTIFICATE_IMMUTABLE'' USING ERRCODE = ''23514''; END IF; RETURN NEW; END;' LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS guard_self_revision ON px_self_certificate_revisions;

CREATE TRIGGER guard_self_revision BEFORE UPDATE ON px_self_certificate_revisions FOR EACH ROW EXECUTE FUNCTION guard_self_revision();

CREATE OR REPLACE FUNCTION guard_self_issued_delete() RETURNS trigger AS 'BEGIN RAISE EXCEPTION ''SELF_CERTIFICATE_IMMUTABLE'' USING ERRCODE = ''23514''; END;' LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS guard_self_issued_delete ON px_self_certificates;

CREATE TRIGGER guard_self_issued_delete BEFORE DELETE ON px_self_certificates FOR EACH ROW EXECUTE FUNCTION guard_self_issued_delete();
