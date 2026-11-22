# Deployment input provenance

Use `deployment_provenance.py` before a separately authorized image build. It
requires the full checked-out Git commit and a clean tree. It checks every tracked
file's bytes and executable mode against Git, rejecting symlinks/submodules. It
packages committed Docker COPY inputs plus deployment configuration and existing
dependency declarations into a deterministic tar (ordered files, fixed timestamps,
UID/GID and Git modes). Declared CRLF checkout conversions are accepted only
when canonical LF bytes match the committed blob exactly. Ignored files never enter this context, even inside COPY
directories. No dependency restore or Docker build is performed.

```sh
python3 ops/deployment_provenance.py --root "$PWD" \
  --source-sha "$(git rev-parse HEAD)" --profile development \
  --context-tar /private/new-context.tar > /private/input-proof.json
```

Use a private output directory and umask 077. The archive is exclusively created
with mode 0600. This archive, not the ambient checkout directory, is the intended
context for a future authorized `docker build -f ops/Dockerfile.development
--build-arg PULSEX_SOURCE_SHA=<full-sha> - < /private/new-context.tar`. Production
uses `--profile production` and `ops/Dockerfile`. Do not build or deploy merely to
obtain a green result. Existing Compose entrypoints are unchanged and do not
automatically enforce this offline packaging step.

The manifest fingerprints the context, configuration, each input and each lock
consumed by pip. The supported simple COPY/FROM/pip syntax fails closed when
inputs are missing, base images are mutable/unlisted or consumed locks lack exact
versions and hashes. It does not invent or regenerate locks. Lock syntax checks
are not a dependency resolution, wheel availability or successful installation
claim. Future Dockerfile syntax changes require extending and reviewing coverage.

Add `--container-id <full-64-character-ID>` for a read-only Docker inspection.
Only container/image IDs, repository digests, a validated revision SHA, running
state and mount count are returned. Environment, commands, health logs and other
labels are omitted. All errors omit exception text. No supplied evidence JSON is
trusted. Runtime inspection always exits 2 with **gate1 UNVERIFIED**, even when
revision labels match: there is no authenticated binding between source/context,
built image, installed dependencies, writable filesystem and effective runtime
configuration. An image content ID and a claimed revision alone cannot prove it.
Exit 0 without runtime inspection means input packaging succeeded only.

Before artifact acceptance, a separately authorized isolated build must record
its exact context hash, build parameters/platform/toolchain and resulting image
content ID, with trusted build evidence. Runtime reconciliation must then account
for writable layers, mounts and effective configuration without exposing secrets.
No historical acceptance can be applied to a new commit.

Tests: `python3 -m unittest discover -s ops/tests -p test_deployment_provenance.py`.
Rollback: discard the isolated candidate branch/worktree after retaining its
proof. No live state is modified by these tools, so no runtime rollback is needed.

The follow-on [OCI receipt workflow](RELEASE_RECEIPT.md) adds authenticated
manifest/attestation and non-secret runtime-policy binding. Its offline preflight
never authorizes release, and explicitly reports missing evidence. Existing
source packaging alone still cannot establish G1.
