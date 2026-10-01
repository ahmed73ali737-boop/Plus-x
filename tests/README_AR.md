# إعادة الاختبارات

`Test-Windows.cmd` هو المسار المحلي المبسط، لا يحتاج pytest أو Playwright بعد تجهيز التطبيق.

للمطور فقط بعد تثبيت متطلبات QA في بيئة منفصلة:

```sh
python -m pytest tests/test_pilot.py tests/test_windows03.py -q
python tests/native_acceptance.py
python tests/run_ui_bridge.py
```

اختبار run_ui_bridge ينشئ خادمًا مؤقتًا وقاعدة خاصة ويمرر المسار إلى حاضنة Chromium. يحتاج Chromium وPlaywright ويمكن ضبط PX_QA_CHROMIUM. لا يختبر شبكة المتصفح الأصلية أو Service Worker أو IndexedDB؛ بدائلها موضحة في رأس الملف. لا تشغّل browser_windows03 على قاعدة جمهور. الصور المرفقة ناتجة عن هذه الحاضنة.
