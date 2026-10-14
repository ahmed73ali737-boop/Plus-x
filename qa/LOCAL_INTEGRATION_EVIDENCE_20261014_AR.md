# PulseX — تقرير اختبارات مستقلة لمصدر الاختبار المحلي — 14 أكتوبر 2026

**لا يمثل هذا التقرير نجاح CI على PR #25 أو قبولاً للإنتاج.** جرى فك أرشيف Linux Candidate السابق (GitHub Artifact ID 11796656183) والتحقق من SHA256 الخارجي `743c35c7f5f8ba4c09e295140fab25f6c5f0f15529a3ea7efe9baf2e213d4e70`، ثم تطبيق تعديلات PR #25 الوظيفية محليًا لاختبارها على FastAPI/SQLite.

## نطاق المطابقة
تم تأكيد Git blob SHA لسبعة ملفات في بيئة الاختبار مقابل نسخة GitHub في PR #25:
- `app/server.py` = `94cef3a24e82fec5a2231f5a0b25ed22af4bde57`
- `web/app.mjs` = `9ead0ad0b5393236da79f0e5a3c92881159f31d7`
- `web/admin.mjs` = `4bbecb49465ef0b01dd290e9c84611d401e4cc4e`
- `web/index.html` = `f8deaebceca2249784342112ab48eb7019388022`
- `web/sw.js` = `05153118cf519ea11dfa57b3ed653ebaa627ef6f`
- `app/application/shared_authorization.py` = `6892bc380a659fefb9acaa2dfc12d95723e386d2`
- `app/infrastructure/g_observability.py` = `7dd118871d3a4c901fe993d16ef2be49534556d1`

الـ22 أصلًا المنقول في PR #25 موجودة ومقفلة بواسطة `ops/consolidated-source-lock.json`، **لكن لم تُنفذ اختبارات كل تلك الملفات في بيئة الاختبار المحلية**. اختلافات بسيطة في نسخة الاختبار المحلية لوحدة Live Wall عن GitHub لا تسمح بوصف الفحص بأنه نجاح لنفس SHA الكامل.

## نتائج محلية فعلية
- `python -m pytest -q`: **239 passed in 51.30s**؛ Python 3.13.5، FastAPI 0.128.2، SQLAlchemy 2.0.50، SQLite.
- `node --check web/livewall.mjs` و`node tests/livewall_smoke.mjs`: **LIVEWALL_CONTRACT_PASS** على source overlay، يشمل رفض التصويت السري/غير المنشور وعدم إبقاء نتائج قديمة عند فشل الشبكة.
- `tests/test_livewall.py`: الاختباران المشمولان ضمن 239 نجحا؛ تحقق مسار العرض، والتحكم بالنشر والحجب بعد نشر المنظم.
- `python tests/native_acceptance.py`: PASS في بيئة SQLite محلية، يشمل الحفظ/النشر/التصدير وإعادة التشغيل.
- `python tests/security_hardening.py`: **13/13 bounded security checks**؛ ليس DAST/Pentest.
- `python tests/capacity_smoke.py`: **1000 read / 1000 submit، zero errors**؛ SQLite، خادم واحد localhost، بيانات اصطناعية وليس 1000 مستخدم بشري متزامن.
- `python tests/exhibition_scale_smoke.py`: **70 entities / 700 bundle requests، zero errors** في اختبار اصطناعي محلي.
- `python tests/guest_capacity_smoke.py`: **1000 guest IDs + check-ins، 100 duplicate replays**؛ بلا أخطاء، SQLite.
- اختبار HTTP حقيقي عبر Uvicorn و`GET /api/health`: نجح `status=hardening_candidate` و`database=sqlite` و`production_ready=false`.
- تجربة فرض IAM بلا provider رُفضت قبل إنشاء DB، والرفض من مزود تجريبي أعاد 403 عند إعداد المسودة والنشر. هذا لا يساوي تكامل IAM الفعلي.

## عوائق معلنة
- Chromium الحقيقي المحلي فشل بـ`net::ERR_BLOCKED_BY_ADMINISTRATOR` عند فتح localhost؛ لم يتم تجاوز سياسة المتصفح. رحلة Live Wall browser E2E ليست PASS.
- GitHub PR #25 Linux/Guest CI فشل قبل تنفيذ أي job step؛ لا يوجد same-head Windows/Linux/PG/Chromium PASS على أحدث SHA.
- مصدر Windows المحلي `8586c6c` (568 ملفًا وفق تقرير التدقيق) غير متاح للمقارنة.
- PostgreSQL production/Restore, RLS, External IAM/U-SEAS, security pentest, physical QR scanners, offline multi-device, five-day soak, field UAT **غير معتمدة**.

هذا تقرير تسليم مراجعة evidence محدود، وليس إغلاقًا لمصفوفة المتطلبات.
