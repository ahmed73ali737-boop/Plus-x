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

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
TEMP = Path(tempfile.mkdtemp(prefix="pulsex-control-contract-"))
with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    PORT = s.getsockname()[1]

URL = f"http://127.0.0.1:{PORT}"
env = {
    **os.environ,
    "HOST": "127.0.0.1",
    "PORT": str(PORT),
    "PUBLIC_ORIGIN": URL,
    "DATABASE_URL": "sqlite:///" + str(TEMP / "controls.sqlite"),
    "CREDENTIALS_PATH": str(TEMP / "accounts.json"),
    "MEDIA_DIR": str(TEMP / "media"),
    "REQUIRE_POSTGRES": "false",
    "PULSEX_ENV": "test",
    "SEED_DEMO": "true",
    "PYTHONUTF8": "1",
}
(ROOT / "qa").mkdir(exist_ok=True)
log = open(ROOT / "qa/browser-control-contract-server.log", "w", encoding="utf-8")
proc = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=log, stderr=log)

try:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(120):
        try:
            with opener.open(URL + "/api/health", timeout=0.5):
                break
        except Exception:
            if proc.poll() is not None:
                raise RuntimeError((ROOT / "qa/browser-control-contract-server.log").read_text(encoding="utf-8")[-4000:])
            time.sleep(0.1)
    else:
        raise RuntimeError("Control contract server startup timeout")

    accounts = json.loads((TEMP / "accounts.json").read_text(encoding="utf-8"))
    by_role = {}
    for account in accounts:
        by_role.setdefault(account["role"], account)
    assert {"platform", "organizer", "agency"} <= set(by_role)

    surfaces = []
    failures = []
    page_errors = []

    def audit(page, role, tab):
        result = page.evaluate(
            """() => {
                const visible = el => {
                    const style = getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.display !== 'none' && style.visibility !== 'hidden'
                        && !el.hidden && (rect.width > 0 || rect.height > 0);
                };
                const nameOf = el =>
                    (el.getAttribute('aria-label') || '').trim()
                    || (el.getAttribute('aria-labelledby')
                        ? (document.getElementById(el.getAttribute('aria-labelledby'))?.textContent || '').trim()
                        : '')
                    || ([...(el.labels || [])].map(x => x.textContent.trim()).filter(Boolean).join(' | '))
                    || (el.textContent || '').trim()
                    || (el.querySelector?.('img[alt]')?.getAttribute('alt') || '').trim()
                    || (el.getAttribute('title') || '').trim();
                const out = {buttons:0, fields:0, links:0, failures:[]};
                for (const el of document.querySelectorAll('button,input,select,textarea,a[href]')) {
                    if (!visible(el)) continue;
                    const tag = el.tagName.toLowerCase();
                    if (tag === 'button') {
                        out.buttons++;
                        const name = nameOf(el);
                        if (!name) out.failures.push({kind:'button-name', html:el.outerHTML.slice(0,240)});
                        const type = (el.getAttribute('type') || 'submit').toLowerCase();
                        const clickBound = el.getAttribute('data-qa-bound-click') === '1';
                        const form = el.closest('form');
                        const submitBound = type === 'submit' && form
                            && form.getAttribute('data-qa-bound-submit') === '1';
                        if (!clickBound && !submitBound) {
                            out.failures.push({kind:'button-handler', name, html:el.outerHTML.slice(0,240)});
                        }
                    } else if (tag === 'a') {
                        out.links++;
                        const name = nameOf(el);
                        const href = (el.getAttribute('href') || '').trim();
                        if (!name) out.failures.push({kind:'link-name', html:el.outerHTML.slice(0,240)});
                        if (!href || /^javascript:/i.test(href)) {
                            out.failures.push({kind:'link-href', name, href});
                        }
                    } else {
                        if (el.getAttribute('type') === 'hidden') continue;
                        out.fields++;
                        const name = nameOf(el);
                        if (!name) out.failures.push({kind:'field-name', html:el.outerHTML.slice(0,240)});
                    }
                }
                return out;
            }"""
        )
        surfaces.append({"role": role, "tab": tab, **result})
        if result["failures"]:
            failures.append({"role": role, "tab": tab, "items": result["failures"]})

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        for role in ("platform", "organizer", "agency"):
            context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="ar-YE")
            context.add_init_script(
                """(() => {
                    const original = EventTarget.prototype.addEventListener;
                    EventTarget.prototype.addEventListener = function(type, listener, options) {
                        try {
                            if (this instanceof Element && ['click','submit','change','input'].includes(type)) {
                                this.setAttribute('data-qa-bound-' + type, '1');
                            }
                        } catch (_) {}
                        return original.call(this, type, listener, options);
                    };
                })();"""
            )
            page = context.new_page()
            page.on("pageerror", lambda e: page_errors.append(str(e)))
            page.goto(URL + "/admin")
            page.get_by_label("البريد الإلكتروني", exact=True).fill(by_role[role]["email"])
            page.get_by_label("كلمة المرور", exact=True).fill(by_role[role]["password"])
            page.get_by_role("button", name="تسجيل الدخول", exact=True).click()
            page.get_by_role("heading", name="نظرة عامة", exact=True).wait_for()
            audit(page, role, "نظرة عامة")

            labels = page.locator("#admin-nav button").all_inner_texts()
            for label in labels:
                label = label.strip()
                if not label or label == "نظرة عامة":
                    continue
                nav = page.locator("#admin-nav").get_by_role("button", name=label, exact=True)
                nav.click()
                page.get_by_role("heading", name=label, exact=True).wait_for()
                page.wait_for_timeout(80)
                audit(page, role, label)

            context.close()
        browser.close()

    # Directly-created buttons outside the UI.button helper must either have
    # an onclick binding or be submit buttons; this also covers controls that
    # only appear inside modals and are not safe to click destructively in QA.
    # Extract the complete props object instead of stopping at the first "}".
    # Template strings such as \`${i} of 5\` contain braces and previously
    # caused false "raw-button-without-handler" failures before an onclick key.
    def js_props_object(source, start):
        open_brace = source.find("{", start)
        if open_brace < 0:
            raise AssertionError("button props object not found")
        depth = 0
        quote = None
        escaped = False
        for index in range(open_brace, len(source)):
            ch = source[index]
            if quote is not None:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == quote:
                    quote = None
                continue
            if ch in ("'", '"', "`"):
                quote = ch
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return source[start:index + 1], index + 1
        raise AssertionError("unterminated button props object")

    for source_name in ("admin.mjs", "public.mjs", "questions.mjs", "ui.mjs"):
        source = (ROOT / "web" / source_name).read_text(encoding="utf-8")
        cursor = 0
        while True:
            cursor = source.find("h('button',{", cursor)
            if cursor < 0:
                break
            snippet, cursor = js_props_object(source, cursor)
            if "onclick:" not in snippet and "type:'submit'" not in snippet:
                failures.append({"source": source_name, "kind": "raw-button-without-handler", "snippet": snippet[:300]})

    assert not page_errors, page_errors
    assert not failures, failures
    totals = {
        "surfaces": len(surfaces),
        "buttons": sum(x["buttons"] for x in surfaces),
        "fields": sum(x["fields"] for x in surfaces),
        "links": sum(x["links"] for x in surfaces),
    }
    report = {
        "status": "passed",
        "roles": ["platform", "organizer", "agency"],
        "totals": totals,
        "surfaces": surfaces,
        "page_errors": page_errors,
        "contract": "every visible admin control has an accessible name; every visible button is click/submit wired; every visible link has a non-javascript href",
        "note": "Destructive actions are wiring-checked here and are functionally covered by their dedicated API/browser journeys where applicable.",
    }
    (ROOT / "qa/browser-control-contract.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))
except Exception as exc:
    report = {
        "status": "failed",
        "reason": str(exc),
        "surfaces": locals().get("surfaces", []),
        "failures": locals().get("failures", []),
        "page_errors": locals().get("page_errors", []),
    }
    (ROOT / "qa/browser-control-contract.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))
    raise
finally:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    log.close()
