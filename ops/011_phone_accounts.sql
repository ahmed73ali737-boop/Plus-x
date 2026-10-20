-- Add phone login identities without rebuilding users or changing legacy emails.
CREATE TABLE IF NOT EXISTS px_user_phones (
    phone VARCHAR(24) PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL UNIQUE REFERENCES px_users(id),
    created_at VARCHAR(64) NOT NULL
);
