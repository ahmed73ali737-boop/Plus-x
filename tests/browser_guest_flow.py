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

        # A different device that only knows the phone number must not receive the existing QR.
        stranger_context=browser.new_context(viewport={"width":900,"height":760},locale="ar-YE")
        stranger=stranger_context.new_page()
        stranger.goto(URL+"/e/demo/guest")
        stranger.get_by_label("رقم الهاتف",exact=True).fill("+967 777 500 600")
        stranger.get_by_text("أوافق على استخدام رقم الهاتف",exact=False).click()
        stranger.get_by_role("button",name="إنشاء / فتح بطاقة الزائر",exact=True).click()
        stranger.get_by_role("heading",name="البطاقة موجودة بالفعل",exact=True).wait_for()
        assert stranger.locator("img.guest-qr").count()==0
        assert guest_number not in stranger.locator("body").inner_text()
        stranger_context.close()
        mark("new_device_phone_only_cannot_recover_existing_qr")

        # Distinct live brand experiences, not one visual template recolored.
        for slug,title,selector in [
            ("agency-08","ثروات",".tharawat-live"),
            ("agency-09","Easy",".easy-live"),
            ("agency-10","RTS",".rts-live"),
        ]:
            page.goto(URL+"/e/demo/p/"+slug)
            page.get_by_role("heading",name=title,exact=True,level=1).wait_for()
            assert page.locator(selector).count()==1
            assert title in page.locator(".site-topbar .brand").inner_text()
            assert "Powered by PulseX" in page.locator(".platform-attribution").inner_text()
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
        page.get_by_text("تم ربط هذا المتصفح وتجهيزه للمسح.",exact=False).wait_for()
        mark("event_operator_device_paired_in_browser")

        # Scanner resolves the QR payload. The CI path uses the exact QR URL text;
        # physical camera hardware is intentionally reported separately.
        page.goto(URL+"/e/demo/scan")
        page.get_by_role("heading",name="بوابة الدخول والتحقق",exact=True).wait_for()
        page.get_by_role("heading",name="جاهزية البوابة",exact=True).wait_for()
        page.get_by_text("سجل الزوار",exact=True).wait_for()
        mark("gate_preflight_visible")
        page.get_by_text("نسخة السجل",exact=True).wait_for()
        page.get_by_text("حداثة السجل",exact=True).wait_for()
        mark("manifest_freshness_visible")
        page.get_by_label("امسح QR أو ابحث بالاسم / الجهة / رقم الزائر",exact=True).fill("زائر تجربة")
        page.get_by_role("button",name="بحث / فتح",exact=True).click()
        page.get_by_text(guest_number,exact=True).wait_for()
        mark("manual_guest_search_fallback")
        page.get_by_label("امسح QR أو ابحث بالاسم / الجهة / رقم الزائر",exact=True).fill(URL+"/e/demo/guest/"+guest_number)
        page.get_by_role("button",name="بحث / فتح",exact=True).click()
        page.get_by_text("زائر تجربة",exact=True).wait_for()
        page.get_by_text(guest_number,exact=True).wait_for()
        mark("qr_payload_resolves_guest_in_scanner")

        # Validate-only mode checks eligibility/presence without writing a movement.
        page.get_by_label("وضع المسح",exact=True).select_option("validate")
        page.get_by_role("button",name="بحث / فتح",exact=True).click()
        page.get_by_text("صالح للدخول",exact=True).wait_for()
        mark("validate_only_does_not_check_in")

        page.get_by_label("وضع المسح",exact=True).select_option("entry")
        page.get_by_role("button",name="بحث / فتح",exact=True).click()

        # Offline scan/check-in from the already prepared local manifest.
        context.set_offline(True)
        page.get_by_role("button",name="تسجيل دخول",exact=True).click()
        page.get_by_text("تم حفظ الدخول محليًا",exact=False).wait_for()
        pending=page.evaluate("""async()=>{const m=await import('/assets/offline.mjs');const xs=await m.all('checkin_outbox');return xs.filter(x=>x.status==='pending').length}""")
        assert pending>=1
        mark("offline_checkin_queued")

        context.set_offline(False)
        page.wait_for_function("navigator.onLine === true")
        page.evaluate("window.dispatchEvent(new Event('online'))")
        for _ in range(120):
            sync_state=page.evaluate("""async()=>{const m=await import('/assets/offline.mjs');const xs=await m.all('checkin_outbox');const rs=await m.all('checkin_receipts');return {accepted:rs.filter(x=>['accepted','duplicate'].includes(x.status)).length,pending:xs.filter(x=>x.status==='pending').length,outbox:xs.length}}""")
            if sync_state['accepted']>=1 and sync_state['pending']==0 and sync_state['outbox']==0:
                break
            page.wait_for_timeout(100)
        assert sync_state['accepted']>=1 and sync_state['pending']==0 and sync_state['outbox']==0, sync_state
        page.get_by_text("تمت المزامنة",exact=False).first.wait_for()
        mark("offline_checkin_synced_after_reconnect")

        page.get_by_label("وضع المسح",exact=True).select_option("entry")
        page.get_by_role("button",name="بحث / فتح",exact=True).click()
        page.get_by_role("button",name="تسجيل دخول",exact=True).click()
        page.get_by_text("داخل الفعالية بالفعل",exact=False).wait_for()
        mark("local_antipassback_blocks_second_entry")

        # The same operator flow supports exit and named checkpoints.
        page.get_by_label("وضع المسح",exact=True).select_option("exit")
        page.get_by_label("نقطة الوصول",exact=True).select_option("main")
        page.get_by_role("button",name="بحث / فتح",exact=True).click()
        page.get_by_role("button",name="تسجيل خروج",exact=True).click()
        page.get_by_text("تم تسجيل الخروج ومزامنته.",exact=False).wait_for()
        mark("online_exit_checkpoint_recorded")

        # Guest can register while the already-loaded page is offline. The local
        # provisional number must reconcile automatically to a server-issued
        # opaque guest number and QR when connectivity returns.
        page.goto(URL+"/e/demo/guest")
        context.set_offline(True)
        page.get_by_label("رقم الهاتف",exact=True).fill("0777 808 080")
        page.get_by_label("الاسم — اختياري",exact=True).fill("زائر أوفلاين")
        page.get_by_text("أوافق على استخدام رقم الهاتف",exact=False).click()
        page.get_by_role("button",name="إنشاء / فتح بطاقة الزائر",exact=True).click()
        page.get_by_role("heading",name="زائر أوفلاين",exact=True).wait_for()
        provisional=page.locator(".guest-number strong").inner_text().strip()
        assert provisional.startswith("P-")
        old_phone_derived=page.evaluate("""async()=>{const phone='+967777808080';const b=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(phone));const h=[...new Uint8Array(b)].map(x=>x.toString(16).padStart(2,'0')).join('').toUpperCase();return 'P-'+h.slice(0,4)+'-'+h.slice(4,8)+'-'+h.slice(8,12)+'-'+h.slice(12,16)}""")
        assert provisional!=old_phone_derived
        assert page.locator("img.guest-qr").count()==0
        pending_guests=page.evaluate("""async()=>{const m=await import('/assets/offline.mjs');const xs=await m.all('guest_outbox');return xs.filter(x=>x.status==='pending').length}""")
        assert pending_guests>=1
        mark("offline_guest_registration_provisional")

        context.set_offline(False)
        page.wait_for_function("navigator.onLine === true")
        page.evaluate("window.dispatchEvent(new Event('online'))")
        page.wait_for_url(lambda u: "/guest/G-" in u,timeout=15000)
        final_number=page.locator(".guest-number strong").inner_text().strip()
        assert final_number.startswith("G-") and final_number!=provisional
        page.locator("img.guest-qr").wait_for()
        guest_storage=page.evaluate("""async()=>{const m=await import('/assets/offline.mjs');const xs=await m.all('guest_outbox');const gs=await m.all('guests');return {pending:xs.filter(x=>x.status==='pending').length,outbox:xs.length,rawPhones:gs.filter(x=>typeof x.phone==='string'&&x.phone.length>0).length}}""")
        assert guest_storage['pending']==0 and guest_storage['outbox']==0
        assert guest_storage['rawPhones']==0
        mark("offline_guest_auto_reconciled_to_secure_qr")

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
