# Offline OCI receipt and runtime reconciliation guard

`release_receipt.py` advances input provenance without granting a release or a G1
pass. It never builds, pulls, deploys, publishes, changes containers, or reads
volume contents. **Every invocation exits 2, reports `release_allowed: false`,
`promotion: NOT_AUTHORIZED`, and `gate1: UNVERIFIED`.** Do not invert that exit
status or use a subset result as deployment authorization. Existing Compose
entrypoints are unchanged; this opt-in guard is not host-wide enforcement.

## Provenance of this change

This work starts at source-context candidate
`ac873c85f7c290f1c3063b4e969f30d8d90ac9cf` (main source
`8f24f87b99b8efab02578e60fd6ad29e78797cc2`). It reuses, then hardens, the local
receipt script and tests from `a562dd335b9c3b966b05d79ffdca4c2e2441ba03`.
Both earlier worktrees remain untouched. Version 1 only signed a receipt with
referenced audit hashes; it did not validate actual OCI manifest or attestation
bytes, reject unknown receipt fields, or bind a runtime configuration projection.
Version 2 intentionally rejects v1 receipts. Never manufacture replacement
attestations for existing images.

## Workflow and trust boundary

1. The coordinator independently approves a builder public key and its exact PEM
   SHA-256 fingerprint, reviewed full source SHA, pinned toolchain/platform,
   authenticated digest-pinned bases, complete offline hash-locked dependency
   closure, non-secret build configuration, runtime policy and immutable rollback.
   A fingerprint copied from an adjacent untrusted key is not a trust anchor.
2. Use `deployment_provenance.py` to package the clean reviewed source. A separately
   authorized builder must consume that exact archive, prove dependency install
   closure, retain build logs, and independently reproduce the same OCI manifest
   digest. The current Dockerfile requires pip dependencies; this task has neither
   built it nor established an available offline wheel closure. Do not build to
   obtain a green result. Recipe/toolchain changes require separate review.
3. The genuine builder emits the actual single-platform OCI manifest bytes and a
   custom in-toto Statement v1 using predicate type
   `https://plusx.invalid/provenance/v2` (an identifier, not a network endpoint).
   This is **not** a SLSA certification or a fabricated BuildKit attestation.
   Its subject is exactly `plusx` with the manifest SHA-256. Its predicate binds
   `source_sha`, `context_sha256`, `manifest_sha256`,
   `dependency_install_receipt_sha256`, `builder_binary_sha256`,
   `runtime_config_sha256`, `rollback_receipt_sha256`, and
   `reproduced_manifest_sha256`. The last must equal the subject digest.
4. The approved builder signs the exact bytes of `plusx-release-receipt/v2` with
   an OpenSSL SHA-256 detached signature. The receipt's `attestation_sha256`
   authenticates the exact statement transitively. A hash without a verified
   receipt signature is never sufficient. This verifier generates no signing key,
   build receipt or production attestation. Test keys/claims are synthetic only.
5. Run offline validation with genuine artifacts. It verifies the pinned signature,
   regenerates the manifest/archive from clean Git bytes, checks the recipe and
   locks, verifies attestation bindings, and hashes actual OCI manifest bytes to
   match the digest reference. The OCI config descriptor must match the separate
   image config digest. A mutable tag or revision label is never the binding.
6. Under separate authorization, omit `--offline` and supply the full container ID
   to inspect a narrow non-secret runtime projection and locally available rollback
   image. It checks the signed runtime projection hash, image identity, revision,
   mounts and runtime policy, then rereads the container to detect replacement,
   restarts or configuration changes. The requested ID must equal the observed ID.
7. **Release stays blocked.** A separate authorized release controller must verify
   complete build/material evidence, independent reproducibility, current registry
   and local OCI content, authentic rollback receipt/availability/compatibility,
   full effective configuration via a secret-safe verifier, and fresh runtime
   identity under a deployment lock. It must also enforce all application,
   database, hosted and release gates. This tool neither implements that controller
   nor provides a bypass. No 20% live gate increment follows from these checks.

## Invocation and blocking codes

Use private directories, `umask 077`, and mode 0600 evidence files:

