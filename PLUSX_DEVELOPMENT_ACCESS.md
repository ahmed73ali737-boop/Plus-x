# Plus-x development access — 16 November 2026

DEVELOPMENT ONLY. No production acceptance or release gates have been asserted.

- Public page: https://5.189.157.131/plusx/
- Administration: https://5.189.157.131/plusx/admin
- Demo event: https://5.189.157.131/plusx/e/demo
- Tenant pages: `/plusx/e/demo/p/agency-01` and `/plusx/e/demo/p/agency-02`.

## Accounts

| Login name | Supported role | Scope |
| --- | --- | --- |
| admin@pulsex.test | platform | platform |
| organizer@pulsex.test | organizer | event-demo |
| agency01@pulsex.test | agency | agency-01 |
| agency02@pulsex.test | agency | agency-02 |

At the admin login select **استخدام البريد للحسابات القديمة** (use email for legacy accounts).
Unique random temporary passwords are in `/project/plusx/secrets.development/accounts.json`
(mode 600, ignored by Git). All accounts require password change at first login.
No passwords are included in this report. These are synthetic development tenants;
no invented production roles or external provider accounts were activated.
The supported seed creates organization ownership and organizer event-manager assignment.

## Deployment and preservation

Initial main and fetched origin/main both pointed to
`706884d522cdbd39f546188611e1b555ceddd065`, ahead/behind 0/0.
No pull was needed. Work is on `deployment/plusx-development-20261116`.
No push, merge, workflow dispatch, or GitHub CI trigger was performed.

The preexisting untracked Compose file was reviewed and privately preserved at
`secrets.development/compose.development.original.yaml` before replacing its embedded
secret and SQLite configuration. The existing rootless `plusx-default-app-1`
deployment and all its data/volumes remain untouched; it is no longer the public
Plus-x route target. New deployment uses system Docker project `plusx-development`,
PostgreSQL 18, and its own PostgreSQL/data volumes. No existing database was migrated,
cleared, or converted. All 22 repository migrations apply to the fresh development DB.

Runtime secrets: `secrets.development/runtime.env` (600). Guest ID secret was regenerated;
the old embedded value is never used by this deployment. Secret directory is 700,
Git-ignored and excluded from Docker build context. Initial PostgreSQL backup:
`secrets.development/development-initial.dump` (600).
Credentials also remain in the protected app-data volume for bootstrap recovery.

The app listens only at `127.0.0.1:14310`; PostgreSQL has no published host port.
`PULSEX_ENV=local`, `REQUIRE_POSTGRES=false`, and `SEED_DEMO=false` are deliberate:
REQUIRE_POSTGRES also enables production gates in this application. DATABASE_URL
explicitly selects PostgreSQL. Demo seeding was a separate empty-database-only action.

Only the existing `/plusx` block in `/var/lib/vps-mcp/nginx/routes.conf` was changed.
Its original contents are privately saved in `secrets.development/host-routes.original.conf`.
The reviewed block is `ops/plusx-development.nginx.conf`. Nginx strips the prefix,
scopes cookies/service workers, and uses the existing shared HTTPS listener.
A separate development image adapts frontend paths; root deployment assets stay unchanged.

Existing Let's Encrypt IP certificate verified with normal TLS trust, valid through
21 November 2026 14:52:55 UTC. Host `/opt/certbot-venv/bin/certbot` is 5.10.0 with
short-lived IP certificate support; the older PATH certbot is 2.9.0. The enabled host
renewal timer uses the newer binary. No sslip hostname or new certificate issuance
was used, and shared certificate/renewal configuration was not changed.

## Commands and verification

- `git status --short --branch`, `git fetch origin main`,
  `git rev-list --left-right --count HEAD...origin/main`: inspected, 0/0.
- `docker compose -f compose.development.yaml config --quiet`: passed.
- `docker compose -f compose.development.yaml up -d --build --wait`: development build/start.
- `docker compose -f compose.development.yaml exec -T app python -m tools.seed_development`:
  four supported accounts created, empty DB only.
- Container readiness and PostgreSQL `select version()`: PostgreSQL 18.6.
- `/usr/sbin/nginx -t` and `systemctl reload nginx`: passed.
- External HTTPS `/plusx/`, `/plusx/admin`, and `/plusx/api/health/ready`:
  HTTP 200; readiness confirms PostgreSQL and all 22 expected migration checksums.
- Disposable Python 3.12 image: `pytest -q tests/test_production_bootstrap.py
  tests/test_shared_organizer_authorization.py`: **17 passed**, one upstream
  FastAPI/Starlette test-client deprecation warning.
- `pytest -q tests/test_development_web.py`: prefix, external URL preservation,
  route parsing, runtime media, manifest, and isolated service-worker cache: **2 passed**.
- Headless Chromium: public, admin, event, tenant render; zero page errors or failed
  requests. All four accounts passed API login/me and actual browser form login,
  mandatory password-change screen, secure HTTP-only `/plusx/` session cookies.
- `python3 tools/asset-control/asset_control.py verify`: source-verified, no findings;
  this is source evidence only, not production acceptance.
- `git diff --check`: passed.

Final image adapter SHA-256 was compared to the local source and matched. The image
build label is `git-706884d-development` (upstream plus the local deployment changes).

Private evidence logs and verification scripts are in `secrets.development/`.
No plaintext passwords were printed. A shell PATH issue (`nginx` unavailable without
absolute path) was corrected using `/usr/sbin/nginx`; the first external probe reached
old SQLite before reload and was not accepted as PostgreSQL evidence.

## Limits and rollback

Production gates, full test suite, hosted GitHub gates, load tests, offline field
acceptance, restore drills, certificate delivery, and provider integrations were not run.
Certificate requests remain paused. Backend-generated absolute links/QRs still assume
an origin-root deployment; those journeys are outside this development prefix acceptance
and must be adapted before relying on shared links/QR delivery. Browser offline storage
uses the application's existing names; cross-app offline storage isolation is not accepted.
The development frontend adapter is fixed to `/plusx`, not a general prefix feature.
The host route file is also managed by VPS MCP; a future MCP publication may regenerate
it. Reconcile its Plus-x target with the reviewed development block before publishing
through MCP. The preserved rootless deployment was not republished.

To roll back routing, review the saved original host route file against current shared
routes, restore only the Plus-x block, run `/usr/sbin/nginx -t`, and reload nginx.
Stop only this development Compose project if needed; never use `down --volumes`.
Keep both original and new volumes and the database backup. The original Compose backup
contains a retired embedded secret and must remain private, never reactivated as-is.
