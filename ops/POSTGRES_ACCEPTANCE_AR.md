# قبول PostgreSQL الأصلي — Windows 12

الاختبار إتلافي ويعمل فقط على قاعدة اختبار مخصصة:

```bash
pip install -r requirements-postgres.txt
export PX_POSTGRES_TEST_URL='postgresql+psycopg://user:password@host:5432/pulsex_test'
export PX_ALLOW_POSTGRES_TEST_RESET=YES
python tests/postgres_native_acceptance.py
```

الاختبار يبدأ من schema سابقة عبر `ops/001_full_schema_postgres.sql` ثم:
- يشغل `tools/migrate_postgres.py`.
- يطبق 002/003/004 ويسجل checksum في `px_schema_migrations`.
- يعيد التشغيل ويتحقق من idempotent skip.
- يتحقق من جميع metadata tables وForeign Keys.
- login/device/heartbeat/submission/idempotency.
- يسجل نفس الهاتف 16 مرة بالتوازي عبر عدة عملاء وصيغ محلية/دولية.
- يجب أن تكون النتيجة Guest row واحد وEvent registration واحد وGuest number واحد.

لا يدعي هذا الاختبار PostgreSQL RLS؛ العزل الحالي Application-level ومغطى باختبارات scope. إذا تقرر فرض RLS فهو Gate إضافي مستقل.
