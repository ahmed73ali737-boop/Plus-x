# Locked dependency profiles

Normal setup installs committed locks; it never regenerates them or selects the latest dependencies.
All direct and transitive packages use exact versions and distribution SHA256 hashes. Installation
uses `--require-hashes --only-binary=:all:`. Runtime source distributions are not built implicitly.

| Profile | Contents |
| --- | --- |
| `runtime` (`local` alias) | Application, SQLite development support, packaged IANA time zones |
| `postgres` | Runtime plus HTTP client and PostgreSQL binary adapter |
| `qa` | Runtime plus pytest, coverage, browser test driver and dependency audit tools |
| `qa-postgres` | QA plus PostgreSQL adapter |
| `observability` | Runtime plus the optional OpenTelemetry HTTP/protobuf exporter |
| `postgres-observability` | PostgreSQL runtime plus that optional exporter |

`bootstrap.txt` pins the pip installer separately. Production Docker installs **only** bootstrap and
postgres locks. Playwright, its browser downloads, pytest and other QA packages are absent from that
profile. Optional observability is explicit; the existing shared `requirements-observability.txt`
source-lock bytes are preserved.

The final installer pin is pip 26.2.1, matching the actual baseline Windows CI job 118264234748.
The older local QA environment used pip 25.0.1; its initial clean-build evidence is retained as
attempt 01 and does not describe the final locks.

```sh
python -m tools.prepare_runtime --profile qa-postgres
python -m tools.prepare_runtime --profile qa-postgres --check --strict-profile
python tools/verify_reproducible_runtime.py --profile qa --output qa/repro/report.json
```

Use `--venv /absolute/path/to/new/environment` for a separate environment. Foreign environments are
never overwritten, and preparation never starts the application. Existing environments may contain
additional development tools; `--strict-profile` rejects those additions for clean-build acceptance.
The read-only check validates exact transitive versions, `pip check`, native imports, and `Asia/Aden`
after clearing all system timezone search paths. It checks pip's pinned version too.

Locks are universal for the existing Python 3.11–3.13 contract. Native acceptance targets are
Python 3.12 Linux x86_64/ARM64 and Python 3.13 Windows x64. Successful resolution or compatible-wheel
metadata is not evidence of native Windows/ARM64 execution; those jobs must run separately.
`verify_reproducible_runtime.py` creates two fresh environments on its current platform, compares
full inventories and lock identities, and saves both installation logs even when a build fails.

## Review and regeneration

1. Review changes to direct input files and `locks/constraints.txt`; do not silently upgrade packages.
2. Run `python tools/lock_dependency_profiles.py` with the recorded **uv 0.12.23** resolver.
3. Review every changed version/hash and run clean-build acceptance on each supported target.
4. Preserve `locks/profiles.json`, which records input/lock SHA256 values and the source index.

`constraints.txt` is the complete pinned resolution shared by profiles; it is **not** an application
installation profile. Existing direct versions and previously observed transitive versions were
retained. The prior coverage and psutil ranges resolve to 7.16.2 and 7.2.2 respectively. All wheel
hashes returned by the package index are retained, permitting matching platform-specific wheels.
Package release metadata is available at `https://pypi.org/pypi/<name>/<version>/json`.

Docker base, PostgreSQL and Caddy references use verified multiarchitecture OCI index digests.
`ops/container-image-lock.json` records the exact registry sources and platform manifest digests.
Update those intentionally after review; never replace a recorded digest with an unverified value.

For a manual image build, pass the reviewed source commit through `--build-arg PULSEX_SOURCE_SHA=<git-sha>`
or set `PULSEX_SOURCE_SHA` before `docker compose build`. The image records the OCI revision label and
the existing application build identity as `git-<git-sha>`. The default is `git-unrecorded`, never a
fabricated commit. This labels a build; it does not deploy or certify the source as a release.

Security update 2026-10-21: Pillow is deliberately pinned to 13.0.0 and certifi to
2026.10.19 after the CI dependency audit reported advisories in the previous
versions. All seven profiles were regenerated with the same uv 0.12.23 resolver;
reviewed version comparisons show no other package version changes. The local
strict audit of the QA/PostgreSQL and installer locks reported zero known
vulnerabilities. Clean Windows/Linux and native acceptance remain CI gates.

Portable certificate rendering adds arabic-reshaper 3.0.1 and python-bidi 0.6.12
to the runtime profiles. Pillow wheels without native RAQM use these to shape
Arabic and apply Unicode BiDi before drawing; native RAQM stays preferred when
available. Both native and forced-portable paths are covered by certificate
journey tests; Windows CI also runs an early PNG/PDF export probe.
