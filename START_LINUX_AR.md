# PulseX — دليل تشغيل النسخة المستقلة على Ubuntu 24.04

**حالة الحزمة:** مرشح إصدار مستقل؛ لا تُعتبر Final أو Production-Ready قبل قبول الاختبارات والقرار البشري. حافظنا على وظائف PulseX وواجهاته وQR/offline وSDK، ولم نُعد بناء المنتج من الصفر.

## المتطلبات

- Ubuntu 24.04 LTS مع Python 3.12 و `python3-venv`. الاختبار المستهدف يشمل x86_64، وARM64 للخادم CAX31 بعد اكتمال بوابته.
- تسليم المصدر المستقل: ZIP/TAR.GZ من Workflow `PulseX Ubuntu 24.04 Standalone Candidate`، أو فرع `release/linux-ubuntu2404-standalone-candidate-20261010`.
- اتصال إنترنت لإعداد التبعيات مرة واحدة؛ لا يحتاج التشغيل الاعتيادي إلى الإنترنت لتثبيت الحزم.
- تُعاد إنشاء `.venv` على Ubuntu ولا تُنسخ من Windows.

## الخطوات المحلية

نفّذ من جذر مجلد PulseX المستخرج:

```sh
python3 --version
python3 -m tools.prepare_runtime --profile local
.venv/bin/python -m tools.prepare_runtime --profile local --check
sh Start-Linux.sh
```

نقطة الدخول `Start-Linux.sh` لا تستدعي pip أو متصفحاً؛ عند غياب البيئة تخرج بخطأ واضح. الواجهة المحلية الافتراضية على `http://127.0.0.1:4310` والإدارة على `/admin`. بيانات الحسابات التجريبية تُكتب إلى `data/first-run-accounts.json` (محتوى حساس؛ احمِه ثم احذفه بعد الاستخدام). **لا ترفع الحسابات أو قاعدة البيانات إلى Git.**

بديل اختبار بمجلد بيانات مستقل:

```sh
export PULSEX_ENV=local
export SEED_DEMO=true
export DATA_DIR=/tmp/pulsex-linux-local
export HOST=127.0.0.1
export PORT=4310
export PUBLIC_ORIGIN=http://127.0.0.1:4310
sh Start-Linux.sh
```

قاعدة SQLite محلية للتجربة فقط، ومسارها النسبي ثابت إلى جذر الشيفرة وليس CWD المستدعي. عند تغيير `DATA_DIR` تحدد `DATABASE_URL` أيضاً إن أردت أن تكون قاعدة SQLite تحت `DATA_DIR` الجديد: `DATABASE_URL=sqlite:////tmp/pulsex-linux-local/db.sqlite3`. لا يغيّر `DATA_DIR` مسار قاعدة بيانات محددة صراحة.

## اختبار QA من نفس الحزمة

```sh
python3 -m tools.prepare_runtime --profile qa
.venv/bin/python -m tools.prepare_runtime --profile qa --check
.venv/bin/python -m pytest -q
sh Test-Hardening-Linux.sh
sh Test-Scale-Linux.sh
```

يلزم Node.js وChromium الخاص بـPlaywright لبعض اختبارات QA، ويتم تثبيتهما في بيئة الاختبار فقط. اختبار PostgreSQL يحتاج قاعدة منفصلة، `PX_POSTGRES_TEST_URL` وتصريح reset خاص بالاختبار؛ لا تستخدم بيانات فعلية.

## إعداد الإنتاج

مسار الإنتاج الحالي **PostgreSQL** فقط، لا SQLite. لا تفعّل `PX_NATIVE_POSTGRES_ACCEPTED` و`PX_LOAD_ACCEPTED` و`PX_SECURITY_ACCEPTED` و`PX_FIELD_OFFLINE_ACCEPTED` لإسكات الحارس؛ ترتبط بموافقات وأدلة جديدة. يُنفّذ الترحيل وbootstrap مرة واحدة قبل بدء عمال ASGI، ولا يجريان ضمن كل مصنع تطبيق. تجهيز VPS/DNS/TLS/Firewall/خدمات النظام ونشر السيرفر خارج حزمة تكييف التطبيق.

## ملفات التشغيل والإعدادات

`PULSEX_ENV`, `SEED_DEMO`, `REQUIRE_POSTGRES`, `DATABASE_URL`, `PUBLIC_ORIGIN`, `HOST`, `PORT`, `WEB_WORKERS`, `DATA_DIR`, `MEDIA_DIR`, `CREDENTIALS_PATH`, `BACKUP_DIR`, `GUEST_ID_SECRET` كلها متغيرات بيئة للعملية. ملفات `.env.*.example` **أمثلة فقط**؛ لا تُحمّل تلقائياً.

## القيود والأمان

لا تتشارك بيانات IndexedDB أو Service Worker تلقائياً بين أصلين (Origin) مختلفين. قبل الانتقال بين نطاقات الويب يجب مزامنة الطابور المعلق أو تصديره وفق إجراء آمن؛ لا تمسح التخزين لاستكمال الترقية. لا يعتبر نجاح `/api/health/ready` قبول أمن أو أداء أو تشغيل ميداني. اطلع على `LINUX_ACCEPTANCE_AR.md` للنتائج الحقيقية.
