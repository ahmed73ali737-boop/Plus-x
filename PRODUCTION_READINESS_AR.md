# PulseX Windows 07 — Production Readiness

## Release Gate
`python tools/production_gate.py` لا يمر إلا إذا كانت الإعدادات Production صحيحة **وكذلك** أعلام الأدلة التالية true بعد نجاح اختبارات فعلية:
- `PX_NATIVE_POSTGRES_ACCEPTED`
- `PX_LOAD_ACCEPTED`
- `PX_SECURITY_ACCEPTED`
- `PX_FIELD_OFFLINE_ACCEPTED`

Docker يشغل هذا Gate قبل التطبيق. إبقاء أي علم false يمنع اعتبار النشر Production.

## PASS محلي
135 pytest، 31 HTTP acceptance، 28 UI bridge، 9 browser components، 13 security smoke، Python SDK 8، JS SDK 5، API contract، x10 synthetic load.

## BLOCKED خارج البيئة
Windows native؛ PostgreSQL native/RLS؛ HTTPS target; physical kiosks/5-day soak; remote concurrent load; DAST/Pentest; PostgreSQL PITR; field/business UAT signatures; distributed WebSocket/Redis.


## Guest Identity / QR hardening
- الإنتاج يتطلب `GUEST_ID_SECRET` مستقلًا بطول 32+ حرفًا عبر Release Gate.
- رقم الزائر العام و`phone_hash` يستخدمان HMAC keyed digest؛ لا يتم اشتقاق QR العام من SHA مباشر للهاتف.
- التسجيل من متصفح معزول تمامًا يحتفظ فقط بمعرف محلي مؤقت `P-...` حتى الوصول إلى خادم الفعالية/شبكة LAN؛ QR النهائي لا يصدر إلا من الخادم.
- قاعدة البيانات تفرض unique على الهاتف/البصمة/رقم الزائر، واختبار PostgreSQL يتضمن تسجيل نفس الهاتف بالتوازي من عدة عملاء.
