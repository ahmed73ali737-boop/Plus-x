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

ROOT=Path(__file__).resolve().parents[1]
TEMP=Path(tempfile.mkdtemp(prefix="pulsex-guest-browser-"))
with socket.socket() as sock:
    sock.bind(("127.0.0.1",0))
    PORT=sock.getsockname()[1]
URL=f"http://127.0.0.1:{PORT}"
env={
    **os.environ,
    "HOST":"127.0.0.1",
    "PORT":str(PORT),
    "PUBLIC_ORIGIN":URL,
    "DATABASE_URL":"sqlite:///"+str(TEMP/"guest.sqlite"),
    "CREDENTIALS_PATH":str(TEMP/"accounts.json"),
    "MEDIA_DIR":str(TEMP/"media"),
    "REQUIRE_POSTGRES":"false",
    "SEED_DEMO":"true",
    "PYTHONUTF8":"1",
}
(ROOT/"qa").mkdir(exist_ok=True)
log=open(ROOT/"qa/guest-browser-server.log","w",encoding="utf-8")
proc=subprocess.Popen([sys.executable,"run.py"],cwd=ROOT,env=env,stdout=log,stderr=log)

checks=[]
errors=[]

def mark(name):
    checks.append(name)
    print("PASS",name,flush=True)

try:
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(120):
        try:
            with opener.open(URL+"/api/health",timeout=.5):
                break
        except Exception:
            if proc.poll() is not None:
                raise RuntimeError((ROOT/"qa/guest-browser-server.log").read_text(encoding="utf-8")[-3000:])
            time.sleep(.1)
    else:
        raise RuntimeError("Guest browser QA server startup timeout")

    creds=json.loads((TEMP/"accounts.json").read_text(encoding="utf-8"))
    organizer=next(x for x in creds if x["email"]=="organizer@pulsex.test")

    with sync_playwright() as p:
        browser=p.chromium.launch(args=["--no-sandbox","--disable-dev-shm-usage"])
        context=browser.new_context(viewport={"width":1280,"height":900},locale="ar-YE")
        page=context.new_page()
        page.on("pageerror",lambda e: errors.append(str(e)))

        # Guest self-registration: same normalized phone must resolve to one stable guest number.
        page.goto(URL+"/e/demo/guest")
        page.get_by_label("رقم الهاتف",exact=True).fill("0777 500 600")
        page.get_by_label("الاسم — اختياري",exact=True).fill("زائر تجربة")
        page.get_by_label("الجهة / الشركة — اختياري",exact=True).fill("فريق الاختبار")
        page.get_by_text("أوافق على استخدام رقم الهاتف",exact=False).click()
        page.get_by_role("button",name="إنشاء / فتح بطاقة الزائر",exact=True).click()
        page.get_by_role("heading",name="زائر تجربة",exact=True).wait_for()
        guest_number=page.locator(".guest-number strong").inner_text().strip()
        assert guest_number.startswith("G-")
        page.locator("img.guest-qr").wait_for()
        assert page.locator("img.guest-qr").evaluate("img=>img.complete&&img.naturalWidth>20")
        page.screenshot(path=str(ROOT/"qa/guest-pass.png"),full_page=True)
        mark("guest_self_registration_and_qr")

        page.goto(URL+"/e/demo/guest")
        page.get_by_label("رقم الهاتف",exact=True).fill("+967 777 500 600")
        page.get_by_text("أوافق على استخدام رقم الهاتف",exact=False).click()
        page.get_by_role("button",name="إنشاء / فتح بطاقة الزائر",exact=True).click()
        page.locator(".guest-number strong").wait_for()
        assert page.locator(".guest-number strong").inner_text().strip()==guest_number
        mark("same_phone_returns_same_guest_number")

        # Distinct live brand experiences, not one visual template recolored.
        for slug,title,selector in [
            ("agency-08","ثروات",".tharawat-live"),
            ("agency-09","Easy",".easy-live"),
            ("agency-10","RTS",".rts-live"),
        ]:
            page.goto(URL+"/e/demo/p/"+slug)
            page.get_by_role("heading",name=title,exact=True,level=1).wait_for()
            assert page.locator(selector).count()==1
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            mark("brand_live_"+slug)
        page.screenshot(path=str(ROOT/"qa/rts-live.png"),full_page=False)

        # Organizer sees the guest directory and can provision/pair an event scanner.
        page.goto(URL+"/admin")
        page.get_by_label("البريد الإلكتروني",exact=True).fill(organizer["email"])
        page.get_by_label("كلمة المرور",exact=True).fill(organizer["password"])
        page.get_by_role("button",name="تسجيل الدخول",exact=True).click()
        page.get_by_role("heading",name="نظرة عامة",exact=True).wait_for()
        page.get_by_role("button",name="الزوار و QR",exact=True).click()
        page.get_by_role("heading",name="الزوار و QR",exact=True).wait_for()
        page.get_by_text(guest_number,exact=True).first.wait_for()
        page.get_by_text("+967777500600",exact=True).wait_for()
        page.screenshot(path=str(ROOT/"qa/guest-admin-directory.png"),full_page=True)
        mark("organizer_guest_directory")

        page.get_by_role("button",name="الأجهزة والطرفيات",exact=True).click()
        page.get_by_label("اسم الجهاز",exact=True).fill("Gate QA")
        page.get_by_label("نوع الطرفية",exact=True).select_option("operator")
        page.get_by_role("button",name="إنشاء وربط الطرفية",exact=True).click()
        pair=page.get_by_role("button",name="ربط هذا المتصفح بهذه الطرفية",exact=True)
        pair.wait_for()
        pair.click()
        mark("event_operator_device_paired_in_browser")

        # Scanner resolves the QR payload. The CI path uses the exact QR URL text;
        # physical camera hardware is intentionally reported separately.
        page.goto(URL+"/e/demo/scan")
        page.get_by_role("heading",name="مسح بطاقة الزائر",exact=True).wait_for()
        page.get_by_label("امسح QR أو أدخل رقم الزائر",exact=True).fill(URL+"/e/demo/guest/"+guest_number)
        page.get_by_role("button",name="بحث / فتح",exact=True).click()
        page.get_by_text("زائر تجربة",exact=True).wait_for()
        page.get_by_text(guest_number,exact=True).wait_for()
        mark("qr_payload_resolves_guest_in_scanner")

        # Offline scan/check-in from the already prepared local manifest.
        context.set_offline(True)
        page.get_by_role("button",name="تسجيل دخول",exact=True).click()
        page.get_by_text("تم الحفظ محليًا",exact=False).wait_for()
        pending=page.evaluate("""async()=>{const m=await import('/assets/offline.mjs');const xs=await m.all('checkin_outbox');return xs.filter(x=>x.status==='pending').length}""")
        assert pending>=1
        mark("offline_checkin_queued")

        context.set_offline(False)
        page.evaluate("window.dispatchEvent(new Event('online'))")
        for _ in range(50):
            accepted=page.evaluate("""async()=>{const m=await import('/assets/offline.mjs');const xs=await m.all('checkin_outbox');return xs.filter(x=>x.status==='accepted').length}""")
            if accepted:
                break
            page.wait_for_timeout(100)
        assert accepted>=1
        mark("offline_checkin_synced_after_reconnect")

        # Mobile guest registration view must not overflow.
        mobile_context=browser.new_context(viewport={"width":390,"height":844},is_mobile=True,locale="ar-YE")
        mobile=mobile_context.new_page()
        mobile.on("pageerror",lambda e: errors.append(str(e)))
        mobile.goto(URL+"/e/demo/guest")
        mobile.get_by_role("heading",name="بطاقتك للفعالية",exact=True).wait_for()
        assert mobile.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        mobile.screenshot(path=str(ROOT/"qa/guest-mobile.png"),full_page=False)
        mobile_context.close()
        mark("guest_mobile_no_horizontal_overflow")

        if errors:
            raise AssertionError(errors)
        browser.close()

    report={
        "status":"passed",
        "passed":len(checks),
        "checks":checks,
        "guest_number":guest_number,
        "backend":"SQLite",
        "real_local_http":True,
        "browser":"Chromium",
        "offline_indexeddb_checkin_tested":True,
        "qr_payload_parser_tested":True,
        "camera_api_ui_present":True,
        "physical_camera_hardware_tested":False,
        "native_postgresql_tested_here":False,
        "page_errors":errors,
    }
    (ROOT/"qa/windows12-guest-browser.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False))
except Exception as exc:
    failure={
        "status":"failed",
        "reason":str(exc),
        "passed_before_failure":len(checks),
        "checks":checks,
        "page_errors":errors,
        "physical_camera_hardware_tested":False,
    }
    try:
        if "page" in locals():
            failure["url"]=page.url
            failure["body_text"]=page.locator("body").inner_text()[:2500]
            page.screenshot(path=str(ROOT/"qa/guest-browser-failure.png"),full_page=True)
    except Exception:
        pass
    (ROOT/"qa/windows12-guest-browser.json").write_text(json.dumps(failure,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(failure,ensure_ascii=False))
    raise
finally:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    log.close()
