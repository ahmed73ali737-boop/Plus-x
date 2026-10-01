# PulseX Windows 11 — تقرير QA والجولة الإضافية

## النتائج المنفذة

- **167 pytest PASS** للنطاق الكامل بعد إضافة Windows 11.
- **11 اختبارًا جديدًا** مخصصًا للهرمية، الأشخاص بلا حساب، الحساب لاحقًا، QR، Kiosk، idempotency وcompat migration.
- **31/31 HTTP local acceptance PASS** عبر خادم Uvicorn محلي حقيقي على Linux/SQLite.
- **13/13 security hardening PASS**.
- **9/9 Chromium DOM component PASS**؛ هذه اختبارات مكونات read-only وليست E2E شبكة كاملة.
- Windows 09 UX contract: PASS.
- Windows 10 role/template UX contract: PASS.
- Python compile: PASS.
- JavaScript syntax: PASS.
- OpenAPI/API contract بعد التعديل: **44 paths / 51 operations**.
- Branch-aware coverage لتطبيق `app/`: **88% إجماليًا**.

## سيناريوهات Windows 11 التي اختبرت

1. Platform Admin ينشئ فعالية ثم ينشئ Organizer account.
2. Organizer ينشئ Organization + Participation + page بدون أي User.
3. إضافة شخص/ممثل للمؤسسة بدون حساب.
4. إنشاء حساب إدارة لذلك الشخص لاحقًا وربطه بعضوية المؤسسة.
5. كلمة المرور المؤقتة تمنع الوصول إلى الإدارة حتى يتم تغييرها.
6. إيقاف Participation يسحب إدارة صفحة المشاركة من عضو المؤسسة بعد تغيير كلمة المرور.
7. الزائر بلا حساب يرسل Survey + Rating من مصدر QR.
8. مصدر QR يبقى محفوظًا في submission/metrics.
9. Offline/server contract: أول إرسال accepted، وإعادة نفس UUID تصبح duplicate ولا تكرر الصف.
10. جلستان Kiosk منفصلتان تحسبان كجلستين تاب مستقلتين.
11. فحص Frontend contract يؤكد IndexedDB stores/outbox/receipts، batch=50، online retry، device heartbeat، QR source وkiosk mode.
12. Compatibility migration تضيف `must_change_password` إلى قاعدة SQLite قديمة دون إعادة إنشاء البيانات.

## اكتشاف مهم تم إصلاحه

قبل Windows 11 كان `scope_id == site_id` يمنح حساب الجهة وصولًا مباشرًا حتى لو كانت Participation موقوفة. تم تعديل Access Policy: حساب الجهة المرتبط مباشرة بصفحتها أصبح خاضعًا لدورة حياة Participation؛ إيقاف المشاركة يسحب إدارة الصفحة.

## اختبار IndexedDB الفعلي

تمت محاولة تشغيل Chromium على origin لاختبار IndexedDB فعليًا، لكن بيئة الأدوات تعيد:

`ERR_BLOCKED_BY_ADMINISTRATOR`

وعلى `about:blank` تمنع IndexedDB بسبب opaque origin. لذلك لم أسجل هذا الاختبار PASS. المطلوب تشغيله على جهاز Windows/Android فعلي عبر HTTPS/localhost.

## ما لا يزال يحتاج بيئة خارجية

- Native Windows + Edge/Chrome E2E.
- Service Worker + IndexedDB native.
- جهازان فعليان مع انقطاع/عودة اتصال.
- Soak خمسة أيام.
- PostgreSQL migrations + RLS + native acceptance.
- HTTPS/domain.
- Load/Stress/Spike/Soak على PostgreSQL/host فعلي.
- DAST/Pentest.
- Business/Field UAT.
