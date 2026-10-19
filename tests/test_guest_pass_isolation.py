"""Regression coverage for event-scoped bearer passes using synthetic guests."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from app.application.guest_service import (
    EVENT_PASS_PATTERN,
    backfill_event_pass_numbers,
    event_guest_by_number,
)
from app.db import event_guests, guest_checkins, guests
from app.server import create_app


@pytest.fixture
def environment(tmp_path):
    app=create_app(f"sqlite:///{tmp_path/'isolation.sqlite'}",origin="http://testserver",seed_demo=True)
    admin=TestClient(app)
    public=TestClient(app)
    credential=next(item for item in app.state.seed_credentials if item["email"]=="admin@pulsex.test")
    auth=admin.post("/api/auth/login",json={"email":credential["email"],"password":credential["password"]})
    assert auth.status_code==200,auth.text
    admin.headers.update({"Origin":"http://testserver","X-CSRF":auth.json()["csrf"]})
    created=admin.post("/api/admin/sites",json={"kind":"event","parent_id":"platform","slug":"isolation-b","title":"Synthetic event B"})
    assert created.status_code==200,created.text
    second_id=created.json()["id"]
    published=admin.post(f"/api/admin/sites/{second_id}/publish",json={"draft_rev":1})
    assert published.status_code==200,published.text
    yield app,admin,public,second_id
    admin.close()
    public.close()
    app.state.engine.dispose()


def register(client,slug="demo",**changes):
    payload={"phone":"+967700001234","name":"Synthetic original attendee","organization":"Private profile","consent":True,**changes}
    response=client.post(f"/api/public/events/{slug}/guests/register",json=payload)
    assert response.status_code==200,response.text
    return response.json()


def test_same_phone_gets_independent_event_credentials_with_one_internal_identity(environment):
    app,admin,public,b_id=environment
    a=register(public)
    b=register(public,"isolation-b",name="Unverified overwrite")
    assert a["guest_number"]!=b["guest_number"]
    assert EVENT_PASS_PATTERN.fullmatch(a["guest_number"])
    assert EVENT_PASS_PATTERN.fullmatch(b["guest_number"])
    assert a["pass_token"]!=b["pass_token"]
    for receipt in (a,b):
        assert not {"phone","phone_e164","name","organization","id","internal_guest_number"}&receipt.keys()
    with app.state.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(guests)).scalar_one()==1
        stored=conn.execute(select(guests)).mappings().one()
        assert stored["name"]=="Synthetic original attendee"
        assert stored["guest_number"] not in {a["guest_number"],b["guest_number"]}
        registrations=conn.execute(select(event_guests)).mappings().all()
        assert {row["pass_number"] for row in registrations}=={a["guest_number"],b["guest_number"]}


@pytest.mark.parametrize("suffix",["","/qr"])
def test_known_phone_in_other_event_cannot_recover_original_event_qr(environment,suffix):
    app,admin,public,b_id=environment
    a=register(public)
    b=register(public,"isolation-b")
    assert public.get(f"/api/public/events/demo/guests/{a['guest_number']}{suffix}").status_code==200
    assert public.get(f"/api/public/events/demo/guests/{b['guest_number']}{suffix}").status_code==404
    assert public.get(f"/api/public/events/isolation-b/guests/{a['guest_number']}{suffix}").status_code==404
    with app.state.engine.connect() as conn:
        internal=conn.execute(select(guests.c.guest_number)).scalar_one()
    for slug in ("demo","isolation-b"):
        assert public.get(f"/api/public/events/{slug}/guests/{internal}{suffix}").status_code==404


def test_pass_recovery_token_is_scoped_and_public_view_is_minimal(environment):
    app,admin,public,b_id=environment
    a=register(public)
    b=register(public,"isolation-b")
    for slug,foreign,owner in (("demo",b,a),("isolation-b",a,b)):
        denied=register(public,slug,pass_token=foreign["pass_token"])
        assert denied["status"]=="verification_required"
        assert not {"guest_number","qr_url","pass_token"}&denied.keys()
        recovered=register(public,slug,pass_token=owner["pass_token"])
        assert recovered["guest_number"]==owner["guest_number"]
        view=public.get(f"/api/public/events/{slug}/guests/{owner['guest_number']}").json()
        assert set(view)=={"guest_number","status","event_slug","event_title"}


def test_staff_list_manifest_and_scanner_use_only_event_pass(environment):
    app,admin,public,b_id=environment
    a=register(public)
    b=register(public,"isolation-b")
    device=admin.post("/api/admin/sites/event-demo/devices",json={"name":"Synthetic gate","device_type":"operator"})
    assert device.status_code==200,device.text
    headers={"X-PulseX-Device-Token":device.json()["device_token"]}
    manifest=public.get("/api/device/events/event-demo/guest-manifest",headers=headers)
    assert manifest.status_code==200,manifest.text
    assert [row["guest_number"] for row in manifest.json()["guests"]]==[a["guest_number"]]
    listing=admin.get("/api/admin/events/event-demo/guests").json()["guests"]
    assert listing[0]["guest_number"]==a["guest_number"]
    assert "internal_guest_number" not in listing[0]
    with app.state.engine.connect() as conn:
        internal=conn.execute(select(guests.c.guest_number)).scalar_one()
    for wrong in (b["guest_number"],internal):
        result=public.post("/api/device/events/event-demo/guest-checkins",headers=headers,json={"items":[{"scan_id":str(uuid.uuid4()),"guest_number":wrong,"mode":"entry","checkpoint":"main"}]})
        assert result.status_code==200,result.text
        assert result.json()["receipts"][0]["status"]=="rejected"
    scan_id=str(uuid.uuid4())
    body={"items":[{"scan_id":scan_id,"guest_number":a["guest_number"],"mode":"entry","checkpoint":"main"}]}
    accepted=public.post("/api/device/events/event-demo/guest-checkins",headers=headers,json=body)
    assert accepted.json()["receipts"][0]["status"]=="accepted"
    replay=public.post("/api/device/events/event-demo/guest-checkins",headers=headers,json=body)
    assert replay.json()["receipts"][0]["status"]=="duplicate"
    with app.state.engine.connect() as conn:
        scans=conn.execute(select(guest_checkins)).mappings().all()
        assert len(scans)==1 and scans[0]["guest_number"]==a["guest_number"]


def test_offline_registration_retry_keeps_same_event_pass_only(environment):
    app,admin,public,b_id=environment
    supplied="synthetic-client-owned-token-"+uuid.uuid4().hex
    item={"client_id":"lost-ack","phone":"+967700009876","consent":True,"pass_token":supplied}
    paths=["/api/public/events/demo/guests/sync","/api/public/events/isolation-b/guests/sync"]
    issued=[]
    for path in paths:
        first=public.post(path,json={"items":[item]}).json()["receipts"][0]
        retry=public.post(path,json={"items":[item]}).json()["receipts"][0]
        assert first["status"]==retry["status"]=="accepted"
        assert first["guest_number"]==retry["guest_number"]
        issued.append(first["guest_number"])
    assert issued[0]!=issued[1]


@pytest.mark.parametrize("legacy_pass",[None,"","G-1111-2222-3333-4444"])
def test_legacy_backfill_is_durable_idempotent_and_has_no_global_alias(environment,legacy_pass):
    app,admin,public,b_id=environment
    original=register(public)
    with app.state.engine.begin() as conn:
        conn.execute(update(event_guests).values(pass_number=legacy_pass))
        assert backfill_event_pass_numbers(conn)==1
        new_pass=conn.execute(select(event_guests.c.pass_number)).scalar_one()
        internal=conn.execute(select(guests.c.guest_number)).scalar_one()
        assert backfill_event_pass_numbers(conn)==0
    assert EVENT_PASS_PATTERN.fullmatch(new_pass)
    assert new_pass!=original["guest_number"]
    with app.state.engine.connect() as conn:
        assert event_guest_by_number(conn,"event-demo",internal) is None
        assert event_guest_by_number(conn,"event-demo",original["guest_number"]) is None
        found=event_guest_by_number(conn,"event-demo",new_pass)
        assert found["guest_number"]==new_pass
        assert found["internal_guest_number"]==internal
    assert admin.get("/api/admin/events/event-demo/guests").json()["guests"][0]["guest_number"]==new_pass


def test_authorized_recovery_lazily_allocates_missing_legacy_pass(environment):
    app,admin,public,b_id=environment
    a=register(public)
    with app.state.engine.begin() as conn:
        conn.execute(update(event_guests).values(pass_number=None))
    recovered=register(public,pass_token=a["pass_token"])
    assert recovered["guest_number"]!=a["guest_number"]
    with app.state.engine.connect() as conn:
        assert conn.execute(select(event_guests.c.pass_number)).scalar_one()==recovered["guest_number"]


def test_public_registration_cannot_inject_server_owned_admission_metadata(environment):
    app,admin,public,b_id=environment
    register(public,metadata={"invitation_id":"somebody-elses-invitation","selected_days":["2030-01-01"],"party_size":50,"entitlement_id":"other-entitlement","admission_managed":True,"source":"synthetic"})
    with app.state.engine.connect() as conn:
        metadata=conn.execute(select(event_guests.c.metadata_json)).scalar_one()
    assert metadata=={"source":"synthetic"}
