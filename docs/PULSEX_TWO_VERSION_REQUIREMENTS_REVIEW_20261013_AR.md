# PulseX — مراجعة متطلبات نسختي Windows/main وLinux المستقلة
تاريخ المراجعة: 2026-10-13. هذه مصفوفة دليل، وليست شهادة اعتماد كامل.

## هوية المصدر والدليل
- Windows/GitHub baseline: `main@e66369ac83e1ee17d52664147e0e874329207501`، 274 ملفًا عاديًا، PulseX CI push #37566634894 ناجح. فشل Workflow النشر #37566634861 عند Validate final manifest؛ لم ينتج Release نهائي.
- Linux candidate: `release/linux-ubuntu2404-standalone-candidate-20261010@35f3347e5aeaa256a47e1898f7b0229c9526419a`، 292 ملفًا عاديًا. مقارنة شجرة Git: 18 إضافة، 25 تعديلًا، صفر حذف. هذا لا يثبت أن سلوك 25 ملفًا لم يتغير سلبًا.
- على رأس إصلاحي Windows/Linux المشترك `ae40111b`: PulseX CI #38024557724 ناجح (Windows/browser/DB/API/SDK) وUbuntu #38364110092 ناجح. على commit الدمج `35f3347e`: Ubuntu/ARM64/PostgreSQL/Browser/packaging #38364627785 ناجح، guest-qr-ci #38364627839 ناجح.
- التقرير المحلي `SYSTEM_AUDIT_AR_2026-10-08.md` دقق `7633742f`، وخطة Linux تصف نسخة محلية `8586c6c` ذات 568 ملفًا. هذان المصدران غير متاحين في GitHub الحالي؛ لا يصح نقل نجاح هذه الفروع إلى مطابقة المصدر المحلي أو إغلاق عيوبه تلقائيًا.
- «موجود» = أثر مصدر/واجهة؛ «مختبر آليًا» = مسار CI محدد؛ «مفتوح» = لا يوجد دليل قبول كافٍ. الأدلة التاريخية ليست اختبارًا للنسخة المحلية الغائبة.

