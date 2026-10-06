from __future__ import annotations

import hashlib
from collections.abc import Mapping
import json
from datetime import datetime, timezone

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError

from app.application.audit_service import new_id
from app.application.guest_service import event_guest_by_number, list_event_guests, staff_guest_view
from app.db import guest_checkins, guest_presence, sites
from app.domain import fail, now, text

SCAN_MODES=("entry","exit","validate")
PRESENCE_STATES=("outside","inside")
TERMINAL_SCAN_STATUSES={"accepted","duplicate","already_inside","already_outside","valid","invalid"}


def _event(conn,event_or_id) -> dict:
    if isinstance(event_or_id,Mapping):
        return dict(event_or_id)
    event=conn.execute(select(sites).where(sites.c.id==event_or_id)).mappings().first()
    if not event or event["kind"]!="event":
        fail("EVENT_REQUIRED",404)
    return dict(event)


def access_config(event: dict) -> dict:
    draft=event.get("draft") if isinstance(event.get("draft"),dict) else {}
    raw=draft.get("access_control") if isinstance(draft.get("access_control"),dict) else {}
    return {
        "anti_passback":raw.get("anti_passback",True) is not False,
        "allow_reentry":raw.get("allow_reentry",True) is not False,
        "manifest_max_age_minutes":int(raw.get("manifest_max_age_minutes") or 7200),
        "guest_types":raw.get("guest_types") if isinstance(raw.get("guest_types"),list) else [
            {"key":"visitor","label":"زائر"},{"key":"vip","label":"VIP"},{"key":"staff","label":"طاقم"},
            {"key":"speaker","label":"متحدث"},{"key":"media","label":"إعلام"},{"key":"exhibitor","label":"عارض"},
        ],
        "checkpoints":raw.get("checkpoints") if isinstance(raw.get("checkpoints"),list) else [
            {"key":"main","label":"البوابة الرئيسية","enabled":True,"allowed_guest_types":[],"start":"","end":""}
        ],
    }


def _checkpoint_rule(access: dict,key: str):
    for item in access["checkpoints"]:
        if item.get("key")==key:
            return item
    return None


def _in_window(rule: dict) -> bool:
    current=datetime.now(timezone.utc)
    for field,is_start in (("start",True),("end",False)):
        raw=rule.get(field)
        if not raw:
            continue
        try:
            value=datetime.fromisoformat(raw)
            if value.tzinfo is None:
                value=value.replace(tzinfo=timezone.utc)
        except (TypeError,ValueError):
            return False
        if is_start and current<value:
            return False
        if not is_start and current>=value:
            return False
    return True


def _ensure_presence(conn,event_id: str,guest_id: str) -> dict:
    row=conn.execute(
        select(guest_presence).where(
            guest_presence.c.event_id==event_id,
            guest_presence.c.guest_id==guest_id,
        )
    ).mappings().first()
    if row:
        return dict(row)
    candidate={
        "event_id":event_id,
        "guest_id":guest_id,
        "state":"outside",
        "last_scan_id":None,
        "last_direction":None,
        "last_checkpoint":None,
        "updated_at":now(),
    }
    try:
        with conn.begin_nested():
            conn.execute(insert(guest_presence).values(**candidate))
        return candidate
    except IntegrityError:
        row=conn.execute(
            select(guest_presence).where(
                guest_presence.c.event_id==event_id,
                guest_presence.c.guest_id==guest_id,
            )
        ).mappings().first()
        if not row:
            raise
        return dict(row)


def guest_presence_state(conn,event_id: str,guest_id: str) -> dict:
    return _ensure_presence(conn,event_id,guest_id)


def event_presence_map(conn,event_id: str) -> dict[str,dict]:
    rows=conn.execute(select(guest_presence).where(guest_presence.c.event_id==event_id)).mappings()
    return {row["guest_id"]:dict(row) for row in rows}


