# PulseX Windows 09 — الموجود والحدود

| المجال | Windows 09 | الحالة |
|---|---|---|
| الأسئلة | 22 نوعًا، منها Date/Time/DateTime، محرر نوعي ديناميكي | Local PASS |
| الاستبيانات | تعريف مستقل بالاسم والوصف ورسالة الإكمال + تجميع أسئلة واضح | Local PASS |
| التصويت | شاشة إدارة مستقلة + schedule حقيقي + منع الإرسال الفارغ | Local PASS |
| التقييم | نجوم لكل معيار + ملاحظة مكتوبة | Local PASS |
| التواصل | هاتف/بريد/رسالة/قناة مفضلة + موافقات منفصلة + ظهور الطلبات للإدارة | Local PASS |
| مواعيد الفعالية | `datetime-local` بدل ISO يدوي في الواجهة | Static/API PASS |
| مواعيد الجلسات والإعلانات | `datetime-local` مع تحويل إلى ISO في الحفظ | Static/API PASS |
| المشاركة في الفعالية | valid from/until كحقول تاريخ ووقت | Static/API PASS |
| Legacy survey data | تُكتشف form ids القديمة تلقائيًا | PASS |
| Admin Panel | Questions Manager + Polls Manager + Metrics contact requests | Local PASS |
| Browser E2E كامل | لم يُعتمد بسبب قيود الحاضنة | BLOCKED |
| PostgreSQL/RLS | غير معتمد بعد | BLOCKED |
| Offline field test | غير معتمد | BLOCKED |
