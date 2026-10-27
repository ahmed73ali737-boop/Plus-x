"""Guard destructive QA operations before any server connection."""
import pytest
from tools import certificate_test_database as helper

def test_no_database_creation_without_explicit_test_server_opt_in(monkeypatch):
    monkeypatch.delenv('PX_ALLOW_CERTIFICATE_TEST_DATABASES',raising=False)
    monkeypatch.setattr(helper,'create_engine',lambda *a,**k:pytest.fail('Unexpected connection'))
    with pytest.raises(RuntimeError,match='APPROVAL_REQUIRED'):helper.create_test_database()

@pytest.mark.parametrize('url',['sqlite:///production.db','postgresql+psycopg://qa@qa/live_database','postgresql://qa@qa/postgres'])
def test_non_postgres_admin_database_is_rejected_without_connection(monkeypatch,url):
    monkeypatch.setenv('PX_ALLOW_CERTIFICATE_TEST_DATABASES','YES')
    monkeypatch.setenv('PX_CERTIFICATE_TEST_ADMIN_URL',url)
    monkeypatch.setattr(helper,'create_engine',lambda *a,**k:pytest.fail('Unexpected connection'))
    with pytest.raises(RuntimeError,match='ADMIN_URL_REQUIRED'):helper.create_test_database()

def test_refuses_to_drop_even_named_test_database_not_owned_by_this_process(monkeypatch):
    monkeypatch.setattr(helper,'create_engine',lambda *a,**k:pytest.fail('Unexpected connection'))
    with pytest.raises(RuntimeError,match='UNOWNED'):
        helper.drop_test_database('postgresql+psycopg://qa@qa/cert_p0_123456789abc')
