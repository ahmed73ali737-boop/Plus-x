from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import insert, select

from app.application.audit_service import new_id
from app.application.guest_service import event_guest_by_number, list_event_guests, staff_guest_view
from app.db import guest_checkins
from app.domain import fail, now, text


TERMINAL_SCAN_STATUSES={"accepted","duplicate","already_checked_in","already_checked_out","valid"}


def _access(event: dict) -> dict:
    draft=event.get("draft") if isinstance(event.get("draft"),dict) else {}
    access=draft.get("access_control") if isinstance(draft.get("access_control"),dict) else {}
    return {
        "anti_passback": access.get("anti_passback",True) is not False,
        "allow_reentry": access.get("allow_reentry",True) is not False,
        "manifest_max_age_minutes": int(access.get("manifest_max_age_minutes") or 60),
        "guest_types": access.get("guest_types") if isinstance(access.get("guest_types"),list) else [],
        "checkpoints": access.get("checkpoints") if isinstance(access.get("checkpoints"),list) else [
            {"key":"main","label":"البوابة الرئيسية","enabled":True,"allowed_guest_types":[],"start":"","end":""}
        ],
    }


def _checkpoint(access: dict, key: str) -> dict:
    for item in access["checkpoints"]:
        if item.get("key")==key:
            return item
    fail("CHECKPOINT_NOT_FOUND",403)


def _within_window(rule: dict) -> bool:
    current=datetime.now(timezone.utc)
    for field,lower in (("start",True),("end",False)):
        raw=rule.get(field)
        if not raw:
            continue
        try:
            value=datetime.fromisoformat(raw)
            if value.tzinfo is None:
                value=value.replace(tzinfo=timezone.utc)
        except (TypeError,ValueError):
            fail("CHECKPOINT_WINDOW_INVALID",500)
        if lower and current<value:
            return False
        if not lower and current>=value:
            return False
    return True


def evaluate_access(event: dict, guest: dict, checkpoint: str) -> dict:
    access=_access(event)
    rule=_checkpoint(access,checkpoint)
    if rule.get("enabled") is False:
        fail("CHECKPOINT_DISABLED",403)
    if not _within_window(rule):
        fail("CHECKPOINT_WINDOW_CLOSED",403)
    allowed=rule.get("allowed_guest_types") or []
    guest_type=guest.get("guest_type") or "visitor"
    if allowed and guest_type not in allowed:
        fail("GUEST_TYPE_NOT_ALLOWED",403)
    if (guest.get("event_guest_status") or guest.get("status")) not in ("registered","active"):
        fail("GUEST_NOT_ACTIVE",403)
    return {"access":access,"checkpoint":rule,"guest_type":guest_type}


def _last_scan(conn,event_id: str,guest_id: str):
    return conn.execute(
        select(guest_checkins)
        .where(guest_checkins.c.event_id==event_id,guest_checkins.c.guest_id==guest_id)
        .order_by(guest_checkins.c.scanned_at.desc(),guest_checkins.c.id.desc())
        .limit(1)
    ).mappings().first()


def _has_prior_entry(conn,event_id: str,guest_id: str) -> bool:
    return bool(conn.execute(
        select(guest_checkins.c.id)
        .where(
            guest_checkins.c.event_id==event_id,
            guest_checkins.c.guest_id==guest_id,
            guest_checkins.c.direction=="entry",
        )
        .limit(1)
    ).first())


def record_checkin(conn, event: dict, guest_number: str, body: dict, *, scanner_id: str | None, source: str) -> dict:
    event_id=event["id"]
    guest=event_guest_by_number(conn,event_id,guest_number)
    if not guest:
        fail("GUEST_NOT_REGISTERED",404)

    mode=body.get("mode") or body.get("direction") or "entry"
    if mode not in ("entry","exit","validate"):
        fail("CHECKIN_MODE_INVALID")
    checkpoint=text(body.get("checkpoint") or "main",40,True)
    policy=evaluate_access(event,guest,checkpoint)
    last=_last_scan(conn,event_id,guest["id"])
    inside=bool(last and last["direction"]=="entry")

    if mode=="validate":
        return {
            "scan_id":text(body.get("scan_id") or new_id(),64,True),
            "status":"valid",
            "direction":"validate",
            "checkpoint":checkpoint,
            "inside":inside,
            "guest":staff_guest_view(guest),
        }

    scan_id=text(body.get("scan_id") or new_id(),64,True)
    existing=conn.execute(select(guest_checkins).where(guest_checkins.c.id==scan_id)).mappings().first()
    if existing:
        return {
            "scan_id":scan_id,
            "status":"duplicate",
            "direction":existing["direction"],
            "checkpoint":existing["checkpoint"],
            "inside":existing["direction"]=="entry",
            "guest":staff_guest_view(guest),
        }

    access=policy["access"]
    if access["anti_passback"]:
        if mode=="entry" and inside:
            return {"scan_id":scan_id,"status":"already_checked_in","direction":"entry","checkpoint":checkpoint,"inside":True,"guest":staff_guest_view(guest)}
        if mode=="exit" and not inside:
            return {"scan_id":scan_id,"status":"already_checked_out","direction":"exit","checkpoint":checkpoint,"inside":False,"guest":staff_guest_view(guest)}
    if mode=="entry" and not access["allow_reentry"] and last and last["direction"]=="exit" and _has_prior_entry(conn,event_id,guest["id"]):
        fail("REENTRY_NOT_ALLOWED",403)

    conn.execute(insert(guest_checkins).values(
        id=scan_id,
        event_id=event_id,
        guest_id=guest["id"],
        guest_number=guest["guest_number"],
        scanner_id=scanner_id,
        source=source,
        direction=mode,
        checkpoint=checkpoint,
        client_time=text(body.get("client_time"),64),
        scanned_at=now(),
    ))
    return {
        "scan_id":scan_id,
        "status":"accepted",
        "direction":mode,
        "checkpoint":checkpoint,
        "inside":mode=="entry",
        "guest":staff_guest_view(guest),
    }


def build_guest_manifest(conn,event: dict) -> dict:
    event_id=event["id"]
    rows=list_event_guests(conn,event_id)
    scans=conn.execute(
        select(guest_checkins.c.guest_id,guest_checkins.c.direction,guest_checkins.c.scanned_at,guest_checkins.c.checkpoint)
        .where(guest_checkins.c.event_id==event_id)
        .order_by(guest_checkins.c.scanned_at.asc(),guest_checkins.c.id.asc())
    ).mappings()
    latest={}
    for scan in scans:
        latest[scan["guest_id"]]=dict(scan)

    manifest=[]
    for guest in rows:
        last=latest.get(guest["id"])
        manifest.append({
            "guest_number":guest["guest_number"],
            "name":guest.get("name") or "",
            "job_title":guest.get("job_title") or "",
            "organization":guest.get("organization") or "",
            "status":guest.get("status") or "registered",
            "guest_type":guest.get("guest_type") or "visitor",
            "registered_at":guest.get("registered_at"),
            "inside":bool(last and last["direction"]=="entry"),
            "last_direction":last["direction"] if last else "",
            "last_scanned_at":last["scanned_at"] if last else "",
            "last_checkpoint":last["checkpoint"] if last else "",
        })
    access=_access(event)
    version_source=json.dumps({"guests":manifest,"access_control":access},ensure_ascii=False,sort_keys=True,separators=(",",":"))
    return {
        "event_id":event_id,
        "generated_at":now(),
        "manifest_version":hashlib.sha256(version_source.encode("utf-8")).hexdigest()[:20],
        "guest_count":len(manifest),
        "access_control":access,
        "guests":manifest,
    }