def validate_guest(conn,event_or_id,guest_number: str,checkpoint: str="main") -> dict:
    event=_event(conn,event_or_id)
    event_id=event["id"]
    guest=event_guest_by_number(conn,event_id,guest_number)
    if not guest:
        fail("GUEST_NOT_REGISTERED",404)
    presence=guest_presence_state(conn,event_id,guest["id"])["state"]
    registration_status=guest.get("event_guest_status") or guest.get("status") or "registered"
    if registration_status not in ("registered","active"):
        return {"status":"invalid","reason":"GUEST_STATUS_"+str(registration_status).upper(),"guest":staff_guest_view(guest),"presence":presence}

    access=access_config(event)
    rule=_checkpoint_rule(access,checkpoint)
    if not rule:
        return {"status":"invalid","reason":"CHECKPOINT_NOT_FOUND","guest":staff_guest_view(guest),"presence":presence}
    if rule.get("enabled") is False:
        return {"status":"invalid","reason":"CHECKPOINT_DISABLED","guest":staff_guest_view(guest),"presence":presence}
    if not _in_window(rule):
        return {"status":"invalid","reason":"CHECKPOINT_WINDOW_CLOSED","guest":staff_guest_view(guest),"presence":presence}
    allowed=rule.get("allowed_guest_types") or []
    guest_type=guest.get("guest_type") or "visitor"
    if allowed and guest_type not in allowed:
        return {"status":"invalid","reason":"GUEST_TYPE_NOT_ALLOWED","guest":staff_guest_view(guest),"presence":presence}

    return {"status":"valid","guest":staff_guest_view(guest),"presence":presence,"checkpoint":rule,"access_control":access}


def _set_presence(conn,event_id: str,guest_id: str,state: str,scan_id: str,direction: str,checkpoint: str):
    conn.execute(
        update(guest_presence)
        .where(guest_presence.c.event_id==event_id,guest_presence.c.guest_id==guest_id)
        .values(state=state,last_scan_id=scan_id,last_direction=direction,last_checkpoint=checkpoint,updated_at=now())
    )


def _duplicate_scan_result(conn,event_id: str,guest_number: str,scan_id: str,mode: str,checkpoint: str,existing) -> dict:
    existing=dict(existing)
    if existing["guest_number"]!=guest_number.upper() or existing["direction"]!=mode or existing["checkpoint"]!=checkpoint:
        fail("SCAN_ID_CONFLICT",409)
    replay_guest=event_guest_by_number(conn,event_id,guest_number)
    if not replay_guest:
        fail("GUEST_NOT_REGISTERED",404)
    current=guest_presence_state(conn,event_id,replay_guest["id"])
    return {
        "scan_id":scan_id,"status":"duplicate","mode":existing["direction"],"direction":existing["direction"],
        "checkpoint":existing["checkpoint"],"presence":current["state"],"guest":staff_guest_view(replay_guest),
    }


