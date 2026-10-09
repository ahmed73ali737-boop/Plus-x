"""Validated application settings shared by CLI, ASGI factory and release gate."""
from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from .paths import resolve_path, resolve_database_url

def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    value = value.strip().lower()
    if value in ("1", "yes", "true", "on"):
        return True
    if value in ("0", "no", "false", "off"):
        return False
    raise ValueError("INVALID_BOOLEAN:" + name)

def bounded_int(name: str, value: str, low: int, high: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("INVALID_INTEGER:" + name) from exc
    if not low <= result <= high:
        raise ValueError("INTEGER_OUT_OF_RANGE:" + name)
    return result

@dataclass(frozen=True)
class Settings:
    environment: str
    production_mode: bool
    database_url: str
    public_origin: str
    seed_demo: bool
    host: str
    port: int
    workers: int
    data_dir: Path
    media_dir: Path
    credentials_path: Path
    backup_dir: Path

def load_settings(*, database_url: str | None = None, origin: str | None = None,
                  seed_demo: bool | None = None,
                  credentials_path: str | Path | None = None,
                  local_launcher: bool = False) -> Settings:
    environment = os.environ.get("PULSEX_ENV", "local").strip().lower() or "local"
    if environment not in ("local", "test", "production"):
        raise ValueError("UNKNOWN_PULSEX_ENV")
    prod = environment == "production" or env_bool("REQUIRE_POSTGRES")
    port = bounded_int("PORT",
        os.environ.get("PORT") or (os.environ.get("PULSEX_PORT") if local_launcher else None) or "4310", 1, 65535)
    workers = bounded_int("WEB_WORKERS", os.environ.get("WEB_WORKERS", "1"), 1, 128)
    db = database_url if database_url is not None else os.environ.get("DATABASE_URL", "sqlite:///./data/pulsex-pilot.sqlite3")
    db = resolve_database_url(db)
    public_origin = origin if origin is not None else os.environ.get("PUBLIC_ORIGIN", f"http://127.0.0.1:{port}")
    parsed = urlsplit(public_origin)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname or
            parsed.username is not None or parsed.password is not None or
            parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError("INVALID_PUBLIC_ORIGIN")
    seed = env_bool("SEED_DEMO", default=local_launcher and not prod) if seed_demo is None else seed_demo
    if not isinstance(seed, bool):
        raise ValueError("SEED_DEMO_NOT_BOOLEAN")
    data = resolve_path(os.environ.get("DATA_DIR") or "data")
    media = resolve_path(os.environ["MEDIA_DIR"]) if os.environ.get("MEDIA_DIR") else data / "media"
    creds = resolve_path(credentials_path) if credentials_path is not None else (
        resolve_path(os.environ["CREDENTIALS_PATH"]) if os.environ.get("CREDENTIALS_PATH") else data / "first-run-accounts.json")
    backup = resolve_path(os.environ["BACKUP_DIR"]) if os.environ.get("BACKUP_DIR") else resolve_path("backups")
    return Settings(environment,prod,db,public_origin.rstrip("/"),seed,
                    os.environ.get("HOST","127.0.0.1"),port,workers,
                    data,media,creds,backup)