## مصفوفة المتطلبات 360
| ID | المتطلب والجهات/الطرفيات | أثر المصدر المشترك في النسختين | الدليل الحالي | الفجوة والحكم |
|---|---|---|---|---|
| PX-01 | Platform→Organization→Brand→Event→Experience؛ التفويض | `app/db.py`, `app/application/access.py`, `web/admin.mjs` | pytest وnative/browser control في PulseX CI | الهيكل المذكور في المتطلبات أوسع من النطاق المثبت؛ مستويات Network/Branch/Department والتفويض الكامل تحتاج عقدًا واختبارًا؛ جزئي |
| PX-02 | تسجيل الدخول والحساب المؤقت وتغيير كلمة المرور | `auth_service.py`, `access_request_service.py`, admin | HTTP/security/browser | تسجيل ذاتي متعدد الأدوار وموافقات كاملة لم تثبت؛ جزئي |
| PX-03 | مدير المنصة/منظم/جهة/عضو/زائر/بوابة/كشك | access, public, guest/device services | scope deny + browser controls | اختبارات كل فعل عبر كل دور وكل حد صلاحية غير مكتملة؛ جزئي |
| PX-04 | إنشاء الجهات والمشاركات والأشخاص بلا حساب | `db.py`, `access_request_service.py`, admin | native/API/browser حالات مختارة | دورة المجموعات والعضويات الهرمية الكاملة غير مثبتة؛ جزئي |
| PX-05 | إعداد مسودة ونشر نسخة ومعاينة/تعارض | `publishing.py`, admin | HTTP/browser smoke | موافقات متعددة المراحل وتراجع/جدولة النشر غير مثبتة؛ جزئي |
| PX-06 | Builder: Welcome/Video/Question/Branch/Image Vote/Info/Live Poll/Ad/Result/CTA/Thank You بالسحب | `web/admin.mjs`, `web/questions.mjs`, `app/domain.py` | سؤال/نشر وبعض كتل المحتوى | محرر سحب وإفلات وجميع البلوكات والتفرعات كرحلة واحدة غير مثبتة؛ مفتوح للنطاق الكامل |
| PX-07 | 24 نوع سؤال، حقول date/time/email/tel، إلزامية وتفرع | `questions.mjs`, `domain.py`, `browser_question_roundtrip.py` | Chromium/DB/export للـ24 نوعًا في التدقيق؛ CI question roundtrip | جميع الأنواع من محرر الإدارة وكل التركيبات السلبية غير مثبتة؛ جزئي |
| PX-08 | Survey/Poll/Vote/Rating/Notes/Results | collection/public services وpublic.mjs | browser/API/CI | شخص واحد عبر أجهزة متعددة، سرية/سياسات جميع القنوات وإغلاق التصويت تحتاج حالات أوسع؛ جزئي |
| PX-09 | إعلانات/عروض/وسائط/معلومات/CTA | `web/exhibition.mjs`, `app/application/public_service.py`, templates | brand browser journeys | نظام إعلانات مستقل للحجز/الاستهداف/الميزانيات غير مثبت؛ الموجود محتوى عرض وتجربة؛ جزئي |
| PX-10 | إدخال Excel/CSV للأسئلة والجهات والإعلانات والتصويت | `app/imports.py`, `xlsx_reader.py`, `templates/*` | preview/commit عينات | لكل كيان وحجم/ملف تالف/rollback شامل دليل مستقل مطلوب؛ جزئي |
| PX-11 | تقارير ولوحات وإحصاء وتصدير وعزل | collection, admin, API | native/browser/export عينات | Live Wall مع اعتماد المشرف والبث الموزع وتقارير كل طرف غير مثبتة؛ جزئي |
| PX-12 | RTS/Easy/ثروات مواقع متمايزة ومتجاوبة | `web/exhibition*.css`, `exhibition.mjs` | browser_exhibition_sites على Windows/Linux Chromium | قبول التصميم والهوية والمحتوى من مالك كل علامة والأجهزة الحقيقية مفتوح؛ مختبر متصفح ضمن النطاق |
| PX-13 | Web/Mobile/QR/Kiosk، RTL والوصولية | public/guest/exhibition CSS/JS | Chromium desktop/mobile 390px, reduced-motion baseline | Safari/Firefox/Edge وWCAG كاملة/عتاد كشك غير مثبتة؛ جزئي |
| PX-14 | رقم زائر فريد وهاتف مطبع وQR بلا هاتف | guest_service/guest_routes وmigrations 004–007 | guest API/browser وPG concurrency/guest-qr-ci | المطالبة الأولى بالهاتف ليست OTP لإثبات الملكية؛ السياسة والخصوصية تحتاج اعتماد؛ جزئي |
| PX-15 | مسح QR والتحقق/الدخول/الخروج/anti-passback | guest_gate_service/device_service/guest.mjs | browser + PostgreSQL/CI | كاميرا وماسح فعليان ونقطتان بالتزامن غير مثبتين؛ جزئي |
| PX-16 | Offline guest وgate/outbox/reconnect/idempotency | offline.mjs, sw.js, IndexedDB | Chromium offline journey وguest-qr-ci | انقطاع متعدد الأجهزة خمسة أيام، تعارض ومزامنة بعد فقد جهاز/Origin غير مثبتة؛ جزئي |
| PX-17 | ترقية Service Worker بلا فقد الطابور | `web/sw.js`, `tests/browser_offline_indexeddb.py` | تحديث namespace واختبار مكون | ترقية نسخة منشورة قديمة فعلًا مع طابور معلق غير مثبتة؛ U1-07 مفتوح جزئيًا |
| PX-18 | ذرّية تسجيل الضيف وعزل عناصر batch | guest_service/guest_routes/db | اختبارات SQLite/PG الحالية | عيب U1-01 في المصدر المحلي المدقق لم يُعَد تشغيل حقن الفشل المطابق على `8586c6c`؛ لا يُغلق المصدر المحلي |
| PX-19 | API/SDK Python وJavaScript/OpenAPI | ops/api-contract, SDK | CI SDK + HTTP | عقد تكامل خارجي حقيقي وإصدارات توافق موثقة كاملة مفتوحة؛ جزئي |
| PX-20 | PostgreSQL migrations/checksum/readiness | migrations.py, ops/002–007, health | PostgreSQL CI على Linux/Windows candidate | ترقية قاعدة تاريخية من المصدر المحلي وPITR/RLS غير مثبتة؛ جزئي |
| PX-21 | Secrets/production gate/CSRF/Host/privacy | security/middleware/settings/files | security smoke + CI | DAST/pentest وملكية ملفات/إعدادات الإنتاج الفعلية مفتوحة؛ جزئي |
| PX-22 | SQLite local + Windows/Linux setup | Start-Windows.cmd, Start-Linux.sh, prepare_runtime.py | Windows CI وUbuntu 24.04 x86/ARM CI | Windows Installer مستقل/تثبيت جديد على جهاز المستخدم والمسار العربي/read-only لم يثبتا؛ جزئي |
| PX-23 | Docker/Compose/health/ops/backup | Dockerfile, compose, tools/backup_local.py | container-import + health CI | restore/PITR/retention وDNS/TLS والمراقبة في بيئة الهدف مفتوحة؛ جزئي |
| PX-24 | 70 جهة، 1000 زائر، 5 أيام | exhibition_scale_smoke, guest_capacity_smoke | حمل اصطناعي bounded في CI | 1000 متزامن وSLO p95/p99 وsoak خمسة أيام غير مثبتة؛ مفتوح للإنتاج |
| PX-25 | شاشة عرض حية وتحكم المشرف بالبث | لا دليل مباشر لمسار Live Wall مستقل في الملفات المختبرة | لا اختبار E2E مسمى | مطلوب تصميم/تنفيذ/اختبار مستقل؛ مفتوح |
| PX-26 | إدخال بيانات الإعلان والتصويت والمشاركين ديناميكيًا | templates/Ads, Polls, Participants, imports | عينات import/public | دورة تحرير/اعتماد/استيراد كل كيان غير مثبتة؛ جزئي |
| PX-27 | أدوار ورسائل/إشعارات/سجل تدقيق | audit_service, admin | عينات API/security | إشعارات فعلية وتغطية كل حدث/موافقة غير مثبتة؛ جزئي |
| PX-28 | Windows/Linux نفس الخصائص | 274 ملفًا مشتركًا؛ صفر حذف؛ 25 تعديلًا محصورًا | Windows CI `ae40111b` وLinux CI `ae40111b`؛ Linux merge CI | مساواة المصدر المحلي `8586c6c` غير قابلة للإثبات؛ مساواة كل سلوك/شاشة تحتاج differential E2E |
| PX-29 | دليل استخدام لكل طرف وسيناريو | DELIVERY_GUIDE_AR, START_LINUX_AR, FIELD_TEST_AR | مستندات مصدر | دليل Linux السريع كان يتجاوز تجهيز venv؛ صُحح في PR هذه المراجعة؛ أدلة الدور الكاملة تحتاج UAT |
| PX-30 | Final Release متطابق مع VERSION والتدقيق | VERSION, FINAL_RELEASE.json, release.yml | main release workflow #37566634861 فشل في Validate final manifest | audit_admission محجوب؛ لا Release موحد معتمد، ولا نشر إنتاجي |

