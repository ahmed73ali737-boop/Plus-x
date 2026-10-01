# PulseX SDKs — Windows 05

هذه حزم عميلة خفيفة فوق API الحالي. لا تدّعي تثبيت عقد API نهائيًا للإنتاج قبل PostgreSQL/UAT/security sign-off.

- `python/`: عميل Python بلا تبعيات تشغيل خارج المكتبة القياسية.
- `javascript/`: عميل ES module يعتمد على `fetch`.
- الجلسة الحالية Cookie-based؛ الـSDK يحافظ على CSRF بعد تسجيل الدخول.
- استخدم HTTPS وعنوانًا عامًا معتمدًا في الإنتاج.
