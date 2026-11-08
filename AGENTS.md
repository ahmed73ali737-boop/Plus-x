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

<!-- CI-COST-CONTROLS-20261108-V2:BEGIN -->
## CI spending and coordinated publication

- Read the current default-branch `.github/ci-cost-policy.json` before any operation that may trigger paid CI. Follow any explicit grant locator in that policy, including a dedicated `ci-cost-policy` branch if configured; do not guess alternate paths. Use only its implemented, finite admission grants. If the policy, grant, remaining allowance, or coordination ownership cannot be verified, continue authorized local work and defer hosted verification.
- Keep review-only work read-only. This policy does not authorize a review task to write, merge, deploy, dispatch, rerun, or add full-CI labels.
- Work and test locally first. Batch related changes into one reviewable candidate with source SHA, commands, results, scope, and limitations. Subagents use isolated local workspaces and return patches/evidence; they do not independently push remote branches, create/update PRs, trigger workflows, or apply CI-triggering labels/comments.
- One explicitly assigned integration coordinator publishes a batch across the account, after verifying the real coordination lock/lease. A task's root agent is not automatically the account-wide publisher. When ownership is missing or conflicting, hand off the local candidate and continue independent work.
- Before publication, inspect the current source and existing runs/evidence, test the relevant local scope, and use an expected-head update without force-pushing or discarding others' work. Do not publish every small fix separately or manufacture a new SHA to obtain another run.
- Treat push, pull request, merge, dispatch, labels, comments, event changes, branch changes, and manual reruns as potential CI triggers. None bypasses admission. Do not repeat valid evidence for identical source bytes and environment; retries after a diagnosed failure still require a valid remaining grant.
- Preserve all required security, test, acceptance, merge, and release checks. Failed, cancelled, skipped, or unexecuted verification is not a pass. Validate the actual final source; do not transfer evidence from a different source without checking its exact applicability.
- After a grant is exhausted, continue authorized local development and report hosted validation as deferred for cost. Do not borrow another repository's or agent's allowance, self-issue grants, enlarge quotas, or relax a financial limit.
- Paid CI requires a separate finite owner authorization and implemented admission. A public standard-runner exemption is not permission to use paid runner classes, enlarge financial limits, or borrow another project's allowance.
- Preserve automation schedules, enabled states, and environments unless the owner explicitly requests a change. Do not create persistent workers or extra independent publishers. Include this policy in delegated tasks.
- Report actual hosted costs only from billing data; label estimates and never convert run counts or wall-clock duration into asserted charges. Prose instructions alone are not an enforced global spending controller.
<!-- CI-COST-CONTROLS-20261108-V2:END -->