```sh
python3 ops/release_receipt.py --offline \
  --source-root /path/to/clean/reviewed-worktree --source-sha <full-source-SHA> \
  --manifest /private/inputs.json --archive /private/context.tar \
  --receipt /private/build-receipt.json --signature /private/build-receipt.sig \
  --public-key /private/approved-builder-public.pem \
  --trusted-key-sha256 <independently-approved-PEM-hash> \
  --oci-manifest /private/oci-manifest.json --attestation /private/statement.json
```

`python3 ops/release_receipt.py --offline` is a safe prerequisite probe: no Docker,
network, source packaging, or output file writes. It lists `MISSING_*` codes.
Successful offline binding returns `OFFLINE_BINDINGS_VERIFIED` with
`FULL_RELEASE_EVIDENCE_REQUIRED` and `LIVE_RUNTIME_AND_ROLLBACK_NOT_OBSERVED`.
Successful runtime subset comparison returns `SUBSET_VERIFIED` with
`FULL_RELEASE_EVIDENCE_REQUIRED`. Both exit **2**, never release success.

Failures include `SOURCE_DRIFT`, `SOURCE_CONTEXT_MISMATCH`, `CONTEXT_DRIFT`,
`OCI_MANIFEST_MISMATCH`, `OCI_CONFIG_MISMATCH`, `ATTESTATION_MISMATCH`,
`ATTESTATION_BINDING_MISMATCH`, `RECEIPT_FIELDS_NOT_ALLOWED`,
`IMMUTABLE_IMAGE_REQUIRED`, `RUNTIME_CONFIG_MISMATCH`, `ROLLBACK_UNAVAILABLE`,
`RUNTIME_ID_MISMATCH`, `RUNTIME_CHANGED`, and `SIGNATURE_OR_INSPECTION_FAILED`.
Untrusted exception text, paths, receipt values and subprocess output are never
printed. Unexpected errors become `EVIDENCE_VALIDATION_FAILED`.

## Non-secret schema and remaining limits

`RECEIPT_FIELDS` is an exact top-level allowlist; image and base-material records
also reject additional fields. Build environment, secret mounts and SSH mounts
must be empty. Never insert raw environment, credentials, secret hashes, volume
contents, command text, arbitrary annotations or logs into receipts. Retain audit
logs separately with appropriate protection. `runtime_config_sha256` covers only
the fixed canonical JSON projection used by `reconcile`: mount identity/policy,
readonly/privilege/capability/network/user policy, command/entrypoint/health equality
booleans and the two fixed public route environment strings. It is deliberately
**not** a hash of secret environment values or complete effective configuration.
Unknown environment is neither read nor claimed reconciled.

Runtime policy requires a read-only root, `pulsex` user, fixed network, direct
application command, no added capabilities, exact readiness command, public origin
`https://5.189.157.131` and prefix `/plusx`, and the existing named data volume at
`/app/data`. It rejects the historically observed writable-root/startup-wrapper
runtime. Historical evidence is not a fresh observation. Volume identity does not
establish data integrity or rollback compatibility. No volume is opened.

The receipt authenticates the builder's claims; it cannot independently prove
that the builder actually reproduced the image or authenticated all referenced
materials. Manifest/config descriptors do not verify every local layer's bytes.
Rollback receipt hashes remain references, not independently verified rollback
receipts. These are mandatory release blockers, not implicit acceptance. The
current release has no supplied trusted signer/receipt/OCI attestation; no genuine
attestation is created by this change.

## Focused verification and rollback

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s ops/tests -p 'test_*receipt.py'
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s ops/tests -p test_deployment_provenance.py
python3 -m py_compile ops/release_receipt.py ops/tests/test_release_receipt.py ops/tests/test_oci_receipt.py
git diff --check
```

Tests use temporary synthetic Git/OCI inputs and ephemeral test-only keys; no
Docker, network, application, database or browser tests. The CLI test exercises
real packaging and signature verification while asserting release remains blocked.

Rollback is non-destructive: retain private evidence and leave the isolated
candidate unselected. Main, both prior candidates and live state are unchanged;
no runtime rollback, volume removal, dirty-tree reset or default-branch edit is
needed. Future deployment requires separately verified immutable rollback evidence.
