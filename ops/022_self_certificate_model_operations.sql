CREATE TABLE IF NOT EXISTS px_self_certificate_model_operations(
 owner_account_id VARCHAR(64) NOT NULL REFERENCES px_users(id),
 idempotency_key VARCHAR(80) NOT NULL,
 input_hash VARCHAR(64) NOT NULL,
 result JSON NOT NULL,
 created_at VARCHAR(64) NOT NULL,
 CONSTRAINT pk_self_model_operations PRIMARY KEY(owner_account_id,idempotency_key)
);
CREATE OR REPLACE FUNCTION guard_self_model_operation_owner() RETURNS trigger AS 'BEGIN IF NEW.result->>''owner_account_id'' IS DISTINCT FROM NEW.owner_account_id OR NEW.result->''revision''->>''owner_account_id'' IS DISTINCT FROM NEW.owner_account_id OR NOT EXISTS(SELECT 1 FROM px_self_certificate_revisions r WHERE r.id=NEW.result->''revision''->>''id'' AND r.owner_account_id=NEW.owner_account_id) THEN RAISE EXCEPTION ''SELF_CERTIFICATE_OWNER_CHAIN_INVALID'' USING ERRCODE=''23514''; END IF; RETURN NEW; END;' LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS guard_self_model_operation_owner ON px_self_certificate_model_operations;
CREATE TRIGGER guard_self_model_operation_owner BEFORE INSERT ON px_self_certificate_model_operations FOR EACH ROW EXECUTE FUNCTION guard_self_model_operation_owner();
CREATE OR REPLACE FUNCTION guard_self_model_operation() RETURNS trigger AS 'BEGIN RAISE EXCEPTION ''SELF_CERTIFICATE_IMMUTABLE'' USING ERRCODE=''23514''; END;' LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS guard_self_model_operation ON px_self_certificate_model_operations;
CREATE TRIGGER guard_self_model_operation BEFORE UPDATE ON px_self_certificate_model_operations FOR EACH ROW EXECUTE FUNCTION guard_self_model_operation();
