CREATE TABLE IF NOT EXISTS px_platform_account_invites (
	id VARCHAR(64) NOT NULL,
	token_hash VARCHAR(64) NOT NULL,
	email VARCHAR(200) NOT NULL,
	phone VARCHAR(40),
	name VARCHAR(160) NOT NULL,
	created_by VARCHAR(64) NOT NULL,
	created_at VARCHAR(64) NOT NULL,
	expires_at VARCHAR(64) NOT NULL,
	request_id VARCHAR(64),
	PRIMARY KEY (id),
	UNIQUE (token_hash),
	FOREIGN KEY(created_by) REFERENCES px_users (id),
	UNIQUE (request_id),
	FOREIGN KEY(request_id) REFERENCES px_account_requests (id)
);
