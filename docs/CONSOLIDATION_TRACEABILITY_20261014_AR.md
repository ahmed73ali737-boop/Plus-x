# PulseX — سجل توحيد النسختين والأصول 2026-10-14

**قرار الحالة: INTEGRATION REVIEW / NOT FINAL / NOT PRODUCTION.**

هذا المسار امتداد للمستودع الأصلي Plus-x، وليس منتجًا جديدًا. آخر main عند بدء التجميع e66369ac، ومرشح PR #24 عند 2f0bec55. النسخة المحلية Windows عند 8586c6c (وفق التقارير 568 ملفًا) غير موجودة في GitHub؛ لا تُدّعى مطابقتها.

## 1. تجميع الفروع والـPR دون نسخ مالكي الخدمات

| المصدر | ما نُقل لهذا الفرع | ما لم يُفعل/يُغلق |
|---|---|---|
| PR #12 و#18 و#20 و#24 | اعتماد شجرة PR #24 التي تحتوي سلسلة Linux/Windows/Update1 | لا merge إلى main قبل اختبارات SHA الموحد والمصدر المحلي |
| PR #13 | عقود IAM والدليل | لا IAM خارجي حقيقي ولا اعتماد Security |
| PR #14 | مصدر منفذ صلاحيات المشرف fail-closed + اختبارات ومصفوفات | Enforce لا يقبل التشغيل دون provider موثوق، Off افتراضيًا |
| PR #15 | تعريف أصل Party/Network | لا نسخ قاعدة Party أو KYC |
| PR #16 و#17 | ملف Python SDK محمي + اختبارات نطاق/موافقة | لا U-SEAS live binding ولا تحويل Guest إلى Party |
| PR #21 | وحدة observability + source-lock والمتطلبات الاختيارية | التصدير معطل دون OTEL_EXPORTER_OTLP_ENDPOINT؛ لا نشر collector |
| PR #22 | PostgreSQL health SQL للقراءة فقط + فحص static | لا تغييرات schema ولا RLS/PITR معتمدين |

جميع الأصول المنقولة محمية بـ ops/consolidated-source-lock.json وتُراجع بواسطة tools/verify_consolidation_assets.py. تغيير ملف يستلزم تحديث الدليل بعد مراجعة، لا أن يُستبدل بكود مكرر عشوائيًا.

## 2. وظيفة Live Wall جديدة على نفس التطبيق

- المسار العام: /live/{site_slug}، يعرض البيانات المنشورة من GET /api/public/site/{slug} وGET /api/public/site/{slug}/results.
- المنظم يتحكم بإظهار النتائج من مربع «عرض النتائج للجمهور» للتصويت ثم «نشر التغييرات»؛ تغير المسودة وحدها لا ينشر شيئًا.
- الواجهة تستبعد التصويت السري وغير الموافق عليه، ولا تستخدم نتائج المشرف أو الهوية أو أرقام الهاتف أو الملاحظات الخاصة.
- تحديث كل 10 ثوانٍ عند ظهور الصفحة؛ عند فشل الشبكة يُمحى العرض القديم بدل تسويقه على أنه حي.
- رابط فتح الشاشة يوجد في رأس لوحة الإدارة، مع CSS للوضع الكبير/الهاتف، وإضافة الموارد إلى Service Worker v22.
- **الحد الحالي:** polling واحد لكل شاشة؛ ليس بعد بثًا موزعًا عبر WebSocket أو نظام إخراج/جدولة إعلان/موافقة منفصلين.

## 3. مصفوفة التتبع المختصرة

| ID | الدور / الرحلة | UI | API/DB | الاختبار / الدليل | القرار |
|---|---|---|---|---|---|
| LW-01 | منظم يحدد إظهار النتائج وينشر | polls editor + publish | site draft/version | tests/test_livewall.py | يحتاج CI على الرأس |
| LW-02 | شاشة عرض تُظهر التصويت الموافق عليه | /live/{slug} | public site/results | tests/livewall_smoke.mjs | اختبار DOM محاكى محليًا، المتصفح الحقيقي مفتوح |
| LW-03 | سحب الموافقة/تغيير الإصدار/انقطاع | Live Wall clear and retry | public published versions | JS privacy contract + test_livewall.py | يحتاج Chromium Windows/Linux |
| IAM-01 | admin draft/publish مع provider اختياري | Admin | app/server + shared_authorization port | test_shared_organizer_authorization.py + test_shared_auth_runtime.py | provider SIT/approval مفتوح |
| PN-01 | ربط مشاركة Party بموافقة صريحة | SDK-only | external U-SEAS protocol | tests/test_party_network_sdk.py + test_party_network_r15.py | استخدام فعلي مفتوح |
| OBS-01 | قياس HTTP دون هوية أو payload | لا واجهة جديدة | optional OTLP | source lock and optional tests | collector نشر واختبار خارجي مفتوح |
| DB-01 | مراقبة كتالوج PG دون تعديل | DBA SQL only | BEGIN READ ONLY | tests/database_architecture/test_readonly_catalog.py | native DB ops مفتوح |
| W/L-01 | تشغيل نفس commit على Windows/Linux | Web/PWA | Python/SQLite pilot + PG CI | PR #24 + new CI gates | اختبار SHA الموحد مطلوب |

