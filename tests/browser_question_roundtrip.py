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

import httpx
from playwright.sync_api import sync_playwright
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import make_engine, submissions

TEMP = Path(tempfile.mkdtemp(prefix="pulsex-question-roundtrip-"))
with socket.socket() as port_socket:
    port_socket.bind(("127.0.0.1", 0))
    PORT = port_socket.getsockname()[1]

URL = f"http://127.0.0.1:{PORT}"
DB_PATH = TEMP / "questions.sqlite"
env = {
    **os.environ,
    "HOST": "127.0.0.1",
    "PORT": str(PORT),
    "PUBLIC_ORIGIN": URL,
    "DATABASE_URL": "sqlite:///" + str(DB_PATH),
    "CREDENTIALS_PATH": str(TEMP / "accounts.json"),
    "MEDIA_DIR": str(TEMP / "media"),
    "REQUIRE_POSTGRES": "false",
    "SEED_DEMO": "true",
    "PYTHONUTF8": "1",
}
(ROOT / "qa").mkdir(exist_ok=True)
log = open(ROOT / "qa/browser-question-roundtrip-server.log", "w", encoding="utf-8")
proc = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=log, stderr=log)


def q(code, qtype, order, **extra):
    item = {
        "kind": "question",
        "code": code,
        "title": code,
        "body": "",
        "order": order,
        "enabled": True,
        "qtype": qtype,
        "required": True,
        "form_id": "main",
    }
    item.update(extra)
    return item


QUESTIONS = [
    q("q_single", "single_choice", 1, options=["One", "Two"]),
    q("q_multi", "multiple_choice", 2, options=["One", "Two"], selection_min=2, selection_max=2),
    q("q_dropdown", "dropdown", 3, options=["One", "Two"]),
    q("q_image", "image_choice", 4, options=["One", "Two"]),
    q("q_yesno", "yes_no", 5),
    q("q_short", "short_text", 6),
    q("q_long", "long_text", 7),
    q("q_number", "number", 8, min=0, max=100),
    q("q_currency", "currency", 9, min=0, max=1000),
    q("q_rating", "rating", 10, min=1, max=5),
    q("q_nps", "nps", 11),
    q("q_slider", "slider", 12, min=1, max=5),
    q("q_ranking", "ranking", 13, options=["One", "Two"]),
    q("q_matrix", "matrix", 14, rows=["Row 1", "Row 2"], min=1, max=5),
    q("q_emoji", "emoji", 15, min=1, max=5),
    q("q_date", "date", 16),
    q("q_time", "time", 17),
    q("q_datetime", "datetime", 18),
    q("q_email", "email", 19),
    q("q_phone", "phone", 20),
    q("q_url", "url", 21),
    q("q_consent", "consent", 22, body="I agree"),
    q("q_allocation", "allocation", 23, options=["One", "Two"]),
    q("q_quiz", "quiz", 24, options=["One", "Two"], correct="o1"),
]

EXPECTED = {
    "q_single": "o1",
    "q_multi": ["o1", "o2"],
    "q_dropdown": "o2",
    "q_image": "o1",
    "q_yesno": "yes",
    "q_short": "test",
    "q_long": "long response",
    "q_number": 42,
    "q_currency": 10.5,
    "q_rating": 4,
    "q_nps": 8,
    "q_slider": 3,
    "q_ranking": ["o2", "o1"],
    "q_matrix": {"Row 1": 3, "Row 2": 4},
    "q_emoji": 4,
    "q_date": "2026-10-07",
    "q_time": "10:30",
    "q_datetime": "2026-10-07T10:30",
    "q_email": "qa@example.test",
    "q_phone": "+967777123456",
    "q_url": "https://example.test",
    "q_consent": True,
    "q_allocation": {"o1": 60, "o2": 40},
    "q_quiz": "o1",
}


def fs(page, code):
    return page.locator(f'fieldset[data-code="{code}"]')


try:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(120):
        try:
            with opener.open(URL + "/api/health", timeout=0.5):
                break
        except Exception:
            if proc.poll() is not None:
                raise RuntimeError((ROOT / "qa/browser-question-roundtrip-server.log").read_text(encoding="utf-8")[-4000:])
            time.sleep(0.1)
    else:
        raise RuntimeError("Question roundtrip server startup timeout")

    creds = json.loads((TEMP / "accounts.json").read_text(encoding="utf-8"))
    with httpx.Client(base_url=URL, timeout=30) as admin:
        agency = creds[2]
        login = admin.post("/api/auth/login", json={"email": agency["email"], "password": agency["password"]})
        assert login.status_code == 200, login.text
        csrf = login.json()["csrf"]
        headers = {"X-CSRF": csrf, "Origin": URL}
        site = admin.get("/api/admin/sites/agency-01").json()
        cfg = site["draft"]
        cfg["welcome"] = False
        cfg["records"] = QUESTIONS
        saved = admin.put(
            "/api/admin/sites/agency-01",
            json={"draft_rev": site["draft_rev"], "config": cfg},
            headers=headers,
        )
        assert saved.status_code == 200, saved.text
        published = admin.post(
            "/api/admin/sites/agency-01/publish",
            json={"draft_rev": saved.json()["draft_rev"]},
            headers=headers,
        )
        assert published.status_code == 200, published.text

    page_errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(viewport={"width": 1440, "height": 1400}, locale="ar-YE")
        page = context.new_page()
        page.on("pageerror", lambda e: page_errors.append(str(e)))
        page.goto(URL + "/e/demo/p/agency-01")
        page.get_by_role("heading", name="الجهة التجريبية 01", exact=True, level=1).wait_for()
        page.locator("#questions").get_by_role("link", name="ابدأ الاستبيان", exact=True).click()

        fs(page, "q_single").locator('input[value="o1"]').check()
        fs(page, "q_multi").locator('input[value="o1"]').check()
        fs(page, "q_multi").locator('input[value="o2"]').check()
        fs(page, "q_dropdown").locator("select").select_option("o2")
        fs(page, "q_image").locator('input[value="o1"]').check()
        fs(page, "q_yesno").locator('input[value="yes"]').check()
        fs(page, "q_short").locator("input").fill("test")
        fs(page, "q_long").locator("textarea").fill("long response")
        fs(page, "q_number").locator('input[type="number"]').fill("42")
        fs(page, "q_currency").locator('input[type="number"]').fill("10.5")
        fs(page, "q_rating").get_by_role("button", name="4", exact=True).click()
        fs(page, "q_nps").get_by_role("button", name="8", exact=True).click()
        slider = fs(page, "q_slider").locator('input[type="range"]')
        slider.evaluate("(el)=>{el.value='3';el.dispatchEvent(new Event('input',{bubbles:true}))}")
        fs(page, "q_ranking").get_by_role("button", name="↓", exact=True).first.click()
        matrix = fs(page, "q_matrix").locator("select")
        matrix.nth(0).select_option("3")
        matrix.nth(1).select_option("4")
        fs(page, "q_emoji").get_by_role("button", name="4", exact=True).click()
        fs(page, "q_date").locator('input[type="date"]').fill("2026-10-07")
        fs(page, "q_time").locator('input[type="time"]').fill("10:30")
        fs(page, "q_datetime").locator('input[type="datetime-local"]').fill("2026-10-07T10:30")
        fs(page, "q_email").locator('input[type="email"]').fill("qa@example.test")
        fs(page, "q_phone").locator('input[type="tel"]').fill("+967777123456")
        fs(page, "q_url").locator('input[type="url"]').fill("https://example.test")
        fs(page, "q_consent").locator('input[type="checkbox"]').check()
        allocation = fs(page, "q_allocation").locator('input[type="number"]')
        allocation.nth(0).fill("60")
        allocation.nth(1).fill("40")
        fs(page, "q_quiz").locator('input[value="o1"]').check()

        form = page.locator('form[data-form="main"]')
        form.get_by_role("button", name="إرسال الاستبيان", exact=True).click()
        form.get_by_text("شكرًا لك، تم استلام إجاباتك.", exact=True).wait_for(timeout=15000)
        page.screenshot(path=str(ROOT / "qa/browser-question-roundtrip.png"), full_page=True)
        browser.close()

    assert not page_errors, page_errors

    engine = make_engine("sqlite:///" + str(DB_PATH))
    with engine.connect() as conn:
        rows = conn.execute(
            select(submissions)
            .where(submissions.c.site_id == "agency-01", submissions.c.kind == "survey", submissions.c.target == "main")
            .order_by(submissions.c.received_at.desc())
        ).mappings().all()
    assert rows, "No survey submission persisted"
    answers = rows[0]["payload"]["answers"]
    assert answers == EXPECTED, {"expected": EXPECTED, "actual": answers}
    assert len(answers) == 24

    report = {
        "status": "passed",
        "backend": "SQLite",
        "browser": "Chromium",
        "real_http": True,
        "question_types": 24,
        "public_controls_exercised": 24,
        "submit_button_clicked": True,
        "server_persisted_all_answers": True,
        "answers": answers,
        "page_errors": page_errors,
    }
    (ROOT / "qa/browser-question-roundtrip.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))
except Exception as exc:
    report = {
        "status": "failed",
        "reason": str(exc),
        "page_errors": locals().get("page_errors", []),
    }
    (ROOT / "qa/browser-question-roundtrip.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))
    raise
finally:
    if proc.poll() is None:
        proc.terminate()
        proc.wait(timeout=10)
    log.close()