## عيوب التدقيق وخطة Linux
- U1-01..08: `LINUX_TRACEABILITY_AR.md` يفصل التنفيذ الجزئي من شروط الإغلاق. نجاح CI على مصدر GitHub لا يغلق تلقائيًا عيوب commit المحلي `7633742f` أو يثبت مطابقته. تعارض الهوية/metadata قد تحسن، لكن admission النهائي ما زال blocked.
- LNX-01..18 وLT-01..48: بوابة Ubuntu/ARM64/PostgreSQL/Chromium والحزمة اجتازت على commit الدمج. لم ينتج سجل نتائج مستقل يربط كل LT من 48 بمعرف اختبار ونتيجة؛ LNX-05/06/08/10/14/16/17/18 تبقى لها حدود مذكورة في `LINUX_TRACEABILITY_AR.md`.
- متطلبات التخطيط والتحليل الأكبر (SRS/BRD/UML/ERD، جميع الشاشات، approval matrices، التقارير، أدلة الأدوار): وجود أصول وثائقية أقدم لا يثبت تنفيذ كل بند في البرنامج. تحتاج تفكيكًا إلى معرفات قبول قابلة للتنفيذ وربطها بالشاشة والصلاحية وAPI/DB/اختبار/دليل.

## قرار الإصدار والخطوات القابلة للإغلاق
1. لا تدمج فرع Linux إلى main ولا تصف النسختين Final قبل إحضار مصدر `8586c6c`/أرشيفه والمقارنة مع 292 ملفًا الحالية وتحليل كل اختلاف وظيفي.
2. شغّل التفاضل على Windows وUbuntu بنفس dataset: كل دور/شاشة/حقل/زر/حالة/طلب/أثر DB/إعادة تحميل/تقرير/Offline، خصوصًا 24 نوع سؤال وGuest/QR/Gate والعلامات الثلاث.
3. حوّل PX-06/11/25 والوظائف غير المثبتة إلى قصص تنفيذ فعلية، لا تُسجل «مكتمل» استنادًا إلى manifest.
4. اغلق U1 وLT بحالات حقن ومصفوفة evidence مرتبطة بـSHA واحد، ثم ميدان/أمن/نسخ احتياطي/استعادة واعتماد مالكي المنتج قبل نشر النسخة.
