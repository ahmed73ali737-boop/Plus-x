# قبول PostgreSQL الأصلي

هذا الاختبار **إتلافي** ويعمل فقط على قاعدة اختبار مخصصة. لا تستخدم قاعدة الإنتاج.

```bash
pip install -r requirements-postgres.txt
export PX_POSTGRES_TEST_URL='postgresql+psycopg://user:password@host:5432/pulsex_test'
export PX_ALLOW_POSTGRES_TEST_RESET=YES
python tests/postgres_native_acceptance.py
```

ينشئ الجداول من metadata، يختبر الاتصال، جميع الجداول، login، جهاز/heartbeat، submission وidempotency ووجود Foreign Keys. لا يدّعي اختبار RLS لأن Windows 07 ما زال يعتمد عزل التطبيق؛ RLS يبقى Release Gate منفصلًا إذا تقرر فرضه في قاعدة البيانات.
