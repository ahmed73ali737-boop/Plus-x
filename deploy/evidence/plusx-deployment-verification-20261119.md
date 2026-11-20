# PlusX deployment verification — 19 November 2026

Verified UTC: 2026-11-19T15:35:59.150749+00:00
Deployment: https://5.189.157.131/plusx/
Admin URL: https://5.189.157.131/plusx/admin
Source: `/project/plusx`, commit `0d88259baccdcdf0cdb3a1dc992df1bee70b53ad`.

## Outcome and repair

Deployment verification passed. The existing app image was built from
`efd4b1285ac9c6fd87f56930f014dd1653337262` and lacked the current
`PUBLIC_PATH_PREFIX=/plusx` environment setting. Rebuilt the checked-in source and
recreated only `plusx-development-app-1` with the existing development Compose
configuration. No source or configuration edits were needed; the repair applied
configuration and source already present in the repository.

Current image: `sha256:75aa89422fea6626b036039b5867de72f09d7e53592fb29990903ae833b1ec33`.
Previous image retained for rollback:
`sha256:95202bfcb6c74ef41e43747ab78068a94fc6e73ffc4830686d9f66e03d509d2c`.
No database migration files changed between the two source revisions.

## Verification and evidence

- `git diff --check`: passed; tracked worktree initially clean. Existing untracked
  `deploy/evidence/plusx-branding-20261118.md` preserved.
- `python3 tools/asset-control/asset_control.py verify`: source-verified,
  two assets, no findings. This verifies registered assets only.
- `docker compose -f compose.development.yaml config --quiet`: passed.
- `PULSEX_SOURCE_SHA=$(git rev-parse HEAD) docker compose -f compose.development.yaml build app`:
  passed, including hash-pinned dependencies and image dependency checks.
- `PULSEX_SOURCE_SHA=$(git rev-parse HEAD) docker compose -f compose.development.yaml up -d --no-deps --no-build --wait app`:
  passed. App and PostgreSQL both healthy, restart count zero.
- SHA-256 comparisons of 269 deployed files against local source passed, applying
  `ops/prepare_development_web.py` to a temporary web copy before comparison.
  Compared app, web, templates, tools, ops, launcher, version, build evidence and
  the three installed dependency lock files. Image revision and readiness build
  identify the current source commit.
- Runtime `PUBLIC_ORIGIN=https://5.189.157.131` and `PUBLIC_PATH_PREFIX=/plusx`
  confirmed. App binds `127.0.0.1:14310`; PostgreSQL has no published host port.
- Trusted HTTPS GET `/plusx/`, `/plusx/admin`, `/plusx/api/health/ready`: HTTP 200.
  No TLS bypass used. These are HTTP deployment checks, not browser smoke tests.
- Readiness: PostgreSQL, schema tables and critical columns current, 22/22
  migrations current, no missing migrations or checksum mismatches; version 1.0.1.
- `/usr/sbin/nginx -t`: passed before and after deployment. Nginx active.
  Existing shared routes include `ops/plusx-development.nginx.conf`; route strips
  `/plusx/` upstream and scopes cookies and service-worker permission to `/plusx/`.
- All previously running unrelated container IDs remain running. PostgreSQL
  container ID is unchanged. Existing PlusX data and PostgreSQL named volumes
  retained. No shared routing, certificate configuration or unrelated service changed.

## Direct-IP TLS and Certbot

`openssl s_client -connect 5.189.157.131:443 -verify_ip 5.189.157.131 -verify_return_error`
returned Verification OK and verify return code 0. Standard HTTPS requests also
passed system trust verification. Certificate issuer: Let's Encrypt YE1.
SAN: IP Address `5.189.157.131`.
Validity: 2026-11-18 16:59:31 through 2026-11-25 08:59:30 GMT.
SHA-256 fingerprint:
`34:77:AA:63:05:01:EC:B9:59:9D:99:34:B4:1C:DC:DE:13:59:F9:56:5B:1B:2C:91:80:39:D7:9A:F2:D0:95:35`.

Nginx's direct-IP listener uses `/etc/letsencrypt/live/5.189.157.131/fullchain.pem`.
Certbot 5.10.0 at `/opt/certbot-venv/bin/certbot` manages the IP lineage using the
production Let's Encrypt ACME directory, shortlived profile and HTTP webroot
`/var/www/acme`. Port 80 serves the ACME challenge path. Renewal configuration
includes nginx reload; the IP deploy hook validates nginx before reloading.
`certbot.timer` is enabled and active; its service override uses that newer
Certbot binary. Latest service result success, exit status 0; next scheduled
activation observed at 2026-11-19 20:06:44 UTC. No renewal or issuance forced:
the current certificate is valid. Future issuance was not simulated.

PlusX URL, origin, verified certificate and routing use the literal IP, with no
sslip dependency. A preexisting separate sslip virtual host/lineage remains
untouched to preserve other host services; it was not used for this verification.

## Private administrator login

Read credentials only from `/project/login/plusx.md`, without printing them or
passing them in process arguments. Using verified HTTPS and an in-memory cookie
jar: POST `/plusx/api/auth/login` 200; GET `/plusx/api/auth/me` 200; identity,
recorded platform role and scope matched. Session cookie Secure, HttpOnly and
path `/plusx/`. Existing account does not require password change.
POST logout with CSRF 200; subsequent identity request 401.

Atomically updated the existing private file's URL and verification metadata,
preserving all credentials and other account fields. File remains root-owned,
mode 0600. No password rotation, account creation or new one-time credentials.
No credentials, tokens, cookie values or API keys are included in this report.
Login verification time: 2026-11-19T15:34:49.048185+00:00.

## Scope, limitations and rollback

This remains the documented development deployment (`PULSEX_ENV=local`), not
production acceptance. Readiness reports new application certificate requests
paused (`CERTIFICATE_REQUESTS_PAUSED`, optional capability); this is unrelated
to HTTPS and was preserved. No core feature tests, browser smoke tests, full
suite, production acceptance gates, hosted CI, push or merge were performed.
No external providers activated. The PATH `python` command is unavailable;
verification used host `python3` and the image's Python 3.12.

For rollback, use the retained previous app image with the previous Compose
configuration (omit `PUBLIC_PATH_PREFIX`), recreating only the app with
`--no-deps --no-build`; never remove volumes or reset the database. Preserve
shared nginx and certificate configuration. This task neither exercised rollback
nor claimed feature acceptance for the current source.
