CREATE TABLE IF NOT EXISTS px_certificate_imports (
	id VARCHAR(64) NOT NULL,
	event_id VARCHAR(64) NOT NULL,
	user_id VARCHAR(64) NOT NULL,
	rows JSON NOT NULL,
	errors JSON NOT NULL,
	created_at VARCHAR(64) NOT NULL,
	committed_at VARCHAR(64),
	PRIMARY KEY (id),
	FOREIGN KEY(event_id) REFERENCES px_sites (id),
	FOREIGN KEY(user_id) REFERENCES px_users (id)
);

CREATE TABLE IF NOT EXISTS px_certificate_jobs (
	id VARCHAR(64) NOT NULL,
	import_id VARCHAR(64) NOT NULL,
	event_id VARCHAR(64) NOT NULL,
	user_id VARCHAR(64) NOT NULL,
	body JSON NOT NULL,
	state VARCHAR(16) NOT NULL,
	available_at VARCHAR(64) NOT NULL,
	certificate_id VARCHAR(64),
	error VARCHAR(160),
	created_at VARCHAR(64) NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(import_id) REFERENCES px_certificate_imports (id),
	FOREIGN KEY(event_id) REFERENCES px_sites (id),
	FOREIGN KEY(user_id) REFERENCES px_users (id),
	FOREIGN KEY(certificate_id) REFERENCES px_certificates (id)
);

CREATE INDEX IF NOT EXISTS px_certificate_jobs_pending ON px_certificate_jobs (state, available_at);

CREATE TABLE IF NOT EXISTS px_certificate_replacements (
	previous_id VARCHAR(64) NOT NULL,
	replacement_id VARCHAR(64) NOT NULL,
	reason VARCHAR(500) NOT NULL,
	created_at VARCHAR(64) NOT NULL,
	PRIMARY KEY (previous_id),
	FOREIGN KEY(previous_id) REFERENCES px_certificates (id),
	UNIQUE (replacement_id),
	FOREIGN KEY(replacement_id) REFERENCES px_certificates (id)
);
