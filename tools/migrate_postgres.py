from __future__ import annotations

import json

from sqlalchemy import inspect, text

from app.db import make_engine, metadata
from app.domain import now
from app.core.migrations import MIGRATION_PATHS, expected_migration_checksums

MIGRATIONS=list(MIGRATION_PATHS)


def split_sql(script: str) -> list[str]:
    """Split simple migration SQL without treating semicolons in strings/comments as terminators."""
    statements=[]
    buf=[]
    single=False
    double=False
    line_comment=False
    i=0
    while i<len(script):
        ch=script[i]
        nxt=script[i+1] if i+1<len(script) else ""

        if line_comment:
            if ch=="\n":
                line_comment=False
                buf.append(ch)
            i+=1
            continue

        if not single and not double and ch=="-" and nxt=="-":
            line_comment=True
            i+=2
            continue

        if ch=="'" and not double:
            if single and nxt=="'":
                buf.extend([ch,nxt]);i+=2;continue
            single=not single
        elif ch=='"' and not single:
            double=not double

        if ch==";" and not single and not double:
            statement="".join(buf).strip()
            if statement:
                statements.append(statement)
            buf=[]
        else:
            buf.append(ch)
        i+=1

    tail="".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def execute_script(conn, script: str) -> int:
    count=0
    for statement in split_sql(script):
        conn.exec_driver_sql(statement)
        count+=1
    return count


def apply_migrations(engine) -> dict:
    if engine.dialect.name!="postgresql":
        raise RuntimeError("POSTGRESQL_REQUIRED_FOR_MIGRATIONS")

    existing=set(inspect(engine).get_table_names())
    fresh="px_sites" not in existing
    if fresh:
        metadata.create_all(engine)

    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS px_schema_migrations ("
            "migration_id VARCHAR(160) PRIMARY KEY,"
            "checksum VARCHAR(64) NOT NULL,"
            "applied_at VARCHAR(64) NOT NULL)"
        )

    applied=[]
    skipped=[]
    for path in MIGRATIONS:
        source=path.read_text(encoding="utf-8")
        migration_id=path.name
        checksum=expected_migration_checksums()[migration_id]
        with engine.begin() as conn:
            row=conn.execute(
                text("SELECT checksum FROM px_schema_migrations WHERE migration_id=:id"),
                {"id":migration_id},
            ).mappings().first()
            if row:
                if row["checksum"]!=checksum:
                    raise RuntimeError("MIGRATION_CHECKSUM_MISMATCH:"+migration_id)
                skipped.append(migration_id)
                continue
            execute_script(conn,source)
            conn.execute(
                text("INSERT INTO px_schema_migrations(migration_id,checksum,applied_at) VALUES(:id,:checksum,:at)"),
                {"id":migration_id,"checksum":checksum,"at":now()},
            )
            applied.append(migration_id)

    # Create newly introduced tables/indexes that may be additive but are not
    # represented by a historical migration file. Existing tables are not altered.
    metadata.create_all(engine)
    return {"status":"ok","fresh":fresh,"applied":applied,"skipped":skipped}


def main():
    result=apply_migrations(make_engine())
    print(json.dumps(result,ensure_ascii=False))


if __name__=="__main__":
    main()
