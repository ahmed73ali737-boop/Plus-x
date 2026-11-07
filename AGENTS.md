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

## CI cost controls — owner instruction, 7 November 2026

- Run the relevant checks locally before publishing. Report missing prerequisites
  and unrun checks explicitly; local checks do not replace required GitHub gates.
- Batch a complete logical change into one push after local verification. Follow
  this repository's branch and PR delivery rules and check the expected remote
  head before publishing. Avoid diagnostic-only pushes, empty commits to trigger
  CI, and repeated default-branch merges solely to restart checks.
- Re-run unchanged source only for an identified transient infrastructure failure
  or an explicitly requested independent verification. Record the reason and
  affected jobs; diagnose deterministic failures and fix their cause first.
- Where workflows support drafts or a full-CI label, keep iterative development
  in the cheaper stage and request the full stage for the reviewed candidate.
  A changed head still needs its required checks; failed, skipped, cancelled, or
  missing checks never count as successful acceptance.
- Use stable workflow/event/branch-or-PR concurrency groups for automatic
  verification and cancel superseded runs. A run ID or commit SHA must not make
  every automatic run a separate group. Isolate manual verification by run ID;
  preserve serialized, non-cancelling controls for deployment and publication.
- Preserve security schedules, test commands, matrices, permissions, and release
  gates. Cost control must remove redundant execution without weakening coverage
  or authorizing deployment, provider activation, or other external effects.
