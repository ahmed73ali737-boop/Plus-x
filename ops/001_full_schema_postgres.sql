
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


CREATE TABLE px_organizations (
	id VARCHAR(64) NOT NULL, 
	slug VARCHAR(80) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	profile JSON NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	created_at VARCHAR(64) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (slug)
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


CREATE TABLE px_devices (
	id VARCHAR(64) NOT NULL, 
	site_id VARCHAR(64) NOT NULL, 
	name VARCHAR(160) NOT NULL, 
	device_type VARCHAR(30) NOT NULL, 
	token_hash VARCHAR(64) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	last_seen_at VARCHAR(64), 
	last_sync_at VARCHAR(64), 
	pending_count INTEGER NOT NULL, 
	app_version VARCHAR(40), 
	metadata_json JSON NOT NULL, 
	created_at VARCHAR(64) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(site_id) REFERENCES px_sites (id), 
	UNIQUE (token_hash)
)

;


CREATE TABLE px_event_participations (
	id VARCHAR(64) NOT NULL, 
	event_id VARCHAR(64) NOT NULL, 
	organization_id VARCHAR(64) NOT NULL, 
	agency_site_id VARCHAR(64), 
	participation_type VARCHAR(40) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	booth VARCHAR(120), 
	summary TEXT, 
	services JSON NOT NULL, 
	valid_from VARCHAR(64), 
	valid_until VARCHAR(64), 
	created_at VARCHAR(64) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_px_event_org UNIQUE (event_id, organization_id), 
	FOREIGN KEY(event_id) REFERENCES px_sites (id), 
	FOREIGN KEY(organization_id) REFERENCES px_organizations (id), 
	FOREIGN KEY(agency_site_id) REFERENCES px_sites (id)
)

;


CREATE TABLE px_signup_requests (
	id VARCHAR(64) NOT NULL, 
	site_id VARCHAR(64) NOT NULL, 
	event_id VARCHAR(64), 
	requested_role VARCHAR(30) NOT NULL, 
	organization_name VARCHAR(200) NOT NULL, 
	contact_name VARCHAR(160) NOT NULL, 
	email VARCHAR(200) NOT NULL, 
	phone VARCHAR(60), 
	participation_type VARCHAR(40), 
	wants_account INTEGER NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	details JSON NOT NULL, 
	created_at VARCHAR(64) NOT NULL, 
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


CREATE TABLE px_users (
	id VARCHAR(64) NOT NULL, 
	email VARCHAR(200) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	role VARCHAR(20) NOT NULL, 
	scope_id VARCHAR(64), 
	password_hash TEXT NOT NULL, 
	active INTEGER NOT NULL, 
	must_change_password INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (email), 
	FOREIGN KEY(scope_id) REFERENCES px_sites (id)
)

;


CREATE TABLE px_assignments (
	id VARCHAR(64) NOT NULL, 
	user_id VARCHAR(64) NOT NULL, 
	site_id VARCHAR(64) NOT NULL, 
	role VARCHAR(40) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	valid_from VARCHAR(64), 
	valid_until VARCHAR(64), 
	created_at VARCHAR(64) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_px_assignment UNIQUE (user_id, site_id, role), 
	FOREIGN KEY(user_id) REFERENCES px_users (id), 
	FOREIGN KEY(site_id) REFERENCES px_sites (id)
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


CREATE TABLE px_memberships (
	user_id VARCHAR(64) NOT NULL, 
	organization_id VARCHAR(64) NOT NULL, 
	role VARCHAR(40) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	created_at VARCHAR(64) NOT NULL, 
	PRIMARY KEY (user_id, organization_id), 
	FOREIGN KEY(user_id) REFERENCES px_users (id), 
	FOREIGN KEY(organization_id) REFERENCES px_organizations (id)
)

;


CREATE TABLE px_organization_people (
	id VARCHAR(64) NOT NULL, 
	organization_id VARCHAR(64) NOT NULL, 
	user_id VARCHAR(64), 
	name VARCHAR(160) NOT NULL, 
	email VARCHAR(200), 
	phone VARCHAR(60), 
	job_title VARCHAR(160), 
	person_role VARCHAR(40) NOT NULL, 
	public_visible INTEGER NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	created_at VARCHAR(64) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(organization_id) REFERENCES px_organizations (id), 
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

CREATE INDEX px_audit_user_time ON px_audit (user_id, at);

CREATE INDEX px_audit_site_time ON px_audit (site_id, at);

CREATE INDEX px_devices_site_status ON px_devices (site_id, status);

CREATE INDEX px_devices_last_seen ON px_devices (last_seen_at);

CREATE INDEX px_participations_event_status ON px_event_participations (event_id, status);

CREATE INDEX px_participations_org_status ON px_event_participations (organization_id, status);

CREATE INDEX px_signup_site_status ON px_signup_requests (site_id, status);

CREATE INDEX px_signup_event_status ON px_signup_requests (event_id, status);

CREATE INDEX px_submissions_event_kind ON px_submissions (event_id, kind);

CREATE INDEX px_submissions_site_time ON px_submissions (site_id, received_at);

CREATE INDEX px_assignments_user_status ON px_assignments (user_id, status);

CREATE INDEX px_assignments_site_status ON px_assignments (site_id, status);

CREATE INDEX px_memberships_user_status ON px_memberships (user_id, status);

CREATE INDEX px_memberships_org_status ON px_memberships (organization_id, status);

CREATE INDEX px_org_people_user ON px_organization_people (user_id);

CREATE INDEX px_org_people_org_status ON px_organization_people (organization_id, status);
