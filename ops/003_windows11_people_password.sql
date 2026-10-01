-- PulseX Windows 11 additive migration
ALTER TABLE px_users ADD COLUMN IF NOT EXISTS must_change_password INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS px_organization_people (
    id VARCHAR(64) PRIMARY KEY,
    organization_id VARCHAR(64) NOT NULL REFERENCES px_organizations(id),
    user_id VARCHAR(64) REFERENCES px_users(id),
    name VARCHAR(160) NOT NULL,
    email VARCHAR(200),
    phone VARCHAR(60),
    job_title VARCHAR(160),
    person_role VARCHAR(40) NOT NULL DEFAULT 'member',
    public_visible INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at VARCHAR(64) NOT NULL
);
CREATE INDEX IF NOT EXISTS px_org_people_org_status ON px_organization_people (organization_id, status);
CREATE INDEX IF NOT EXISTS px_org_people_user ON px_organization_people (user_id);
