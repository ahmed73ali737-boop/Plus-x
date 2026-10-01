# حالة الإغلاق — PulseX Windows 10

## يعمل ومختبر محليًا
- الموقع العام للمنصة والفعاليات والجهات.
- المؤسسات الدائمة والمشاركات المؤقتة.
- الحسابات والعضويات وكلمات المرور المؤقتة.
- طلب الانضمام من الموقع العام واختيار Organizer/Participant.
- إنشاء Participant كعرض فقط أو بحساب تحكم.
- الأسئلة والاستبيانات والتصويت والتقييم والملاحظات والتواصل.
- الخدمات والحقائق والإعلانات والوسائط.
- Theme Studio وTemplates العامة + RTS Tech + Easy Finance & Payments.
- Excel/CSV، المعاينة، النشر، النتائج، Audit، Devices، API وSDK الموروثة.

## مؤجل عمدًا
- Tenant مستقل متعدد المستأجرين: مؤجل بناءً على أولوية الاستقرار. البنية الحالية Platform → Organization → Event → Participation تمنع الحاجة لإعادة البناء لاحقًا، لكن لا تدعي Tenant isolation الآن.

## يحتاج بيئة خارجية قبل Production
- Windows Native acceptance.
- PostgreSQL migrations/RLS/native tests.
- HTTPS/domain.
- Service Worker + IndexedDB على الأجهزة.
- اختبار انقطاع جهازين وخمسة أيام.
- Load/Stress/Spike/Soak على PostgreSQL وhost حقيقي.
- DAST/Pentest.
- Business/Field UAT والتوقيع.
