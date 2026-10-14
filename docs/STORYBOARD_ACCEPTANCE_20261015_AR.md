# PulseX — ترتيب عناصر التجربة على نفس مصدر المنتج (15 أكتوبر 2026)

**نطاق هذه الإضافة: STORYBOARD PARTIAL / INTEGRATION REVIEW.** لا تعني وجود Builder مرئي متكامل أو قبول نسخة Production.

- أضيف تبويب مستقل 'ترتيب التجربة' في Studio وشارة وصول من الرئيسية.
- محرر مصوّر للقائمة الحالية من record blocks التي أنشأها المدير مسبقًا عبر tabs (أسئلة، تصويت، إعلانات، خدمات، وسائط...)
- سحب وإفلات داخل الصفحة، وأزرار تقديم وتأخير عبر الصفحات للهاتف ولوحة المفاتيح، 25 مادة لكل صفحة، مع دعم حتى حد 2000 المسموح للخادم.
- يحفظ الترتيب إلى نفس المسودة ونفس Draft Revision عبر PUT /api/admin/sites/{sid} مع CSRF ودور الإدارة وفحص revision؛ لا نشر تلقائي، ولا تغيير schema، ولا حذف/إعادة إنشاء أي record.
- عند رفض الخادم للحفظ أو تضارب تعديل متزامن يعيد الترتيب السابق ويُظهر سبب الرفض.
- سؤال ذو تفرع show_if لا يمكن وضعه قبل السؤال المرجعي ضمن الاستبيان نفسه (تحقق واجهة وخادم).
- **مهم:** هذا ترتيب سجلات موجودة داخل قوائمها وأقسامها الحالية؛ الواجهة العامة تعرض أنماط المحتوى في أقسام منفصلة. لا يُقدّم هذا تحريرًا كاملًا لمسار التصفح العابر للأقسام أو إنشاء/تشغيل Blocks جديدة مثل Welcome/Branch/CTA/Thank You أو بثًا موزعًا للمخرجات.

## التتبع

| ID | الطرف | الشاشة | API/DB | السيناريو | إثبات مبدئي |
|---|---|---|---|---|---|
| ST-01 | مدير جهة/منظم | Studio / ترتيب التجربة | PUT draft config / sites.draft_rev | تقديم/تأخير وحفظ المسودة دون نشر | tests/test_storyboard.py، tests/storyboard_core_smoke.mjs |
| ST-02 | زائر | الصفحة العامة | GET published site/version | لا تتغير بيانات الجمهور حتى publish | tests/test_storyboard.py |
| ST-03 | مسؤول مقابل جهة أخرى | Studio | require_scope + CSRF | رفض تعديل جهة أخرى | tests/test_storyboard.py |
| ST-04 | مشرف | Studio | optimistic revision check | خطأ 409 عند استخدام revision قديم | tests/test_storyboard.py |
| ST-05 | محرر أسئلة | Studio / ترتيب التجربة | normalize_config show_if | رفض جعل التفرع قبل مرجعه | tests/storyboard_core_smoke.mjs |
| ST-06 | هاتف/لوحة مفاتيح | أزرار التحريك / الصفحات | نفسه | نقل عبر صفحات، rollback عند خطأ، DnD | tests/storyboard_ui_contract.mjs |

**دليل محلي أولي:** Node ST core PASS، Node ST UI simulated PASS، pytest tests/test_storyboard.py PASSED، و87/87 من اختبار storyboard + pilot ضمن مصدر الحزمة المحلية. هذا الاختبار **ليس** Chromium ولا كل CI على GitHub HEAD؛ عمل Windows/Ubuntu/PostgreSQL واختبار UX field/UAT وBuilder الكامل ما زال مفتوحًا.