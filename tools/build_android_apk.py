"""Build the dependency-free Android preview using official SDK/JDK tools.

No Gradle dependency resolution is needed for this bounded fallback. The Gradle
project remains usable in Android Studio. Signing uses a local disposable debug
key, never a production key. See android/README_AR.md.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import zipfile
import xml.etree.ElementTree as ET
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "android"

def main():
    sdk = Path(os.environ["ANDROID_HOME"])
    jdk = Path(os.environ["JAVA_HOME"])
    tools = sdk / "build-tools" / "35.0.0"
    platform = sdk / "platforms" / "android-35" / "android.jar"
    out = ANDROID / "app/build/manual"
    out.mkdir(parents=True, exist_ok=True)
    decoder = out / "zxing-core-3.5.3.jar"
    decoder_hash = "8d8064c1636fdaef7189dd9055c7d59950a8940a12f2293956446ec3c109fd82"
    if not decoder.exists():
        with urllib.request.urlopen("https://repo.maven.apache.org/maven2/com/google/zxing/core/3.5.3/core-3.5.3.jar", timeout=60) as response:
            decoder.write_bytes(response.read(1024 * 1024))
    if hashlib.sha256(decoder.read_bytes()).hexdigest() != decoder_hash:
        raise RuntimeError("ZXING_DEPENDENCY_HASH_MISMATCH")
    gen, classes, dex = [out / x for x in ("generated", "classes", "dex")]
    for directory in (gen, classes, dex):
        if directory.exists(): shutil.rmtree(directory)
        directory.mkdir(parents=True)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if os.environ.get("PULSEX_SOURCE_SHA", revision) != revision:
        raise RuntimeError("SOURCE_SHA_DOES_NOT_MATCH_CHECKOUT")
    tracked_dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip())
    if tracked_dirty: revision += "-working-tree"
    def run(*args):
        subprocess.run([str(x) for x in args], cwd=ROOT, check=True)
    manifest = ET.parse(ANDROID / "app/src/main/AndroidManifest.xml")
    manifest.getroot().set("package", "com.pulsex.app")
    manifest.getroot().find("application").set("{http://schemas.android.com/apk/res/android}debuggable", "false")
    manifest.write(out / "AndroidManifest.xml", encoding="utf-8", xml_declaration=True)
    run(tools / "aapt2", "compile", "--dir", ANDROID / "app/src/main/res", "-o", out / "res.zip")
    run(tools / "aapt2", "link", "-I", platform, "--manifest", out / "AndroidManifest.xml",
        "--java", gen, "--min-sdk-version", "26", "--target-sdk-version", "35",
        "--version-code", "10003", "--version-name", "1.0.3-android-preview-debug",
        "--rename-manifest-package", "com.pulsex.app.preview",
        "-o", out / "resources.apk", out / "res.zip")
    build_config = gen / "com/pulsex/app/BuildConfig.java"
    build_config.parent.mkdir(parents=True, exist_ok=True)
    build_config.write_text('package com.pulsex.app; public final class BuildConfig { '
        'public static final boolean DEBUG=false; public static final String VERSION_NAME="1.0.3-android-preview-debug"; '
        'public static final String SOURCE_SHA=' + json.dumps(revision) + '; }\n')
    sources = sorted((ANDROID / "app/src/main/java").rglob("*.java")) + sorted(gen.rglob("*.java"))
    bootclasspath = os.pathsep.join((str(platform), str(tools / "core-lambda-stubs.jar")))
    run(jdk / "bin/javac", "-encoding", "UTF-8", "-source", "8", "-target", "8", "-bootclasspath", bootclasspath,
        "-classpath", decoder, "-d", classes, *sources)
    run(tools / "d8", "--lib", platform, "--min-api", "26", "--output", dex, *sorted(classes.rglob("*.class")), decoder)
    unsigned = out / "unsigned.apk"
    shutil.copyfile(out / "resources.apk", unsigned)
    with zipfile.ZipFile(unsigned, "a", zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(dex.glob("*.dex")): archive.write(file, file.name)
        with zipfile.ZipFile(decoder) as dependency:
            for name in dependency.namelist():
                if name.startswith("META-INF/") and ("LICENSE" in name or "NOTICE" in name):
                    archive.writestr(name, dependency.read(name))
    aligned, apk = out / "aligned.apk", out / "Eventna-Android-preview.apk"
    run(tools / "zipalign", "-f", "4", unsigned, aligned)
    key = out / "preview-debug.keystore"
    if not key.exists():
        run(jdk / "bin/keytool", "-genkeypair", "-keystore", key, "-storepass", "android", "-keypass", "android",
            "-alias", "androiddebugkey", "-dname", "CN=Eventna Preview,O=Development,C=YE", "-keyalg", "RSA",
            "-keysize", "2048", "-validity", "3650")
        key.chmod(0o600)
    run(tools / "apksigner", "sign", "--ks", key, "--ks-pass", "pass:android", "--out", apk, aligned)
    signature = subprocess.check_output([str(tools / "apksigner"), "verify", "--verbose", "--print-certs", str(apk)], text=True)
    print(signature)
    certificate = re.search(r"Signer #1 certificate SHA-256 digest: ([0-9a-f]{64})", signature)
    if not certificate: raise RuntimeError("APK_CERTIFICATE_DIGEST_MISSING")
    badging = subprocess.check_output([str(tools / "aapt"), "dump", "badging", str(apk)], text=True)
    permissions = sorted(re.findall(r"uses-permission: name='([^']+)'", badging))
    allowed = sorted(["android.permission.INTERNET", "android.permission.ACCESS_NETWORK_STATE", "android.permission.CAMERA"])
    if "application-debuggable" in badging: raise RuntimeError("APK_MUST_NOT_BE_DEBUGGABLE")
    if permissions != allowed: raise RuntimeError("APK_PERMISSION_ALLOWLIST_MISMATCH")
    run(tools / "zipalign", "-c", "4", apk)
    evidence = {"source_revision": revision, "source_dirty": tracked_dirty, "package": "com.pulsex.app.preview",
        "min_sdk": 26, "target_sdk": 35, "build_tools": "35.0.0", "signing": "disposable_debug_key_not_production",
        "qr_decoder": {"artifact": "com.google.zxing:core:3.5.3", "sha256": decoder_hash},
        "apk_sha256": hashlib.sha256(apk.read_bytes()).hexdigest(), "apk_bytes": apk.stat().st_size,
        "device_tested": False, "server_included": False, "debuggable": False,
        "distribution": "internal_review_only", "malware_scanned": False,
        "certificate_sha256": certificate.group(1), "permissions": permissions,
        "static_checks": "signature_alignment_permission_allowlist_no_debug_passed"}
    (out / "BUILD_EVIDENCE.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))
    print(apk)

if __name__ == "__main__": main()
