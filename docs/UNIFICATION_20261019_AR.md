# توحيد Plus-x والتحقق من التطبيق والإدارة — 19 أكتوبر 2026

الحالة: مصدر موحد ومرشح اختبار؛ ليس اعتماد إنتاج أو إصدارًا نهائيًا.

## النطاق

جرد 28 فرعًا و13 طلب دمج مفتوحًا (#12، #13، #14، #15، #16، #17، #18، #20، #21، #22، #24، #25، #30). جميع رؤوس الفروع في UNIFICATION_BRANCH_HEADS_20261019.json محفوظة في تاريخ التكامل. لا حذف للفروع أو force push. طلب المستخدم الحالي يجيز توحيد المصدر في main؛ قيود النشر والإنتاج باقية.

اعتمدنا فرع integration/pulsex-consolidated-20261014 كأساس أحدث للتطبيق. ضممنا عقود UIP وParty وPostgreSQL والأصول الأخرى، وراجعنا تعارضات الفروع التاريخية مع الإبقاء على الإصلاحات الأحدث. الفروع القديمة لا تعيد factory startup أو SQLite rollback أو health/readiness أو guest identity أو UI أو Service Worker إلى نسخة أقدم.

تم الاحتفاظ بتعريفات CI التاريخية الأربعة في docs/archive/workflows بدل تكرار وظائف Windows/PostgreSQL الحالية أو تشغيل سير تكامل خارجي يحتاج إعدادات خاصة. بوابتا PulseX CI وguest-qr-ci وقيود release admission باقية. تم دمج تعطيل FastAPI automatic telemetry، والإبقاء على تثبيت shared observability مرة واحدة فقط.

## التطبيق والإدارة

التقنية الفعلية: Python/FastAPI + JavaScript modules، SQLite للتجربة المحلية وPostgreSQL لمسار الإنتاج. ليس مشروع Flutter أو .NET.

| الواجهة | المسار بعد التشغيل | الدليل |
|---|---|---|
| تطبيق الزائر والكتالوج | / | web/app.mjs وpublic.mjs؛ HTTP acceptance |
| صفحة الفعالية | /e/demo | HTTP acceptance |
| لوحة الإدارة | /admin | web/admin.mjs؛ login/CSRF/scope/publish/import/report acceptance |
| التسجيل وبطاقة QR | /e/demo/guest | web/guest.mjs وguest API؛ pytest |
| ماسح البوابة | /e/demo/scan | يتطلب جهازًا مصرحًا؛ ليس تحقق ماسح ميداني |
| شاشة النتائج | /live/demo | livewall.mjs؛ اختبارات API وJavaScript |
| تطبيق قابل للتثبيت | manifest + SW + أيقونات 192/512 | PWA contract؛ التثبيت على جهاز حقيقي لم يُختبر |

لوحة الإدارة تضم 19 تبويبًا: نظرة عامة، الهوية، الأقسام، المؤسسات والمشاركات، الزوار وQR، المحتوى، ترتيب التجربة، الأسئلة، التصويت، التقييم، الإعلانات، الحقائق، الاستيراد، النتائج، المعاينة، الأجهزة، الحسابات، التدقيق، أمان الحساب. ظهورها يتبع الدور والنطاق. الأدوار الحالية: المنصة، المنظم، الجهة. هذا ليس ادعاء اكتمال جميع الأدوار المقترحة في المواصفات.

شغّل Start-Windows.cmd أو جهّز بيئة Linux وفق DELIVERY_GUIDE_AR.md ثم Start-Linux.sh. العنوان الافتراضي http://127.0.0.1:4310. حسابات التجربة تُولّد محليًا في data/first-run-accounts.json أو CREDENTIALS_PATH؛ لا تُنشر بيانات الدخول في Git.

## التحقق وحدوده

- HTTP/SQLite على Linux: 32 فحصًا ناجحًا، منها تسجيل الدخول، حدود المنظم، CSRF، إنشاء سؤال ونشره، استبيان، منع تكرار الإدخال، تصويت، استيراد XLSX/CSV، إحصاءات، QR PNG، تصدير، وحفظ البيانات بعد إعادة التشغيل. qa/linux-local-acceptance.json.
- JavaScript: SDK (10 checks)، Live Wall، Storyboard core/UI، Session UI ناجحة.
- مصدر الأصول: 22/22 ملفًا مطابقًا للـsource lock، وفحص observability source lock ناجح.
- UIP preview: 8 اختبارات static ناجحة؛ ليس مزودًا خارجيًا عاملًا.
- pytest على المصدر المستقر: 294 passed و14 subtests passed في 100.12 ثانية؛ qa/unification-20261019/pytest.txt.
- Python compile وJavaScript syntax وgit diff --check ناجحة.
- Chromium الحقيقي محجوب: تنزيل Playwright فشل بأرشيف مبتور وGatewayExceptionResponse. لا يُدّعى اختبار متصفح بصري حقيقي.
- PostgreSQL محلي لم يُختبر في هذه الجلسة: تعذر تشغيل مستخدم خدمة مستقل ضمن قيود البيئة. Windows native وDocker وCI الخارجي لم يُنفذوا محليًا.

## المتبقي قبل اعتماد الإنتاج

نسخة Windows المحلية 8586c6c المشار إليها سابقًا ليست في المستودع المتاح، لذلك لا ادعاء مطابقته. تبقى اختبارات Windows/PostgreSQL/Chromium على SHA الموحد، التثبيت الفعلي، العمل دون اتصال على أجهزة فعلية، فحص ماسح QR، اختبار الأيام الخمسة، الأمن، PITR وUAT مفتوحة. لا توجد حزمة APK/MSI أصلية مؤكدة. تكاملات IAM/U-SEAS/UIP الخارجية ليست مثبتة تشغيليًا؛ عقودها وقيودها محفوظة ولا تحل محل المزود.

الوثائق التاريخية التي تستخدم Final Release لا تمنح هذا الدمج اعتماد إنتاج. مرجع الحالة الحالية هذا التقرير وملفات الأدلة المؤرخة.
