from __future__ import annotations

import hashlib
import hmac
import os
import re

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError

from app.application.audit_service import new_id
from app.db import event_guests, guest_checkins, guests
from app.domain import boolean, fail, now, text

PHONE_DIGIT_TRANSLATION=str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹','01234567890123456789')


def normalize_phone(raw, country_code="+967") -> str:
    """Normalize a phone number to a stable E.164-like representation.

    Local numbers are combined with country_code so the same guest cannot be
    created twice merely because one entry used a local format and another used
    an international format.
    """
    value=text(raw,40,True).translate(PHONE_DIGIT_TRANSLATION)
    compact=re.sub(r"[\s().-]+","",value)
    if compact.startswith("00"):
        compact="+"+compact[2:]
    if compact.startswith("+"):
        digits=compact[1:]
    else:
        digits=re.sub(r"\D","",compact)
        cc=re.sub(r"\D","",text(country_code,8,True).translate(PHONE_DIGIT_TRANSLATION))
        if not cc:
            fail("COUNTRY_CODE_INVALID")
        local=digits.lstrip("0")
        digits=local if local.startswith(cc) and len(local)>=len(cc)+6 else cc+local
    if not digits.isdigit() or len(digits)<8 or len(digits)>15:
        fail("PHONE_INVALID")
    return "+"+digits


def _guest_identity_key() -> bytes:
    # Production requires GUEST_ID_SECRET via the release gate. The deterministic
    # fallback exists only so local/demo/test databases remain reproducible.
    raw=os.environ.get("GUEST_ID_SECRET") or "pulsex-local-development-guest-identity-v1"
    return raw.encode("utf-8")


