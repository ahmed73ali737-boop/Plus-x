from pathlib import Path
import json
import os
import re
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
TEMP = Path(tempfile.mkdtemp(prefix="pulsex-browser-"))

with socket.socket() as port_socket:
    port_socket.bind(("127.0.0.1", 0))
    PORT = port_socket.getsockname()[1]

URL = f"http://127.0.0.1:{PORT}"
env = {
    **os.environ,
    "HOST": "127.0.0.1",
    "PORT": str(PORT),
    "PUBLIC_ORIGIN": URL,
    "DATABASE_URL": "sqlite:///" + str(TEMP / "pilot.sqlite"),
    "CREDENTIALS_PATH": str(TEMP / "accounts.json"),
    "MEDIA_DIR": str(TEMP / "media"),
    "REQUIRE_POSTGRES": "false",
    "SEED_DEMO": "true",
    "PYTHONUTF8": "1",
}
(ROOT / "qa").mkdir(exist_ok=True)
log = open(ROOT / "qa/browser-server.log", "w", encoding="utf-8")
proc = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=log, stderr=log)

try:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(100):
        try:
            with opener.open(URL + "/api/health", timeout=0.5):
                break
        except Exception:
            if proc.poll() is not None:
                raise RuntimeError((ROOT / "qa/browser-server.log").read_text(encoding="utf-8")[-2000:])
            time.sleep(0.1)
    else:
        raise RuntimeError("Browser QA server startup timeout")

    creds = json.loads((TEMP / "accounts.json").read_text(encoding="utf-8"))
    checks, errors = [], []
    console_messages, failed_requests = [], []

    def mark(name):
        checks.append(name)
        print("PASS", name, flush=True)

    def dismiss_welcome(target):
        welcome = target.get_by_role("button", name="الدخول دون بيانات", exact=True)
        try:
            welcome.wait_for(state="visible", timeout=3000)
            welcome.click()
            target.locator("dialog").wait_for(state="detached", timeout=3000)
        except PlaywrightTimeoutError:
            pass

    def wait_semantic_heading(target, selector, expected):
        heading = target.locator(selector).first
        try:
            heading.wait_for(state="visible", timeout=30000)
        except PlaywrightTimeoutError:
            diagnostic = {
                "url": target.url,
                "title": target.title(),
                "selector": selector,
                "expected": expected,
                "body_text": target.locator("body").inner_text()[:3000],
                "page_errors": list(errors),
                "console_messages": list(console_messages),
                "failed_requests": list(failed_requests),
            }
            (ROOT / "qa/browser-platform-diagnostic.json").write_text(
                json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            target.screenshot(path=str(ROOT / "qa/browser-platform-failure.png"), full_page=True)
            raise
        actual = heading.inner_text().strip()
        assert actual == expected, (actual, expected)
        tag = heading.evaluate("el => el.tagName.toLowerCase()")
        assert tag in {"h1", "h2", "h3", "h4", "h5", "h6"}, tag
        return heading

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="ar-YE")
        page = context.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: console_messages.append({"type": m.type, "text": m.text}))
        page.on("requestfailed", lambda r: failed_requests.append({"url": r.url, "failure": r.failure}))

        page.goto(URL)
        wait_semantic_heading(page, "#events h2", "الفعاليات الجارية والقادمة")
        page.screenshot(path=str(ROOT / "qa/platform-desktop.png"), full_page=True)
        mark("platform_real_http_render")

        page.goto(URL + "/e/demo/p/agency-01")
        page.get_by_role("heading", name="الجهة التجريبية 01", exact=True, level=1).wait_for()
        dismiss_welcome(page)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        page.screenshot(path=str(ROOT / "qa/agency-desktop.png"), full_page=True)
        mark("agency_real_http_render_no_overflow")

        page.locator("#questions").get_by_role("link", name="ابدأ الاستبيان", exact=True).click()
        page.locator('fieldset[data-code="q-interest"] input').first.check()
        page.locator('fieldset[data-code="q-rate"] button').last.click()
        page.locator('form[data-form="main"]').get_by_role("button", name="إرسال الاستبيان", exact=True).click()
        page.get_by_text(re.compile("تم استلام|استلام إجابات")).first.wait_for()
        mark("public_survey_ui_to_database")

        mobile_context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, locale="ar-YE")
        mobile = mobile_context.new_page()
        mobile.on("pageerror", lambda e: errors.append(str(e)))
        mobile.goto(URL + "/e/demo/p/agency-01")
        mobile.get_by_role("heading", name="الجهة التجريبية 01", exact=True, level=1).wait_for()
        dismiss_welcome(mobile)
        assert mobile.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        mobile.screenshot(path=str(ROOT / "qa/agency-mobile.png"), full_page=False)
        mark("mobile_layout_no_overflow")

        page.goto(URL + "/admin")
        page.get_by_label("البريد الإلكتروني", exact=True).fill(creds[2]["email"])
        page.get_by_label("كلمة المرور", exact=True).fill(creds[2]["password"])
        page.get_by_role("button", name="تسجيل الدخول", exact=True).click()
        page.get_by_role("heading", name="نظرة عامة", exact=True).wait_for()
        page.screenshot(path=str(ROOT / "qa/admin-overview.png"), full_page=True)
        mark("agency_login_and_dashboard")

        page.get_by_role("button", name="إدخال الأسئلة", exact=True).click()
        page.get_by_role("button", name="+ سؤال واحد", exact=True).first.click()
        dialog = page.locator("dialog")
        dialog.get_by_label("رمز داخلي", exact=True).fill("UI-TIME")
        dialog.get_by_label("نص السؤال", exact=True).fill("ما الوقت الأنسب لزيارتك؟")
        dialog.get_by_label("نوع الإجابة", exact=True).select_option("time")
        dialog.get_by_role("button", name="حفظ السؤال", exact=True).click()
        page.get_by_text("ما الوقت الأنسب لزيارتك؟", exact=True).wait_for()
        mark("time_question_saved_from_admin_ui")

        page.get_by_role("button", name="نشر التغييرات", exact=True).click()
        page.wait_for_timeout(500)
        public_after_publish = context.new_page()
        public_after_publish.on("pageerror", lambda e: errors.append(str(e)))
        public_after_publish.goto(URL + "/e/demo/p/agency-01")
        public_after_publish.get_by_role("heading", name="الجهة التجريبية 01", exact=True, level=1).wait_for()
        dismiss_welcome(public_after_publish)
        public_after_publish.locator("#questions").get_by_role("link", name="ابدأ الاستبيان", exact=True).click()
        time_question = public_after_publish.locator('fieldset[data-code="UI-TIME"]')
        time_question.wait_for()
        assert time_question.locator('input[type="time"]').count() == 1
        mark("time_question_renders_semantic_time_input_after_publish")

        page.get_by_role("button", name="Excel / CSV", exact=True).click()
        page.locator('input[type="file"]').set_input_files(str(ROOT / "templates/PulseX_Windows04_Import.xlsx"))
        page.get_by_role("button", name="فحص ومعاينة الاستيراد", exact=True).click()
        page.get_by_role("button", name="اعتماد الاستيراد وحفظ المسودة", exact=True).wait_for()
        page.screenshot(path=str(ROOT / "qa/import-preview.png"), full_page=True)
        page.get_by_role("button", name="اعتماد الاستيراد وحفظ المسودة", exact=True).click()
        page.get_by_text("تم الحفظ في المسودة.", exact=True).wait_for()
        mark("xlsx_preview_commit_ui")

        page.get_by_role("button", name="معاينة الصفحة", exact=True).click()
        frame = page.frame_locator("iframe")
        frame.get_by_text(re.compile("وضع المعاينة")).wait_for()
        page.screenshot(path=str(ROOT / "qa/preview-studio.png"), full_page=True)
        mark("draft_preview_ui")

        page.get_by_role("button", name="النتائج والتقارير", exact=True).click()
        page.get_by_text("أشخاص فريدون موثّقون", exact=True).wait_for()
        mark("analytics_output_ui")

        if errors:
            raise AssertionError(errors)

        browser.close()

    report = {
        "status": "passed",
        "passed": len(checks),
        "checks": checks,
        "page_errors": errors,
        "console_messages": console_messages,
        "failed_requests": failed_requests,
        "backend": "SQLite",
        "real_local_http": True,
        "native_browser_network_tested": True,
        "semantic_time_input_verified": True,
        "not_native_postgresql": True,
    }
    (ROOT / "qa/browser-smoke.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
except Exception as exc:
    failure_page = locals().get("page")
    failure_errors = locals().get("errors", [])
    failure_state = {}
    if failure_page is not None:
        try:
            failure_state = {
                "url": failure_page.url,
                "title": failure_page.title(),
                "body_text": failure_page.locator("body").inner_text()[:2000],
            }
            failure_page.screenshot(path=str(ROOT / "qa/browser-failure-http.png"), full_page=True)
        except Exception as diagnostic_exc:
            failure_state = {"diagnostic_error": str(diagnostic_exc)}
    report = {
        "status": "failed",
        "reason": str(exc),
        "passed_before_failure": len(locals().get("checks", [])),
        "checks": locals().get("checks", []),
        "page_errors": failure_errors,
        "console_messages": locals().get("console_messages", []),
        "failed_requests": locals().get("failed_requests", []),
        "failure_state": failure_state,
        "not_passed": True,
    }
    (ROOT / "qa/browser-smoke.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    raise
finally:
    if proc.poll() is None:
        proc.terminate()
        proc.wait(timeout=10)
    log.close()
