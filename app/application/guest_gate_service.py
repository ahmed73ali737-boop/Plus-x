from __future__ import annotations

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError

from app.application.audit_service import new_id
from app.application.guest_service import event_guest_by_number, staff_guest_view
from app.db import guest_checkins, guest_presence
from app.domain import fail, now, text

SCAN_MODES=("entry","exit","validate")
PRESENCE_STATES=("outside","inside")


def _ensure_presence(conn, event_id: str, guest_id: str) -> dict:
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


def guest_presence_state(conn, event_id: str, guest_id: str) -> dict:
    return _ensure_presence(conn,event_id,guest_id)


def event_presence_map(conn, event_id: str) -> dict[str,dict]:
    rows=conn.execute(select(guest_presence).where(guest_presence.c.event_id==event_id)).mappings()
    return {row["guest_id"]:dict(row) for row in rows}


def validate_guest(conn, event_id: str, guest_number: str) -> dict:
    guest=event_guest_by_number(conn,event_id,guest_number)
    if not guest:
        fail("GUEST_NOT_REGISTERED",404)
    registration_status=guest.get("event_guest_status") or guest.get("status") or "registered"
    if registration_status not in ("registered","active"):
        return {
            "status":"invalid",
            "reason":"GUEST_STATUS_"+str(registration_status).upper(),
            "guest":staff_guest_view(guest),
            "presence":guest_presence_state(conn,event_id,guest["id"])["state"],
        }
    return {
        "status":"valid",
        "guest":staff_guest_view(guest),
        "presence":guest_presence_state(conn,event_id,guest["id"])["state"],
    }


def record_checkin(conn, event_id: str, guest_number: str, body: dict, *, scanner_id: str | None, source: str) -> dict:
    validated=validate_guest(conn,event_id,guest_number)
    guest=validated["guest"]
    mode=body.get("mode") or body.get("direction") or "entry"
    if mode not in SCAN_MODES:
        fail("SCAN_MODE_INVALID")
    checkpoint=text(body.get("checkpoint") or "main",80)

    if mode=="validate":
        return {
            "scan_id":None,
            "status":validated["status"],
            "mode":"validate",
            "direction":None,
            "checkpoint":checkpoint,
            "presence":validated["presence"],
            "guest":guest,
        }

    scan_id=text(body.get("scan_id") or new_id(),64,True)
    existing=conn.execute(select(guest_checkins).where(guest_checkins.c.id==scan_id)).mappings().first()
    if existing:
        presence=guest_presence_state(conn,event_id,guest["id"])
        return {
            "scan_id":scan_id,
            "status":"duplicate",
            "mode":existing["direction"],
            "direction":existing["direction"],
            "checkpoint":existing["checkpoint"],
            "presence":presence["state"],
            "guest":guest,
        }

    presence=_ensure_presence(conn,event_id,guest["id"])
    expected="outside" if mode=="entry" else "inside"
    next_state="inside" if mode=="entry" else "outside"
    transition=conn.execute(
        update(guest_presence)
        .where(
            guest_presence.c.event_id==event_id,
            guest_presence.c.guest_id==guest["id"],
            guest_presence.c.state==expected,
        )
        .values(
            state=next_state,
            last_scan_id=scan_id,
            last_direction=mode,
            last_checkpoint=checkpoint,
            updated_at=now(),
        )
    )
    if transition.rowcount!=1:
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
            "mode":mode,
            "direction":mode,
            "checkpoint":checkpoint,
            "presence":state,
            "last_scan_id":(current or presence).get("last_scan_id"),
            "last_checkpoint":(current or presence).get("last_checkpoint"),
            "guest":guest,
        }

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
        "mode":mode,
        "direction":mode,
        "checkpoint":checkpoint,
        "presence":next_state,
        "guest":guest,
    }
