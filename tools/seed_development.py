"""Explicit, empty-database-only development demo with private credentials."""
import json
import os
from pathlib import Path
from sqlalchemy import update
from app.db import make_engine, users
from app.infrastructure.seed import seed_demo_data


def main():
    if os.environ.get('PULSEX_ENV') != 'local':
        raise RuntimeError('DEVELOPMENT_ONLY')
    os.environ['DATABASE_URL'] = 'postgresql+psycopg://pulsex:' + os.environ['POSTGRES_PASSWORD'] + '@postgres:5432/pulsex'
    engine = make_engine()
    try:
        result = seed_demo_data(engine, credentials_path=Path('/app/data/development-accounts.json'), count=2)
        if result:
            with engine.begin() as conn:
                conn.execute(update(users).where(users.c.email.in_([x['email'] for x in result])).values(must_change_password=1))
        print(json.dumps({'created': len(result), 'credentials_path': '/app/data/development-accounts.json'}))
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
