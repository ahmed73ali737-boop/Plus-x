"""The QA coordinator must never certify a pg_restore error as a restore."""
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import native_restore_coordinator as coordinator


class RestoreExitStatus(unittest.TestCase):
    def setUp(self):
        self.admin = SimpleNamespace(password=None, host='127.0.0.1', port=5432, username='postgres')
        self.source = 'cert_p0_111111111111'
        self.target = 'cert_p0_222222222222'

    def test_success_requires_both_commands_to_succeed(self):
        with patch.object(coordinator.subprocess, 'run', side_effect=[
            subprocess.CompletedProcess([], 0, b'dump-bytes', b''),
            subprocess.CompletedProcess([], 0, b'', b'')
        ]) as run:
            result = coordinator.restore(self.admin, self.source, self.target)
        self.assertEqual(result['backup']['bytes'], 10)
        self.assertEqual(run.call_count, 2)

    def test_exit_one_is_an_error_even_without_the_word_fatal(self):
        with patch.object(coordinator.subprocess, 'run', side_effect=[
            subprocess.CompletedProcess([], 0, b'dump-bytes', b''),
            subprocess.CompletedProcess([], 1, b'', b'pg_restore: error: could not execute query')
        ]):
            with self.assertRaisesRegex(RuntimeError, 'pg_restore_FAILED'):
                coordinator.restore(self.admin, self.source, self.target)

    def test_dump_failure_does_not_start_restore(self):
        with patch.object(coordinator.subprocess, 'run', return_value=
            subprocess.CompletedProcess([], 1, b'', b'permission denied')) as run:
            with self.assertRaisesRegex(RuntimeError, 'pg_dump_FAILED'):
                coordinator.restore(self.admin, self.source, self.target)
        self.assertEqual(run.call_count, 1)

    def test_unsafe_database_names_never_start_a_command(self):
        with patch.object(coordinator.subprocess, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'UNSAFE_COORDINATOR_DATABASE_NAME'):
                coordinator.restore(self.admin, 'production', self.target)
        run.assert_not_called()
