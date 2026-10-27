-- New exports capture rows and values at accepted request time.
-- Historical completed artifacts remain downloadable. A pre-V3 pending job
-- cannot reconstruct its former request-time snapshot; request a new export.
ALTER TABLE px_self_certificate_export_jobs ADD COLUMN IF NOT EXISTS snapshot_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE px_self_certificate_export_jobs ADD COLUMN IF NOT EXISTS snapshot_taken_at VARCHAR(64);
ALTER TABLE px_self_certificate_export_jobs ADD COLUMN IF NOT EXISTS expected_rows INTEGER;
ALTER TABLE px_self_certificate_export_jobs ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(80);
ALTER TABLE px_self_certificate_export_jobs ADD COLUMN IF NOT EXISTS input_hash VARCHAR(64);
CREATE UNIQUE INDEX IF NOT EXISTS uq_self_export_idempotency ON px_self_certificate_export_jobs(owner_account_id,idempotency_key);
DO 'BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid=''px_self_certificate_export_jobs''::regclass AND conname=''uq_self_export_idempotency'') THEN ALTER TABLE px_self_certificate_export_jobs ADD CONSTRAINT uq_self_export_idempotency UNIQUE USING INDEX uq_self_export_idempotency; END IF; END;';
CREATE TABLE IF NOT EXISTS px_self_certificate_export_snapshot_rows (
 export_id VARCHAR(64) NOT NULL REFERENCES px_self_certificate_export_jobs(id),
 ordinal INTEGER NOT NULL,
 owner_account_id VARCHAR(64) NOT NULL REFERENCES px_users(id),
 source_request_id VARCHAR(64) NOT NULL,
 participant_name_original VARCHAR(250) NOT NULL,
 phone_original VARCHAR(60) NOT NULL,
 model_name_snapshot VARCHAR(160) NOT NULL,
 event_name_snapshot VARCHAR(250) NOT NULL,
 submitted_at_utc VARCHAR(64) NOT NULL,
 status VARCHAR(20) NOT NULL,
 PRIMARY KEY(export_id,ordinal),
 CONSTRAINT uq_self_snapshot_request UNIQUE(export_id,source_request_id),
 CONSTRAINT ck_self_snapshot_ordinal CHECK(ordinal>0),
 CONSTRAINT ck_self_snapshot_status CHECK(status IN ('registered','processing','failed','issued'))
);
UPDATE px_self_certificate_export_jobs SET status='failed',error_code='EXPORT_SNAPSHOT_LEGACY_REQUIRED',lease_owner=NULL,lease_until=NULL WHERE snapshot_version=1 AND status IN ('pending','processing');
CREATE OR REPLACE FUNCTION guard_self_export_identity() RETURNS trigger AS 'BEGIN IF NEW.id IS DISTINCT FROM OLD.id OR NEW.owner_account_id IS DISTINCT FROM OLD.owner_account_id OR NEW.cutoff IS DISTINCT FROM OLD.cutoff OR NEW.format IS DISTINCT FROM OLD.format OR NEW.snapshot_version IS DISTINCT FROM OLD.snapshot_version OR NEW.snapshot_taken_at IS DISTINCT FROM OLD.snapshot_taken_at OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key OR NEW.input_hash IS DISTINCT FROM OLD.input_hash OR NEW.created_at IS DISTINCT FROM OLD.created_at OR (OLD.expected_rows IS NOT NULL AND NEW.expected_rows IS DISTINCT FROM OLD.expected_rows) THEN RAISE EXCEPTION ''SELF_CERTIFICATE_IMMUTABLE'' USING ERRCODE=''23514''; END IF; RETURN NEW; END;' LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS guard_self_export_identity ON px_self_certificate_export_jobs;
CREATE TRIGGER guard_self_export_identity BEFORE UPDATE ON px_self_certificate_export_jobs FOR EACH ROW EXECUTE FUNCTION guard_self_export_identity();
CREATE OR REPLACE FUNCTION guard_self_snapshot_insert() RETURNS trigger AS 'BEGIN IF NOT EXISTS (SELECT 1 FROM px_self_certificate_export_jobs j WHERE j.id=NEW.export_id AND j.owner_account_id=NEW.owner_account_id AND j.snapshot_version=2 AND j.expected_rows IS NULL AND j.status=''pending'') THEN RAISE EXCEPTION ''EXPORT_SNAPSHOT_INVALID'' USING ERRCODE=''23514''; END IF; RETURN NEW; END;' LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS guard_self_snapshot_insert ON px_self_certificate_export_snapshot_rows;
CREATE TRIGGER guard_self_snapshot_insert BEFORE INSERT ON px_self_certificate_export_snapshot_rows FOR EACH ROW EXECUTE FUNCTION guard_self_snapshot_insert();
CREATE OR REPLACE FUNCTION guard_self_snapshot_update() RETURNS trigger AS 'BEGIN RAISE EXCEPTION ''SELF_CERTIFICATE_IMMUTABLE'' USING ERRCODE=''23514''; END;' LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS guard_self_snapshot_update ON px_self_certificate_export_snapshot_rows;
CREATE TRIGGER guard_self_snapshot_update BEFORE UPDATE ON px_self_certificate_export_snapshot_rows FOR EACH ROW EXECUTE FUNCTION guard_self_snapshot_update();
CREATE OR REPLACE FUNCTION guard_self_snapshot_delete() RETURNS trigger AS 'BEGIN IF NOT EXISTS (SELECT 1 FROM px_self_certificate_export_jobs j WHERE j.id=OLD.export_id AND j.error_code=''EXPORT_EXPIRED'') THEN RAISE EXCEPTION ''SELF_CERTIFICATE_IMMUTABLE'' USING ERRCODE=''23514''; END IF; RETURN OLD; END;' LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS guard_self_snapshot_delete ON px_self_certificate_export_snapshot_rows;
CREATE TRIGGER guard_self_snapshot_delete BEFORE DELETE ON px_self_certificate_export_snapshot_rows FOR EACH ROW EXECUTE FUNCTION guard_self_snapshot_delete();
