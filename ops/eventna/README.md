# Eventna إيفنتنا on the VPS

> **Operational details live in the private ops store.** This public file
> intentionally uses placeholders. The real server address, SSH user and key,
> administrator account, host paths and shared-edge layout must never be
> committed here.

Canonical public URL: **https://eventna.app/**. Administration:
**https://eventna.app/admin**. `www.eventna.app` and the previous IP-subpath
links (`https://<server-ip>/eventna/`) redirect to the canonical domain while
preserving routes and query parameters. DNS: apex A `<server-ip>`, `www`
CNAME `eventna.app`. The shared Caddy edge manages domain HTTPS certificates.

The application is deployed in explicit test-candidate mode with PostgreSQL,
two workers, persistent storage, and no demo seed. Production acceptance flags
remain unset. The existing administrator account (`<admin-email>`, recorded in
the private ops store) is unchanged by the rename; the rename does not reset
credentials, accounts, events, or guest identity secrets.

## Release layout

SSH: `ssh -i <ssh-key-file> <ssh-user>@<server-ip>` (values in the private ops store)

- `<release-root>/current` points to the active release.
- Each release contains `compose.yaml`, `source/` (an exact Git archive), and
  a private `.env` (location recorded in the private ops store) with the
  database password, guest secret, `BOOTSTRAP_ADMIN_EMAIL`,
  `EVENTNA_RELEASE` image tag and full `EVENTNA_SOURCE_SHA`.
- Compose project `eventna` retains volumes `eventna_postgres_data` and
  `eventna_app_data`. Never use `docker compose down -v`.
- The app joins the shared edge network as `eventna-app`; PostgreSQL is on a
  separate internal network. No additional host ports are needed.
- Add this directory's site blocks to the shared edge Caddyfile
  (`<edge-caddyfile>`); preserve other applications' routes.

Build with `docker compose build`, then start with `docker compose up -d`.
Startup applies existing schema migrations, bootstraps only an empty database,
and runs `tools.rebrand_eventna --apply`. The rebrand changes only default
platform titles starting with the former name. It preserves unpublished
content and custom names, creates a new published version, and records an
audit entry. Repeated runs make no further changes.

## Verification and rollback

```sh
cd <release-root>/current
docker compose ps
docker compose logs --tail=100 app
curl --fail https://eventna.app/api/health/ready
```

Verify public/admin/start pages, login, HTTPS redirects, PWA assets, and the
Android download. Readiness checks PostgreSQL and migration checksums.

Before deployment, save `pg_dump -Fc`, an app-data archive, and the current
Caddyfile in a protected backup directory under `<release-root>/backups/`.
To roll back, use the prior release's image and its saved environment with
`docker compose up -d --no-build`; restore the matching Eventna proxy routing.
For a rollback to the former IP-subpath build, use its `/eventna` adapter and
IP public origin together. Do not overwrite newer unrelated proxy edits.
Database/media backups are point-in-time snapshots, not scheduled backups.

## Naming compatibility

Visible web, PWA and Android branding is Eventna إيفنتنا. Existing `PULSEX_*`
environment variables, `px_*` database tables, API/device headers, SDK import
names and Android package IDs remain compatible with existing integrations.
Historical release evidence retains its original names and hashes. The new
Android preview download is `/downloads/eventna-android-preview.apk`; the old
download route remains an alias. Preview APK signing is not production signing.
