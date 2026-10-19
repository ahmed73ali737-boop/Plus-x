# PulseX Android preview APK

`PulseX-Android-Preview-1.0.2.apk` is the **debug-signed preview** built from clean source `d18f5c992fb625120059fe97a46a23c9f48a90a3` (PR #34), already contained in main. It is not a production-signed release. Its SHA256 is recorded in `BUILD_EVIDENCE.json`:

`1c14b96c350066c2561956b010caa75a920d058d8bebacad0894cd9a767bd90c`

The APK hosts the current PulseX server UI and does not bundle the FastAPI server. Deploy the current main web assets to receive offline synchronization fixes and Service Worker v27; those server-served updates do not require changing this APK's bytes. First configure a working HTTPS PulseX origin inside the app. Android 8+ and an up-to-date Android System WebView are required.

See [Android guide](../../android/README_AR.md) and [offline verification and limits](../../docs/OFFLINE_UPLOAD_VERIFICATION_20261020_AR.md). No signing keystore is included. Synchronize pending data before uninstalling or changing servers.
