"""Create initial admin exactly once; credentials and DB writes fail together."""
from __future__ import annotations
import json
import os
import re
from pathlib import Path
from sqlalchemy import func, insert, select
from app.core.security import hash_password, new_temporary_password
from app.core.files import create_private_file
from app.core.paths import resolve_path
from app.db import ensure_compat_schema, make_engine, metadata, sites, users, versions
from app.domain import default_config,normalize_config,now
from app.application.audit_service import new_id

def bootstrap(engine, *, email: str, name: str, credentials_path: Path) -> dict:
    email=(email or "").strip().lower()
    name=(name or "").strip() or "Platform Administrator"
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",email):
        raise RuntimeError("BOOTSTRAP_ADMIN_EMAIL_INVALID")
    target=resolve_path(credentials_path)
    metadata.create_all(engine)
    ensure_compat_schema(engine)
    created=False
    try:
        with engine.begin() as conn:
            count_sites=conn.execute(select(func.count()).select_from(sites)).scalar_one()
            count_users=conn.execute(select(func.count()).select_from(users)).scalar_one()
            if count_sites and count_users:
                return {"status":"already_initialized","sites":count_sites,"users":count_users}
            if count_sites or count_users:
                raise RuntimeError("BOOTSTRAP_PARTIAL_DATABASE_REQUIRES_MANUAL_REVIEW")
            if target.exists() or target.is_symlink():
                raise RuntimeError("BOOTSTRAP_CREDENTIALS_FILE_ALREADY_EXISTS")
            cfg=default_config("PulseX — Live Experience Platform","platform")
            cfg["subtitle"]="منصة الفعاليات والتجارب التفاعلية"
            cfg["description"]="تم إنشاء مساحة المنصة الأساسية. أكمل الهوية والفعاليات والجهات من لوحة الإدارة."
            cfg["welcome"]=False
            cfg=normalize_config(cfg)
            published_at=now()
            conn.execute(insert(sites).values(id="platform",parent_id=None,event_id=None,
                       kind="platform",slug="platform",draft=cfg,draft_rev=1,published_version=1))
            conn.execute(insert(versions).values(site_id="platform",version=1,
                       config=cfg,published_at=published_at))
            password=new_temporary_password()
            conn.execute(insert(users).values(id=new_id(),email=email,name=name,
                       role="platform",scope_id="platform",
                       password_hash=hash_password(password),active=1,must_change_password=1))
            payload={"created_at":published_at,"email":email,
                     "temporary_password":password,"must_change_password":True,
                     "instruction":"Sign in, change the temporary password, then securely delete this file."}
            # Save in the transaction: file failure aborts the DB transaction.
            create_private_file(target,json.dumps(payload,ensure_ascii=False,indent=2))
            created=True
    except BaseException:
        # Includes DB-commit failure after the file was saved.
        if created:
            target.unlink(missing_ok=True)
        raise
    return {"status":"bootstrapped","email":email,"credentials_path":str(target)}

def main() -> None:
    engine=make_engine()
    try:
        result=bootstrap(engine,email=os.environ.get("BOOTSTRAP_ADMIN_EMAIL",""),
                name=os.environ.get("BOOTSTRAP_ADMIN_NAME","Platform Administrator"),
                credentials_path=Path(os.environ.get("BOOTSTRAP_CREDENTIALS_PATH","data/bootstrap-admin.json")))
        # Never print the password.
        print(json.dumps(result,ensure_ascii=False))
    finally:
        engine.dispose()

if __name__=="__main__":
    main()
