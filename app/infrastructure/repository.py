from __future__ import annotations

from sqlalchemy import select

from app.db import sites
from app.domain import fail


def fetch_one(conn, table, key: str, value):
    return conn.execute(select(table).where(table.c[key] == value)).mappings().first()


def get_site(conn, site_id: str):
    site = fetch_one(conn, sites, 'id', site_id)
    if not site:
        fail('SITE_NOT_FOUND', 404)
    return site
