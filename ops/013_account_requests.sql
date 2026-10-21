-- Additive phase 1 only: requests do not create users or grant access.

CREATE TABLE IF NOT EXISTS px_account_requests (
	id VARCHAR(64) NOT NULL,
	email VARCHAR(200) NOT NULL,
	name VARCHAR(160) NOT NULL,
	phone VARCHAR(40),
	requested_role VARCHAR(20) NOT NULL,
	scope_type VARCHAR(20) NOT NULL,
	scope_id VARCHAR(64) NOT NULL,
	site_id VARCHAR(64),
	organization_id VARCHAR(64),
	event_id VARCHAR(64),
	person_id VARCHAR(64),
	participation_id VARCHAR(64),
	membership_role VARCHAR(20),
	assignment_role VARCHAR(40),
	source VARCHAR(20) NOT NULL,
	supervisor_id VARCHAR(64) NOT NULL,
	requested_by VARCHAR(64),
	reviewed_by VARCHAR(64),
	status VARCHAR(20) DEFAULT 'pending' NOT NULL,
	created_at VARCHAR(64) NOT NULL,
	expires_at VARCHAR(64) NOT NULL,
	reviewed_at VARCHAR(64),
	decision_reason VARCHAR(500),
	request_key VARCHAR(80) NOT NULL,
	password_hash TEXT,
	PRIMARY KEY (id),
	CONSTRAINT ck_px_ar_status CHECK (status IN ('pending','approved','rejected','expired','cancelled')),
	CONSTRAINT ck_px_ar_email CHECK (email = lower(trim(email)) AND length(email) BETWEEN 3 AND 200),
	CONSTRAINT ck_px_ar_role CHECK (requested_role IN ('platform','organizer','agency','member')),
	CONSTRAINT ck_px_ar_source CHECK (source IN ('signup','admin','organization','committee','access')),
	CONSTRAINT ck_px_ar_scope CHECK ((scope_type = 'site' AND site_id IS NOT NULL AND scope_id = site_id AND organization_id IS NULL) OR (scope_type = 'organization' AND organization_id IS NOT NULL AND scope_id = organization_id AND site_id IS NULL)),
	CONSTRAINT ck_px_ar_membership_role CHECK (membership_role IS NULL OR membership_role IN ('owner','admin','editor','analyst')),
	CONSTRAINT ck_px_ar_assignment_role CHECK (assignment_role IS NULL OR assignment_role IN ('event_manager','reception','scanner','committee_supervisor','analyst','auditor')),
	CONSTRAINT ck_px_ar_expiry CHECK (expires_at > created_at),
	CONSTRAINT ck_px_ar_hash CHECK (password_hash IS NULL OR (length(password_hash) = 161 AND substr(password_hash,33,1) = ':')),
	CONSTRAINT ck_px_ar_terminal_secret CHECK (status = 'pending' OR password_hash IS NULL),
	CONSTRAINT ck_px_ar_pending_review CHECK (status <> 'pending' OR (reviewed_by IS NULL AND reviewed_at IS NULL AND decision_reason IS NULL)),
	CONSTRAINT ck_px_ar_review CHECK (status NOT IN ('approved','rejected') OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)),
	CONSTRAINT ck_px_ar_rejection_reason CHECK (status <> 'rejected' OR (decision_reason IS NOT NULL AND length(trim(decision_reason)) > 0)),
	FOREIGN KEY(site_id) REFERENCES px_sites (id),
	FOREIGN KEY(organization_id) REFERENCES px_organizations (id),
	FOREIGN KEY(event_id) REFERENCES px_sites (id),
	FOREIGN KEY(person_id) REFERENCES px_organization_people (id),
	FOREIGN KEY(participation_id) REFERENCES px_event_participations (id),
	FOREIGN KEY(supervisor_id) REFERENCES px_users (id),
	FOREIGN KEY(requested_by) REFERENCES px_users (id),
	FOREIGN KEY(reviewed_by) REFERENCES px_users (id),
	UNIQUE (request_key)
);

CREATE UNIQUE INDEX IF NOT EXISTS px_ar_pending_identity ON px_account_requests (email, scope_type, scope_id) WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS px_ar_scope_status_time ON px_account_requests (scope_type, scope_id, status, created_at);

CREATE INDEX IF NOT EXISTS px_ar_status_expiry ON px_account_requests (status, expires_at);

CREATE INDEX IF NOT EXISTS px_ar_supervisor_status_time ON px_account_requests (supervisor_id, status, created_at);
