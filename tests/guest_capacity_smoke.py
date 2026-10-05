from __future__ import annotations

import json
import tempfile
import time
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db import event_guests, guest_checkins, guests
from app.server import create_app

ROOT=Path(__file__).resolve().parents[1]
COUNT=1000
BATCH=100

with tempfile.TemporaryDirectory(prefix="pulsex-guest-capacity-") as td:
    db_path=Path(td)/"capacity.sqlite"
    app=create_app("sqlite:///"+str(db_path),origin="http://testserver",seed_demo=True)
    client=TestClient(app)
    numbers=[]
    started=time.perf_counter()

    for start in range(0,COUNT,BATCH):
        items=[]
        for i in range(start,min(start+BATCH,COUNT)):
            local=770000000+i
            items.append({
                "client_id":str(uuid.uuid4()),
                "phone":f"+967{local}",
                "country_code":"+967",
                "consent":True,
                "name":f"Guest {i:04}",
                "organization":"Capacity QA",
            })
        response=client.post("/api/public/events/demo/guests/sync",json={"items":items})
        assert response.status_code==200,response.text
        receipts=response.json()["receipts"]
        assert len(receipts)==len(items)
        assert all(x["status"]=="accepted" for x in receipts),receipts
        numbers.extend(x["guest_number"] for x in receipts)

    assert len(numbers)==COUNT
    assert len(set(numbers))==COUNT

    with app.state.engine.connect() as db:
        assert db.execute(select(func.count()).select_from(guests)).scalar_one()==COUNT
        assert db.execute(select(func.count()).select_from(event_guests)).scalar_one()==COUNT

    organizer=next(x for x in app.state.seed_credentials if x["email"]=="organizer@pulsex.test")
    auth=client.post("/api/auth/login",json={"email":organizer["email"],"password":organizer["password"]})
    assert auth.status_code==200,auth.text
    client.headers.update({"X-CSRF":auth.json()["csrf"],"Origin":"http://testserver"})
    device=client.post("/api/admin/sites/event-demo/devices",json={"name":"Capacity Gate","device_type":"operator"})
    assert device.status_code==200,device.text
    token=device.json()["device_token"]

    manifest=client.get("/api/device/events/event-demo/guest-manifest",headers={"X-PulseX-Device-Token":token})
    assert manifest.status_code==200,manifest.text
    manifest_guests=manifest.json()["guests"]
    assert len(manifest_guests)==COUNT
    assert all("phone" not in x and "phone_e164" not in x for x in manifest_guests)

    scan_batches=[]
    for start in range(0,COUNT,BATCH):
        batch=[]
        for i,number in enumerate(numbers[start:start+BATCH],start=start):
            batch.append({
                "scan_id":str(uuid.uuid4()),
                "guest_number":number,
                "direction":"entry",
                "checkpoint":"capacity-main",
                "client_time":"2026-10-06T02:00:00+03:00",
            })
        scan_batches.append(batch)
        response=client.post(
            "/api/device/events/event-demo/guest-checkins",
            headers={"X-PulseX-Device-Token":token},
            json={"items":batch},
        )
        assert response.status_code==200,response.text
        receipts=response.json()["receipts"]
        assert all(x["status"]=="accepted" for x in receipts),receipts

    replay=client.post(
        "/api/device/events/event-demo/guest-checkins",
        headers={"X-PulseX-Device-Token":token},
        json={"items":scan_batches[0]},
    )
    assert replay.status_code==200,replay.text
    assert all(x["status"]=="duplicate" for x in replay.json()["receipts"])

    with app.state.engine.connect() as db:
        assert db.execute(select(func.count()).select_from(guest_checkins)).scalar_one()==COUNT

    elapsed=time.perf_counter()-started
    report={
        "status":"passed",
        "guests":COUNT,
        "unique_guest_numbers":len(set(numbers)),
        "manifest_guests":len(manifest_guests),
        "checkins":COUNT,
        "duplicate_replay_batch":BATCH,
        "backend":"SQLite",
        "elapsed_seconds":round(elapsed,3),
        "scope":"capacity smoke for guest registry/manifest/check-in; not a production load certificate",
    }
    out=ROOT/"qa/guest-capacity-smoke.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False))
