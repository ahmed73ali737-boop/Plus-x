# PulseX — Enterprise integration and composition (candidate)

This branch extends existing IAM adoption PR #13 without replacing public guest/QR/event functionality.

- The authorization manifest pins G.Authorization as a shared candidate for **protected organizer and event-management paths**.
- Public visitor, vote, gate/QR and offline experiences remain governed by PulseX Event Policy. Guest identity must not be converted into another IAM/KYC master.
- UI360 and negative-case definitions cover organizer, supervisor, kiosk operator and guest terminals; these are source definitions, **not executed tests**.
- No runtime permissions, QRs, database schema, offline logic or deployment is changed in this adoption branch.
- The shared source-only GitHub workflow requires approved cross-private-repository actions access and a read-only `GOVERNANCE_READ_TOKEN`. Failure to provision it is a BLOCK, not a pass.

Before activation: real provider/terminal binding, server auth/role/API checks, offline expiration replay, browser/mobile native SIT, security and field UAT.

## Sprint 2 — protected organizer source integration (2026-10-09)

Added a pure canonical decision port in `app/application/shared_authorization.py`; applied after existing `identify` and `require_scope` for protected event configure and publish endpoints. Public QR, kiosk guest polls and offline event participation remain unaffected by this port. `PULSEX_SHARED_AUTHORIZATION_MODE=Off` default; `Enforce` is refused at startup unless a trusted external provider is injected. The exact-GitHub-blob helper and test source passed 15 isolated local pytest cases (separate evidence file), using a stub for `app.domain.fail`, not a full-app HTTP or production acceptance. Native CI and external provider/role/guest UAT are separate.
