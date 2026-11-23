# Plusx deployment evidence

Final job status: BLOCKED — production release acceptance NOT VERIFIED.
Verified UTC: 2026-11-19T21:33:50.286013+00:00
URL: https://5.189.157.131/plusx/

## Git and preservation
Repository: https://github.com/ahmed73ali737-boop/Plus-x
Worktree: /project/plusx; branch fix/user-journey-boundaries-20261119.
Deployed SHA: 0d88259baccdcdf0cdb3a1dc992df1bee70b53ad
Fetched origin/main: 26be494d09c93deb6d632e3f552f6141f47481f1
`git fetch origin main` succeeded; `git merge --ff-only origin/main` returned Already up to date.
Latest main is contained in HEAD; HEAD is two commits ahead, not identical to origin/main.
Both local commits were preserved. No reset, clean, checkout, push, PR or hosted CI was performed.
Initial untracked evidence hashes are in before.json and all remain unchanged.
Other existing worktree remained untouched. Tracked source remained unchanged.

## Build and deployment
`git diff --check`: exit 0.
`python3 tools/asset-control/asset_control.py verify`: source-verified, 2 assets, no findings; not runtime or production acceptance.
`docker compose -f compose.development.yaml config --quiet`: exit 0.
`PULSEX_SOURCE_SHA=<deployed SHA> docker compose -f compose.development.yaml build app`: exit 0; build.log.
`PULSEX_SOURCE_SHA=<deployed SHA> docker compose -f compose.development.yaml up -d --no-deps --no-build --force-recreate --wait app`: exit 0; redeploy.log.
Only Plusx app recreated. Existing named data volumes retained; PostgreSQL and unrelated containers were not restarted (IDs and start times compared).
Image: sha256:79dd42d70fd62d540ee8b0d73a40fd35bb011a90df50b6d236e20be30edaa6e3; OCI revision matches deployed SHA.
App and PostgreSQL healthy, zero restarts. Existing loopback app binding 127.0.0.1:14310 retained.
Previous app image retained: sha256:75aa89422fea6626b036039b5867de72f09d7e53592fb29990903ae833b1ec33.
Rollback can restore that image and recreate only app with --no-deps --no-build; do not remove volumes. Rollback NOT VERIFIED.

## HTTP, nginx and TLS
Curl without TLS bypass: /plusx returns 308; /plusx/, /plusx/admin and /plusx/api/health/ready return 200, TLS verification result 0.
Internal /, /admin and /api/health/ready return 200. See verification.json and readiness.json.
nginx -t passed. Shared nginx, other routes and certificates unchanged; no nginx restart/reload required.
OpenSSL verified chain and IP identity with -verify_ip 5.189.157.131 -verify_return_error: return code 0.
Publicly trusted Let's Encrypt YE1 certificate has IP SAN 5.189.157.131, valid November 18–25, 2026; see tls.txt.
A valid public IP certificate already exists in this environment; no issuance or renewal needed or attempted.
Certbot 5.10.0 is installed; certbot.timer active. Future renewal NOT VERIFIED. No sslip.io use.

## Administrator credential rotation
Existing platform administrator password rotated through authenticated HTTPS /api/auth/password (200).
Fresh login and /api/auth/me returned 200 and verified platform role and platform scope.
Logout returned 200; subsequent identity request returned 401.
Session cookie Secure, HttpOnly, path /plusx/. See login.json.
Credentials saved atomically in /project/login/plusx.md, mode 0600; directory mode 0700.
Previous credential file preserved privately in /project/login/plusx-before-20261119T213324Z.md; its former platform password is invalidated.
Other account entries preserved. Credentials are retrievable by authorized root SSH/SFTP access to the VPS; no public download route was created.
No password, session, CSRF token or API key is included in this report.

## Concrete blocker and limits
Current deployment remains PULSEX_ENV=local using compose.development.yaml.
Actual production gate exits 2. Failed checks: multi_worker_configured, bootstrap_admin_email_configured, native_postgres_accepted, load_accepted, security_accepted, field_offline_accepted.
Production acceptance flags cannot truthfully be enabled without the corresponding evidence. Load, security, native PostgreSQL acceptance and field/offline acceptance are NOT VERIFIED by this deployment task.
The requested scope prohibits core-feature work/tests and browser smoke tests; none were performed.
No provider activation, other-project changes, GitHub publication or billing changes.
Production mode was not enabled and production readiness is not claimed. Everything else requested was executed and verified within this scope.
