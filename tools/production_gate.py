from __future__ import annotations

import json
import os
from urllib.parse import urlparse


def enabled(name: str) -> bool:
    return os.environ.get(name, "false").lower() == "true"


def evaluate_production_config(*, database_url=None, origin=None, seed_demo=None, workers=None) -> dict:
    db = database_url if database_url is not None else os.environ.get("DATABASE_URL", "")
    origin = origin if origin is not None else os.environ.get("PUBLIC_ORIGIN", "")
    guest_secret = os.environ.get("GUEST_ID_SECRET", "")
    bootstrap_email = os.environ.get("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
    if workers is None:
        try:
            workers = int(os.environ.get("WEB_WORKERS", "1") or 1)
        except ValueError:
            workers = 0
    demo_enabled = enabled("SEED_DEMO") if seed_demo is None else seed_demo
    checks = {
        "postgresql_required": db.startswith("postgresql+psycopg://"),
        "https_public_origin": urlparse(origin).scheme == "https" and bool(urlparse(origin).netloc),
        "demo_seed_disabled": demo_enabled is False,
        "multi_worker_configured": workers >= 2,
        "database_password_not_placeholder": "REPLACE_" not in db and "example" not in db.lower(),
        "guest_identity_secret_configured": len(guest_secret) >= 32
        and "REPLACE_" not in guest_secret
        and "example" not in guest_secret.lower(),
        "bootstrap_admin_email_configured": "@"
        in bootstrap_email
        and "."
        in bootstrap_email.split("@")[-1]
        and "example" not in bootstrap_email,
        "native_postgres_accepted": enabled("PX_NATIVE_POSTGRES_ACCEPTED"),
        "load_accepted": enabled("PX_LOAD_ACCEPTED"),
        "security_accepted": enabled("PX_SECURITY_ACCEPTED"),
        "field_offline_accepted": enabled("PX_FIELD_OFFLINE_ACCEPTED"),
    }
    return {
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "note": (
            "Release gate requires explicit evidence flags after native PostgreSQL, "
            "load, security and field/offline acceptance. Flags are acknowledgements, not tests themselves."
        ),
    }


def assert_production_ready(*, database_url=None, origin=None, seed_demo=None, workers=None) -> dict:
    result = evaluate_production_config(database_url=database_url, origin=origin,
                                        seed_demo=seed_demo, workers=workers)
    if result["status"] != "pass":
        failed = ",".join(name for name, ok in result["checks"].items() if not ok)
        raise RuntimeError("PRODUCTION_GATE_FAILED:" + failed)
    return result


def main():
    result = evaluate_production_config()
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] == "pass" else 2)


if __name__ == "__main__":
    main()
