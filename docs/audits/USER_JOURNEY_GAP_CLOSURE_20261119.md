# Bounded user journey gap closure — 20261119

Executed 2026-11-18 UTC; report identifier/date requested by the owner is 20261119.
Local candidate only, on `fix/user-journey-boundaries-20261119`, based on
`efd4b1285ac9c6fd87f56930f014dd1653337262` (`branding/arabic-only-20261118`).
The implementation commit is the commit containing this report; resolve with
`git log -1 --format=%H -- docs/audits/USER_JOURNEY_GAP_CLOSURE_20261119.md`.
File hashes and command results are recorded in `USER_JOURNEY_GAP_CLOSURE_20261119.json`.

## Fixed binary assessment

The same 19 criteria apply before and after. A 1 means the stated, bounded
criterion has supporting evidence, not that its whole product journey is accepted.
A 0 means failed or unverified; intentional safety restrictions are not defects.
Baseline is the exact source SHA above, inspected before edits. New regression
checks ran against it before implementation: **10 failed, 1 passed**. Transformed
JavaScript baseline: **0/3 passed**. Existing admission/security baseline:
**28 passed**. The media preparation negative case was added during implementation;
its BEFORE result below is source-inspection evidence, not a claimed baseline run.

| # | Fixed binary criterion | Before | After | Evidence / level |
|---|---|---:|---:|---|
| 1 | Root deployment still generates event QR, invitation and guest links; foreign Origin rejected | 1 | 1 | `test_generated_links_and_qr_keep_mount[]`, disposable ASGI |
| 2 | Mounted organizer event QR encodes `/plusx/e/demo` | 0 | 1 | Same test `[/plusx]`; captures encoder input and returns real PNG, no camera/decode acceptance |
| 3 | Mounted invitation creation returns `/plusx/invite/…` | 0 | 1 | Same ASGI test; BEFORE origin-only source |
| 4 | Mounted guest registration returns `/plusx/e/demo/guest/…` | 0 | 1 | Same ASGI test; BEFORE origin-only source |
| 5 | Scanner parses a canonical mounted guest QR URL | 0 | 1 | `journey_boundaries.mjs`, transformed module execution |
| 6 | Scanner rejects foreign-origin and sibling-mount QR URLs | 0 | 1 | Same Node case; BEFORE parser did not check origin |
| 7 | Platform organizer share link stays in `/plusx/` | 0 | 1 | Transformed `publicPath` contract; static assertion, not browser navigation |
| 8 | Mounted offline database has a separate name | 0 | 1 | Adapter/runtime contract; no claim of per-account isolation |
| 9 | Mounted media cache has a separate name | 0 | 1 | Transformed module and actual preparation calls under Node |
| 10 | Worker ignores sibling navigation, APIs and non-GET requests | 0 | 1 | Worker event harness; BEFORE sibling navigation intercepted |
| 11 | Media fallback searches only its named cache; activation preserves other caches | 0 | 1 | Worker cache harness; BEFORE origin-wide `caches.match` |
| 12 | Preparation remaps root media and excludes API, sibling, foreign, traversal and redirected responses | 0 | 1 | New `prepare` runtime test with fake IndexedDB; BEFORE fetched any same-origin URL |
| 13 | Invalid configured mount paths fail startup validation | 0 | 1 | Eight negative settings cases; BEFORE variable ignored |
| 14 | Controlled admission denies offline use, enforces scope and handles replay/conflict without excess consumption | 1 | 1 | Existing admission integration/device/frontend suites, baseline and final runs |
| 15 | Lost HTTP acknowledgement recovers as duplicate with one ledger use | 1 | 1 | `test_admission_http_ack.py`, disposable real HTTP server and SQLite ledger |
| 16 | Paused certificate requests stay blocked while previous work remains accessible | 1 | 1 | BEFORE pause implementation inspected; AFTER existing pause regression run with `/plusx` in disposable test runtime |
| 17 | Android distribution remains withdrawn, GET/HEAD return 410 | 1 | 1 | BEFORE unchanged download router inspected; AFTER new router integration test |
| 18 | Physical device offline admission/reconnect and QR scan journey accepted | 0 | 0 | Not run; Node/ASGI/HTTP evidence does not establish this |
| 19 | External delivery provider accepts and delivers real messages | 0 | 0 | Unproven; no provider activated or called |

**Before: 5/19 = 26.32%. After: 17/19 = 89.47%. Change: +12 criteria,
+63.16 percentage points.** This is a mixed local verification/safety-control
coverage score, not an E2E completion percentage. **Full device/provider E2E
verified here: 0/19 = 0%.** The real HTTP retry test is explicitly a narrower
server integration test. Certificate new requests remain **PAUSED**; Android APK
remains **WITHDRAWN pending security review**. Neither issuance nor APK usability
is counted as an available journey.

## Implementation

- `app/core/settings.py`: validated optional `PUBLIC_PATH_PREFIX`, separate
  `public_base_url`. `PUBLIC_ORIGIN` remains an origin for security checks.
- `app/server.py`, `app/api/self_certificate_routes.py`: generated URLs use that
  base. Origin/CSRF validation retains the origin without the path. No feature
  flags, certificate acceptance gates or provider behavior changed.
- `compose.development.yaml`: candidate configuration sets `/plusx`. This file
  was validated but not applied to the running service.
