# PulseX SDKs — Guest QR / Offline Gate

هذه حزم عميلة خفيفة فوق API الحالي. لا تدّعي تثبيت عقد API نهائيًا للإنتاج قبل PostgreSQL/UAT/security sign-off.

- `python/`: عميل Python بلا تبعيات تشغيل خارج المكتبة القياسية.
- `javascript/`: عميل ES module يعتمد على `fetch`.
- الجلسة الحالية Cookie-based؛ الـSDK يحافظ على CSRF بعد تسجيل الدخول.
- استخدم HTTPS وعنوانًا عامًا معتمدًا في الإنتاج.

## Guest/QR operations

كلا العميلين (Python وJavaScript) يغطيان الآن:
- قراءة إعداد Guest للفعالية.
- تسجيل/استرجاع الزائر برقم الهاتف.
- مزامنة دفعات التسجيل.
- قراءة الحالة العامة للضيف دون كشف الهاتف.
- دليل الزوار الإداري وسجل check-in.
- Manifest طرفية البوابة ودفعات check-in باستخدام `X-PulseX-Device-Token`.

QR النهائي نفسه صورة PNG من endpoint العام؛ SDK يعيد بيانات الهوية/الحالة، بينما تنزيل الصورة يمكن تنفيذه مباشرة عبر رابط الـQR عند الحاجة.
