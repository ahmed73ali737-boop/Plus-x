CREATE TABLE IF NOT EXISTS px_preferences (
 user_id VARCHAR(64) PRIMARY KEY REFERENCES px_users(id), config JSON NOT NULL
);
CREATE TABLE IF NOT EXISTS px_notifications (
 id VARCHAR(64) PRIMARY KEY, user_id VARCHAR(64) NOT NULL REFERENCES px_users(id),
 sender_id VARCHAR(64) NOT NULL REFERENCES px_users(id), title VARCHAR(160) NOT NULL,
 body TEXT NOT NULL, created_at VARCHAR(64) NOT NULL, read_at VARCHAR(64)
);
CREATE INDEX IF NOT EXISTS px_notifications_owner_time ON px_notifications(user_id, created_at);
