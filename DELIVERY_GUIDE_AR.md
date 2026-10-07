# PulseX Exhibition — دليل التسليم والتشغيل والاستخدام v1.0.1

> هذه الوثيقة هي نقطة الدخول authoritative للحزمة. إذا تعارضت معها وثيقة Windows 09/10/11/12 قديمة، فهذه الوثيقة وحالة CI على نفس revision هما المرجع الأحدث.

## 1. ماذا تحتوي الحزمة
- التطبيق والواجهات العامة والإدارية.
- تجربة الفعالية والجهات المشاركة.
- مواقع المعرض المخصصة لـ RTS وEasy وثروات.
- Guest identity / Guest Number / QR Pass.
- Gate/Scanner: validate / entry / exit / anti-passback.
- Offline registration وoffline check-in وIndexedDB outbox/reconnect.
- Surveys / Questions / Ratings / Polls / Results.
- Content / services / facts / offers / ads / contact.
- Excel/CSV preview + commit.
- Analytics / metrics / reports / CSV export.
- Platform/Admin/Organizer/Organization participant scopes.
- API/OpenAPI + Python SDK + JavaScript SDK.
- PostgreSQL migrations + Docker/Compose + health/readiness.
- أدلة QA وClosure وField UAT.

## 2. التشغيل السريع

### Windows
1. فك ZIP في مسار محلي مثل `C:\PulseX`.
2. شغّل `Start-Windows.cmd`.
3. الموقع العام: `http://127.0.0.1:4310/`.
4. الإدارة: `http://127.0.0.1:4310/admin`.
5. للحسابات التجريبية استخدم `Open-Accounts.cmd`.

### Linux
```bash
chmod +x Start-Linux.sh
./Start-Linux.sh
```

### Production
استخدم `compose.yaml` و`ops/Dockerfile` واقرأ `ops/DEPLOY_AR.md`.
Production gate يتطلب PostgreSQL وHTTPS وsecrets حقيقية وSEED_DEMO=false وإعداد workers الصحيح.

## 3. الأطراف والطرفيات

| الطرف | الحساب | الطرفية/الواجهة | النطاق |
|---|---|---|---|
| Platform Admin | مطلوب | Admin dashboard | المنصة كاملة |
| Event Organizer | مطلوب | Admin/Organizer | الفعالية والجهات التابعة والزوار والأجهزة |
| Organization/Participant Admin | عند الحاجة | Agency admin | المؤسسة/المشاركة/الصفحة المسموحة |
| Organization member بدون حساب | غير مطلوب | لا توجد إدارة | سجل شخص/ممثل فقط |
| Public Visitor | غير مطلوب | Mobile/Web/QR | تصفح وتفاعل حسب السياسة |
| Registered Guest | غير مطلوب كحساب إدارة | Guest mobile/QR pass | بطاقة الزائر وحالته |
| Gate Operator | device pairing | Tablet/Scanner | manifest + validate/entry/exit |
| Kiosk/Display | device token | Kiosk/Display | تجربة عامة محددة |

قاعدة الصلاحية: Public request لا يمنح صلاحية مباشرة؛ الاعتماد من مستخدم مخول أولًا.

## 4. الواجهات الرئيسية

### الجمهور
- Event landing.
- Participant/brand page.
- RTS technical live experience.
- Easy living-wallet experience.
- Tharawat financial/editorial experience.
- Services/facts/media/offers/ads/contact.
- Survey/question flows.
- Poll + live result.
- Rating/notes.
- Guest registration and Guest Pass.
- QR-source and kiosk modes.

### الإدارة/المنظم
- Login/password-change.
- Dashboard.
- Site/content configuration and publish.
- Questions/surveys/polls/ratings.
- Imports preview/commit.
- Organizations/participations/members.
- Guest directory and QR.
- Devices/gate pairing.
- Metrics/results/export.

## 5. Validation والحقول

| المعنى | HTML/UI type | تحقق مطلوب |
|---|---|---|
| Date | date | قيمة تاريخ صالحة |
| Time | time | قيمة وقت صالحة |
| Date & Time | datetime-local | تاريخ ووقت |
| Email | email | صيغة بريد |
| Phone | tel | normalization؛ يدعم الأرقام العربية/الفارسية؛ Guest phone unique |
| URL | url | صيغة رابط |
| Number/Currency | number | رقم/حدود النوع |
| Dropdown | select | خيار صالح |
| Consent | checkbox | يجب أن تكون صريحة عند جمع بيانات التواصل |
| Required question | حسب النوع | يمنع الإرسال بدون إجابة |
| Rating/NPS/Emoji | scale controls | قيمة ضمن المدى |
| Matrix | rows + shared scale | قيمة لكل صف مطلوب |

