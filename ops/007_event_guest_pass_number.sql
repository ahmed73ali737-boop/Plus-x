-- PulseX additive migration: event-scoped public guest pass number.
-- Global guest identity remains internal; public QR numbers are unique per event.
ALTER TABLE px_event_guests
    ADD COLUMN IF NOT EXISTS pass_number VARCHAR(32);

CREATE UNIQUE INDEX IF NOT EXISTS px_event_guests_pass_number
    ON px_event_guests (pass_number);
