# PulseX Windows 11 — Hierarchy, People & Offline Verification

هذه النسخة تكمل Windows 10 ولا تعيد المشروع من البداية.

## إضافات وظيفية

- Organization People: أعضاء/ممثلو الجهة يمكن تسجيلهم **بدون حساب**.
- إنشاء حساب إدارة للشخص لاحقًا وربطه بعضوية المؤسسة.
- واجهة Admin تعرض «الفريق / أعضاء بدون حساب» و«عضويات الحسابات» بصورة منفصلة.
- الحسابات الجديدة ذات كلمة المرور المؤقتة أصبحت تحمل `must_change_password` ويمنع عنها استخدام الإدارة حتى تغييرها.
- Migration توافقية لقواعد SQLite السابقة لإضافة حقل تغيير كلمة المرور دون حذف البيانات.
- تعديل Access Policy حتى يوقف تعليق Participation وصول حساب الجهة إلى صفحة الفعالية.
- إضافة PostgreSQL migration `003_windows11_people_password.sql`.
- إعادة توليد Full PostgreSQL schema وOpenAPI/API contract.

## اختبارات

- 167 pytest PASS.
- 31 HTTP acceptance PASS.
- 13 security PASS.
- 9 browser component PASS.
- 11 اختبارات Windows 11 الجديدة PASS.
- Coverage app: 88% branch-aware.
