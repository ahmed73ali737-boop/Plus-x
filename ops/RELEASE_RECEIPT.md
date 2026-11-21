# Opt-in release receipt and runtime guard

This candidate adds a separate guard after archive validation. It neither replaces
nor reruns `deployment_provenance.py` from the prior candidate. Existing Compose,
Dockerfiles and application source are unchanged. It never builds, pulls, starts,
stops, migrates, publishes, or generates deployment credentials. No Compose
fallback to a host directory or default revision is accepted by its recipe check.

Run only with genuine evidence produced by an approved isolated builder:

```sh
python3 ops/release_receipt.py \
  --source-root /project/plusx --source-sha <full-reviewed-source-commit> \
  --manifest /private/validated-inputs.json --archive /private/validated-context.tar \
  --receipt /private/build-receipt.json --signature /private/build-receipt.sig \
  --public-key /private/approved-builder-public.pem \
  --trusted-key-sha256 <independently-approved-public-PEM-file-hash> \
  --container-id <full-running-container-ID>
```

All inputs are mandatory. Receipt authentication uses an OpenSSL SHA-256 detached
signature over the exact receipt bytes. The public key fingerprint MUST be approved
independently of the receipt and candidate artifacts by the release coordinator.
Computing a fingerprint from an untrusted adjacent key does not establish trust.
The guard creates no production signing key or attestation. Test keys are ephemeral,
synthetic fixtures and never release trust anchors. Signature verification failure
prevents all Docker inspection. Errors emit no receipt values or third-party text.

The versioned `plusx-release-receipt/v1` schema is exercised in the focused fixture.
The approved builder's signature attests to all of the following, not merely an
operator's proposed build plan:

- Exact source, manifest bytes, archive bytes, Dockerfile, base references and
  dependency lock contents. The archive is rehashed without extraction; duplicate,
  missing, unsafe, nonregular, modified and unexpected members are rejected.
- Exact `build_argv` returned by `recipe(source)`: full source build argument,
  `linux/amd64`, network disabled, no pull, no cache, explicit Dockerfile, and stdin
  archive context (`-`). No directory context, extra arguments, build environment,
  secret mounts or SSH forwarding. This is a deterministic invocation contract,
  not a claim that Docker output is bit-for-bit reproducible.
- Builder binary hash, authenticated base-origin receipt hashes and platform,
  successful offline hash-verified dependency installation receipt hash, and build
  log hash. These hashes reference retained audit material; the signature makes
  the approved builder accountable for authenticating that material. The guard
  does not independently validate vendor signatures or reconstruct the build.
- Registry manifest reference and distinct image config digest, plus a different
  immutable rollback image and its approved receipt hash. A label alone is never
  accepted. Both images must already exist locally and match Docker image inspect.

The previous archive has source and dependency declarations, not an authenticated
offline dependency closure or successful build. Its development Dockerfile uses
pip installation. With network disabled, missing cached wheels fail the build.
**Do not run this recipe against the current inputs.** An approved, fully archived
offline dependency closure and any necessary separately reviewed recipe change,
authenticated bases, approved builder key, genuine build receipt and immutable
rollback evidence are prerequisites. Never substitute invented hashes or labels.
Current receipt absence is an expected blocker, not a request to build for proof.
The archived source must equal the explicitly supplied reviewed source and the
clean source checkout before and after validation; there is no SHA default.

Runtime inspection uses a narrow Docker formatting projection. It never retrieves
secret environment values, complete inspect documents, command text, or health
logs. It verifies image identity/revision, running state, non-root user, no added
capabilities, no privilege, fixed network, read-only root filesystem, the existing
`plusx-development_plusx_development_data` volume mounted only at `/app/data`,
public prefix/origin, fixed readiness command and direct application command.
The health tool's existing internal route is `/api/health/ready`; public proxy
transport is `/plusx/api/health/ready`. Entrypoint must be empty. A second identical
projection detects container restarts/configuration changes during inspection.
This policy deliberately rejects the current writable-root/migration-wrapper
runtime. It does not alter it or authorize changing its startup behavior.

Exit 0 means signed receipt and the inspected runtime subset agree. It **always**
reports promotion NOT_AUTHORIZED and G1 UNVERIFIED: secret configuration,
volume contents, database compatibility, complete effective runtime configuration,
application acceptance and required hosted gates remain independent checks.
Exit 2 means blocked. Arbitrary direct Docker/Compose invocations can bypass this
opt-in tool; it is not a host-wide enforcement mechanism or a promotion command.

Tests (standard library plus installed OpenSSL; no network/Docker in fixtures):
`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s ops/tests -p test_release_receipt.py`.

Rollback: retain private proof and abandon this isolated candidate if rejected.
No runtime rollback is required because this work changes no deployed state.
Actual future promotion still requires a separately verified immutable rollback
image and authorization. Do not remove volumes, reset dirty trees or touch main.
