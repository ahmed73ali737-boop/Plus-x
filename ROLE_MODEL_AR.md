# نموذج الأطراف والحسابات — Windows 10

| المستوى/الطرف | دائم؟ | يحتاج حساب؟ | من ينشئه؟ | النطاق |
|---|---|---|---|---|
| Platform Admin | دائم | نعم | إعداد المنصة | المنصة كاملة |
| Organization | دائم | ليس بالضرورة | Platform/Organizer/Approval | ملف المؤسسة الدائم |
| Organization Owner/Admin | دائم | نعم | Platform/Organizer/Owner | المؤسسة والمشاركات المسموحة |
| Event Organizer | حسب الفعالية | نعم | Platform/Assignment | الفعالية |
| Participant Organization | دائم كمؤسسة، مؤقت كمشاركة | اختياري | Organizer/Platform/Public Request | الفعالية + صفحتها |
| Participant User | دائم في المؤسسة | نعم عند التحكم | Organizer/Owner | المؤسسة/المشاركة |
| Public Visitor | Session | لا | — | تصفح/تفاعل حسب السياسة |
| Kiosk/Display | Device | Device token | Admin | جهاز محدد |

## حالات الجهة المشاركة

1. جهة عرض فقط: لها صفحة ومحتوى ولا يوجد User.
2. جهة متحكم بها من المنظم: المنظم يدير الصفحة بالكامل.
3. جهة بحساب تحكم مباشر: ينشأ User + كلمة مرور مؤقتة.
4. جهة يضاف مستخدمها لاحقًا: تنشأ المؤسسة والمشاركة الآن، والحساب لاحقًا.

## قاعدة الأمان
لا يمنح أي Public Request صلاحية مباشرة. كل طلب Pending حتى اعتماد مستخدم مخول.
