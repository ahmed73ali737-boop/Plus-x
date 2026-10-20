"""Real HTTP + browser Service Worker/IndexedDB outage and recovery acceptance.

An explicit Chrome for Testing executable is allowed and recorded as such.
This does not claim Android WebView, physical venue hardware or five-day soak.
"""
from harness_support import sqlite_connection
from pathlib import Path
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]

def run():
    checks = []
    report = {"scope": "Real browser + HTTP/SQLite + actual Service Worker + IndexedDB; no hardware/five-day claim", "checks": checks}
    with tempfile.TemporaryDirectory(prefix="pulsex-offline-http-") as temporary:
        data = Path(temporary)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        origin = f"http://127.0.0.1:{port}"
        env = {**os.environ, "HOST": "127.0.0.1", "PORT": str(port), "PUBLIC_ORIGIN": origin,
               "DATABASE_URL": "sqlite:///" + str(data / "qa.sqlite"), "CREDENTIALS_PATH": str(data / "accounts.json"),
               "MEDIA_DIR": str(data / "media"), "REQUIRE_POSTGRES": "false", "SEED_DEMO": "true", "PYTHONUTF8": "1"}
        with (data / "server.log").open("w") as log:
            process = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=log, stderr=log)
            try:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                for _ in range(200):
                    try:
                        with opener.open(origin + "/api/health", timeout=.5): break
                    except Exception:
                        if process.poll() is not None: raise RuntimeError("QA server exited")
                        time.sleep(.1)
                else: raise RuntimeError("QA server startup timeout")
                with sync_playwright() as playwright:
                    executable = os.environ.get("PULSEX_TEST_CHROMIUM_PATH")
                    options = {"args": ["--no-sandbox", "--disable-dev-shm-usage"]}
                    if executable: options["executable_path"] = executable
                    browser = playwright.chromium.launch(**options)
                    report.update(browser_version=browser.version, browser_source="explicit Chrome executable" if executable else "Playwright-managed Chromium")
                    context = browser.new_context(locale="ar-YE", viewport={"width": 412, "height": 915})
                    page = context.new_page()
                    page.goto(origin + "/e/demo/p/agency-01")
                    prepared = page.evaluate("""async()=>{
                        const o=await import('/assets/offline.mjs');
                        const b=await o.bundle('agency-01');return await o.prepare(b);
                    }""")
                    assert prepared["pages"] > 0, prepared
                    report["prepared_pages"] = prepared["pages"]
                    report["missing_optional_media_count"] = len(prepared["missing"])
                    page.evaluate("async()=>{await navigator.serviceWorker.ready;}")
                    page.reload()
                    page.wait_for_function("navigator.serviceWorker.controller !== null")
                    checks.append("prepare_real_service_worker_and_public_content")

                    context.set_offline(True)
                    page.reload(wait_until="domcontentloaded")
                    cached = page.evaluate("async()=>{const o=await import('/assets/offline.mjs');return await o.bundle('agency-01');}")
                    assert cached["offline"] is True
                    checks.append("cached_shell_and_bundle_reload_with_network_disconnected")
                    item_id = str(uuid.uuid4())
                    envelope = {"id": item_id, "site_id": cached["id"], "version": cached["version"], "kind": "visit",
                                "visitor_id": str(uuid.uuid4()), "session_id": str(uuid.uuid4()), "source": "kiosk",
                                "target": "", "payload": {}, "client_time": "2026-10-20T00:00:00+03:00"}
                    result = page.evaluate("async e=>{const o=await import('/assets/offline.mjs');const r=await o.enqueue(e);return {r,s:await o.status()};}", envelope)
                    assert result["r"]["status"] == "pending" and any(item["id"] == item_id and item["status"] == "pending" for item in result["s"]["items"]), result
                    checks.append("offline_interaction_persisted_without_false_acknowledgment")
                    page.close()
                    page = context.new_page()
                    page.goto(origin + "/e/demo/p/agency-01", wait_until="domcontentloaded")
                    assert page.evaluate("async id=>{const o=await import('/assets/offline.mjs');return (await o.get('outbox',id))?.status;}", item_id) == "pending"
                    checks.append("offline_queue_survives_page_close_and_cached_reopen")
                    context.set_offline(False)
                    result = page.evaluate("async id=>{const o=await import('/assets/offline.mjs');await o.sync();return {receipt:await o.get('receipts',id),s:await o.status()};}", item_id)
                    assert result["receipt"]["status"] in ("accepted", "duplicate") and all(item["id"] != item_id for item in result["s"]["items"]), result
                    with sqlite_connection(data / "qa.sqlite") as database:
                        assert database.execute("select count(*) from px_submissions where id=?", (item_id,)).fetchone()[0] == 1
                    checks.append("reconnect_receipt_drains_queue_and_server_has_one_row")

                    # Authentic server denial must be distinguished from a network error.
                    # No real bearer credentials or personal data are included in reports.
                    result = page.evaluate("""async()=>{
                        const o=await import('/assets/offline.mjs');
                        const token='invalid-qa-device-token-at-least-20';
                        await o.put('bundles',{id:'device-auth',data:{token}});
                        await o.put('guest_manifests',{id:'revoked-event',token,data:{guests:[]}});
                        await o.put('bundles',{id:'gate-context:revoked',token,data:{event_id:'revoked-event'}});
                        await o.put('guest_manifests',{id:'other-device',token:'other-token',data:{guests:[]}});
                        await o.put('checkin_outbox',{id:'pending-preserved',event_id:'revoked-event',status:'pending'});
                        let notified=0;window.addEventListener('px-device-authorization-revoked',()=>notified++,{once:true});
                        const heartbeat=await o.deviceHeartbeat();
                        return {heartbeat,auth:await o.get('bundles','device-auth')||null,
                            manifest:await o.get('guest_manifests','revoked-event')||null,
                            gate:await o.get('bundles','gate-context:revoked')||null,
                            other:!!await o.get('guest_manifests','other-device'),
                            pending:!!await o.get('checkin_outbox','pending-preserved'),notified};
                    }""")
                    assert result["heartbeat"].get("authorization_failed") is True, result
                    assert result["auth"] is None and result["manifest"] is None and result["gate"] is None, result
                    assert result["other"] and result["pending"] and result["notified"] == 1, result
                    checks.append("heartbeat_denial_clears_only_revoked_device_cache_preserving_pending_data")
                    browser.close()
                report["status"] = "passed"
            except Exception as error:
                blocked = not checks and "socket() failed: Operation not permitted" in str(error)
                report.update(status="blocked" if blocked else "failed", error="Browser launch blocked: Unix socket creation is not permitted in this environment" if blocked else str(error)[:2000])
                raise
            finally:
                process.terminate()
                try: process.wait(timeout=15)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
                output = ROOT / "qa/offline-recovery.json"
                output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
                print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)

if __name__ == "__main__": run()
