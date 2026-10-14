"""Stable project paths: never resolve operational files against caller CWD."""
from __future__ import annotations
from pathlib import Path
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]

def resolve_path(value: str | Path, *, root: Path = ROOT) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else root / path).resolve()

def resolve_database_url(raw: str, *, root: Path = ROOT) -> str:
    """Resolve only SQLite files; do not rewrite database server or SQLite URI URLs."""
    url = make_url(raw)
    if url.get_backend_name() != "sqlite" or url.database in (None, "", ":memory:"):
        return raw
    if url.query.get("uri", "").lower() == "true":
        return raw
    return str(url.set(database=str(resolve_path(url.database, root=root))))
