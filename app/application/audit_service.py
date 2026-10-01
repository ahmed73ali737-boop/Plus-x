from __future__ import annotations

import uuid
from sqlalchemy import insert

from app.db import audit
from app.domain import now


def new_id() -> str:
    return str(uuid.uuid4())


def write_audit(conn, user, site_id, action: str, detail=None) -> None:
    conn.execute(
        insert(audit).values(
            id=new_id(),
            user_id=user['id'] if user else None,
            site_id=site_id,
            action=action,
            at=now(),
            details=detail or {},
        )
    )
