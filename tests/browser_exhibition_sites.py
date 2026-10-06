from __future__ import annotations
from pathlib import Path
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

ROOT = Path(__file__).resolve().parents[1]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
TEMP = Path(tempfile.mkdtemp(prefix="pulsex-expo-"))
with socket.socket() as port_socket:
    port_socket.bind(("127.0.0.1", 0))
    PORT = port_socket.getsockname()[1]
URL = f"http://127.0.0.1:{PORT}"
env = {
    **os.environ,
    "HOST": "127.0.0.1",
    "PORT": str(PORT),
    "PUBLIC_ORIGIN": URL,
    "DATABASE_URL": "sqlite:///" + str(TEMP / "expo.sqlite"),
    "CREDENTIALS_PATH": str(TEMP / "accounts.json"),
    "MEDIA_DIR": str(TEMP / "media"),
    "REQUIRE_POSTGRES": "false",
    "SEED_DEMO": "true",
    "PYTHONUTF8": "1",
}
(ROOT / "qa").mkdir(exist_ok=True)
log = open(ROOT / "qa/exhibition-browser-server.log", "w", encoding="utf-8")
proc = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=log, stderr=log)
checks, errors = [], []

def mark(name):
    checks.append(name)
    print("PASS", name, flush=True)

def dismiss_welcome(page):
    button = page.get_by_role("button", name="الدخول دون بيانات", exact=True)
    try:
        button.wait_for(state="visible", timeout=2000)
        button.click()
    except PlaywrightTimeoutError:
        pass

def assert_no_overflow(page):
    width = page.evaluate("({scroll:document.documentElement.scrollWidth,inner:innerWidth})")
    assert width["scroll"] <= width["inner"] + 1, width

try:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(100):
        try:
            with opener.open(URL + "/api/health", timeout=0.5):
                break
        except Exception:
            if proc.poll() is not None:
                raise RuntimeError((ROOT / "qa/exhibition-browser-server.log").read_text(encoding="utf-8")[-3000:])
            time.sleep(0.1)
    else:
        raise RuntimeError("Exhibition browser QA server startup timeout")

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(viewport={"width": 1440, "height": 1050}, locale="ar-YE")
        page = context.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))

        # Tharawat must be an editorial/financial experience, not the generic hero.
        page.goto(URL + "/e/demo/p/agency-08")
        page.locator(".expo-tharawat-stage").wait_for()
        dismiss_welcome(page)
        page.get_by_text("THARAWAT · EXHIBITION EDITION", exact=True).wait_for()
        page.locator(".expo-tharawat-salon").wait_for()
        assert page.locator(".expo-easy-stage,.expo-rts-stage").count() == 0
        assert_no_overflow(page)
        page.screenshot(path=str(ROOT / "qa/tharawat-exhibition.png"), full_page=True)
        mark("tharawat_distinct_exhibition_surface")

        # Easy must read and behave like a living wallet surface.
        page.goto(URL + "/e/demo/p/agency-09")
        page.locator(".expo-easy-stage").wait_for()
        dismiss_welcome(page)
        page.locator(".expo-easy-phone").wait_for()
        page.get_by_text("بطاقات Wi‑Fi", exact=True).first.wait_for()
        page.get_by_text("حسابات الأطفال", exact=True).first.wait_for()
        assert page.locator(".expo-tharawat-stage,.expo-rts-stage").count() == 0
        assert_no_overflow(page)
        page.screenshot(path=str(ROOT / "qa/easy-exhibition.png"), full_page=True)
        mark("easy_distinct_living_wallet_surface")

        # RTS must expose a technical system map and capability rail.
        page.goto(URL + "/e/demo/p/agency-10")
        page.locator(".expo-rts-stage").wait_for()
        dismiss_welcome(page)
        page.locator(".expo-rts-system").wait_for()
        page.get_by_text("RTS / LIVE DIGITAL SYSTEMS", exact=True).wait_for()
        page.get_by_text("Payment & Collection", exact=True).first.wait_for()
        page.get_by_text("Integration & Platforms", exact=True).first.wait_for()
        assert page.locator(".expo-tharawat-stage,.expo-easy-stage").count() == 0
        assert_no_overflow(page)
        page.screenshot(path=str(ROOT / "qa/rts-exhibition-360.png"), full_page=True)
        mark("rts_distinct_command_center_surface")

        # Mobile layout for all three surfaces must stay inside the viewport.
        mobile_context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, locale="ar-YE")
        mobile = mobile_context.new_page()
        mobile.on("pageerror", lambda e: errors.append(str(e)))
        for slug, selector, name in [
            ("agency-08", ".expo-tharawat-stage", "tharawat"),
            ("agency-09", ".expo-easy-stage", "easy"),
            ("agency-10", ".expo-rts-stage", "rts"),
        ]:
            mobile.goto(URL + f"/e/demo/p/{slug}")
            mobile.locator(selector).wait_for()
            dismiss_welcome(mobile)
            assert_no_overflow(mobile)
            mobile.screenshot(path=str(ROOT / f"qa/{name}-exhibition-mobile.png"), full_page=False)
            mark(f"{name}_mobile_no_horizontal_overflow")
        mobile_context.close()

        # Regression for the Windows failure: local cache persistence must never
        # gate the first network render. Simulate an IndexedDB open that never settles.
        stalled = browser.new_context(viewport={"width": 1280, "height": 900}, locale="ar-YE")
        stalled.add_init_script("""
            (() => {
              const original = IDBFactory.prototype.open;
              Object.defineProperty(IDBFactory.prototype, 'open', {
                configurable: true,
                value: function(){ return {}; }
              });
              window.__pulsexOriginalIdbOpen = original;
            })();
        """)
        stalled_page = stalled.new_page()
        stalled_page.goto(URL + "/e/demo/p/agency-10", wait_until="domcontentloaded")
        stalled_page.locator(".expo-rts-stage").wait_for(timeout=7000)
        mark("network_render_not_blocked_by_indexeddb_cache")
        stalled.close()

        if errors:
            raise AssertionError(errors)
        browser.close()

    report = {
        "status": "passed",
        "checks": checks,
        "distinct_brand_surfaces": ["tharawat_finance", "easy_finance", "rts_tech"],
        "desktop_tested": True,
        "mobile_tested": True,
        "indexeddb_cache_nonblocking_tested": True,
        "physical_devices_tested": False,
        "page_errors": errors,
    }
    (ROOT / "qa/exhibition-brands.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
except Exception as exc:
    failure = {"status": "failed", "reason": str(exc), "checks": checks, "page_errors": errors}
    (ROOT / "qa/exhibition-brands.json").write_text(json.dumps(failure, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(failure, ensure_ascii=False))
    raise
finally:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    log.close()
