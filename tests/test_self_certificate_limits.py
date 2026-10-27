"""Shared certificate rate buckets survive independent workers and restart."""
from concurrent.futures import ThreadPoolExecutor
import os

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine

from app.application.self_certificate_limits import consume
from app.self_certificates_db import rate_buckets


def _assert_shared_bucket(url):
    timeout_option = 'timeout' if url.startswith('sqlite:') else 'connect_timeout'
    engines = [create_engine(url, connect_args={timeout_option: 20}) for _ in range(2)]
    try:
        rate_buckets.create(engines[0])

        def attempt(index):
            engine = engines[index % len(engines)]
            try:
                consume(engine, 'certificate-submit', 'synthetic-browser', limit=30)
                return True
            except HTTPException as error:
                assert error.status_code == 429 and error.detail == 'RATE_LIMIT'
                return False

        with ThreadPoolExecutor(max_workers=20) as pool:
            accepted = list(pool.map(attempt, range(100)))

        assert sum(accepted) == 30
        assert accepted.count(False) == 70

        # A new engine models a restarted web worker. Its decision must use
        # the same persisted bucket, not a process-local counter.
        restarted = create_engine(url, connect_args={timeout_option: 20})
        try:
            with pytest.raises(HTTPException) as error:
                consume(restarted, 'certificate-submit', 'synthetic-browser', limit=30)
            assert error.value.status_code == 429
            assert error.value.detail == 'RATE_LIMIT'
        finally:
            restarted.dispose()
    finally:
        for engine in engines:
            engine.dispose()


def test_atomic_limit_is_shared_across_engines_and_survives_worker_restart(tmp_path):
    _assert_shared_bucket('sqlite:///' + str(tmp_path / 'shared-limits.sqlite'))


@pytest.mark.skipif(os.environ.get('CERTIFICATE_TEST_POSTGRES') != 'true',
                    reason='isolated PostgreSQL shared-counter rehearsal is opt-in')
def test_postgres_limit_is_shared_across_engines_and_survives_worker_restart():
    from tools.certificate_test_database import create_test_database, drop_test_database

    url = create_test_database()
    try:
        _assert_shared_bucket(url)
    finally:
        drop_test_database(url)
