"""Portable source check; does not constitute native PostgreSQL evidence."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
SQL = ROOT / "ops/postgresql/health_readonly.sql"

class CatalogSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SQL.read_text(encoding="utf-8")
        cls.statements = re.sub(r"(?m)^--.*$", "", cls.source)

    def test_read_only_transaction_and_bounded_timeouts(self):
        for item in ("BEGIN READ ONLY;", "COMMIT;", "SET LOCAL lock_timeout",
                     "SET LOCAL statement_timeout"):
            self.assertIn(item, self.source)

    def test_reject_data_mutating_sql(self):
        forbidden = r"\b(?:INSERT|UPDATE|DELETE|MERGE|TRUNCATE|DROP|ALTER|CREATE|EXEC|EXECUTE|CALL|DO|COPY|VACUUM|ANALYZE)\b"
        self.assertIsNone(re.search(forbidden, self.statements, re.IGNORECASE))

    def test_only_catalog_tables(self):
        for view in ("pg_stat_user_tables", "pg_class", "pg_index", "pg_inherits"):
            self.assertIn(view, self.source)
        self.assertNotRegex(self.statements, r"(?i)\bFROM\s+(?:ads|financial|accounting|accounts|asset|px_)\.")

if __name__ == "__main__":
    unittest.main()
