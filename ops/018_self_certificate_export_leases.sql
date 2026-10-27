ALTER TABLE px_self_certificate_export_jobs ADD COLUMN IF NOT EXISTS lease_owner VARCHAR(64);
ALTER TABLE px_self_certificate_export_jobs ADD COLUMN IF NOT EXISTS lease_until VARCHAR(64);
ALTER TABLE px_self_certificate_export_jobs ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE px_self_certificate_export_jobs ADD COLUMN IF NOT EXISTS started_at VARCHAR(64);
