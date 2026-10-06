-- PulseX Windows 12 additive migration: atomic guest presence / anti-passback.
CREATE TABLE IF NOT EXISTS px_guest_presence (
    event_id VARCHAR(64) NOT NULL REFERENCES px_sites(id),
    guest_id VARCHAR(64) NOT NULL REFERENCES px_guests(id),
    state VARCHAR(12) NOT NULL DEFAULT 'outside',
    last_scan_id VARCHAR(64),
    last_direction VARCHAR(12),
    last_checkpoint VARCHAR(80),
    updated_at VARCHAR(64) NOT NULL,
    PRIMARY KEY (event_id, guest_id)
);
CREATE INDEX IF NOT EXISTS px_guest_presence_event_state
    ON px_guest_presence (event_id, state);
