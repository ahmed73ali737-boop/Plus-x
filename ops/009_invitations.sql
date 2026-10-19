-- PulseX additive invitations/RSVP and atomic daily admission entitlements.

CREATE TABLE IF NOT EXISTS px_event_admission (
	event_id VARCHAR(64) NOT NULL,
	config JSON NOT NULL,
	rev INTEGER NOT NULL,
	updated_at VARCHAR(64) NOT NULL,
	PRIMARY KEY (event_id),
	FOREIGN KEY(event_id) REFERENCES px_sites (id)
)

;

CREATE TABLE IF NOT EXISTS px_guest_lists (
	id VARCHAR(64) NOT NULL,
	event_id VARCHAR(64) NOT NULL,
	name VARCHAR(160) NOT NULL,
	created_at VARCHAR(64) NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_px_guest_list_name UNIQUE (event_id, name),
	FOREIGN KEY(event_id) REFERENCES px_sites (id)
)

;

CREATE TABLE IF NOT EXISTS px_invitations (
	id VARCHAR(64) NOT NULL,
	event_id VARCHAR(64) NOT NULL,
	list_id VARCHAR(64),
	guest_id VARCHAR(64),
	name VARCHAR(160) NOT NULL,
	phone VARCHAR(24) NOT NULL,
	token_hash VARCHAR(64) NOT NULL,
	status VARCHAR(24) NOT NULL,
	response VARCHAR(24) NOT NULL,
	max_companions INTEGER NOT NULL,
	companions INTEGER NOT NULL,
	allowed_days JSON NOT NULL,
	days JSON NOT NULL,
	answers JSON NOT NULL,
	consent_at VARCHAR(64),
	reviewed_by VARCHAR(64),
	reviewed_at VARCHAR(64),
	revision INTEGER NOT NULL,
	created_at VARCHAR(64) NOT NULL,
	updated_at VARCHAR(64) NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_px_invitation_event_phone UNIQUE (event_id, phone),
	CONSTRAINT ck_px_invitation_companions CHECK (max_companions >= 0 AND companions >= 0 AND companions <= max_companions),
	FOREIGN KEY(event_id) REFERENCES px_sites (id),
	FOREIGN KEY(list_id) REFERENCES px_guest_lists (id),
	FOREIGN KEY(guest_id) REFERENCES px_guests (id),
	UNIQUE (token_hash)
)

;
CREATE INDEX IF NOT EXISTS px_invitations_event_status ON px_invitations (event_id, status);

CREATE TABLE IF NOT EXISTS px_admission_entitlements (
	id VARCHAR(64) NOT NULL,
	invitation_id VARCHAR(64) NOT NULL,
	event_id VARCHAR(64) NOT NULL,
	guest_id VARCHAR(64) NOT NULL,
	day VARCHAR(10) NOT NULL,
	quantity INTEGER NOT NULL,
	consumed INTEGER NOT NULL,
	status VARCHAR(20) NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_px_entitlement_day UNIQUE (invitation_id, day),
	CONSTRAINT ck_px_entitlement_quantity CHECK (quantity > 0 AND consumed >= 0 AND consumed <= quantity),
	FOREIGN KEY(invitation_id) REFERENCES px_invitations (id),
	FOREIGN KEY(event_id) REFERENCES px_sites (id),
	FOREIGN KEY(guest_id) REFERENCES px_guests (id)
)

;
CREATE INDEX IF NOT EXISTS px_entitlement_event_day ON px_admission_entitlements (event_id, day);

CREATE TABLE IF NOT EXISTS px_admission_uses (
	scan_id VARCHAR(64) NOT NULL,
	entitlement_id VARCHAR(64) NOT NULL,
	quantity INTEGER NOT NULL,
	used_at VARCHAR(64) NOT NULL,
	PRIMARY KEY (scan_id),
	CONSTRAINT ck_px_admission_use_quantity CHECK (quantity > 0),
	FOREIGN KEY(entitlement_id) REFERENCES px_admission_entitlements (id)
)

;

CREATE TABLE IF NOT EXISTS px_invitation_imports (
	id VARCHAR(64) NOT NULL,
	event_id VARCHAR(64) NOT NULL,
	user_id VARCHAR(64) NOT NULL,
	rows JSON NOT NULL,
	errors JSON NOT NULL,
	state VARCHAR(20) NOT NULL,
	created_at VARCHAR(64) NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(event_id) REFERENCES px_sites (id),
	FOREIGN KEY(user_id) REFERENCES px_users (id)
)

;
