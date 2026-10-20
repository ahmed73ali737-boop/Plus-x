-- Additive certificate register. Issued snapshots are immutable through application use cases.

CREATE TABLE IF NOT EXISTS px_certificate_templates (
	id VARCHAR(64) NOT NULL,
	event_id VARCHAR(64) NOT NULL,
	name VARCHAR(160) NOT NULL,
	design JSON NOT NULL,
	created_at VARCHAR(64) NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(event_id) REFERENCES px_sites (id)
);

CREATE TABLE IF NOT EXISTS px_certificates (
	id VARCHAR(64) NOT NULL,
	event_id VARCHAR(64) NOT NULL,
	template_id VARCHAR(64) NOT NULL,
	request_key VARCHAR(80) NOT NULL,
	request_hash VARCHAR(64) NOT NULL,
	recipient_key VARCHAR(160) NOT NULL,
	award_key VARCHAR(80) NOT NULL,
	serial VARCHAR(64) NOT NULL,
	access_hash VARCHAR(64) NOT NULL,
	snapshot JSON NOT NULL,
	snapshot_hash VARCHAR(64) NOT NULL,
	status VARCHAR(16) NOT NULL,
	issued_at VARCHAR(64) NOT NULL,
	expires_at VARCHAR(64),
	revoked_at VARCHAR(64),
	revoke_reason VARCHAR(500),
	PRIMARY KEY (id),
	CONSTRAINT uq_px_certificate_request UNIQUE (event_id, request_key),
	CONSTRAINT uq_px_certificate_award UNIQUE (event_id, recipient_key, award_key),
	CONSTRAINT ck_px_certificate_status CHECK (status IN ('issued', 'revoked')),
	FOREIGN KEY(event_id) REFERENCES px_sites (id),
	FOREIGN KEY(template_id) REFERENCES px_certificate_templates (id),
	UNIQUE (serial),
	UNIQUE (access_hash)
);

CREATE INDEX IF NOT EXISTS px_certificates_event_time ON px_certificates (event_id, issued_at);
