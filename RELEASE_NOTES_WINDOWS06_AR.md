# PulseX Windows 06 — Scale & Hardening

- رفع إصدار التطبيق إلى `0.6.0` وbuild إلى `windows-06`.
- إضافة load profiles حتى 25,000 submission صناعية قابلة للتشغيل؛ تم تسجيل نجاح x10 = 10,000 submission بلا أخطاء.
- إضافة فهارس لعمليات membership/participation/assignment/audit.
- دعم `WEB_WORKERS` لمسار التشغيل الإنتاجي، مع منع demo seed في multi-worker.
- تعطيل Demo seed افتراضيًا في Docker Compose وإضافة 4 workers افتراضيًا قابلة للتعديل.
- إضافة Production Configuration Gate.
- إضافة اختبارات Windows 06؛ المجموع الحالي 125 pytest pass.
- الحفاظ على API/OpenAPI 33 paths / 38 operations، version 0.6.0.
- إعادة تنفيذ HTTP/security/UI bridge/browser component/SDK checks بنجاح.

المتبقي المعتمد على البيئة: PostgreSQL/RLS، native Windows، offline physical kiosks، distributed realtime، production TLS، large concurrent browser load، DAST/Pentest، PostgreSQL recovery وfield UAT.
