# سجل قبول نسخة PulseX المستقلة على Linux

**تاريخ فتح السجل:** 2026-10-10.  
**نوع التسليم:** Candidate؛ غير معتمد للتشغيل الإنتاجي حتى تتوافر الأدلة.  
**الأساس المتاح:** GitHub PR #12 عند `208ba752b7a4d349bb48acdd96a6a4d02baf3bde`.  
**الأساس المحلي المطلوب:** `8586c6cb257b995387ff7acb7608a7e3d3730305` غير موجود في GitHub المتاح؛ لا يمكن ادعاء تطابق كل الملفات الـ568.

## قواعد قرار القبول

تُعد الحزمة مقبولة فقط إذا نجحت الاختبارات الفعلية على SHA واحد للشفرة والحزمة: Python 3.12/Ubuntu 24.04، إعداد venv جديد، فحص HTTP والواجهات والأدوار والأذونات وQR/offline، حفظ البيانات والنسخ، صحة PostgreSQL الأصلية والترحيلات والتزامن والحمل، تثبيت VERSION في الصورة، اختبارات ARM64 عندما تكون هي بيئة النشر، وعدم تراجع Windows.

**لا يُعد Commit أو PR أو Workflow مكتوب اختباراً ناجحاً.** لكل Gate: نتيجة GitHub Actions، URL للتشغيل، SHA، مجموعة السيناريوهات، حالة Passed/Failed/Blocked، ملف الأدلة وسبب الحجب. لا تخلط الاختبارات التاريخية 252/259 مع نتائج Ubuntu.

## بوابات مطلوبة

| البوابة | التنفيذ | الإثبات المطلوب |
|---|---|---|
| Linux runtime | `tools.prepare_runtime` و`Start-Linux.sh` | Ubuntu 24.04/Python 3.12/arch + HTTP + SIGTERM |
| Core / Roles / API | pytest + native acceptance + security | نتائج التشغيل الفعلية وسجلات الخطأ |
| UI/UX & Offline | Playwright brand, guest, questions, admins, IndexedDB | صور أو تقارير Chromium وoffline/replay |
| Data consistency | SQLite rollback + credentials/backup | اختبارات الحقن وإعادة التشغيل |
| PostgreSQL | native/capacity/migrations | نتيجة على قاعدة اختبار PG أصلية |
| ARM64 | GitHub arm64 runner + PostgreSQL + container | نتيجة ARM64 مستقلة عن x86 |
| Packaging | source ZIP/TAR.GZ + VERSION + modes + SHA256 | artifact من نفس SHA الناجح |
| Windows | Python3.13 / browser regression | نتائج workflow الحالية |
| Source parity | مقارنة 8586c6c المحلي مع المصدر المستقل | حصر كل اختلاف وتفسير عدم الفقد |
| Field/Production | موافقات أمن ونشر وتشغيل ميداني | دليل خارجي، ليس فقط CI |

## الحالة المعروفة عند إنشاء السجل

- **منفّذ في فرع منفصل:** تغييرات الإعدادات والمسارات، bootstrap/seed، إغلاق engine، إطلاق Linux، ملفات الحزمة، version/offline، وتوسعة اختبارات.
- **الاختبارات:** تُراجع حالات GitHub Actions للـPR #18 في الوقت الفعلي؛ وجودها وحده لا يجعلها ناجحة.
- **غير مثبت:** تطابق المحلي 8586c6c، جميع معايير التوافق 48، اعتماد الإنتاج، الحقل، DNS/TLS والخادم.
- **قيد المنتج التاريخي:** عيوب U1-01..08 لا تغلق إلا باختبار كل حالة فعلياً، ولا تُعتبر جميعها مغلقة لمجرد تغير الملفات.

راجع `LINUX_TRACEABILITY_AR.md` لربط الملفات بالعيوب والسيناريوهات، و`SOURCE_PROVENANCE_LINUX.json` لهوية خط الأساس.
