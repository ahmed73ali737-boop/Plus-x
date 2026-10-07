from __future__ import annotations

from sqlalchemy import insert, select

from app.application.audit_service import new_id
from app.db import event_guests, guests
from app.domain import now
from app.server import create_app
from tools.cleanup_orphan_guests import cleanup_orphan_guests


def test_orphan_guest_cleanup_is_dry_run_by_default_and_guarded_on_apply(tmp_path):
    app = create_app(
        f"sqlite:///{tmp_path/'cleanup.sqlite'}",
        origin="http://testserver",
        seed_demo=True,
    )
    engine = app.state.engine
    orphan_id = new_id()
    linked_id = new_id()

    with engine.begin() as conn:
        for guest_id, suffix in ((orphan_id, "ORPH"), (linked_id, "LINK")):
            conn.execute(
                insert(guests).values(
                    id=guest_id,
                    phone_e164=f"+96770000{suffix == 'LINK'}1{len(suffix)}",
                    phone_hash=(suffix.lower() * 16)[:64],
                    guest_number=f"G-{suffix}-0001-0002-0003",
                    name=suffix,
                    job_title="",
                    organization="",
                    status="active",
                    created_at=now(),
                    updated_at=now(),
                )
            )
        conn.execute(
            insert(event_guests).values(
                id=new_id(),
                event_id="event-demo",
                guest_id=linked_id,
                status="registered",
                guest_type="visitor",
                pass_number=None,
                pass_token_hash=None,
                metadata_json={},
                registered_at=now(),
                updated_at=now(),
            )
        )

    dry = cleanup_orphan_guests(engine)
    assert dry["status"] == "dry_run"
    assert [row["id"] for row in dry["guests"]] == [orphan_id]

    try:
        cleanup_orphan_guests(engine, apply=True, expected_count=2)
    except RuntimeError as exc:
        assert str(exc).startswith("EXPECTED_COUNT_MISMATCH")
    else:
        raise AssertionError("guarded apply must reject a changed expected count")

    applied = cleanup_orphan_guests(engine, apply=True, expected_count=1)
    assert applied["status"] == "applied" and applied["deleted_ids"] == [orphan_id]

    with engine.connect() as conn:
        remaining = set(conn.execute(select(guests.c.id)).scalars())
    assert orphan_id not in remaining
    assert linked_id in remaining
