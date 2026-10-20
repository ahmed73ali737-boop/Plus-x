# مصفوفة المراحل 05–08

الخريطة الكاملة للشاشة والدور والصلاحية وAPI والجداول والاختبار والدليل لكل حالة في [السجل الآلي](acceptance-register.json). verified هنا تعني تحققًا محليًا في النطاق المبين؛ لا توجد حالة accepted.

| الحالة | الاختبار أو الإجراء | الوضع | حدود الدليل |
|---|---|---|---|
| P05-T01 | `tests/postgres_upgrade_rehearsal.py` | blocked | PostgreSQL unavailable |
| P05-T02 | `tests/postgres_upgrade_rehearsal.py` | blocked | Transactional DDL and tracker checks prepared; not executed |
| P05-T03 | `tests/test_upgrade_safety.py`, `tests/test_invitations.py` | verified | Linux/SQLite; no automatic conversion tool |
| P05-T04 | `tests/test_guest_frontend_security.mjs` | verified | Node VM contract; not browser IndexedDB acceptance |
| P05-T05 | `tests/test_admission_gate_integration.py`, `tests/postgres_invitations_acceptance.py` | in_progress | SQLite verified; PostgreSQL blocked |
| P05-T06 | `tests/test_device_admission_scope.py`, `tests/test_guest_frontend_security.mjs` | verified | Python/SQLite and Node contracts |
| P05-T07 | `tests/test_device_admission_scope.py`, `tests/test_admission_gate_integration.py` | verified | Controlled local clock tests; no physical clock attestation |
| P05-T08 | `tests/test_upgrade_safety.py`, `tests/postgres_upgrade_rehearsal.py` | in_progress | SQLite restore verified; PostgreSQL/PITR blocked |
| P06-T01 | `tests/test_public_bundle_query_budget.py`, `tests/test_invitations.py` | verified | HTTP/SQLite; preserved authorization |
| P06-T02 | `tests/test_upgrade_safety.py`, `tests/invitations_ui_contract.mjs` | verified | Create-once dates and explicit independent schedule labels |
| P06-T03 | `tests/invitations_ui_contract.mjs` | verified | 28 total DOM cases, not 28 browser journeys |
| P06-T04 | `tests/invitations_ui_contract.mjs`, `tests/test_guest_frontend_security.mjs` | verified | DOM and policy contracts only |
| P06-T05 | `tests/invitations_native_acceptance.py` | blocked | Chromium download unavailable; physical devices not tested |
| P06-T06 | `tests/test_pwa_install_contract.py` | in_progress | All precache assets HTTP/MIME verified; live Service Worker transition blocked |
| P07-T01 | `tests/postgres_invitations_acceptance.py` | in_progress | Native workload not executed here |
| P07-T02 | `tests/exhibition_scale_smoke.py`, `tests/test_public_bundle_query_budget.py` | in_progress | 70 entities/700 reads/20 workers pass; SLO undefined; native PG pending |
| P07-T03 | `tests/test_admission_gate_integration.py`, `tests/postgres_invitations_acceptance.py` | in_progress | SQLite invariants pass; native race acceptance blocked |
| P07-T04 | `tests/test_performance_measurement.py`, `tests/load_profiles.py` | verified | Bounded error categories, receipt counts and SQL row reconciliation |
| P07-T05 | `tests/security_hardening.py`, `tests/test_admission_permissions.py` | in_progress | 13 hardening checks and QA audit 55 packages; runtime lock audit timed out |
| P07-T06 | `tests/test_upgrade_safety.py`, `tests/postgres_upgrade_rehearsal.py` | in_progress | Logical SQLite restore verified; PostgreSQL and restore-time evidence blocked |
| P07-T07 | `tests/test_public_bundle_query_budget.py` | verified | Identical 70-child SELECT count144→5; no production latency/SLO claim |
| P08-T01 | `tools/run_candidate_checks.py` | verified | Single code SHA with source hashes and artifact hashes; external acceptance remains blocked |
| P08-T02 | `tests/test_acceptance_evidence.py`, `tests/test_audit_release_admission.py` | verified | Contract validation; not authenticity proof of field evidence |
| P08-T03 | `tests/runtime_recovery_acceptance.py`, `.github/workflows/upgrade-rehearsal.yml` | blocked | Target runtime unavailable; workflows unexecuted |
| P08-T04 | `docs/acceptance-manifest.example.json` | blocked | No field devices or venue access |
| P08-T05 | `docs/UPGRADE_PASSES_OFFLINE_RUNBOOK_AR.md` | in_progress | Runbook and patch prepared; production acceptance not signed |
| P08-T06 | `docs/acceptance-manifest.example.json` | blocked | Deployment integrations not selected/verified; not silently marked N/A |