def _guest_hmac(namespace: str, phone_e164: str) -> str:
    return hmac.new(
        _guest_identity_key(),
        (namespace+":"+phone_e164).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def phone_hash(phone_e164: str) -> str:
    # A keyed digest prevents an exported hash column from becoming a simple
    # phone-number enumeration oracle.
    return _guest_hmac("phone",phone_e164)


def guest_number_for_phone(phone_e164: str) -> str:
    # Public guest numbers are keyed/opaque. They are associated with the phone
    # identity, but cannot be reproduced from the phone without the server key.
    h=_guest_hmac("guest-number",phone_e164).upper()
    return f"G-{h[:4]}-{h[4:8]}-{h[8:12]}-{h[12:16]}"


def guest_qr_payload(event_slug: str, guest_number: str, public_origin: str) -> str:
    return f"{public_origin.rstrip('/')}/e/{event_slug}/guest/{guest_number}"


def register_guest(conn, event: dict, body: dict, *, allow_profile_update: bool = False) -> dict:
    if event["kind"]!="event":
        fail("EVENT_REQUIRED",404)
    if body.get("consent") is not True and not boolean(body.get("consent",False)):
        fail("GUEST_CONSENT_REQUIRED")
    phone=normalize_phone(body.get("phone"),body.get("country_code") or "+967")
    p_hash=phone_hash(phone)
    g_number=guest_number_for_phone(phone)
    guest=conn.execute(
        select(guests).where(
            (guests.c.phone_e164==phone) |
            (guests.c.phone_hash==p_hash) |
            (guests.c.guest_number==g_number)
        )
    ).mappings().first()
    created=False
    values={
        "name":text(body.get("name"),160),
        "job_title":text(body.get("job_title") or body.get("job"),160),
        "organization":text(body.get("organization"),200),
        "updated_at":now(),
    }
    if guest:
        # A phone number is an identity/deduplication key, not proof of possession.
        # Public re-registration must not let somebody who knows a phone number
        # overwrite an established guest profile. Admin flows opt in explicitly.
        current=dict(guest)
        updates={"updated_at":values["updated_at"]}
        for key in ("name","job_title","organization"):
            incoming=values.get(key)
            if incoming and (allow_profile_update or not current.get(key)):
                updates[key]=incoming
        conn.execute(update(guests).where(guests.c.id==guest["id"]).values(**updates))
        guest={**current,**updates}
    else:
        candidate={
            "id":new_id(),
            "phone_e164":phone,
            "phone_hash":p_hash,
            "guest_number":g_number,
            **values,
            "status":"active",
            "created_at":now(),
        }
        try:
            # A savepoint converts simultaneous "same phone" inserts into a
            # deterministic lookup instead of aborting the outer transaction.
            with conn.begin_nested():
                conn.execute(insert(guests).values(**candidate))
            guest=candidate
            created=True
        except IntegrityError:
            guest=conn.execute(
                select(guests).where(
                    (guests.c.phone_e164==phone) |
                    (guests.c.phone_hash==p_hash) |
                    (guests.c.guest_number==g_number)
                )
            ).mappings().first()
            if not guest:
                raise
            guest=dict(guest)

    reg=conn.execute(
        select(event_guests).where(
            event_guests.c.event_id==event["id"],
            event_guests.c.guest_id==guest["id"],
        )
    ).mappings().first()
    event_registration_created=False
    if not reg:
        candidate_reg={
            "id":new_id(),
            "event_id":event["id"],
            "guest_id":guest["id"],
            "status":"registered",
            "guest_type":text(body.get("guest_type") or "visitor",40),
            "metadata_json":body.get("metadata") if isinstance(body.get("metadata"),dict) else {},
            "registered_at":now(),
            "updated_at":now(),
        }
        try:
            with conn.begin_nested():
                conn.execute(insert(event_guests).values(**candidate_reg))
            reg=candidate_reg
            event_registration_created=True
        except IntegrityError:
            reg=conn.execute(
                select(event_guests).where(
                    event_guests.c.event_id==event["id"],
                    event_guests.c.guest_id==guest["id"],
                )
            ).mappings().first()
            if not reg:
                raise
            reg=dict(reg)
    return {
        "id":guest["id"],
        "guest_number":guest["guest_number"],
        "phone":guest["phone_e164"],
        "name":guest.get("name") or "",
        "job_title":guest.get("job_title") or "",
        "organization":guest.get("organization") or "",
        "status":reg["status"],
        "created":created,
        "event_registration_created":event_registration_created,
    }


def event_guest_by_number(conn, event_id: str, guest_number: str):
    row=conn.execute(
        select(
            guests,
            event_guests.c.id.label("event_guest_id"),
            event_guests.c.status.label("event_guest_status"),
            event_guests.c.guest_type,
            event_guests.c.metadata_json,
            event_guests.c.registered_at,
        )
        .join(event_guests,event_guests.c.guest_id==guests.c.id)
        .where(event_guests.c.event_id==event_id,guests.c.guest_number==guest_number.upper())
    ).mappings().first()
    return dict(row) if row else None


def public_guest_view(row: dict) -> dict:
    return {
        "guest_number":row["guest_number"],
        "status":row.get("event_guest_status") or row.get("status") or "registered",
        "guest_type":row.get("guest_type") or "visitor",
        "registered_at":row.get("registered_at"),
    }


def staff_guest_view(row: dict) -> dict:
    return {
        "id":row["id"],
        "guest_number":row["guest_number"],
        "phone":row["phone_e164"],
        "name":row.get("name") or "",
        "job_title":row.get("job_title") or "",
        "organization":row.get("organization") or "",
        "status":row.get("event_guest_status") or row.get("status") or "registered",
        "guest_type":row.get("guest_type") or "visitor",
        "registered_at":row.get("registered_at"),
    }


def list_event_guests(conn, event_id: str) -> list[dict]:
    rows=conn.execute(
        select(
            guests,
            event_guests.c.id.label("event_guest_id"),
            event_guests.c.status.label("event_guest_status"),
            event_guests.c.guest_type,
            event_guests.c.metadata_json,
            event_guests.c.registered_at,
        )
        .join(event_guests,event_guests.c.guest_id==guests.c.id)
        .where(event_guests.c.event_id==event_id)
        .order_by(event_guests.c.registered_at.desc())
    ).mappings()
    return [staff_guest_view(dict(x)) for x in rows]


def record_checkin(conn, event_id: str, guest_number: str, body: dict, *, scanner_id: str | None, source: str) -> dict:
    guest=event_guest_by_number(conn,event_id,guest_number)
    if not guest:
        fail("GUEST_NOT_REGISTERED",404)
    scan_id=text(body.get("scan_id") or new_id(),64,True)
    existing=conn.execute(select(guest_checkins).where(guest_checkins.c.id==scan_id)).mappings().first()
    if existing:
        return {
            "scan_id":scan_id,
            "status":"duplicate",
            "direction":existing["direction"],
            "checkpoint":existing["checkpoint"],
            "guest":staff_guest_view(guest),
        }
    direction=body.get("direction") if body.get("direction") in ("entry","exit") else "entry"
    checkpoint=text(body.get("checkpoint") or "main",80)
    conn.execute(insert(guest_checkins).values(
        id=scan_id,
        event_id=event_id,
        guest_id=guest["id"],
        guest_number=guest["guest_number"],
        scanner_id=scanner_id,
        source=source,
        direction=direction,
        checkpoint=checkpoint,
        client_time=text(body.get("client_time"),64),
        scanned_at=now(),
    ))
    return {"scan_id":scan_id,"status":"accepted","direction":direction,"checkpoint":checkpoint,"guest":staff_guest_view(guest)}
