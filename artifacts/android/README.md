# Eventna Android preview

`Eventna-Android-Preview-1.0.3.apk` was built from clean source `64b720b098c18404b4b59f344da98c34e73ecc92` by [GitHub Actions](https://github.com/ahmed73ali737-boop/Plus-x/actions/runs/39354220074).

SHA256: `6d1b47087f1e93c29917e6a8a482dc8fc9af4db056c8b42d2c2d96b753f66e87`. Size: 299736 bytes. Signature, alignment, server-origin checks and offline QR decoder checks passed.

This remains a debug-signed preview, not a production-signed release. Physical-device testing has not been performed. It uses the existing `com.pulsex.app.preview` package identifier for compatibility.

**2026-11-16:** the APK binary was removed from the tree and `artifacts/android/*.apk`
is now git-ignored. Public distribution was already withdrawn pending the Android
security review (`/downloads/*.apk` return HTTP 410). `BUILD_EVIDENCE.json` is kept
for traceability; the server-side integrity audit fails closed (503) when the binary
is absent. Distribute signed builds only through a release channel, never from git.
