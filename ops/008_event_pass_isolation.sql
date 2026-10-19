-- Replace the public phone-derived identity with a distinct bearer pass per event.
-- gen_random_uuid() is built into the supported PostgreSQL runtime; no extension
-- or phone-derived value is required. MD5 distributes the UUID's 122 random bits
-- across the 120-bit output rather than retaining the fixed UUID version bits.
-- Existing public global numbers MUST NOT be retained as accepted aliases.
UPDATE px_event_guests
SET pass_number = 'G-' || upper(substr(md5(gen_random_uuid()::text), 1, 30))
WHERE pass_number IS NULL
   OR pass_number !~ '^G-[0-9A-F]{30}$';

-- Leave legacy scan history intact: its guest_id remains the authoritative link.
-- Operators must refresh prepared manifests before accepting any offline entry.
