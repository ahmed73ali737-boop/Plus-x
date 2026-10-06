import os

import pytest

from tools import production_gate


def production_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL","postgresql+psycopg://pulsex:0123456789abcdef@db:5432/pulsex")
    monkeypatch.setenv("PUBLIC_ORIGIN","https://events.example.com")
    monkeypatch.setenv("WEB_WORKERS","2")
    monkeypatch.setenv("SEED_DEMO","false")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL","admin@events.test")
    monkeypatch.setenv("PX_NATIVE_POSTGRES_ACCEPTED","true")
    monkeypatch.setenv("PX_LOAD_ACCEPTED","true")
    monkeypatch.setenv("PX_SECURITY_ACCEPTED","true")
    monkeypatch.setenv("PX_FIELD_OFFLINE_ACCEPTED","true")


def test_production_gate_rejects_missing_guest_identity_secret(monkeypatch):
    production_env(monkeypatch)
    monkeypatch.delenv("GUEST_ID_SECRET",raising=False)
    with pytest.raises(SystemExit) as exc:
        production_gate.main()
    assert exc.value.code==2


def test_production_gate_rejects_placeholder_guest_identity_secret(monkeypatch):
    production_env(monkeypatch)
    monkeypatch.setenv("GUEST_ID_SECRET","REPLACE_WITH_ANOTHER_64_RANDOM_HEX_CHARACTERS")
    with pytest.raises(SystemExit) as exc:
        production_gate.main()
    assert exc.value.code==2


def test_production_gate_accepts_independent_guest_identity_secret(monkeypatch):
    production_env(monkeypatch)
    monkeypatch.setenv("GUEST_ID_SECRET","0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")
    with pytest.raises(SystemExit) as exc:
        production_gate.main()
    assert exc.value.code==0
