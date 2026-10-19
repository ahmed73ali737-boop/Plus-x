# PostgreSQL architecture safety — PulseX canonical source

Status: diagnostic-only candidate. This source uses SQLite for local pilot and PostgreSQL as the planned production database; PostgreSQL diagnostic scripts MUST NOT run against SQLite.

Added bounded read-only catalog inspection. The dedicated static CI checks source, and the existing Linux/Windows CI remains mandatory.

- Preserve platform/organization/event/participation/guest master identities. Do not split user or guest tables annually by default.
- High-volume `px_guest_checkins`, responses, audit and device events may need measured date-range indexing, aggregation, or partitioning only after query/load profiling.
- Never archive pending offline submissions, idempotency receipts, active guest passes, attendance evidence or access-control records without explicit replay/legal-hold validation.
- `make_engine` currently allows SQLite for local pilot; production configuration must enforce PostgreSQL (`REQUIRE_POSTGRES=true`) and correct secrets/connection pooling.
- `ensure_compat_schema` is a local additive compatibility helper, NOT a substitute for controlled production migrations.
- RPO/RTO, backup restore, signed retention policies and P95/P99 regression are required before production acceptance.

No database mutation or production performance claim is included in this change.