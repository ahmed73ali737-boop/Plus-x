-- PulseX Windows 12 additive migration: guest identity, event registration, QR/check-in
-- Safe for an existing Windows 11 PostgreSQL database.

CREATE TABLE IF NOT EXISTS px_guests (
    id VARCHAR(64) PRIMARY KEY,
    phone_e164 VARCHAR(24) NOT NULL UNIQUE,
    phone_hash VARCHAR(64) NOT NULL UNIQUE,
    guest_number VARCHAR(32) NOT NULL UNIQUE,
    name VARCHAR(160),
    job_title VARCHAR(160),
    organization VARCHAR(200),
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL
);
CREATE INDEX IF NOT EXISTS px_guests_phone_hash ON px_guests (phone_hash);
CREATE INDEX IF NOT EXISTS px_guests_guest_number ON px_guests (guest_number);

CREATE TABLE IF NOT EXISTS px_event_guests (
    id VARCHAR(64) PRIMARY KEY,
    event_id VARCHAR(64) NOT NULL REFERENCES px_sites(id),
    guest_id VARCHAR(64) NOT NULL REFERENCES px_guests(id),
    status VARCHAR(20) NOT NULL DEFAULT 'registered',
    guest_type VARCHAR(40) NOT NULL DEFAULT 'visitor',
    metadata_json JSON NOT NULL,
    registered_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    CONSTRAINT uq_px_event_guest UNIQUE (event_id, guest_id)
);
CREATE INDEX IF NOT EXISTS px_event_guests_event_status ON px_event_guests (event_id, status);
CREATE INDEX IF NOT EXISTS px_event_guests_guest ON px_event_guests (guest_id);

CREATE TABLE IF NOT EXISTS px_guest_checkins (
    id VARCHAR(64) PRIMARY KEY,
    event_id VARCHAR(64) NOT NULL REFERENCES px_sites(id),
    guest_id VARCHAR(64) NOT NULL REFERENCES px_guests(id),
    guest_number VARCHAR(32) NOT NULL,
    scanner_id VARCHAR(64),
    source VARCHAR(20) NOT NULL,
    direction VARCHAR(12) NOT NULL DEFAULT 'entry',
    checkpoint VARCHAR(80) NOT NULL DEFAULT 'main',
    client_time VARCHAR(64),
    scanned_at VARCHAR(64) NOT NULL
);
CREATE INDEX IF NOT EXISTS px_guest_checkins_event_time ON px_guest_checkins (event_id, scanned_at);
CREATE INDEX IF NOT EXISTS px_guest_checkins_guest_time ON px_guest_checkins (guest_id, scanned_at);
