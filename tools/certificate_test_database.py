"""Create/drop only databases owned by this pytest process on a dedicated QA server."""
import os, re, secrets
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

_owned = set()

def _admin_url():
    raw=os.environ.get('PX_CERTIFICATE_TEST_ADMIN_URL','')
    if os.environ.get('PX_ALLOW_CERTIFICATE_TEST_DATABASES')!='YES':
        raise RuntimeError('DEDICATED_CERTIFICATE_TEST_SERVER_APPROVAL_REQUIRED')
    url=make_url(raw)
    if url.drivername!='postgresql+psycopg' or url.database!='postgres':
        raise RuntimeError('DEDICATED_POSTGRES_ADMIN_URL_REQUIRED')
    return url

def create_test_database():
    admin=_admin_url()
    name='cert_p0_'+secrets.token_hex(6)
    engine=create_engine(admin,isolation_level='AUTOCOMMIT')
    try:
        with engine.connect() as conn:conn.exec_driver_sql('CREATE DATABASE "'+name+'"')
    finally:engine.dispose()
    url=admin.set(database=name).render_as_string(hide_password=False)
    _owned.add(url)
    return url

def drop_test_database(raw):
    if raw not in _owned:
        raise RuntimeError('REFUSING_TO_DROP_UNOWNED_TEST_DATABASE')
    url=make_url(raw)
    if not re.fullmatch(r'cert_p0_[0-9a-f]{12}',url.database):
        raise RuntimeError('UNSAFE_TEST_DATABASE_NAME')
    engine=create_engine(_admin_url(),isolation_level='AUTOCOMMIT')
    try:
        with engine.connect() as conn:conn.exec_driver_sql('DROP DATABASE "'+url.database+'" WITH (FORCE)')
    finally:engine.dispose()
    _owned.remove(raw)

