from __future__ import annotations

import csv
import io
import re

import qrcode
from fastapi import Request
from fastapi.responses import Response

from app.api.errors import install_error_handlers
from app.application.access import require_event_permission
from app.application.device_service import authenticate_gate_device
from app.application.event_lookup import event_by_id_or_slug
from app.application.event_visibility import require_public_event
from app.application.guest_desk import require_event_kind, require_open_public_registration, staff_guest_list, staff_register
from app.application.guest_gate_service import (
    access_config,
    attendance_report,
    build_guest_manifest,
    checkin_overview,
    record_checkin,
    validate_guest,
)
from app.application.guest_service import event_guest_by_number, register_guest
from app.application.invitation_service import get_policy
from app.domain import fail, text
from app.domain.gate import checkpoint_key, device_checkpoint_allowed, scan_mode
from app.domain.guests import guest_qr_payload, public_guest_view, require_active_pass


def install_guest_routes(app, engine, public_origin: str, identify, site_row, log):
    install_error_handlers(app)

    def event_by_slug(conn, slug: str):
        return event_by_id_or_slug(conn, slug=slug)

    def gate_event(conn, event_id: str):
        return require_event_kind(site_row(conn, event_id))

    @app.get("/api/device/events/by-slug/{event_slug}/gate-context")
    def gate_context(event_slug: str, request: Request):
        with engine.connect() as c:
            event=event_by_slug(c,event_slug)
            authenticate_gate_device(c,request.headers.get("X-PulseX-Device-Token",""),event["id"])
            return {"event_id":event["id"],"slug":event["slug"],"title":event["draft"].get("title") or event["slug"],"access_control":access_config(event)}

    @app.get("/api/public/events/{event_slug}/guest-config")
    def guest_config(event_slug: str):
        with engine.connect() as c:
            event=event_by_slug(c,event_slug)
            require_public_event(c,event["id"])
            policy=get_policy(c,event["id"])
            return {
                "admission_managed":policy["enabled"],
                "registration_url":"/e/"+event["slug"]+"/register",
                "event_id":event["id"],
                "event_slug":event["slug"],
                "title":event["draft"].get("title") or event["slug"],
                "country_code":"+967",
                "guest_identity":"phone",
                "guest_number_strategy":"event_random_120",
                "offline_registration":"random_provisional_then_reconcile",
                "offline_edge_recommended":True,
            }

    @app.post("/api/public/events/{event_slug}/guests/register")
    def guest_register(event_slug: str, body: dict):
        with engine.begin() as c:
            event=event_by_slug(c,event_slug)
            require_open_public_registration(c,event)
            guest=register_guest(c,event,body)
            if not guest["verified"]:
                return {
                    "status":"verification_required",
                    "verification_required":True,
                    "created":False,
                    "event_registration_created":False,
                }
            return {
                "guest_number":guest["guest_number"],
                "status":guest["status"],
                "verification_required":False,
                "created":guest["created"],
                "event_registration_created":guest["event_registration_created"],
                "pass_token":guest.get("pass_token"),
                "qr_url":guest_qr_payload(event["slug"],guest["guest_number"],public_origin),
            }

    @app.post("/api/public/events/{event_slug}/guests/sync")
    def guest_sync(event_slug: str, body: dict):
        items=body.get("items")
        if not isinstance(items,list) or not items or len(items)>100:
            fail("GUEST_BATCH_1_TO_100")
        receipts=[]
        with engine.begin() as c:
            event=event_by_slug(c,event_slug)
            require_open_public_registration(c,event)
            for item in items:
                client_id=item.get("client_id") if isinstance(item,dict) else None
                try:
                    # Each offline item owns a savepoint. If this item is rejected,
                    # rolling back the savepoint removes *all* of its writes while
                    # allowing accepted siblings in the same batch to commit.
                    with c.begin_nested():
                        guest=register_guest(c,event,item)
                        if guest["verified"]:
                            receipt={
                                "client_id":client_id,
                                "status":"accepted",
                                "guest_number":guest["guest_number"],
                                "created":guest["created"],
                                "pass_token":guest.get("pass_token"),
                                "qr_url":guest_qr_payload(event["slug"],guest["guest_number"],public_origin),
                            }
                        else:
                            receipt={
                                "client_id":client_id,
                                "status":"verification_required",
                                "verification_required":True,
                            }
                    receipts.append(receipt)
                except Exception as exc:
                    detail=getattr(exc,"detail",str(exc))
                    receipts.append({"client_id":client_id,"status":"rejected","error":detail})
        return {"receipts":receipts}

    @app.get("/api/public/events/{event_slug}/guests/{guest_number}")
    def guest_public(event_slug: str, guest_number: str):
        with engine.connect() as c:
            event=event_by_slug(c,event_slug)
            guest=require_active_pass(event_guest_by_number(c,event["id"],guest_number))
            return {**public_guest_view(guest),"event_slug":event["slug"],"event_title":event["draft"].get("title") or event["slug"]}

    @app.get("/api/public/events/{event_slug}/guests/{guest_number}/qr")
    def guest_qr(event_slug: str, guest_number: str):
        with engine.connect() as c:
            event=event_by_slug(c,event_slug)
            guest=require_active_pass(event_guest_by_number(c,event["id"],guest_number))
        link=guest_qr_payload(event_slug,guest["guest_number"],public_origin)
        qr=qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_Q,
            box_size=10,
            border=4,
        )
        qr.add_data(link)
        qr.make(fit=True)
        image=qr.make_image(fill_color="black",back_color="white")
        buff=io.BytesIO()
        image.save(buff,format="PNG")
        return Response(buff.getvalue(),media_type="image/png",headers={"Cache-Control":"private, no-store","Referrer-Policy":"no-referrer"})

    @app.get("/api/admin/events/{event_id}/guests")
    def admin_event_guests(event_id: str, request: Request):
        with engine.connect() as c:
            u,_=identify(request,c)
            require_event_kind(require_event_permission(c,u,event_id,"guests.read"))
            rows=staff_guest_list(c,u,event_id)
            return {"guests":rows}

    @app.get("/api/admin/events/{event_id}/guests/export")
    def admin_export_guests(event_id: str, request: Request):
        with engine.connect() as c:
            u,_=identify(request,c)
            require_event_kind(require_event_permission(c,u,event_id,"guests.export"))
            guest_rows,stats=attendance_report(c,event_id)
        def safe(value):
            value=str(value or "")
            if re.match(r"^[\s\x00-\x1f]*[=+@-]",value):
                value="'"+value
            return value
        buff=io.StringIO()
        writer=csv.writer(buff)
        columns=["guest_number","name","phone","organization","job_title","status","guest_type","registered_at","entries","exits","first_entry","last_entry"]
        writer.writerow(columns)
        for guest in guest_rows:
            st=stats.get(guest["id"],{"entries":0,"exits":0,"first_entry":"","last_entry":""})
            writer.writerow([safe(guest.get(k)) for k in columns[:8]]+[st["entries"],st["exits"],st["first_entry"],st["last_entry"]])
        return Response(
            "\ufeff"+buff.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition":f'attachment; filename="pulsex-guests-{event_id}.csv"'},
        )

    @app.post("/api/admin/events/{event_id}/guests")
    def admin_register_guest(event_id: str, body: dict, request: Request):
        with engine.begin() as c:
            u,_=identify(request,c,True)
            event=require_event_kind(require_event_permission(c,u,event_id,"guests.register"))
            guest,view=staff_register(c,event,body,public_origin)
            log(c,u,event_id,"guest_registered",{"guest_number":guest["guest_number"],"created":guest["created"]})
            return view

    @app.get("/api/admin/events/{event_id}/guest-checkins")
    def admin_guest_checkins(event_id: str, request: Request):
        with engine.connect() as c:
            u,_=identify(request,c)
            require_event_kind(require_event_permission(c,u,event_id,"guests.read"))
            return checkin_overview(c,event_id)

    @app.post("/api/admin/events/{event_id}/guest-checkins")
    def admin_guest_checkin(event_id: str, body: dict, request: Request):
        with engine.begin() as c:
            u,_=identify(request,c,True)
            event=require_event_kind(require_event_permission(c,u,event_id,"guests.checkin"))
            result=record_checkin(c,event,text(body.get("guest_number"),32,True),body,scanner_id=u["id"],source="admin")
            log(c,u,event_id,"guest_checkin",{"guest_number":result["guest"]["guest_number"],"direction":result["direction"],"checkpoint":result["checkpoint"]})
            return result

    @app.get("/api/device/events/{event_id}/guest-manifest")
    def device_guest_manifest(event_id: str, request: Request):
        raw=request.headers.get("X-PulseX-Device-Token","")
        with engine.connect() as c:
            device=authenticate_gate_device(c,raw,event_id)
            event=gate_event(c,event_id)
            manifest=build_guest_manifest(c,event)
            policy=device.get("metadata_json") or {}
            manifest.update(device_valid_from=policy.get("valid_from"),device_valid_until=policy.get("valid_until"))
            if "checkpoints" in policy:
                manifest["allowed_checkpoints"]=policy["checkpoints"]
            return manifest

    @app.get("/api/device/events/{event_id}/guests/{guest_number}/validate")
    def device_validate_guest(event_id: str, guest_number: str, request: Request):
        raw=request.headers.get("X-PulseX-Device-Token","")
        with engine.begin() as c:
            device=authenticate_gate_device(c,raw,event_id)
            event=gate_event(c,event_id)
            checkpoint=checkpoint_key(request.query_params.get("checkpoint"))
            device_checkpoint_allowed(device.get("metadata_json"),checkpoint)
            mode=scan_mode(request.query_params.get("mode","entry"))
            result=validate_guest(c,event,text(guest_number,32,True),checkpoint,check_admission=mode!="exit",body={"quantity":request.query_params.get("quantity",1)})
            guest=result["guest"]
            return {
                "status":result["status"],
                "admission":result.get("admission"),
                "reason":result.get("reason"),
                "presence":result["presence"],
                "guest":{
                    "guest_number":guest["guest_number"],
                    "name":guest["name"],
                    "organization":guest["organization"],
                    "job_title":guest["job_title"],
                    "guest_type":guest["guest_type"],
                    "status":guest["status"],
                },
            }

    @app.post("/api/device/events/{event_id}/guest-checkins")
    def device_guest_checkins(event_id: str, body: dict, request: Request):
        raw=request.headers.get("X-PulseX-Device-Token","")
        items=body.get("items")
        if not isinstance(items,list) or not items or len(items)>100:
            fail("CHECKIN_BATCH_1_TO_100")
        receipts=[]
        with engine.begin() as c:
            device=authenticate_gate_device(c,raw,event_id)
            event=gate_event(c,event_id)
            for item in items:
                try:
                    if not isinstance(item,dict):
                        fail("SCAN_OBJECT_REQUIRED")
                    device_checkpoint_allowed(device.get("metadata_json"),item.get("checkpoint") or "main")
                    result=record_checkin(c,event,text(item.get("guest_number"),32,True),item,scanner_id=device["id"],source="device")
                    receipt={
                        "scan_id":result["scan_id"],
                        "status":result["status"],
                        "guest_number":result["guest"]["guest_number"],
                        "direction":result.get("direction"),
                        "checkpoint":result.get("checkpoint"),
                        "presence":result.get("presence"),
                        "reason":result.get("reason"),
                        "admission":result.get("admission"),
                    }
                    receipts.append(receipt)
                    if result["status"] in ("already_inside","already_outside","invalid"):
                        log(c,{"id":device["id"]},event_id,"guest_scan_blocked",receipt)
                except Exception as exc:
                    error=getattr(exc,"detail",str(exc))
                    item=item if isinstance(item,dict) else {}
                    receipt={"scan_id":item.get("scan_id"),"status":"rejected","error":error}
                    receipts.append(receipt)
                    log(c,{"id":device["id"]},event_id,"guest_scan_rejected",{
                        "guest_number":text(item.get("guest_number"),32),
                        "checkpoint":text(item.get("checkpoint") or "main",40),
                        "mode":text(item.get("mode") or item.get("direction") or "entry",20),
                        "error":error,
                    })
        return {"receipts":receipts}
