# PulseX Windows 12 — الأطراف والهرمية وGuest QR/Offline

## الهرمية والحسابات
تستمر البنية: Platform → Events → Event Participations → Organizations/Agency pages. أعضاء المؤسسة يمكن أن يوجدوا بلا حساب؛ Membership لا تنشأ إلا لمن يحتاج الإدارة. الزائر العام لا يحتاج حسابًا للتصفح أو الاستبيان/التصويت/التقييم وفق سياسة الصفحة.

## Guest Identity
- الهاتف بعد normalization هو مفتاح الهوية الفريدة.
- قاعدة البيانات تفرض uniqueness، ويغطي PostgreSQL CI التسجيل المتزامن لنفس الهاتف من عدة عملاء.
- رقم الزائر النهائي `G-...` مشتق بـHMAC server-side باستخدام `GUEST_ID_SECRET` ولا يحتوي الهاتف ولا يمكن توليده من الهاتف دون المفتاح.
- lookup العام لا يعيد الاسم أو الهاتف؛ دليل المنظم فقط يعرض بيانات التواصل.
- Manifest البوابة لا يحتوي الهاتف.

## QR
يوجد نوعان:
1. QR الصفحة العامة مع `?source=qr` لتتبع مصدر التفاعل.
2. Guest QR فردي يفتح `/e/{event}/guest/{guest_number}`.
Guest QR يستخدم Error Correction Q وquiet zone مناسبًا للمسح.

## التسجيل دون اتصال
إذا كانت صفحة التسجيل محملة ثم انقطع الاتصال:
1. ينشأ رقم محلي عشوائي مؤقت `P-...`.
2. لا يصدر QR نهائي قبل الوصول إلى خادم الفعالية.
3. الطلب يحفظ في IndexedDB.
4. عند عودة الاتصال تتم المصالحة تلقائيًا إلى رقم `G-...` وQR النهائي.
5. بعد receipt ناجح يحذف raw phone من السجل المحلي المكتمل ويحذف عنصر outbox.

بهذا لا نحول SHA الهاتف إلى بطاقة عامة حتى مؤقتًا.

## Gate Scanner Offline
عند Pair للطرفية:
- يحفظ Device token في IndexedDB وليس localStorage.
- يجهز manifest الحد الأدنى: guest number/name/org/job/status بلا هاتف.
- check-in يحفظ في outbox عند الانقطاع.
- sync يعيد الإرسال ويستخدم scan UUID ثابتًا؛ accepted/duplicate يثبتان receipt ثم يحذفان outbox.
- retry يتم عند online ودوريًا، ويمكن للمشغل الضغط «مزامنة الآن».

## الأدلة الآلية
CI يغطي:
- IndexedDB component.
- real Chromium local HTTP guest journey.
- same-phone recovery.
- offline registration → reconnect → final QR.
- offline gate check-in → reconnect.
- Windows hosted Chromium.
- native PostgreSQL + concurrency.
- 1000 guest capacity smoke.

## حدود لا يجوز تحويلها إلى PASS آلي
- كاميرا هاتف/تاب فعلية وUSB scanner.
- انقطاع مادي لبوابتين/عدة بوابات.
- Local venue/LAN deployment فعلي.
- 5-day soak.
- real domain/TLS.
هذه تحتاج UAT ميدانيًا.
