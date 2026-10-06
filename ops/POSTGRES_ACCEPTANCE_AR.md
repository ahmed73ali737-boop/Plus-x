# قبول PostgreSQL الأصلي

هذا الاختبار **إتلافي** ويعمل فقط على قاعدة اختبار مخصصة. لا تستخدم قاعدة الإنتاج.

## التشغيل المحلي

```bash
pip install -r requirements-postgres.txt
export PX_POSTGRES_TEST_URL='postgresql+psycopg://user:password@host:5432/pulsex_test'
export PX_ALLOW_POSTGRES_TEST_RESET=YES
python tests/postgres_native_acceptance.py
```

يعتمد ملف القبول على نفس متطلبات التطبيق مع `httpx==0.28.1` لتشغيل FastAPI TestClient و`psycopg[binary]==3.3.6` لاتصال PostgreSQL.

## بوابة CI

`.github/workflows/g-postgres-native-gate.yml` تشغّل قاعدة PostgreSQL **18.6** مخصصة ومؤقتة داخل GitHub Actions، ثم تنفذ نفس `tests/postgres_native_acceptance.py`. لا توجد إعادة استخدام لقاعدة خارجية ولا يسمح الاختبار بالعمل دون `PX_ALLOW_POSTGRES_TEST_RESET=YES`.

الاختبار ينشئ الجداول من metadata، ويختبر الاتصال، جميع الجداول، login، جهاز/heartbeat، submission، idempotency ووجود Foreign Keys.

## حدود الدليل

نجاح هذه البوابة يثبت مسار التطبيق المذكور ضد PostgreSQL الأصلي فقط. لا يدّعي اختبار PostgreSQL RLS لأن العزل الحالي في هذا المسار ما يزال على مستوى التطبيق؛ RLS يبقى Release Gate منفصلًا إذا تقرر فرضه في قاعدة البيانات. كما لا يثبت browser/offline soak أو load/DAST/pentest أو UAT أو deployment أو Production Ready.
