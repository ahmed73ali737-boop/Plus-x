# دليل التحقق الجاري — 20 أكتوبر 2026

ابدأ من [سجل القبول الجاري](../docs/CURRENT_ACCEPTANCE_AR.md) ومن [دليل الترقية والبطاقات](../docs/UPGRADE_PASSES_OFFLINE_RUNBOOK_AR.md). الأرقام والعلامات التاريخية أدناه لا تعتمد المرشح الحالي تلقائيًا.

لـWindows وLinux، استخدم بيئة QA مستقلة من القفل المطابق، ثم شغّل المجموعة المطلوبة. تثبيت QA لا يخص صورة الإنتاج:

```sh
python -m pip install --require-hashes --only-binary=:all: -r requirements/locks/qa.txt
python -m pytest -q tests/test_upgrade_safety.py tests/test_device_admission_scope.py tests/test_pwa_install_contract.py tests/test_acceptance_evidence.py
python -m tools.run_candidate_checks --output codex-audit-artifacts/candidate-current
```

أداة المرشح تتطلب commit ثابتًا لملفات المصدر، وتحفظ SHA وبصمات المصدر والأدلة. رمز3 يعني أن الفحوص المحلية نجحت لكن القبول الخارجي محجوب، وليس نجاح إصدار.

عقد DOM يستعمل Node داخل pytest، ولا يمثل Chromium. المتصفح الحقيقي: `python tests/invitations_native_acceptance.py` بعد تثبيت Playwright/Chromium. القاعدة الأصلية: `python tests/postgres_invitations_acceptance.py` وبروفة النقل: `python tests/postgres_upgrade_rehearsal.py` مع قاعدة اختبار وتصريح البيئة. التعافي بالحاويات: `python tests/runtime_recovery_acceptance.py` على مضيف Docker مخصص. هذه الأوامر لا تنصب VPS ولا تضبط DNS أو الجدار الناري.

لا تستعمل ملف backup أو قاعدة جمهور في اختبارات reset أو الأعطال. لا تعين أعلام PX_*_ACCEPTED لإمرار بناء. راجع حدود offline وSLO والعتاد في سجل القبول.

---

## إرشادات تاريخية محفوظة

# إعادة الاختبارات

`Test-Windows.cmd` هو المسار المحلي المبسط، لا يحتاج pytest أو Playwright بعد تجهيز التطبيق.

للمطور فقط بعد تثبيت متطلبات QA في بيئة منفصلة:

```sh
python -m pytest tests/test_pilot.py tests/test_windows03.py -q
python tests/native_acceptance.py
python tests/run_ui_bridge.py
```

اختبار run_ui_bridge ينشئ خادمًا مؤقتًا وقاعدة خاصة ويمرر المسار إلى حاضنة Chromium. يحتاج Chromium وPlaywright ويمكن ضبط PX_QA_CHROMIUM. لا يختبر شبكة المتصفح الأصلية أو Service Worker أو IndexedDB؛ بدائلها موضحة في رأس الملف. لا تشغّل browser_windows03 على قاعدة جمهور. الصور المرفقة ناتجة عن هذه الحاضنة.
