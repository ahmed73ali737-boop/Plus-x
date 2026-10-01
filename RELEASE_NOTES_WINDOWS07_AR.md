# PulseX Windows 07 — Closure & Devices

- ترقية الإصدار إلى `0.7.0` واسم البناء إلى `windows-07`.
- إضافة سجل طرفيات فعلي: Kiosk / Tablet / Display / Operator مع token hashed وحالة وآخر ظهور وآخر مزامنة وعدد المعلّق.
- إضافة API وواجهة Admin للطرفيات، ونبضات Heartbeat من الجهاز.
- إضافة ربط الطرفية من واجهة وضع الجهاز/Offline باستخدام رمز يظهر مرة واحدة من الإدارة.
- إضافة مراجعة ورفض طلبات الحساب من لوحة الإدارة.
- إضافة إيقاف/تفعيل الحساب وإنهاء جلساته عند الإيقاف.
- فصل منطق public rendering إلى `application/public_service.py`، ومنطق الأجهزة وطلبات الوصول إلى Application Services مستقلة.
- تحديث Python SDK وJavaScript SDK لدعم الطرفيات ومراجعة طلبات الوصول.
- تحديث Service Worker cache إلى v07 لمنع بقاء أصول قديمة بعد الترقية.
- إضافة API contract snapshot واختبارات لحماية سطح API من الحذف غير المقصود.
- توليد DDL PostgreSQL كامل من metadata وإضافة migration خاصة بالطرفيات.
- إضافة اختبار PostgreSQL أصلي إتلافي لقاعدة اختبار مخصصة؛ لم يُنفذ في هذه البيئة لعدم توفر PostgreSQL.
- تشديد Production Gate: لا يمر إلا بعد قبول PostgreSQL والحمل والأمن واختبار Offline الميداني صراحةً.
- Docker يشغل Production Gate قبل بدء التطبيق.
