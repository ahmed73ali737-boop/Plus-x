# Eventna (PulseX) — use cases, actors and journeys

This document maps every business capability to the layer that owns it after the
clean-architecture refactor (`refactor/ddd-clean-architecture`).

## Architecture in one page

```
app/domain/          pure Python rules (entities, value objects, aggregates, errors)
app/application/     use cases; depend on app/application/ports.py only
app/infrastructure/  SQLAlchemy Core tables, repositories, unit of work, storage adapters
app/api/ + server.py HTTP adapters (FastAPI) and the composition root
```

* **Dependency rule** (enforced by `tests/test_architecture.py`): domain imports only the
  standard library; application imports domain, ports and framework-free `app.core` helpers;
  infrastructure never imports FastAPI or use cases; no SQL outside infrastructure.
* **Errors**: the domain raises `DomainError` subclasses (`InvalidInput`, `Unauthenticated`,
  `Forbidden`, `NotFound`, `Conflict`, `Gone`, `PreconditionRequired`, `RateLimited`,
  `Unavailable`) carrying a stable code. `app/api/errors.py` is the only place that maps a
  category to an HTTP status; the response body is unchanged (`{"detail": "<CODE>"}`).
* **Ports**: `app/application/ports.py` declares one `Protocol` per repository and a
  `persistence` registry. `make_engine()` (the persistence composition root) installs the SQL
  adapters from `app/infrastructure/persistence`; `tests/test_use_cases.py` installs in-memory
  fakes instead. Use cases receive an opaque transaction handle (`tx`) owned by their caller.
* **Legacy import paths** `app.db`, `app.invitations_db`, `app.certificates_db`,
  `app.self_certificates_db`, `app.account_requests_db` are aliases (same module object) of the
  table modules now in `app/infrastructure/persistence/` and are kept for ops tools and tests.

## Actors

| Actor | Who | Authenticates with |
|---|---|---|
| Visitor | Anonymous public user of an event site or kiosk | nothing (visitor/session UUIDs) |
| Guest | Person registered for an event; holds a pass (QR) | possession of the pass number/token |
| Invitee | Person invited to a managed-admission event | invitation token |
| Participant | Person requesting a self-declared certificate | request link + browser cookie |
| Platform admin | `role=platform` | session cookie + CSRF |
| Organizer | `role=organizer`, scoped to one event | session cookie + CSRF |
| Agency / exhibitor staff | `role=agency` or organization membership (owner/admin/editor/analyst) | session cookie + CSRF |
| Committee member | event assignment (event_manager, reception, scanner, committee_supervisor, analyst, auditor), time-bounded | session cookie + CSRF |
| Gate / kiosk device | enrolled device (`operator`, `kiosk`, `tablet`, `display`) | `X-PulseX-Device-Token` |
| Account applicant | person asking for an account | tracking token |
| Background workers | certificate render/export/batch workers | in-process |

## Use cases

