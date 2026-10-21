CREATE TABLE IF NOT EXISTS px_account_request_workflows (
	request_id VARCHAR(64) NOT NULL,
	purpose VARCHAR(20) NOT NULL,
	tracking_hash VARCHAR(64) NOT NULL,
	payload_hash VARCHAR(64) NOT NULL,
	existing_user_id VARCHAR(64),
	user_id VARCHAR(64),
	signup_id VARCHAR(64),
	access_id VARCHAR(64),
	result_site_id VARCHAR(64),
	result_organization_id VARCHAR(64),
	valid_from VARCHAR(64),
	valid_until VARCHAR(64),
	setup_expires_at VARCHAR(64),
	PRIMARY KEY (request_id),
	CONSTRAINT ck_px_ar_workflow_purpose CHECK (purpose IN ('personal','site','organization','committee','signup','access')),
	FOREIGN KEY(request_id) REFERENCES px_account_requests (id),
	UNIQUE (tracking_hash),
	FOREIGN KEY(existing_user_id) REFERENCES px_users (id),
	FOREIGN KEY(user_id) REFERENCES px_users (id),
	UNIQUE (signup_id),
	FOREIGN KEY(signup_id) REFERENCES px_signup_requests (id),
	UNIQUE (access_id),
	FOREIGN KEY(access_id) REFERENCES px_access_requests (id),
	FOREIGN KEY(result_site_id) REFERENCES px_sites (id),
	FOREIGN KEY(result_organization_id) REFERENCES px_organizations (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS px_ar_pending_phone ON px_account_requests (phone, scope_type, scope_id) WHERE status = 'pending' AND phone IS NOT NULL;