Guest QR لا يحتوي رقم الهاتف. Manifest البوابة لا يحمل الهاتف.

## 6. الأزرار والإجراءات الحرجة

| الإجراء | المتوقع |
|---|---|
| إرسال الاستبيان | validation ثم receipt وحفظ |
| إرسال التصويت | حفظ ballot ثم تحديث النتيجة |
| إرسال طلب التواصل | consent + validation ثم حفظ |
| Preview Import | لا يعدل البيانات؛ يعرض الأخطاء |
| Commit Import | يطبق فقط preview صالح |
| Publish | ينشر revision المقصود ولا يسرب draft |
| Guest Register | نفس الهاتف يعيد نفس guest identity |
| Generate/View QR | QR نهائي فقط للـG-number |
| Gate Validate | يتحقق بلا تغيير presence |
| Entry | يمنع duplicate entry حسب anti-passback |
| Exit | يسجل الخروج وفق الحالة |
| Sync Now | يعيد pending outbox idempotently |
| Export CSV | scoped + spreadsheet-injection protection |

## 7. السيناريوهات الأساسية

### S1 — زائر عام
فتح QR/الرابط → تصفح الجهة → خدمة/معلومة → Survey/Poll/Rating → receipt/نتيجة.

### S2 — Guest
إدخال الهاتف + consent → normalization/dedupe → G-number → QR Pass → scan at gate.

### S3 — Offline Guest
انقطاع بعد تحميل الصفحة → P provisional محلي → outbox → reconnect → reconcile إلى G-number + QR نهائي.

### S4 — Offline Gate
Pair + manifest → فصل الشبكة → scan/check-in pending → reconnect → sync → accepted/duplicate receipt بلا تكرار.

### S5 — Organizer
Login → إدارة الفعالية/الجهات → المحتوى والأسئلة → preview/publish → guests/devices → analytics/export.

### S6 — Participant Organization
إنشاء المؤسسة/المشاركة → شخص بدون حساب أو admin account → إدارة الصفحة ضمن scope → توقف المشاركة يسحب الإدارة المرتبطة بها.

### S7 — Easy
فتح Easy → living wallet/quick actions → services → survey → persisted response.

### S8 — RTS
فتح RTS → system map/capability rail → poll → live result.

### S9 — Tharawat
فتح ثروات → insight horizon/discovery salon → contact → phone/message/consent → submit.

### S10 — Import
Upload Excel/CSV → preview → validation errors أو valid → commit → draft → publish.

## 8. UI/UX التي تم التحقق منها آليًا
- Desktop Chromium.
- Mobile 390×844 للواجهات الثلاث.
- no horizontal overflow.
- visitor-first chrome؛ لا تظهر أدوات الإدارة للزائر.
- brand surfaces منفصلة لـ RTS/Easy/Tharawat.
- semantic input types.
- required validation في السيناريوهات المغطاة.
- reduced-motion/focus baseline.
- first network render لا ينتظر IndexedDB.
- Windows-hosted Chromium + Linux-hosted Chromium.

## 9. الاختبارات المطلوبة لإصدار هذه الحزمة
على نفس release head يجب أن ينجح:
- full pytest Linux.
- full pytest Windows.
- native Windows HTTP acceptance.
- Chromium component + real HTTP E2E على Windows/Linux.
- brand journeys.
- Guest QR/offline browser journey.
- IndexedDB component.
- PostgreSQL native acceptance + application-path capacity.
- 1000 guest capacity smoke.
- interaction capacity smoke.
- 70-entity topology smoke.
- security hardening smoke.
- JS syntax + JS SDK.
- Python SDK real HTTP.
- API/OpenAPI contract.
- production Docker build/import/migration assets.

## 10. ما لا يجوز اعتباره PASS من CI
هذه ليست أخطاء معروفة، لكنها تحتاج بيئة فعلية:
- physical phone/tablet camera وUSB scanner.
- two/multi-device hard outage.
- venue LAN/edge.
- 5-day offline soak.
- real HTTPS/domain.
- production-like saturation/SLO measurements.
- independent DAST/Pentest.
- production backup restore/PITR/retention.
- signed Business/Field UAT.

راجع `WINDOWS_UAT_AR.md` لتنفيذها في موقع المعرض.

## 11. قاعدة القبول
لا نستخدم كلمة PASS لخاصية إلا بوجود اختبار/دليل. ولا نستخدم Production Ready قبل إغلاق Field/Deployment/Security/Ops sign-offs أعلاه.
