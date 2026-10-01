-- Windows 07 additive migration for deployments already on Windows 06 schema.
CREATE TABLE IF NOT EXISTS px_devices (
  id VARCHAR(64) PRIMARY KEY,
  site_id VARCHAR(64) NOT NULL REFERENCES px_sites(id),
  name VARCHAR(160) NOT NULL,
  device_type VARCHAR(30) NOT NULL,
  token_hash VARCHAR(64) NOT NULL UNIQUE,
  status VARCHAR(20) NOT NULL DEFAULT 'active',
  last_seen_at VARCHAR(64),
  last_sync_at VARCHAR(64),
  pending_count INTEGER NOT NULL DEFAULT 0,
  app_version VARCHAR(40),
  metadata_json JSON NOT NULL,
  created_at VARCHAR(64) NOT NULL
);
CREATE INDEX IF NOT EXISTS px_devices_site_status ON px_devices(site_id,status);
CREATE INDEX IF NOT EXISTS px_devices_last_seen ON px_devices(last_seen_at);
