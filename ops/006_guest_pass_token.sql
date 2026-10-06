-- PulseX additive migration: per-event guest pass possession token.
-- Keep applied migrations immutable; this follows 004 guest identity and 005 presence.
ALTER TABLE px_event_guests
    ADD COLUMN IF NOT EXISTS pass_token_hash VARCHAR(64);
