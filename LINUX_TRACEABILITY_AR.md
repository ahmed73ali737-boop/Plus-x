# PulseX Linux — تتبع المتطلبات والإصلاح والاختبار

**أساس هذا السجل:** الخطة المرفقة `Linux _changing_plan.md` (18 فجوة LNX، و8 عيوب U1، و48 سيناريو LT). الحالة المقصودة "نُفذ في الشيفرة" **ليست** مساوية "نجح الاختبار" أو "جاهز للإنتاج". المصدر المحلي 8586c6c غير متاح، وبالتالي لا يُغلق بند تطابق المصدر.

| الرمز | التطبيق في النسخة المستقلة | دليل التحقق المطلوب | حالة التنفيذ |
|---|---|---|---|
| LNX-01 | `Start-Linux.sh`, `tools/prepare_runtime.py` | تشغيل ثان بلا pip، LT-01/03 | منفذ؛ قبول CI مطلوب |
| LNX-02 | سكربتا Test Linux يستخدمان venv | LT-04 والـQA الكاملة | منفذ؛ قبول CI مطلوب |
| LNX-03 | Git executable bit للشِل | TAR وgit ls-tree، LT-05 | منفذ؛ قبول artifact مطلوب |
| LNX-04 | `tools/launcher.py` يستعلم live/version | Windows launcher + LT-11 | منفذ جزئياً؛ انحدار Windows مطلوب |
| LNX-05 | `app/core/paths.py`, settings, db, server | LT-06/07/08/09 | منفذ جزئياً؛ المسار العربي/read-only مفتوح |
| LNX-06 | CLI بوضع `python -m tools.*` | LT-10 لجميع الأدوات | جزئي؛ فحص جميع entrypoints مفتوح |
| LNX-07 | Gate يأخذ effective overrides قبل DB | LT-12/13/14 | منفذ؛ اختبار جديد |
| LNX-08 | Start exec وlifespan؛ QA process-groups | LT-21..26 | جزئي؛ process-group غير منفذ هنا |
| LNX-09 | Credentials 0600 + bootstrap/seed rollback | LT-15/16/17 | منفذ؛ حقن الفشل جزئياً |
| LNX-10 | `migration_checksum` LF/CRLF + .gitattributes | LT-27..30 | منفذ؛ ترقية PG تاريخية مفتوحة |
| LNX-11 | `ops/Dockerfile` VERSION وexec | LT-43 + arm64 image | منفذ؛ native image acceptance مطلوب |
| LNX-12 | Playwright Chromium افتراضي | LT-40 | منفذ للاختبار المفحوص؛ توحيد بقية QA مفتوح |
| LNX-13 | Ubuntu24.04/Python3.12 في CI مع Windows3.13 | CI per-SHA | منفذ؛ نتائج مطلوبة |
| LNX-14 | runner strict + المجموعات المحجوبة | LT-31/46 | مفتوح؛ runner المحدد غير موجود في المصدر GitHub |
| LNX-15 | أمثلة env محلية/QA ودليل واضح | LT-12/13 | منفذ توثيقياً؛ فحص parser مطلوب |
| LNX-16 | backup_local لSQLite المخصصة | LT-19/20 | منفذ؛ restore ميداني/اختبار معزول مفتوح |
| LNX-17 | lifespan + تفريغ engine | LT-21/22 | منفذ جزئياً؛ غلق موارد خارج engine مفتوح |
| LNX-18 | نسخة SW وheartbeat؛ release metadata | LT-36/37/43/44 | جزئي؛ release evidence والعملاء القدامى مفتوح |
| U1-01 | SQLite outer BEGIN يصلح SAVEPOINT؛ بقاء زائر بعد late failure | exact HTTP injected late failure/DB row checks | يحتاج إعادة اختبار مباشر |
| U1-02 | effective factory args تحكم قبل engine | test_gate_uses_effective_factory... | منفذ؛ CI مطلوب |
| U1-03 | normalized checksum | test_migration_checksum... + native PG | منفذ جزئياً |
| U1-04 | launcher /live + version | Windows launcher smoke | منفذ؛ تحقق مباشر مفتوح |
| U1-05 | release notes/manifest نسخة متسقة من PR12 | metadata contract | جزئي |
| U1-06 | Heartbeat app version من /api/health | guest browser + DB | منفذ؛ اختبار متصفح/DB مطلوب |
| U1-07 | SW shell-v21 وترقية cache دون حذف IndexedDB | old SW -> new SW -> pending replay | جزئي؛ old-client E2E مفتوح |
| U1-08 | release gate في PR12 يمنع النشر بدون evidence | workflow validator | منع النشر منفذ؛ القبول مفتوح |

## Matrix 360 — رحلات الأطراف والنهايات

| الطرف/القناة | السيناريو | منبع التنفيذ | سيناريو QA | اعتماد الحالة |
|---|---|---|---|---|
| المنصة/المنظم | تسجيل الدخول، الإنشاء، نشر التجربة | `app/server.py`, UI admin | native_acceptance + browser_control_contract | CI جديد |
| الجهة المشاركة | إدارة ملف الجهة وتجربتها | `app/application`، واجهة RTS/Easy/Tharawat | browser_exhibition_sites | CI جديد |
| الزائر | هاتف فريد، QR، تصويت وأسئلة | guest_service/guest_routes، UI public | guest_flow + question_roundtrip | CI جديد، حقن U1-01 مفتوح |
| موظف البوابة | مسح QR، أذونات الجهاز ودخول/خروج | device/gate routes، IndexedDB | guest_flow وoffline browser | CI جديد + اختبارات الحقل مفتوحة |
| مشرف العرض | تقارير حية/إحصاءات ونشر | collection/public services | native + browser + capacity | CI جديد |
| المشرف التقني | PG/migrations/backup/health | db, ops, tools | PostgreSQL native + restore | CI جديد؛ نسخ/استرجاع الإنتاج مفتوح |
| كل الأطراف | عزل وصلاحيات وأمان وخصوصية | middleware/access & gate | security QA + DAST/field UAT | CI محدود؛ DAST وUAT مفتوحة |

**قبول 48 حالة LT:** لا تدّعي هذه الوثيقة تنفيذها جميعاً؛ تُنشأ نتائج مستقلة مرتبطة بمعرفات الاختبارات وملفات workflow. تُحفظ تاريخية Windows (252/259 و27/32) من دون نقلها إلى قبول Ubuntu.
