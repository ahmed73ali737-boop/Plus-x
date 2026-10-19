# PulseX Exhibition 360 — Final Release v1.0.1

## 1. تعريف هذا المخرج
هذا الإصدار هو **المخرج البرمجي الموحد النهائي** لنطاق المعرض الذي تم بناؤه فوق آخر baseline، وليس مشروعًا جديدًا أو إعادة بداية.

يجمع في مسار واحد:
- PulseX core.
- إدارة الفعالية والجهات والتجارب.
- Guest QR / Guest Number / phone deduplication.
- Gate / Scanner / Entry / Exit / Validate / anti-passback.
- Offline registration / offline check-in / outbox / synchronization.
- Kiosk / Tablet / Mobile / QR.
- الاستبيانات والأسئلة والتفرعات والتحقق.
- التصويت والنتائج الحية.
- التقييم والملاحظات وطلبات التواصل والموافقة.
- Excel/CSV import.
- Analytics / Reports / Export.
- Admin / Organizer وقيود النطاق.
- API + Python SDK + JavaScript SDK.
- PostgreSQL migrations + Docker/Compose + health/readiness.
- مواقع معرض حية ومستقلة لـ **ثروات، Easy، RTS** مع محرك بيانات وتفاعل مشترك.
- Public Experience v2: استبيانات موجهة للعلامة، تقييمات نجومية، تصويت حي، إعلانات معلنة بوضوح، وتجارب متجاوبة Web/Mobile-QR/Kiosk مع reduced-motion وfocus-visible.

## 2. ما الذي يُسلَّم
GitHub Release `v1.0.1` ينشئ تلقائيًا:
- `PulseX-Exhibition-v1.0.1.zip`
- `PulseX-Exhibition-v1.0.1.tar.gz`
- `SHA256SUMS.txt`

وتمثل الحزمة snapshot كاملة لنفس commit المنشور في Release.

## 3. بوابات الإصدار
قبل الدمج إلى `main` يجب أن ينجح على **رأس فرع الإصدار نفسه**:
1. PulseX CI.
2. guest-qr-ci.

وتغطي البوابات الموحّدة الاختبارات البرمجية، Windows/Linux، Chromium E2E، Guest QR/Offline، IndexedDB، PostgreSQL application path، migrations، SDK/API، security smoke، container build، وقدرات smoke للزوار والجهات والتفاعلات.

## 4. دليل سابق مثبت لنطاق Exhibition 360
تم توثيق نجاح candidate الذي دخل `main` في:
- `EXHIBITION_CI_EVIDENCE_20261006.md`
- `EXHIBITION_360_CLOSURE_AR.md`
- `GUEST_QR_360_COMPLETION_AR.md`

ويتم إعادة التحقق على فرع الإصدار النهائي قبل النشر.

## 5. حدود لا يجوز تزويرها
هذا **Final Software Release**. أما اعتماد **Production / Venue Field Sign-off** فيحتاج أدلة فعلية لا يمكن تعويضها بادعاء داخل الكود:
- كاميرا/Scanner على جهاز حقيقي.
- أكثر من جهاز أثناء انقطاع فعلي.
- Venue LAN/Edge الفعلي.
- Offline soak لمدة خمسة أيام.
- Domain/TLS حقيقي.
- Load/Saturation على بيئة مماثلة للإنتاج مع p50/p95/p99 وCPU/RAM/SLO.
- DAST/Pentest مستقل.
- Backup restore / PITR / retention على بيئة الإنتاج.
- توقيع Business/Field UAT.

عدم إغلاق هذه البنود لا يعني أن الحزمة البرمجية ناقصة؛ يعني أن **الاعتماد الميداني والإنتاجي** مرحلة تحقق مستقلة يجب تنفيذها في البيئة الحقيقية.

## 6. التشغيل
- Windows: `Start-Windows.cmd`
- Linux: `Start-Linux.sh`
- Containers: `compose.yaml` + `ops/Dockerfile`
- Deployment: `ops/DEPLOY_AR.md`
- Production readiness: `PRODUCTION_READINESS_AR.md`

## 7. قاعدة الإصدار
لا يُنشر `v1.0.1` يدويًا من فرع جانبي. Workflow الإصدار ينشره من `main` بعد دمج فرع الإصدار الذي اجتاز الاختبارات.

