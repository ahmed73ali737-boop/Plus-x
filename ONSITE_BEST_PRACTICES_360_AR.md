# PulseX Onsite / Guest Access — 360° Best-Practices Review

هذه الوثيقة تسجل ما تمت دراسته من أنظمة Onsite / Event Check-in مشابهة، وما تم استيعابه فعليًا داخل PulseX بدون إعادة بناء جذرية.

## الأنظمة المرجعية

- Eventbrite Organizer — QR/manual lookup، Check-in / Check-out / Validate Only، warning عند التكرار.
  https://www.eventbrite.com/help/en-gb/articles/741083/how-to-check-in-attendees-at-the-event-with-eventbrite-organizer/
- Cvent OnArrival — offline pre-download، badge/check-in، kiosk، session tracking، real-time stats، on-demand badging.
  https://support.cvent.com/articles/en_US/FAQ/Does-OnArrival-work-without-internet
  https://www.cvent.com/en/event-marketing-management/onarrival-event-check-in-software
- Swoogo Go Onsite — offline event/session check-in مع sync بعد الاتصال.
  https://swoogo.events/mobile/go-onsite/
- Whova — kiosk/self check-in، on-demand badge printing، attendee category filters، session/self check-in.
  https://whova.com/blog/kiosk-check-in-badge-printing/
  https://whova.com/blog/onsite-badge-printing/
  https://whova.com/blog/attendee-check-in-filters/

## Adopted / Implemented

| Practice | PulseX implementation | Why it adds value |
|---|---|---|
| QR + manual search fallback | QR camera + guest number/name/org/job search | Queue resilience if camera/QR fails |
| Check-in / Check-out / Validate-only | Three scanner modes | Separates validation from movement writes |
| Anti-passback | Atomic `px_guest_presence` transition | Stops double-entry across multiple gates |
| Current occupancy | Presence state + organizer KPI | Accurate “inside now”, not historical check-in count |
| Guest categories | Configurable visitor/VIP/staff/speaker/media/exhibitor | Fast lane/access segmentation |
| Access checkpoints | Configurable checkpoint + guest types + time window | One policy model for Main/VIP/Staff/etc |
| Re-entry policy | allow_reentry + last direction | Event-level control without custom code |
| Offline preload | Device pairing downloads manifest + policy | Gate continues without internet |
| Offline sync | Durable IndexedDB outbox + receipt + retry | No silent loss on reconnect |
| Manifest version/freshness | version hash + configurable freshness warning | Operators know whether offline data is stale |
| Five-day-compatible freshness | default 7200 min, configurable up to 10080 | Matches exhibition requirement without blocking operation |
| Device preflight | pairing/manifest/version/queue/storage/camera/network | Prevents discovering setup gaps at the door |
| Least-privilege device role | guest gate APIs require `operator` | Displays/tablets cannot retrieve attendee manifest |
| Manual/walk-in registration | organizer guest registration | Handles onsite exceptions |
| Badge on demand | print-ready final Guest Pass | Immediate value without printer-vendor lock-in |
| Secure badge/pass recovery | per-event possession secret hash | Phone number is dedupe key, not authentication |
| Secure public identifier | keyed HMAC guest number | Avoids phone-derived enumerable QR IDs |
| Reprint/exception desk path | organizer can open/print pass | Safe recovery without exposing QR via phone lookup |
| Privacy-minimized gate manifest | no phone in device manifest | Gate has only operational fields |
| Trusted guest type | only admin can promote VIP/staff/etc | Prevents public privilege self-escalation |
| Safe idempotency | immutable scan ID + payload conflict rejection | Lost ACK can replay safely; altered replay is rejected |
| Multi-gate concurrency | PostgreSQL atomic presence test | Prevents two gates accepting same entry simultaneously |
| Operational export | scoped CSV + entry/exit stats | Post-event reconciliation and reporting |

## Adapted rather than copied

### Offline behavior
Commercial platforms often require event data to be downloaded before network loss. PulseX follows the same principle but separates:
- Internet outage with venue LAN/server available: canonical registration + uniqueness can continue centrally.
- Fully isolated device: cached manifest/check-in works; new guest registration remains provisional until reconciliation.

This avoids falsely promising global uniqueness between devices that cannot communicate.

### Badge printing
PulseX currently uses print-ready web badges. We deliberately did **not** hard-code Zebra/Brother/AirPrint APIs into the domain. Printer integration should be an adapter/print-queue module so core Guest Identity remains vendor-neutral.

### Guest category filtering
Rather than a UI-only VIP filter, categories are part of one published Access Policy downloaded in the manifest and revalidated by the server.

## Deferred intentionally — requires a separate domain/module

| Practice | Decision | Reason |
|---|---|---|
| Session capacity / waitlist | DEFER | Needs session enrollment/capacity/reservation domain, not a checkpoint hack |
| Session self-check-in QR | DEFER | Best added on top of session attendance domain |
| Native printer pools / auto-print | DEFER | Requires hardware adapters, queue health, reprint lifecycle |
| Badge credential rotation on reprint | DEFER | Needs separate badge credential identity/revocation model |
| Kiosk 2FA/OTP | DEFER | Requires verified OTP provider and recovery policy |
| Payments at door | OUT OF CURRENT EVENT PILOT | Separate financial/payment workflow |
| RFID/NFC tracking | DEFER | Hardware + consent + privacy model |
| Signature/release forms | DEFER | Legal record/version/signature evidence domain |
| Distributed rate limiting | PRODUCTION INFRA | Requires shared gateway/Redis or equivalent across workers |
| Session certificates/credits | DEFER | Depends on session attendance rules |
| Formal waitlists | DEFER | Depends on reservations/capacity domain |

## Refactoring principles applied

1. `guest_service.py` = identity/registration/pass possession only.
2. `guest_gate_service.py` = access policy, validation, presence, movement, anti-passback.
3. API routes = thin transport/auth/scope layer.
4. IndexedDB = offline state/outbox/receipts; server remains canonical.
5. Access Policy = single source for online + offline gate decisions.
6. PostgreSQL transitions = authoritative concurrency control.
7. Applied SQL migrations are immutable; every later change gets a new migration.
8. Public phone registration never becomes a substitute for authentication.

## Acceptance boundary

Hosted CI can prove API/browser/IndexedDB/PostgreSQL/container behavior. It cannot certify:
- actual venue Wi-Fi/LAN topology,
- physical phone/USB scanner reliability,
- printer hardware,
- five-day hardware soak,
- real public TLS/domain,
- independent penetration test.

Those remain signed field/deployment gates rather than being mislabeled as automated PASS.
