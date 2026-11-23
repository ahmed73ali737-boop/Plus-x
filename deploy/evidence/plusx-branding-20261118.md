# Plus-x branding deployment evidence

Verified UTC: 2026-11-18T20:47:16.833518+00:00
URL: https://5.189.157.131/plusx/
Source commit: efd4b1285ac9c6fd87f56930f014dd1653337262
Branch: branding/arabic-only-20261118
Initial main and fetched origin/main: 26be494d09c93deb6d632e3f552f6141f47481f1.
Initial worktree clean; git fetch origin succeeded; no fast-forward needed.
Only this task appeared in project_status active jobs; no competing Plus-x job found.

## Scope
15 web files: Arabic-only display branding in titles, shell, help and manifest.
Known stored platform title is mapped to Arabic in public frontend memory only.
No database content, backend contracts, identifiers, core features or routes changed.
Existing Compose development configuration and fixed /plusx adapter retained.
This is a development deployment, not production release acceptance.

## Commands and actual results
- `git diff --check`: passed.
- `node --check <each web/*.js and web/*.mjs>` and Python JSON parsing of web JSON/manifest: passed. Final public.mjs syntax rechecked after stored-title adjustment.
- `/tmp/plusx-brand-tests/bin/python -m pytest -q tests/test_development_web.py tests/test_guest_frontend_security.py`: 3 passed on final source. Security wrapper runs 11 Node cases with --experimental-vm-modules.
- `docker compose -f compose.development.yaml config --quiet`: passed.
- `PULSEX_SOURCE_SHA=$(git rev-parse HEAD) docker compose -f compose.development.yaml build app`: passed. Build log: /tmp/plusx-brand-build.log.
- `PULSEX_SOURCE_SHA=$(git rev-parse HEAD) docker compose -f compose.development.yaml up -d --no-deps --no-build --wait app`: passed, app healthy.
- Docker image revision label equals source commit above. All 15 changed files compared byte-for-byte with workspace after applying ops/prepare_development_web.py in a temporary directory: matched.
- `curl -sS -o /tmp/plusx-response -w '%{http_code}' https://5.189.157.131<path>`: /plusx 308; /plusx/, /plusx/admin, /plusx/api/health/ready, /plusx/assets/app.mjs, /plusx/assets/manifest.webmanifest, /plusx/assets/public.mjs all 200. No insecure TLS option used.
- Public/admin HTML and manifest retain Arabic and contain no English Eventna.
- `/usr/sbin/nginx -t`: passed. Existing /var/lib/vps-mcp/nginx/routes.conf includes ops/plusx-development.nginx.conf; /plusx/ proxies to 127.0.0.1:14310 with scoped cookies/service workers. No nginx configuration or unrelated route changed.
- `docker inspect plusx-development-app-1 plusx-development-postgres-1`: both healthy. Existing volumes plusx-development_plusx_development_data and plusx-development_postgres_development_data retained. All previously running unrelated container IDs and PostgreSQL container ID unchanged.

## TLS
- `certbot --version`: 2.9.0; `/opt/certbot-venv/bin/certbot --version`: 5.10.0.
- `certbot certificates`: direct IP certificate valid; existing unrelated hostname certificate not used.
- `openssl s_client -connect 5.189.157.131:443 -verify_ip 5.189.157.131 -verify_return_error </dev/null`: Verification OK; verify return code 0.
- `openssl s_client -connect 5.189.157.131:443 -verify_ip 5.189.157.131 -verify_return_error </dev/null 2>/dev/null | openssl x509 -noout -issuer -dates -ext subjectAltName`: issuer Let's Encrypt YE1; SAN IP Address:5.189.157.131; valid Nov 18 16:59:31 through Nov 25 08:59:30 2026 GMT.
- Enabled certbot.timer uses service override /opt/certbot-venv/bin/certbot -q renew --no-random-sleep-on-renew. Existing valid certificate needed no issuance or renewal. No sslip routing used.

## Login
Existing organizer test account, event-demo scope, retained without rotating any account.
Credentials remain /project/login/plusx.md, mode 0600, outside Git. No new one-time password issued or needed.
Post-deployment curl commands used temporary private payload, cookie jar and CSRF config:
`curl -sS -o <private-response> -w '%{http_code}' -b <private-cookies> -c <private-cookies> -H 'Content-Type: application/json' --data-binary @<private-payload> https://5.189.157.131/plusx/api/auth/login`: 200.
Same curl cookie arguments GET /api/auth/me: 200, expected organizer role matched.
Same curl cookie arguments --config <private-CSRF-config> -X POST /api/auth/logout: 200; subsequent GET /api/auth/me: 401.
Temporary credential-bearing files deleted automatically; no password or session value logged.

## Corrections and limits
Initial system python pytest attempt failed because pytest was absent; isolated /tmp venv installed pytest and passed. Initial direct Node test invocation omitted required experimental VM flag and failed; repository pytest wrapper supplies the correct flag and passed. An initial login assertion incorrectly expected platform role; saved account is organizer, subsequently checked against recorded role and passed. Initial exploratory /api/public/platform returned 404; correct /api/public/site/platform returned 200.
No browser smoke test, full suite, production gate, provider activation, or hosted GitHub checks run.
No push/PR/merge/CI trigger: AGENTS.md requires an explicitly assigned account integration coordinator and verified real lock/lease; none assigned for this task. Conditional branch push omitted; candidate remains local for coordinator handoff.
Existing development prefix limitations documented in PLUSX_DEVELOPMENT_ACCESS.md still apply, including backend-generated absolute links/QRs. No production acceptance claimed.
Rollback: previous app image sha256:395dc66ea38be9188b287a449a40a9a01b306d314d76710d9e8ba2d6cbf34ee9 remains available; retag it as plusx-development-app and recreate only app with --no-deps --no-build. Preserve all volumes and current shared routes.
