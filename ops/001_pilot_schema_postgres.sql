-- PulseX Pilot 02 — PostgreSQL dialect compilation ONLY; not executed against PostgreSQL.

-- The live pilot currently initializes through SQLAlchemy metadata.create_all.

-- Not a migration from the prior Node/PostgreSQL foundation; separate schema and acceptance needed.


CREATE TABLE px_audit (
	id VARCHAR(64) NOT NULL, 
	user_id VARCHAR(64), 
	site_id VARCHAR(64), 
	action VARCHAR(80) NOT NULL, 
	at VARCHAR(64) NOT NULL, 
	details JSON NOT NULL, 
	PRIMARY KEY (id)
)

;


CREATE TABLE px_sites (
	id VARCHAR(64) NOT NULL, 
	parent_id VARCHAR(64), 
	event_id VARCHAR(64), 
	kind VARCHAR(20) NOT NULL, 
	slug VARCHAR(80) NOT NULL, 
	draft JSON NOT NULL, 
	draft_rev INTEGER NOT NULL, 
	published_version INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(parent_id) REFERENCES px_sites (id), 
	UNIQUE (slug)
)

;


CREATE TABLE px_access_requests (
	id VARCHAR(64) NOT NULL, 
	site_id VARCHAR(64) NOT NULL, 
	email VARCHAR(200) NOT NULL, 
	name VARCHAR(160) NOT NULL, 
	created_at VARCHAR(64) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(site_id) REFERENCES px_sites (id)
)

;


CREATE TABLE px_site_versions (
	site_id VARCHAR(64) NOT NULL, 
	version INTEGER NOT NULL, 
	config JSON NOT NULL, 
	published_at VARCHAR(64) NOT NULL, 
	PRIMARY KEY (site_id, version), 
	FOREIGN KEY(site_id) REFERENCES px_sites (id)
)

;


CREATE TABLE px_submissions (
	id VARCHAR(64) NOT NULL, 
	site_id VARCHAR(64) NOT NULL, 
	event_id VARCHAR(64), 
	version INTEGER NOT NULL, 
	kind VARCHAR(30) NOT NULL, 
	visitor_id VARCHAR(64) NOT NULL, 
	session_id VARCHAR(64) NOT NULL, 
	source VARCHAR(20) NOT NULL, 
	target VARCHAR(150), 
	payload JSON NOT NULL, 
	client_time VARCHAR(64), 
	received_at VARCHAR(64) NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	dedup_key VARCHAR(240), 
	PRIMARY KEY (id), 
	FOREIGN KEY(site_id) REFERENCES px_sites (id), 
	UNIQUE (dedup_key)
)

;

CREATE INDEX px_submissions_event_kind ON px_submissions (event_id, kind);

CREATE INDEX px_submissions_site_time ON px_submissions (site_id, received_at);


CREATE TABLE px_users (
	id VARCHAR(64) NOT NULL, 
	email VARCHAR(200) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	role VARCHAR(20) NOT NULL, 
	scope_id VARCHAR(64), 
	password_hash TEXT NOT NULL, 
	active INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (email), 
	FOREIGN KEY(scope_id) REFERENCES px_sites (id)
)

;


CREATE TABLE px_imports (
	id VARCHAR(64) NOT NULL, 
	site_id VARCHAR(64) NOT NULL, 
	user_id VARCHAR(64) NOT NULL, 
	base_rev INTEGER NOT NULL, 
	records JSON NOT NULL, 
	errors JSON NOT NULL, 
	state VARCHAR(30) NOT NULL, 
	created_at VARCHAR(64) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(site_id) REFERENCES px_sites (id), 
	FOREIGN KEY(user_id) REFERENCES px_users (id)
)

;


CREATE TABLE px_sessions (
	token_hash VARCHAR(64) NOT NULL, 
	user_id VARCHAR(64) NOT NULL, 
	csrf VARCHAR(100) NOT NULL, 
	expires_at VARCHAR(64) NOT NULL, 
	PRIMARY KEY (token_hash), 
	FOREIGN KEY(user_id) REFERENCES px_users (id)
)

;