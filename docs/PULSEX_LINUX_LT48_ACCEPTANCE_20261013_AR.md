# PulseX Linux LT-01..LT-48 — قائمة القبول الفردية
المصدر: `Linux _changing_plan.md`، 2026-10-09. نُقلت الحالات الـ48 وأهدافها من الخطة دون إسقاط. هذه قائمة تحقق؛ نجاح workflow شامل لا يجعل كل حالة PASS تلقائيًا.

المرجع العام: Ubuntu/ARM64/PostgreSQL/browser/package على `35f3347e` نجح في workflow #38364627785. Windows CI على رأس الإصلاح المشترك `ae40111b` نجح في #38024557724. للقبول الفردي يلزم اسم الاختبار ونتيجته وملف الأدلة وSHA لكل صف؛ لا يوجد هذا الربط للـ48 كلّها. التقرير المفصل للمنتج: `docs/PULSEX_TWO_VERSION_REQUIREMENTS_REVIEW_20261013_AR.md`.

| ID | السيناريو | معيار القبول | الاختبار المقترح في الخطة | قرار الفردي الحالي |
|---|---|---|---|---|
| LT-01 | إعداد clean venv على Ubuntu3.12 ثم imports وpip check | تثبيت ناجح وفق profile ومفسر مسجل | `test_linux_runtime.py` + CI | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-02 | تمرير مجلد venv يحوي تخطيط Windows/مفسراً غير متوافق | رفض واضح دون حذفه أو مسح data | runtime tests | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-03 | بدء التطبيق مرتين بعد الإعداد مع تعطيل تنزيل الحزم في تجربة الاختبار | لا pip ولا اتصال setup؛ التطبيق يبدأ ببيئته الموجودة | subprocess startup | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-04 | بدء قبل setup أو مع حزمة مطلوبة ناقصة | exit غير صفر وسبب وأمر إعداد؛ لا إنشاء جزئي للبيانات | runtime tests | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-05 | ملف .sh من Git archive وclone | LF دون BOM؛ TAR executable؛ بديل sh يعمل | `test_linux_packaging.py` | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-06 | تشغيل من CWD خارجي | نفس DB وmedia والهوية، دون ملف بيانات بديل | `test_runtime_paths.py` | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-07 | checkout اختبار اسمه يحتوي مسافة وحروفاً عربية | setup/help/run/HTTP/cleanup تنجح مع quote صحيح | paths integration | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-08 | موارد source للقراءة فقط وDATA_DIR مستقل | يعمل التطبيق دون محاولة الكتابة في web/app/templates | paths integration | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-09 | SQLite ذاكرة ومطلق ونسبي مع خيارات URL | تحليل ومسار واتصال صحيح دون string replacement عام | DB tests | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-10 | استدعاء كل tool بـmodule وPYTHONPATH غير معرف | help لا تتصل DB؛ الأدوات المحددة تنجح في بيئة اختبار | `test_tool_entrypoints.py` | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-11 | import run.py/مصنع التطبيق دون تشغيل | لا CWD change ولا إنشاء DB/account/media غير مطلوب | startup tests | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-12 | أسبقية override مقابل env، خصوصاً False/None | إعداد نهائي مطابق للعقد | `test_runtime_settings.py` | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-13 | PORT/WEB_WORKERS/Boolean غير صالح | خطأ مبكر موحد؛ لا تصحيح صامت أو بدء جزئي | settings tests | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-14 | production env صالحة مع overrides SQLite/HTTP/seedTrue | رفض الثلاثة قبل make_engine | gate regression الحالي | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-15 | ملف حساب تحت umask متساهلة | 0600 عند الإنشاء؛ لا ظهور السر في log أو HTTP | `test_posix_files.py` | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-16 | وجهة حساب غير قابلة للكتابة/ملف موجود/symlink | رفض معلوم دون استبدال وجهة غير مقصودة | files integration | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-17 | فشل file write أو rename أو DB commit في bootstrap | حالة قابلة للاسترداد ومؤشرات دقيقة؛ لا duplicate admin | bootstrap tests | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-18 | إعادة تشغيل SQLite بعد إنشاء ونشر وجمع إجابة | بيانات مستمرة؛ لا seed/reset جديد | native_acceptance expansion | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-19 | snapshot SQLite ووسائط من مسارات مخصصة، ثم restore في مجلد آخر | integrity وبيانات وHTTP صحيحة؛ ملف حساب غير مضمن | backup integration | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-20 | محاولة backup_local لPostgreSQL | رفض صريح؛ لا نجاح كاذب أو ZIP فارغ | backup tests | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-21 | SIGINT وSIGTERM لمسار Start-Linux | shutdown منظم وخروج ومنفذ محرر | `test_posix_lifecycle.py` | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-22 | SIGTERM أثناء طلب جارٍ، بمهلة معروفة | إكمال/إنهاء حسب العقد دون بيانات جزئية أو تعليق | lifecycle integration | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-23 | عدة عمال مع seed=false ثم shutdown | كل العمال بنفس الإعدادات؛ لا orphan أو bootstrap متكرر | multi-worker integration | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-24 | QA group يتجاوز المهلة وله خادم ابن | إنهاء المجموعة المملوكة كلها وتنظيف DB | qa_support tests | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-25 | خروج قائد QA وبقاء ابن، وعملية أخرى غير تابعة | تنظيف الابن فقط؛ العملية الأخرى تبقى | QA process ownership | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-26 | تعارض المنفذ عند بدء التطبيق | فشل واضح دون قتل العملية التي تشغله | startup integration | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-27 | SQL واحد بـLF وCRLF وفق التاريخ، وتعديل منطقي حقيقي | توافق تاريخي، ورفض التغيير الحقيقي | migrate regression expansion | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-28 | PostgreSQL fresh ثم repeat ثم upgrade من نسخة قديمة | 002–007 مطبقة صحيحة، repeat لا يعيدها | postgres_native expansion | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-29 | migration مفقودة/bad checksum/فشل SQL أثناء التنفيذ | ready503/rollback بحسب المعاملة؛ لا نجاح عام | PG native + health | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-30 | bootstrap/migration منافسان | قفل/رفض/انتظار معلوم؛ حساب أول واحد ومخطط صحيح | PG integration | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-31 | غياب PG URL الاختبار أو تصريح reset | blocked3 واضح؛ strict profile لا يقبل المجموعة | runner tests | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-32 | assets وموديولات وmanifest وtemplates وmedia بأسماء دقيقة | 200 وMIME صحيح، و404 لأسماء غير موجودة فعلاً | Linux HTTP asset contract | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-33 | CSV/XLSX عربية واستيراد ZIP غير صالح ثم export | حفظ Unicode ورفض المدخل الضار؛ CSV بلا فساد أو صيغة خطرة | import/security/native | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-34 | hash كلمة مرور تاريخية ثم إنشاء جديدة على3.12 | old/new login ينجح؛ السر والسياسة محفوظان | security/password integration | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-35 | فشل تسجيل الزائر بعد insert، وsync batch فيه رفض | لا صف يتيم؛ savepoints تبقي العمليات السليمة | guest regression الحالي | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-36 | جهاز heartbeat بعد تحديث الحزمة | app_version توافق نسخة الواجهة المقبولة وتظهر في DB | browser_guest_flow | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-37 | عميل SW قديم ثم موارد إصدار جديد | JS الجديد يظهر دون clear storage أو حذف pending | browser_shell_upgrade | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-38 | offline enqueue ثم reload ثم reconnect/replay | العدد النهائي صحيح بلا فقد أو duplicate | browser_offline/guest/http | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-39 | اختلاف origin في fixture متصفح مستقلة | عدم وعد مشاركة storage؛ إجراء المنتج الموثق يحمي pending | offline migration UX | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-40 | اختيار browser الافتراضي وoverride صريح وغياب browser | نفس النسخة مسجلة؛ missing سبب واضح؛ لا fallback صامت | `test_qa_browser_selection.py` | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-41 | runtime profile دون QA/Node/Chromium | backend/public HTTP يعمل؛ غياب أدوات QA لا يمنع run | runtime integration | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-42 | SDK Python مثبت وSDK JS مع Node الاختبار المحدد | health/auth/errors وHTTP تعمل دون مسار Windows | SDK existing + packaging | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-43 | VERSION داخل مصدر ومستخرج وصورة إن اعتمدت | الهوية متفقة؛ لا بديل dev في حزمة قبول | metadata/package tests | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-44 | release_type وnotes وأسماء ZIP/TAR | validator موحد ينجح؛ تعارض متعمد يرفض | release metadata tests | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-45 | artifact source inventory | جميع الموارد المطلوبة موجودة، ولا .env/venv/DB/accounts | packaging tests | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-46 | timeout/failure/blocked وغياب dependency في runner | summary كاملة ورمز خروج مناسب، وأدلة الجولة لا تختلط | runner integration | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-47 | تعدد العمال والـrate-limit الحالي | يوضح هل العد لكل عامل؛ لا يعتبر الحد المحلي حداً عالمياً | middleware multi-worker | دليل فردي غير مربوط بعد؛ راجع CI العام |
| LT-48 | load بنفس workload ومنصة معلومة | errors/latency/RSS/CPU مسجلة؛ لا مقارنة مضللة بـVPS مجهول | load profiles | دليل فردي غير مربوط بعد؛ راجع CI العام |
## ترتيب إغلاق عملي
- LT-01..05: نظافة التثبيت والحزمة، المسار التنفيذي وملفات shell.
- LT-06..17: المسارات والإعدادات والملفات الحساسة وحقن الفشل.
- LT-18..31: المعاملات، الاستعادة، lifecycle، الترحيلات وPostgreSQL.
- LT-32..42: الموارد، الاستيراد، الضيف، الترقية، offline وSDK.
- LT-43..48: هوية الإصدار، محتويات الحزمة، runner، تعدد العمال والحمل.

لا يُنقل أي صف إلى PASS إلا بعد تشغيله على المصدر المعني وتثبيت أثره. المصدر المحلي `8586c6c` غير متاح؛ أي حالة تعتمد عليه تبقى مفتوحة للمطابقة حتى لو نجح فرع GitHub.
