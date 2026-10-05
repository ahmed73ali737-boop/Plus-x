from __future__ import annotations

import json
import os
import re
from pathlib import Path

from sqlalchemy import func, insert, select

from app.core.security import hash_password, new_temporary_password
from app.db import ensure_compat_schema, make_engine, metadata, sites, users, versions
from app.domain import default_config, normalize_config, now
from app.application.audit_service import new_id


def bootstrap(engine, *, email: str, name: str, credentials_path: Path) -> dict:
    email=(email or "").strip().lower()
    name=(name or "").strip() or "Platform Administrator"
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",email):
        raise RuntimeError("BOOTSTRAP_ADMIN_EMAIL_INVALID")

    metadata.create_all(engine)
    ensure_compat_schema(engine)
    with engine.begin() as conn:
        site_count=conn.execute(select(func.count()).select_from(sites)).scalar_one()
        user_count=conn.execute(select(func.count()).select_from(users)).scalar_one()
        if site_count and user_count:
            return {"status":"already_initialized","sites":site_count,"users":user_count}
        if site_count or user_count:
            raise RuntimeError("BOOTSTRAP_PARTIAL_DATABASE_REQUIRES_MANUAL_REVIEW")
        if credentials_path.exists():
            raise RuntimeError("BOOTSTRAP_CREDENTIALS_FILE_ALREADY_EXISTS")

        cfg=default_config("PulseX — Live Experience Platform","platform")
        cfg["subtitle"]="منصة الفعاليات والتجارب التفاعلية"
        cfg["description"]="تم إنشاء مساحة المنصة الأساسية. أكمل الهوية والفعاليات والجهات من لوحة الإدارة."
        cfg["welcome"]=False
        cfg=normalize_config(cfg)
        published_at=now()
        conn.execute(insert(sites).values(
            id="platform",parent_id=None,event_id=None,kind="platform",slug="platform",
            draft=cfg,draft_rev=1,published_version=1,
        ))
        conn.execute(insert(versions).values(
            site_id="platform",version=1,config=cfg,published_at=published_at,
        ))

        password=new_temporary_password()
        user_id=new_id()
        conn.execute(insert(users).values(
            id=user_id,email=email,name=name,role="platform",scope_id="platform",
            password_hash=hash_password(password),active=1,must_change_password=1,
        ))

    credentials_path.parent.mkdir(parents=True,exist_ok=True)
    payload={
        "created_at":published_at,
        "email":email,
        "temporary_password":password,
        "must_change_password":True,
        "instruction":"Sign in once, change the temporary password immediately, then securely delete this file.",
    }
    credentials_path.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    try:
        credentials_path.chmod(0o600)
    except OSError:
        pass
    return {"status":"bootstrapped","email":email,"credentials_path":str(credentials_path)}


def main():
    email=os.environ.get("BOOTSTRAP_ADMIN_EMAIL","")
    name=os.environ.get("BOOTSTRAP_ADMIN_NAME","Platform Administrator")
    path=Path(os.environ.get("BOOTSTRAP_CREDENTIALS_PATH","data/bootstrap-admin.json"))
    result=bootstrap(make_engine(),email=email,name=name,credentials_path=path)
    # Never print the generated password.
    print(json.dumps(result,ensure_ascii=False))


if __name__=="__main__":
    main()
