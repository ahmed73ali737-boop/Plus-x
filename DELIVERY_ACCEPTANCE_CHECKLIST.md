# PulseX v1.0.1 — Delivery Acceptance Checklist

## Software/Functional
- [x] Unified source tree and versioned release process
- [x] Public event/participant experience
- [x] RTS distinct exhibition surface
- [x] Easy distinct exhibition surface
- [x] Tharawat distinct exhibition surface
- [x] Surveys/questions/required validation
- [x] Poll submit/result roundtrip
- [x] Rating/notes/contact/consent flows
- [x] Excel/CSV preview + commit
- [x] Admin/Organizer scope flows
- [x] Organization/participation/member model
- [x] Guest phone dedupe + opaque number + QR
- [x] Offline guest reconciliation
- [x] Offline gate queue/reconnect/idempotency
- [x] API/OpenAPI + Python/JS SDK
- [x] PostgreSQL migrations
- [x] Docker production image

## UI/UX automated evidence
- [x] Desktop Chromium journeys
- [x] Mobile 390×844 brand journeys
- [x] No horizontal overflow in covered public brand surfaces
- [x] Visitor chrome excludes admin controls
- [x] Semantic date/time/email/phone/url/number controls
- [x] Consent/required validation in covered flows
- [x] Windows Chromium
- [x] Linux Chromium
- [x] IndexedDB non-blocking first render

## Release CI
The v1.0.1 release PR must pass all required CI on its exact head before merge.

## External field sign-off — intentionally not pre-checked
- [ ] Physical camera/scanner
- [ ] Two/multi-device hard outage/recovery
- [ ] Venue LAN/edge
- [ ] Five-day offline soak
- [ ] Real TLS/domain
- [ ] Production-like saturation/SLO
- [ ] Independent DAST/Pentest
- [ ] Production backup restore/PITR
- [ ] Signed business/field UAT
