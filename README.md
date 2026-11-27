# Eventna إيفنتنا

Website: https://eventna.app | [Deployment guide](ops/eventna/README.md)

## Unified application source — test candidate

هذا المستودع يجمع مصدر تطبيق Eventna إيفنتنا ولوحة إدارته للمعارض والفعاليات. تجميع المصدر لا يعني اعتماد الإنتاج؛ راجع [تقرير التوحيد والتحقق](docs/UNIFICATION_20261019_AR.md).

### النطاق الموحّد
- إدارة Platform / Organization / Event / Experience / participating entities.
- تجربة الزائر عبر Web / Mobile / Tablet / Kiosk / QR.
- Guest identity موحدة حسب رقم الهاتف بعد normalization ومنع التكرار.
- Guest Number + QR Pass بدون تضمين رقم الهاتف داخل رابط QR.
- Gate / Scanner للدخول والخروج والتحقق، مع anti-passback وidempotency.
- Offline registration / check-in / IndexedDB outbox / reconnect synchronization.
- Organizer/Admin flows وإدارة الجهات والمحتوى والأسئلة والاستبيانات والتصويت والتقييم والنتائج.
- Excel/CSV import preview + commit.
- Analytics / reports / exports.
- API + Python SDK + JavaScript SDK.
- PostgreSQL migrations، health/readiness، security hardening، Docker/Compose.
- مواقع وتجارب معرض مستقلة بصريًا ووظيفيًا لـ **Tharawat / Easy / RTS** فوق محرك Eventna إيفنتنا المشترك.

### التشغيل على Windows
جهّز بيئة Python أولًا باستخدام `python -m tools.prepare_runtime --profile local`، ثم شغّل:
`Start-Windows.cmd`

### التشغيل على Linux
```bash
python3 -m tools.prepare_runtime --profile local
chmod +x Start-Linux.sh
./Start-Linux.sh
```

### التشغيل بالحاويات
راجع:
- `compose.yaml`
- `ops/Dockerfile`
- `ops/DEPLOY_AR.md`

### وثائق الإغلاق
- `FINAL_RELEASE_AR.md`
- `FINAL_RELEASE.json`
- `EXHIBITION_360_CLOSURE_AR.md`
- `EXHIBITION_CI_EVIDENCE_20261006.md`
- `GUEST_QR_360_COMPLETION_AR.md`
- `PRODUCTION_READINESS_AR.md`
- `WINDOWS_UAT_AR.md`

### قاعدة الحقيقة
الإصدار النهائي البرمجي لا يعني تزوير اختبارات العالم الحقيقي. الاختبارات التي تحتاج أجهزة فعلية، شبكة موقع المعرض، نطاق HTTPS حقيقي، soak متعدد الأيام، DAST/Pentest مستقل، أو توقيع UAT ميداني تبقى **Field / Deployment Sign-off** منفصلة حتى تنفيذها فعليًا.

الإصدار المنشور من GitHub Release يُنشأ فقط من فرع `main` بعد اجتياز بوابات الإصدار المعتمدة.

## الحزمة الموحدة للتسليم v1.0.1
ابدأ من `DELIVERY_GUIDE_AR.md`. يجمع دليل التشغيل والاستخدام، الأطراف والطرفيات، الواجهات، الحقول وValidation، الأزرار الحرجة، السيناريوهات، UI/UX، الاختبارات وحدود Field UAT.
راجع أيضًا `DELIVERY_ACCEPTANCE_CHECKLIST.md` لقائمة القبول المختصرة.

## الشهادات

أُضيفت نواة إصدار الشهادات إلى لوحة الإدارة في تبويب **الشهادات** للفعالية: قوالب نصوص وصور وتحريك طبقات، معاينة، إصدار فردي ومجمع من Excel/CSV مع جدولة، QR للتحقق، رابط استلام خاص، تنزيل SVG/PNG/PDF وتصحيح وإلغاء بسجل محفوظ. راجع [التصميم المحسن وحالة التنفيذ والمتبقي](docs/CERTIFICATES_SYSTEM_AR.md). PDF مصوّر عالي الدقة. الإرسال الخارجي والمحافظ الرقمية وربط «شهاداتي» والأهلية الآلية ما زالت متطلبات لاحقة.

## التطبيق والإدارة

حزمة Android المعاينة متاحة في [artifacts/android](artifacts/android/README.md). راجع [حالة الأوفلاين والتجهيز والأدلة](docs/OFFLINE_UPLOAD_VERIFICATION_20261020_AR.md) قبل فصل الاتصال أو تشغيل البوابات.

بعد تشغيل Start-Windows.cmd أو Start-Linux.sh افتح http://127.0.0.1:4310 :

| الواجهة | المسار |
|---|---|
| تطبيق الزائر | `/` |
| الفعالية التجريبية | `/e/demo` |
| لوحة الإدارة | `/admin` |
| تسجيل الزائر وبطاقته | `/e/demo/guest` |
| ماسح البوابة (يتطلب جهازًا مصرحًا) | `/e/demo/scan` |
| شاشة النتائج العامة | `/live/demo` |

التطبيق Web/PWA قابل للتثبيت من المتصفح المدعوم. يوجد الآن مشروع Android وحزمة APK معاينة بواجهة بدء عربية وماسح QR محلي، تتصل بخادم Eventna إيفنتنا الحالي؛ راجع [دليل Android](android/README_AR.md). لا توجد حزمة MSI مؤكدة. حسابات التشغيل التجريبي تُنشأ محليًا في ملف credentials المحدد؛ لا تستخدمها للإنتاج. أدوار الإدارة الحالية: المنصة والمنظم والجهة وصلاحيات البوابة واللجان المحددة، مع صلاحيات نطاقية؛ وجودها لا يثبت اكتمال جميع الأدوار المستقبلية.

## English onboarding

Eventna supports event organizers, participating organizations, visitors and authorized gate operators. Its source includes event content, guest registration and QR passes, scoped administration, offline synchronization, reports and SDK clients. Review the [unification evidence](docs/UNIFICATION_20261019_AR.md) and [production readiness record](PRODUCTION_READINESS_AR.md) for acceptance boundaries.

### Local setup

From the repository root, prepare the isolated, hash-locked Python runtime before starting the application.

On Linux with Python 3 installed, run the Linux commands above. On Windows, run the following commands in a terminal with Python available.

```bat
python -m tools.prepare_runtime --profile local
Start-Windows.cmd
```

Open <http://127.0.0.1:4310>. The visitor application is at `/`, administration at `/admin`, and the demo guest registration and gate scanner at `/e/demo/guest` and `/e/demo/scan`. Gate scanning requires an authorized device. Use locally generated credentials for the development instance.

For Docker deployment, follow the [deployment guide](ops/eventna/README.md) and configure the required environment values in [compose.yaml](compose.yaml), including the database password, guest identity secret, public domain and bootstrap administrator. Production startup has explicit acceptance gates.

### Architecture and API references / المعمارية وواجهات التكامل

- [Architecture and dependency boundaries / المعمارية](ARCHITECTURE_AR.md)
- [API and SDK guide / دليل الواجهات](SDK_API_AR.md)
- [Generated OpenAPI document / مواصفات OpenAPI](ops/openapi.generated.json)
- [Python and JavaScript SDKs / مكتبات التكامل](sdk/README.md)
- [Delivery and operator guide / دليل التشغيل والاستخدام](DELIVERY_GUIDE_AR.md)

The SDKs cover guest registration, synchronization, visitor status and gate operations. Authentication uses cookies and CSRF protection. Gate clients use the device token header described in the SDK guide. Field devices, venue networking and production acceptance require their own recorded verification.
