# PulseX / UIP candidate: guest status preview, without shared guest storage

Reference: issue #29; Factory governed intake https://github.com/ahmed73ali737-boop/G-Factory/pull/105.
Parent main SHA: e66369ac83e1ee17d52664147e0e874329207501.

## Ownership, actors and contracts
- PulseX owns all Guest identity, pass generation, offline outbox, scanner anti-passback, votes and visit logs.
- Intended actor: organizer-authorized service principal with event+tenant scope and per-purpose consent validation.
- Intended input: opaque guest identifier, event identifier, no phone/PII in QR, correlation id; all claims verified server-side.
- Intended output: minimal status/eligibility preview; no guest record export, personal identifiers or side effects.
- UI: existing PulseX Gate/QR/Organizer flows; no new complete screen asserted.
- Storage and migrations: unchanged; no UIP replicas of guest database.
- Notifications/events: none live in this PR; UIP not an authority on offline queue or gate outcome.
- Tests: static candidate source guard only. Actual browser scanner/offline replay, negative tenant/consent, service auth and production IAM are OPEN.

## Rollout gates
1. Keep execution SIMULATION_ONLY and externalEffectsEnabled false.
2. Add privacy-minimizing, tenant-bound authenticated read-only API only after owner approval.
3. Verify duplicate check-in, offline reconnect, QR anti-passback, credential revocation and audit events under actual PulseX runtime.
4. Re-run combined CI and independent security/UX assessment at exact commit before integration.
5. Deploy no new UIP service and do not enable payments, provider execution or guest exports from this PR.

## Reuse and rollback
Apply versioned UIP SDK/API contracts as optional adapters, never copy the PulseX identity engine to UIP. Revert this manifest, one static test script, this doc and its CI job. Existing application runtime remains unchanged.

Evidence: original uploaded archive SHA256 ac62bab6b7d12bd38578928e7f4731f20ea24f1b8200d25150c811039bccc3be; reviewed local bundle SHA256 23ce18d59e0b60b6417ce990b36d12738b518bd20da6827836896990849416c4.