def record_checkin(conn,event_or_id,guest_number: str,body: dict,*,scanner_id: str|None,source: str) -> dict:
    event=_event(conn,event_or_id)
    event_id=event["id"]
    mode=body.get("mode") or body.get("direction") or "entry"
    if mode not in SCAN_MODES:
        fail("SCAN_MODE_INVALID")
    checkpoint=text(body.get("checkpoint") or "main",40,True)

    # Resolve exact replay before evaluating mutable access rules. If an ACK was
    # lost, the same scan remains idempotent even after a gate closes or changes.
    if mode!="validate":
        scan_id=text(body.get("scan_id") or new_id(),64,True)
        existing=conn.execute(select(guest_checkins).where(guest_checkins.c.id==scan_id)).mappings().first()
        if existing:
            return _duplicate_scan_result(conn,event_id,guest_number,scan_id,mode,checkpoint,existing)

    validated=validate_guest(conn,event,guest_number,checkpoint)
    guest=validated["guest"]
    if mode=="validate":
        return {
            "scan_id":text(body.get("scan_id") or new_id(),64,True),
            "status":validated["status"],
            "reason":validated.get("reason"),
            "mode":"validate",
            "direction":None,
            "checkpoint":checkpoint,
            "presence":validated["presence"],
            "guest":guest,
        }
    if validated["status"]!="valid":
        fail(validated.get("reason") or "ACCESS_DENIED",403)

    presence=_ensure_presence(conn,event_id,guest["id"])
    access=validated["access_control"]
    expected="outside" if mode=="entry" else "inside"
    next_state="inside" if mode=="entry" else "outside"

    if mode=="entry" and not access["allow_reentry"] and presence.get("last_direction")=="exit" and presence.get("last_scan_id"):
        fail("REENTRY_NOT_ALLOWED",403)

    if access["anti_passback"]:
        transition=conn.execute(
            update(guest_presence)
            .where(
                guest_presence.c.event_id==event_id,
                guest_presence.c.guest_id==guest["id"],
                guest_presence.c.state==expected,
            )
            .values(
                state=next_state,last_scan_id=scan_id,last_direction=mode,last_checkpoint=checkpoint,updated_at=now(),
            )
        )
        if transition.rowcount!=1:
            replay=conn.execute(select(guest_checkins).where(guest_checkins.c.id==scan_id)).mappings().first()
            if replay:
                return _duplicate_scan_result(conn,event_id,guest_number,scan_id,mode,checkpoint,replay)
            current=conn.execute(
                select(guest_presence).where(
                    guest_presence.c.event_id==event_id,
                    guest_presence.c.guest_id==guest["id"],
                )
            ).mappings().first()
            state=(current or presence)["state"]
            return {
                "scan_id":scan_id,
                "status":"already_inside" if mode=="entry" else "already_outside",
                "mode":mode,"direction":mode,"checkpoint":checkpoint,"presence":state,
                "last_scan_id":(current or presence).get("last_scan_id"),
                "last_checkpoint":(current or presence).get("last_checkpoint"),
                "guest":guest,
            }
    else:
        _set_presence(conn,event_id,guest["id"],next_state,scan_id,mode,checkpoint)

    try:
        with conn.begin_nested():
            conn.execute(insert(guest_checkins).values(
                id=scan_id,event_id=event_id,guest_id=guest["id"],guest_number=guest["guest_number"],
                scanner_id=scanner_id,source=source,direction=mode,checkpoint=checkpoint,
                client_time=text(body.get("client_time"),64),scanned_at=now(),
            ))
    except IntegrityError:
        replay=conn.execute(select(guest_checkins).where(guest_checkins.c.id==scan_id)).mappings().first()
        if replay:
            return _duplicate_scan_result(conn,event_id,guest_number,scan_id,mode,checkpoint,replay)
        raise
    return {
        "scan_id":scan_id,"status":"accepted","mode":mode,"direction":mode,"checkpoint":checkpoint,
        "presence":next_state,"guest":guest,
    }

def build_guest_manifest(conn,event_or_id) -> dict:
    event=_event(conn,event_or_id)
    event_id=event["id"]
    presence=event_presence_map(conn,event_id)
    guests=[]
    for guest in list_event_guests(conn,event_id):
        p=presence.get(guest["id"],{})
        guests.append({
            "guest_number":guest["guest_number"],
            "name":guest.get("name") or "",
            "organization":guest.get("organization") or "",
            "job_title":guest.get("job_title") or "",
            "guest_type":guest.get("guest_type") or "visitor",
            "status":guest.get("status") or "registered",
            "registered_at":guest.get("registered_at"),
            "presence":p.get("state","outside"),
            "last_direction":p.get("last_direction") or "",
            "last_checkpoint":p.get("last_checkpoint") or "",
            "presence_updated_at":p.get("updated_at") or "",
        })
    access=access_config(event)
    source=json.dumps({"guests":guests,"access_control":access},ensure_ascii=False,sort_keys=True,separators=(",",":"))
    return {
        "event_id":event_id,
        "generated_at":now(),
        "manifest_version":hashlib.sha256(source.encode("utf-8")).hexdigest()[:20],
        "guest_count":len(guests),
        "access_control":access,
        "guests":guests,
    }
