from __future__ import annotations

import csv
import io
import re

import qrcode
from fastapi import Request
from fastapi.responses import Response
from sqlalchemy import select

from app.application.device_service import authenticate_device
from app.application.guest_service import (
    event_guest_by_number,
    guest_qr_payload,
    list_event_guests,
    public_guest_view,
    record_checkin,
    register_guest,
)
from app.application.access import require_scope
from app.db import guest_checkins, sites
from app.domain import fail, now, text


def install_guest_routes(app, engine, public_origin: str, identify, site_row, log):
    def event_by_slug(conn, slug: str):
        event=conn.execute(select(sites).where(sites.c.slug==slug,sites.c.kind=="event")).mappings().first()
        if not event:
            fail("EVENT_NOT_FOUND",404)
        return dict(event)

    @app.get("/api/public/events/{event_slug}/guest-config")
    def guest_config(event_slug: str):
        with engine.connect() as c:
            event=event_by_slug(c,event_slug)
            return {
                "event_id":event["id"],
                "event_slug":event["slug"],
                "title":event["draft"].get("title") or event["slug"],
                "country_code":"+967",
                "guest_identity":"phone",
                "guest_number_strategy":"deterministic_phone_hash",
                "offline_edge_recommended":True,
            }

    @app.post("/api/public/events/{event_slug}/guests/register")
    def guest_register(event_slug: str, body: dict):
        with engine.begin() as c:
            event=event_by_slug(c,event_slug)
            guest=register_guest(c,event,body)
            guest["qr_url"]=guest_qr_payload(event["slug"],guest["guest_number"],public_origin)
            return guest

    @app.post("/api/public/events/{event_slug}/guests/sync")
    def guest_sync(event_slug: str, body: dict):
        items=body.get("items")
        if not isinstance(items,list) or not items or len(items)>100:
            fail("GUEST_BATCH_1_TO_100")
        receipts=[]
        with engine.begin() as c:
            event=event_by_slug(c,event_slug)
            for item in items:
                client_id=item.get("client_id") if isinstance(item,dict) else None
                try:
                    guest=register_guest(c,event,item)
                    receipts.append({
                        "client_id":client_id,
                        "status":"accepted",
                        "guest_number":guest["guest_number"],
                        "created":guest["created"],
                        "qr_url":guest_qr_payload(event["slug"],guest["guest_number"],public_origin),
                    })
                except Exception as exc:
                    detail=getattr(exc,"detail",str(exc))
                    receipts.append({"client_id":client_id,"status":"rejected","error":detail})
        return {"receipts":receipts}

    @app.get("/api/public/events/{event_slug}/guests/{guest_number}")
    def guest_public(event_slug: str, guest_number: str):
        with engine.connect() as c:
            event=event_by_slug(c,event_slug)
            guest=event_guest_by_number(c,event["id"],guest_number)
            if not guest:
                fail("GUEST_NOT_FOUND",404)
            return {**public_guest_view(guest),"event_slug":event["slug"],"event_title":event["draft"].get("title") or event["slug"]}

    @app.get("/api/public/events/{event_slug}/guests/{guest_number}/qr")
    def guest_qr(event_slug: str, guest_number: str):
        with engine.connect() as c:
            event=event_by_slug(c,event_slug)
            guest=event_guest_by_number(c,event["id"],guest_number)
            if not guest:
                fail("GUEST_NOT_FOUND",404)
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
        return Response(buff.getvalue(),media_type="image/png",headers={"Cache-Control":"private, max-age=300"})

    @app.get("/api/admin/events/{event_id}/guests")
    def admin_event_guests(event_id: str, request: Request):
        with engine.connect() as c:
            u,_=identify(request,c)
            event=require_scope(c,u,event_id)
            if event["kind"]!="event":
                fail("EVENT_REQUIRED",404)
            return {"guests":list_event_guests(c,event_id)}

    @app.get("/api/admin/events/{event_id}/guests/export")
    def admin_export_guests(event_id: str, request: Request):
        with engine.connect() as c:
            u,_=identify(request,c)
            event=require_scope(c,u,event_id)
            if event["kind"]!="event":
                fail("EVENT_REQUIRED",404)
            guest_rows=list_event_guests(c,event_id)
            scans=list(c.execute(
                select(guest_checkins)
                .where(guest_checkins.c.event_id==event_id)
                .order_by(guest_checkins.c.scanned_at.asc())
            ).mappings())
        stats={}
        for scan in scans:
            item=stats.setdefault(scan["guest_id"],{"entries":0,"exits":0,"first_entry":"","last_entry":""})
            if scan["direction"]=="entry":
                item["entries"]+=1
                item["first_entry"]=item["first_entry"] or scan["scanned_at"]
                item["last_entry"]=scan["scanned_at"]
            else:
                item["exits"]+=1
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
            event=require_scope(c,u,event_id)
            if event["kind"]!="event":
                fail("EVENT_REQUIRED",404)
            guest=register_guest(c,event,{**body,"consent":body.get("consent") is True})
            log(c,u,event_id,"guest_registered",{"guest_number":guest["guest_number"],"created":guest["created"]})
            return {**guest,"qr_url":guest_qr_payload(event["slug"],guest["guest_number"],public_origin)}

    @app.get("/api/admin/events/{event_id}/guest-checkins")
    def admin_guest_checkins(event_id: str, request: Request):
        with engine.connect() as c:
            u,_=identify(request,c)
            event=require_scope(c,u,event_id)
            if event["kind"]!="event":
                fail("EVENT_REQUIRED",404)
            rows=c.execute(
                select(guest_checkins)
                .where(guest_checkins.c.event_id==event_id)
                .order_by(guest_checkins.c.scanned_at.desc())
                .limit(500)
            ).mappings()
            return {"checkins":[dict(x) for x in rows]}

    @app.post("/api/admin/events/{event_id}/guest-checkins")
    def admin_guest_checkin(event_id: str, body: dict, request: Request):
        with engine.begin() as c:
            u,_=identify(request,c,True)
            event=require_scope(c,u,event_id)
            if event["kind"]!="event":
                fail("EVENT_REQUIRED",404)
            result=record_checkin(c,event_id,text(body.get("guest_number"),32,True),body,scanner_id=u["id"],source="admin")
            log(c,u,event_id,"guest_checkin",{"guest_number":result["guest"]["guest_number"],"direction":result["direction"],"checkpoint":result["checkpoint"]})
            return result

    @app.get("/api/device/events/{event_id}/guest-manifest")
    def device_guest_manifest(event_id: str, request: Request):
        raw=request.headers.get("X-PulseX-Device-Token","")
        with engine.connect() as c:
            device=authenticate_device(c,raw)
            if device["site_id"]!=event_id:
                fail("DEVICE_EVENT_SCOPE",403)
            event=site_row(c,event_id)
            if event["kind"]!="event":
                fail("EVENT_REQUIRED",404)
            manifest=[]
            for guest in list_event_guests(c,event_id):
                manifest.append({k:v for k,v in guest.items() if k!="phone"})
            return {"event_id":event_id,"generated_at":now(),"guests":manifest}

    @app.post("/api/device/events/{event_id}/guest-checkins")
    def device_guest_checkins(event_id: str, body: dict, request: Request):
        raw=request.headers.get("X-PulseX-Device-Token","")
        items=body.get("items")
        if not isinstance(items,list) or not items or len(items)>100:
            fail("CHECKIN_BATCH_1_TO_100")
        receipts=[]
        with engine.begin() as c:
            device=authenticate_device(c,raw)
            if device["site_id"]!=event_id:
                fail("DEVICE_EVENT_SCOPE",403)
            for item in items:
                try:
                    result=record_checkin(c,event_id,text(item.get("guest_number"),32,True),item,scanner_id=device["id"],source="device")
                    receipts.append({"scan_id":result["scan_id"],"status":result["status"],"guest_number":result["guest"]["guest_number"]})
                except Exception as exc:
                    receipts.append({"scan_id":item.get("scan_id"),"status":"rejected","error":getattr(exc,"detail",str(exc))})
        return {"receipts":receipts}