Rules column: the domain class/module that owns the rule. Events column: the audit actions
written (the system's durable domain events).

### Sites, publishing and content

| Use case | Actor | Input | Output | Rules (owner) | Events |
|---|---|---|---|---|---|
| Create site (event/agency) | Platform admin, Organizer | kind, parent_id, slug, title | `{id, draft_rev}` | `sites.authorize_new_site`, `values.slug`, `site_config.default_config` | `site_created` |
| Save draft | Site manager | config, draft_rev | `{draft_rev}` | `site_config.normalize_config` (SiteConfig/Record factories), `sites.require_draft_revision`; repository CAS on `draft_rev` | `draft_saved` |
| Publish | Site manager | draft_rev | `{published_version}` | `sites.publish` (Publication), `sites.require_publish_revision`; repository CAS on draft_rev+version | `publish` |
| Preview / public bundle | Site manager / Visitor | slug | site bundle | `site_config.public_config_without_answer_keys`, `sites.event_status`, `sites.visibility_from_policy` | — |
| Import content (preview/commit) | Site manager | CSV/XLSX | records, errors | `app/imports.py`, `normalize_record`; draft CAS | `import_committed` |
| Upload media | Signed-in user | base64 | `/media/<sha>.ext` | `media.media_extension`, `MEDIA_MAX_BYTES` | — |
| QR for a site | Site manager | site id | PNG | `sites.public_path` | — |

### Visitor collection and analytics

| Use case | Actor | Input | Output | Rules (owner) | Events |
|---|---|---|---|---|---|
| Collect batch (visit/survey/poll/feedback/contact/ad) | Visitor, kiosk | ≤50 items | receipts (accepted/duplicate/rejected) | `submissions.*` (poll must match live version and be open, feedback scope/criteria, contact consent), `surveys.survey_answers`/`answer_value`; one-vote dedup key | — |
| Poll results | Visitor | slug | counts per option | `surveys.ballot_items`, poll visibility rule | — |
| Metrics / raw export | Site reader / manager | site id | metrics JSON / CSV | read-scope rules (`authorization`) | `raw_export` |

### Guests and the gate (anti-passback)

| Use case | Actor | Input | Output | Rules (owner) | Events |
|---|---|---|---|---|---|
| Register (public / offline sync) | Visitor | phone, consent, profile | pass number + token or `verification_required` | `guests.GuestRegistration`, `guests.normalize_phone`; only public/unlisted events without managed admission | — |
| Register (staff) | Reception (`guests.register`) | phone, profile, guest_type | guest + QR | `GuestRegistration(allow_guest_type)`, profile updates opt-in | `guest_registered` |
| Show pass / pass QR | Guest | pass number | status / PNG | `guests.require_active_pass` | — |
| Validate pass | Gate device, staff | pass, checkpoint, mode | valid/invalid + reason | `gate.admission_denial`, `access_control.Checkpoint`, `devices.require_gate_device`, `gate.device_checkpoint_allowed` | — |
| Record entry/exit scan | Gate device, staff (`guests.checkin`) | pass, mode, checkpoint, scan_id, offline fields | accepted / duplicate / already_inside / already_outside | **`gate.GuestPresence.pass_gate`** (anti-passback, re-entry), `gate.offline_scan_time` (policy version, clock), `admission.Entitlement`; repository applies the transition with a conditional UPDATE on the expected state (optimistic concurrency) | `guest_checkin`, `guest_scan_blocked`, `guest_scan_rejected` |
| Offline manifest | Gate device | event id | guests + policy version | `access_control.AccessPolicy.version` | — |
| Guest list / attendance CSV / check-in overview | Staff (`guests.read/export`) | event id | rows | phone visible only with `guests.export` | — |

### Managed admission (invitations)

| Use case | Actor | Input | Output | Rules (owner) | Events |
|---|---|---|---|---|---|
| Save admission policy | `policy.manage` | policy | policy + rev | **`admission.AdmissionPolicy`** (`revise`, `guard_fixed_admissions`, `guard_days`) | `admission_policy_updated` |
| Create / import invitations | `invitations.manage` | name, phone, days | invitation + token/link | `admission.clean_invitation`, `invitation_limits`, list scope | `invitation_created`, `invitations_imported` |
| RSVP | Invitee | response, companions, days, consent | invitation view | **`admission.Invitation.rsvp`**, `outcome_after_rsvp`, `check_window`; capacity via `Invitation.check_capacity` | `invitation_rsvp` |
| Review | `invitations.review` | decision, revision | invitation | `Invitation.check_review`, `forbid_after_attendance` | `invitation_reviewed` |
| Revoke / rotate | `invitations.manage` | invitation id | invitation (+ new token) | `admission.require_active`; pass rotated (`guests.new_event_pass_number`) | `invitation_revoked`, `invitation_token_rotated` |
| Public / on-site registration | Visitor / reception | phone, name | invitation or `verification_required` | `assert_public_registration`; a known phone never recovers a pass | `public_registration_requested`, `onsite_registration` |
| Consume entitlement at the gate | (part of scan) | scan_id, quantity | remaining | **`admission.Entitlement`** (`admission_day`, `requested_quantity`, `check_replay`); repository atomic `consumed + q <= quantity` | — |

### Accounts, authorization and committees

| Use case | Actor | Input | Output | Rules (owner) | Events |
|---|---|---|---|---|---|
| Login / logout / sessions | Any user | phone or e-mail + password | session cookie + CSRF | `accounts.SESSION_HOURS`, constant-work password check | `login`, `login_failed` (audited after rollback), `sessions_revoked_all` |
| Change password / add phone login | Signed-in user | current + new | sessions revoked | `accounts.check_password_change`, `PasswordPolicy` | `password_changed`, `phone_login_added` |
| Admin reset / suspend | Platform admin, organizer | user id | temporary password / status | `accounts.require_reset_target`, `require_platform` | `admin_password_reset`, `user_status_changed` |
| Request account (personal, site, organization, committee, access, sign-up, platform invite) | Applicant / staff | contact, scope, role | pending request + tracking token | **`account_requests`** (`check_roles`, `check_target`, `request_key`, `assignment_window`, `supervisor_preference`, `may_supervise`) | `account_request_submitted` |
| Review account request | Designated supervisor | approved/rejected, reason | request view | `account_requests.check_reviewer` (no self-review), `delegated_grant_allowed`, `granted_assignment_role`, `new_login` | `account_request_approved/rejected/expired/cancelled` |
| Set up password from approval | Applicant | tracking token + password | login required | `account_requests.setup_available` | `account_password_set` |
| Event capabilities | Any staff | event id | permission set | **`authorization.event_capabilities`**, `active_window` (shift windows fail closed) | `scope_denied` (audited) |
| Committee assign / update | `committee.manage` | role, window | pending request / assignment | `committee.assignment_changes`, `validated_window` | `committee_updated` |
| Organizations, people, members, participations | Platform, organizer, org owner/admin | profile data | records | `organizations.*` (`new_organization`, `person_values`, `membership_changes`, `participation_changes`, `require_event_operator`) | `organization_created`, `organization_person_added/updated`, `membership_updated`, `participation_added/updated` |
| Devices (enrol, update, heartbeat) | Site manager / device | name, type, metadata | token shown once / telemetry ack | **`devices`** (`validate_device_metadata`, `device_changes`, `require_usable`, `heartbeat_values` — telemetry can never change policy) | `device_created`, `device_updated` |
| Preferences / inbox / notifications | Signed-in user / platform | preferences, message | stored values | `accounts.check_preferences` | `notification_sent` |

### Certificates

| Use case | Actor | Input | Output | Rules (owner) | Events |
|---|---|---|---|---|---|
| Templates, issue, revoke, replace, rotate access | `certificates.*` | design, data | certificate + links | **`certificates.CertificateDesign`** (bounded design), **`IssueRequest`** (idempotency key + hash, legacy-UTC replay, future expiry), **`Certificate`** (`issue` snapshot, derived `state`, `require_valid`, replacement award key); repository insert-if-absent | `certificate_template_created`, `certificate_issued`, `certificate_revoked`, `certificate_replaced`, `certificate_access_rotated` |
| Bulk import + queued issuance | `certificates.issue` / worker | CSV/XLSX + mapping | queued jobs, progress | **`certificate_imports`** (`decode_upload`, `headers_of`, `check_mapping`, `preview_rows`, `IssuanceBatch` commit-once/TTL/per-row request key); one job per transaction in `certificate_batches` | `certificate_batch_queued`, `certificate_issued` |
| Self-service library (models, assets, links) | Library manager | design, uploads | models/links | `self_certificate_access` (library authority), owner-filtered repository, owner-chain triggers (defence in depth) | `self_certificate_model_*`, `self_certificate_link_*` |
| Participant self-declaration | Participant | name, phone, consent, nonce | request state (202 when created) | `domain.self_certificates` (`participant_submission`, `declared_phone`, `browser_remaining_seconds`, `require_accepting`, `require_revision_intact`, `require_failed_request/job`), browser dedup, `owner_can_accept` | — |
| Render / export workers | Workers | leased jobs | issued certificates / files | leased queue with fencing in `SqlSelfCertificateRepository`; retry policy in `self_certificate_worker.fail_job` | `self_certificate_retry` |

## Journeys per actor

* **Visitor**: open `/e/<event>` → `GET /api/public/site/<slug>` (bundle) → interact → batched
  `POST /api/collect` (survey/poll/feedback/contact) → `GET .../results`.
* **Guest (open event)**: `/e/<event>/register` → `POST .../guests/register` (consent, phone) →
  pass + QR → at the gate the device validates and records an entry (`accepted`); a second
  entry with the same pass is `already_inside` (anti-passback); exit → re-entry if allowed.
* **Invitee (managed admission)**: invitation link → `GET /api/public/invitations/<token>` →
  RSVP → auto-approve or `pending_approval` → reviewer approves → pass with day entitlements →
  gate consumes `1 + companions` per day.
* **Gate device**: enrolled by a site manager (token shown once) → `gate-context` →
  `guest-manifest` (offline) → batched `guest-checkins` with scan ids (idempotent replays) →
  heartbeat telemetry.
* **Organizer**: login → create agency pages/participations → edit draft → publish → manage
  admission policy, invitations, committee and devices → monitor check-ins and metrics.
* **Exhibitor (agency)**: login → edit own page within the participation lifecycle → view
  metrics → request accounts for people.
* **Account applicant**: submit request → keep tracking token → supervisor approves →
  set password (setup link) → login.
* **Participant (self certificate)**: open request link → prepare (browser cookie) → submit →
  poll `mine` → receive/download/verify.

## Test map

| Area | Tests |
|---|---|
| Dependency rule, HTTP-free inner layers, ports implemented | `tests/test_architecture.py` |
| Domain rules (gate aggregate, access policy, admission, devices, sites, authorization, submissions, account requests) | `tests/test_domain.py` |
| Use cases with in-memory ports (scan cycle, anti-passback, concurrent gate, re-entry, manifest, publishing) | `tests/test_use_cases.py` |
| HTTP behaviour and SQL adapters (pre-existing suite, unchanged expectations) | `tests/test_*.py` (e.g. `test_guest_identity.py`, `test_admission_gate_integration.py`, `test_invitations.py`, `test_account_approval.py`, `test_self_certificate_*.py`, `test_pilot.py`) |
| Native PostgreSQL acceptance | `tests/postgres_native_acceptance.py`, `tests/postgres_invitations_acceptance.py`, `tests/postgres_capacity_smoke.py` (+ account suites with `PX_ACCOUNT_*_TEST_DATABASE_URL`) |

## Phase 2 — shrink-only ratchet and what moved

`tests/architecture_baseline.json` records, per `app/application` module, how many `fail(...)`
rule checks are still written outside the domain; `tests/test_architecture.py::test_rules_in_application_ratchet_only_shrinks`
fails when a count grows, when a new module appears, **or** when a count dropped without the
baseline being lowered. Phase-2 start: 344 checks in 36 modules; after phase 2: 250; after phase 3: 60.

| Context | Rules now owned by the domain | Domain class / module | Tests |
|---|---|---|---|
| Certificate issuance (integrity, credentials) | design bounds, issue request + idempotency, snapshot freeze, derived validity, revoke/replace key | `domain/certificates.py` (`CertificateDesign`, `IssueRequest`, `Certificate`) | `tests/test_domain_certificates.py` |
| Bulk certificate issuance | upload limits, header/mapping rules, per-row errors, commit-once, TTL, canonical availability | `domain/certificate_imports.py` | `tests/test_domain_certificate_imports.py` |
| Account approvals (maker/checker) | pause switch, designated supervisor only, review disposition (replay/expired), identity collision, setup window, setup renewal, platform invitation | `domain/account_requests.py` | `tests/test_domain_account_approval.py` |
| Account administration | reset authority and scope, platform/site status changes, credential re-entry | `domain/accounts.py` | `tests/test_domain_accounts.py` |
| Gate admission | scan-id replay equality, managed admission needs entitlement, single-person unmanaged scan | `domain/gate.py` | `tests/test_domain_gate_rules.py` |
| Invitation import | upload limits, table shape, preview commit lifecycle | `domain/admission.py` (`GuestImport`) | `tests/test_domain_guest_import.py` |
| Site administration | staff-only directory actions, signup role, membership manager, person link, content-import commit | `domain/sites.py`, `domain/organizations.py` | `tests/test_domain_site_admin.py` |
| Self-declared certificates | phone normalisation, browser remember window, accepting switch, revision integrity, retry | `domain/self_certificates.py` | `tests/test_domain_self_certificates.py` |

## Phase 3 — authorization, accounts, collection, admission and self-certificates

Phase 3 started at 250 checks in 37 modules and ends at **60 in 12** (25 modules now have none).
Domain rules take their facts as plain values or lazy callables, so use cases only *load* (ports) and
*apply* (domain); behaviour, routes, status codes and bodies are unchanged (the OpenAPI document and
route table are byte-identical before and after, and the pre-existing suite passes unchanged).

New shared vocabulary: `domain/guards.py` (`require_found` -> `NotFound`, `reject_existing` -> `Conflict`)
so "missing/duplicate" is a typed domain decision instead of a `fail(...)` next to a repository call.

| Context | Rules now owned by the domain | Domain class / module | Tests |
|---|---|---|---|
| Site scope and event capabilities (authorization) | `can_manage_site` / `can_read_site` decision order over a `SiteAccessFacts` port (inactive user, role, own agency page lifecycle, shift assignment, organization membership + active participation; read never flows into manage), organization visibility, unknown permission fails closed, event-only capabilities | `domain/authorization.py` | `tests/test_domain_authorization.py`, `tests/test_use_cases_phase3.py` |
| Certificate library authority | live principal (active, password change done), library capability set, who manages the library, event authority, eligible events, owner-only concealment | `domain/authorization.py` | `tests/test_domain_authorization.py` |
| Phone/contact accounts | strict E.164 account phone (+967 mobiles only), login principal, `tel:` never exposed as email, one person per contact, phone binding (bind/keep/takeover/change), review-queue visibility | `domain/contacts.py` | `tests/test_domain_contacts.py` |
| Sessions and identity | live session, active account, CSRF on writes, notification ownership, message targets | `domain/accounts.py` | `tests/test_domain_accounts.py`, `tests/test_use_cases_phase3.py` |
| Account approvals (maker/checker) | supervisor availability, submitter scope (lazy), request-key replay vs changed payload, supervision concealment, setup activation, new-account-only invitations | `domain/account_requests.py` | `tests/test_domain_account_approval.py` |
| Visitor collection and metrics | batch of 1..50, item must be an object, idempotent replay vs conflict, feedback scope/target, **metrics aggregation** | `domain/submissions.py`, `domain/metrics.py` | `tests/test_domain_submissions_collection.py`, `tests/test_use_cases_phase3.py` |
| Site administration | access-request targets/roles, legacy-workflow and scope concealment, slug/organization/participation uniqueness, hidden-organization concealment, people-manager authority, draft-save race | `domain/sites.py`, `domain/organizations.py` | `tests/test_domain_site_admin.py`, `tests/test_use_cases_phase3.py` |
| Managed admission | legacy-pass migration, guest-list scope, one invitation per phone, entitlement availability/consumption, per-file uniqueness, direct-registration closure, registered-guest rule | `domain/admission.py`, `domain/gate.py` | `tests/test_domain_guest_import.py`, `tests/test_domain_gate_rules.py` |
| Public event visibility | event targeting, published-version requirement, private events concealed, guarded publish conflict | `domain/sites.py` | `tests/test_domain_site_admin.py`, `tests/test_use_cases_phase3.py` |
| Certificates, devices, committee | lookups, bounded public lookup, concurrent-issue winner, single replacement, single-sheet import, commit-once, inline-image/render limits, committee role/assignee, device scope/token | `domain/certificates.py`, `domain/certificate_imports.py`, `domain/committee.py`, `domain/devices.py` | `tests/test_domain_certificates.py`, `tests/test_domain_certificate_imports.py`, `tests/test_domain.py` |
| Self-certificate links, models, assets | `LinkRequest`/`LinkStateChange`, strict row versions, idempotent replay, pilot gate, expected revision, upgrade requirement, pagination/filter, upload gate, browser seed/token | `domain/self_certificates.py` | `tests/test_domain_self_certificates.py` |
| Self-certificate layout and branding | typography/shape/pixel rules, name normalisation, shrink-then-drop-penultimate fitting (metrics injected), stamp placement, frozen branding profiles, card manifest, reserved-area clearance | `domain/certificate_layout.py`, `domain/certificate_branding.py` | `tests/test_domain_certificate_layout.py`, `tests/test_domain_certificate_branding.py` |
| Participant exports and capability tokens | export request/lease/snapshot/download rules, token and nonce shape, +/-1 window freshness | `domain/self_certificates.py`, `domain/capability_tokens.py` | `tests/test_domain_self_certificates.py`, `tests/test_domain_capability_tokens.py` |

Differential checks (old vs new implementation, identical results): metrics aggregation (200 random
data sets), name fitting (3000), branding profiles (1500), reserved rectangles/manifests (3000).
Ten domain rules were removed one at a time (can_manage inactive check, phone takeover, CSRF compare,
replay conflict, people-manager rule, penultimate-word drop, card clearance, nonce window, strict row
version, consumption guard) and each removal fails the domain/use-case suite.

### Not yet migrated (what the ratchet still counts: 60 in 12 modules)

What is left is adapter-shaped, not request-level business rules:

* `self_certificate_fonts` (16), `self_certificate_storage` (10), `self_certificate_worker` (8),
  `self_certificate_delivery`/`executor`/`limits`/`slots` (8): font-file and manifest verification,
  file/lease storage, worker supervision and resource limits. These are infrastructure that still lives
  under `app/application` and should move to `app/infrastructure` (not a domain extraction).
* `self_certificate_assets` (5) and `self_certificate_branding` (2): isolated decoder process and resource
  file hashing errors (`Unavailable`).
* `invitation_service` (3): spreadsheet/CSV parse errors (`xlsx_reader` is an adapter).
* `self_certificate_crypto` (3): key-file availability.
* `shared_authorization` (5): **locked asset** (`ops/consolidated-source-lock.json`); untouched on purpose.

Use cases still pass rows as dicts; the domain functions take those records (or lazy fact callables) as
their input, which is the seam for introducing entities (`Principal`, `Site`, `Invitation`) later.
