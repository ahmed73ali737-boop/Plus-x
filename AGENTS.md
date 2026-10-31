# Repository execution

## System independence — owner decision, 31 October 2026

The owner's current instruction supersedes earlier requirements to keep reusable
implementation only in an external repository. This system owns its local source,
configuration, migrations, build and release. Shared origins are provenance and
optional upgrade sources; never silently refresh a local copy or require a sibling
checkout to run an internal component. Preserve data ownership, tenant isolation,
financial invariants and versioned external business contracts.

Use tools/asset-control/asset_control.py for offline snapshot adoption and integrity.
Record origin commit, local version, file hashes and local modifications. Upgrades
are explicit reviewed changes with relevant tests and rollback planning. Existing
local changes must never be overwritten. A copied source or a passing source check
does not establish build, database, UI, integration or production acceptance.
Historical repositories remain read-only; this decision does not reactivate them.