- `ops/prepare_development_web.py`: fixed-prefix development adapter handles
  platform sharing, scanner URL pattern, IndexedDB and media-cache names.
- `web/guest.mjs`: QR URL origin must match. Bare canonical guest numbers still
  work; QR parsing does not grant admission or replace server checks.
- `web/offline.mjs`: only public media enters prepared cache; root media paths
  are mapped, external/sibling/API URLs and redirected responses excluded.
- `web/sw.js`: shell version advanced, request interception restricted to mount,
  fallback restricted to its media cache, existing namespace cleanup retained.
- `tests/test_journey_boundaries.py`, `tests/journey_boundaries.mjs`: new root and
  mounted link integration, settings rejection, Android denial, transformed
  worker/scanner and offline-media preparation tests.

## Verification actually performed

Use `/tmp/plusx-brand-tests/bin/python` for the Python commands below.

1. `python -m pytest -q tests/test_journey_boundaries.py` on baseline source:
   **10 failed, 1 passed**, expected regression evidence. Initial collection
   attempt failed because FastAPI was absent; it was not a test pass.
2. Baseline `python -m pytest -q tests/test_admission_gate_integration.py
   tests/test_admission_http_ack.py tests/test_guest_frontend_security.py
   tests/test_device_admission_scope.py`: **28 passed**.
3. Final `python -m pytest -q tests/test_journey_boundaries.py
   tests/test_development_web.py tests/test_admission_gate_integration.py
   tests/test_admission_http_ack.py tests/test_guest_frontend_security.py
   tests/test_device_admission_scope.py tests/test_linux_standalone_contract.py`:
   **56 passed**. This run includes four transformed Node boundary cases and
   the existing 11-case scanner wrapper. Android case was added afterwards and
   run separately; no application source changed afterwards.
4. `python -m pytest -q tests/test_journey_boundaries.py::test_android_remains_withdrawn`:
   **1 passed**, including both withdrawn APK aliases, GET and HEAD.
5. `PUBLIC_PATH_PREFIX=/plusx python -m pytest -q
   tests/test_self_certificate_http.py::test_pause_revocation_flags_keep_old_receive_and_finish_registered_job`:
   **1 passed**, no skip. Synthetic isolated certificate fixture only; no live
   certificate flags or records touched.
6. `npm ci --prefix tests/offline-runtime`, then
   `node --experimental-global-customevent --experimental-vm-modules --test
   tests/test_offline_runtime.mjs tests/admission_resilience.mjs`: **18 passed**.
   Node 18 needs the CustomEvent flag. These cover receipt retention, duplicate
   recovery, denied-device cleanup, re-pairing races, and desk retry identity.
7. `node --check` for every JS/MJS file in original and temporary transformed
   web trees; both manifests parsed as JSON. Compose `config --quiet` and
   `git diff --check` passed. Exact count is in the companion JSON.

Final Python total across the three final invocations: **58 passed, 0 skipped**.
Separate Node suite: **18 passed**; embedded Node cases are not added to the
Python count. Python emitted the existing Starlette/httpx deprecation warning.
The venv was extended with `requirements.txt` and httpx. An initial attempt to
mix the hash-locked bootstrap requirement and an unpinned httpx failed pip's
hash requirement; no repo dependency pins were changed. Test reruns followed
source/test changes or the explicitly requested before/after verification.

Not run: full repository suite, PostgreSQL acceptance, container image build,
browser smoke (not requested), actual service-worker installation/restart,
physical camera/Android acceptance, provider delivery, production or hosted
GitHub gates. Nothing here substitutes for those gates.

## Preservation, deployment and handoff

Existing untracked `deploy/evidence/plusx-branding-20261118.md` is preserved,
not staged, not deleted. SHA-256:
`14e895cbb925c82afc39865038235e3b3fd09bd79a672ee78978a911269131ce`.
No external snapshot was adopted. No secrets were read or printed, credentials
rotated, deployment restarted, migrations applied to a live database, or volumes
changed. Tests use disposable databases/servers and synthetic identities.

No push, PR, label, workflow, merge or deployment: no assigned account publisher
with verified coordinator lease exists in this session. The local commit is the
handoff candidate. Existing deployment URL from preserved evidence:
https://5.189.157.131/plusx/ — **unchanged and not reaccepted by this task**.
No one-time login was created or needed; stored credentials remain private.

Before a rollout, reconcile pending work in the old `pulsex-pilot-02` database
under the correct application/account authority. The new isolated namespace does
not import or erase it; it will not automatically expose those old pending rows.
This avoids silently mixing apps but requires an explicit operator migration or
sync plan. Likewise old media caches are not deleted. Mount isolation is not
per-tenant or per-account storage isolation. Test actual browser update/offline
behavior and device pairing before relying on it in the field.

Frontend remains a fixed `/plusx` image adapter, not a general multi-prefix
frontend. Backend prefix is trusted configuration, never inferred from incoming
forwarded headers. Deploy the adapter and matching backend setting together in a
reviewed build. Rollback is the previous app image/config without deleting any
browser storage or server volumes. This task itself needs no deployment rollback.
Historical deployment evidence and `PLUSX_DEVELOPMENT_ACCESS.md` describe the
currently running image; this report describes the un-deployed candidate only.