## 4. لا تغلق دون دليل

ما زال مطلوبًا: جلب نسخة 8586c6c ومقارنة 568 ملفًا، إصلاح كل U1-01..08 على المصدر الصحيح، ربط 48 اختبار LT الفردية بنتائج وأدلة، Builder السحب والإفلات الكامل، الاعتماد والبث الموزع للـLive Wall، تكاملات IAM/U-SEAS الواقعية، كل الأدوار/الشاشات/الأزرار/الحالات والحقول وإعادة التحميل، قارئ QR حقيقي، جهازان دون اتصال، خمسة أيام soak، 70 جهة و1000 زائر في حمل إنتاجي، توافق المتصفحات، اختبارات DAST/Pentest، استعادة PostgreSQL/PITR، وتوقيع UAT ميداني.

## 5. قرار الدمج

1. تدقيق الاختبارات والأصول والشيفرة على رأس هذا الفرع تحديدًا.
2. التأكد من نجاح Windows + Linux + guest QR + PostgreSQL + browser E2E + packaging على SHA واحد.
3. إحضار المصدر المحلي الغائب وتحليل فروقه، ثم حسم عيوب audit.
4. دمج إلى main بلا force، وإغلاق PRs التابعة فقط بعد إثبات دمج نطاقها فعليًا.
5. نشر نسختي Windows/Linux من commit واحد مع SHA256 ودليل تشغيل لكل دور.
6. اعتماد الإنتاج/المعرض ميدانياً منفصل، وليس نتيجة CI فقط.

**حالة العائق الحالية:** آخر Jobs على PR #24 بتاريخ 14 أكتوبر انتهت بالفشل قبل ظهور أي خطوات، لذا لا تُفسَّر على أنها فشل اختبار التطبيق ولا كنجاح للنسخة الحالية.

## 6. متابعة 15 أكتوبر — صلاحيات الجلسات، Live Wall، PWA
| ID | ما تغير فعلياً | الواجهات والأطراف | الاختبار | المتبقي |
|---|---|---|---|---|
| PX-31 | إنهاء جلسات الحساب مع CSRF وتسجيل التدقيق؛ دمج PR #28 في PR #25 | لوحة أمان الحساب وتغيير كلمة المرور | test_session_revocation.py وsession_ui_contract.mjs | إقرار Security والمتصفح الحقيقي |
| PX-32 | منع نشر نتائج poll_style=secret أو flags غير boolean في الخادم | شاشة Live Wall العامة | 4 اختبارات FastAPI/SQLite؛ فشل سابق أُعيد إنتاجه ثم أصلح | البث الموزع والأجهزة |
| PX-33 | صورتا PWA أصليتان 192/512 وManifest وApple icon وService Worker v23 | ويب/هاتف/سطح مكتب | اختبارا PWA API ناجحان | اختبار التثبيت على أجهزة فعلية، لا APK/EXE |
| PX-34 | تحديث OpenAPI من 44 إلى 57 مساراً وتصحيح الإصدار إلى 1.0.1 | جميع واجهات API | API contract محلي ناجح | تثبيت FastAPI 0.142.2 وإعادة التوليد، لأن المحلي 0.128.2 |

**البيئة المحلية:** Python 3.13.5 وSQLite وFastAPI 0.128.2 وNode 22؛ 246/246 pytest ناجحة في 64.59 ثانية على مصدر أرشيف Linux الاختباري بعد ترقيع الوظائف، لا يمثل commit GitHub الكامل ولا اختبار Windows.

**سلامة التجميع:** مطابقة 22/22 Git blob SHA للأصول المستوردة على commit 8ebda29d، دون إثبات provider SIT.

**العوائق:** GitHub Actions #38642801097 و#38642801145 فشلا قبل بدء أي خطوة، runner فارغ. نسخة Windows المحلية 8586c6c غير متاحة؛ Venue/Scanner/Offline خمسة أيام وTLS وPenTest وPITR وUAT ما زالت مفتوحة. لا موافقة على الدمج إلى main أو نشر Final.
