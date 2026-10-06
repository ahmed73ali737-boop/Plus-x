# PulseX Exhibition CI Evidence — 2026-10-06

This evidence note reconciles the merged Exhibition 360 / Guest QR candidate with the current automated verification record.

## Candidate and merge

- PR #3 candidate head: `29422416a40a824ac0b933b8bc6f2f3bc6e93cdd`.
- Merge commit on `main`: `b2af516d84c73d7b5fe8bdea8c20c1f98ce8b01c`.

## Exact-head automated evidence

The following pull-request-triggered runs completed successfully on the exact candidate head before merge:

- PulseX CI run `37425282781`.
  - PostgreSQL native acceptance.
  - PostgreSQL application-path capacity smoke.
  - Windows pytest, native HTTP acceptance, Chromium component and real HTTP browser E2E.
  - Windows exhibition brand journeys, Guest QR/offline flow and IndexedDB component.
  - Linux browser components and real HTTP browser flow.
  - Python core, security smoke, exhibition capacity smoke and 70-entity topology smoke.
  - JavaScript SDK tests and Python SDK real HTTP smoke.
  - Production image build/import and migration-asset verification.
- guest-qr-ci run `37425281740`.
  - Guest QR and offline regression.
  - 1000-guest capacity smoke.
  - Current OpenAPI generation.
  - Real Chromium guest journey and exhibition brand journeys.
- PulseX CI run `37425281791`: PASS on the same candidate head.

## Truth boundary

Implemented/source-verified/native-tested: YES for the automated scope above.

External-blocked / not proven by hosted CI:
- physical camera/scanner UAT;
- physical multi-device outage and venue LAN/edge validation;
- five-day soak;
- real TLS/domain deployment;
- independent DAST/pentest;
- production backup-restore/PITR/retention;
- signed business/field UAT.

Production-ready: NO until the external gates above are closed.
