# PulseX — Live Experience & Insights Platform

## Exhibition 360 Final Software Release

هذا المستودع هو المخرج البرمجي الموحد لمنصة PulseX الخاصة بالمعارض والفعاليات والتجارب التفاعلية الحية.

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
- مواقع وتجارب معرض مستقلة بصريًا ووظيفيًا لـ **Tharawat / Easy / RTS** فوق محرك PulseX المشترك.

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
