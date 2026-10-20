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
شغّل:
`Start-Windows.cmd`

### التشغيل على Linux
```bash
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
