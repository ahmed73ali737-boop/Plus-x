from __future__ import annotations

import argparse
import json

from sqlalchemy import delete, exists, select

from app.db import event_guests, guest_checkins, guest_presence, guests, make_engine


def orphan_guest_query():
    return (
        select(guests.c.id, guests.c.guest_number, guests.c.created_at)
        .where(
            ~exists(select(1).where(event_guests.c.guest_id == guests.c.id)),
            ~exists(select(1).where(guest_checkins.c.guest_id == guests.c.id)),
            ~exists(select(1).where(guest_presence.c.guest_id == guests.c.id)),
        )
        .order_by(guests.c.created_at.asc())
    )


def cleanup_orphan_guests(engine, *, apply: bool = False, expected_count: int | None = None) -> dict:
    with engine.begin() as conn:
        rows = [dict(row) for row in conn.execute(orphan_guest_query()).mappings()]
        count = len(rows)
        if not apply:
            return {"status": "dry_run", "count": count, "guests": rows}

        if expected_count is None:
            raise RuntimeError("EXPECTED_COUNT_REQUIRED")
        if expected_count != count:
            raise RuntimeError(f"EXPECTED_COUNT_MISMATCH:{expected_count}!={count}")

        ids = [row["id"] for row in rows]
        if ids:
            conn.execute(delete(guests).where(guests.c.id.in_(ids)))
        return {"status": "applied", "count": count, "deleted_ids": ids}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find guest rows with no event registration, check-in, or presence reference."
    )
    parser.add_argument("--apply", action="store_true", help="Delete exactly the dry-run set.")
    parser.add_argument(
        "--expected-count",
        type=int,
        default=None,
        help="Required with --apply; protects against deleting a changed set.",
    )
    args = parser.parse_args()
    result = cleanup_orphan_guests(
        make_engine(),
        apply=args.apply,
        expected_count=args.expected_count,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
