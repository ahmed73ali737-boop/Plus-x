# PulseX — جرد مصالحة الفروع 2026-10-14

الأساس: مقارنة جميع الفروع الـ25 التي كانت موجودة قبل إنشاء `integration/pulsex-consolidated-20261014` بفرع التكامل بعد نقل المصادر. المقارنة تشير إلى **الأنساب والتعديلات البرمجية** ولا تُساوي فحص الوظائف. مرجع الصلاحيات والواجهات في `docs/CONSOLIDATION_TRACEABILITY_20261014_AR.md`.

## أصول تاريخية مدمجة ضمن سلالة الفرع (12)
هذه الفروع تظهر **behind** بالنسبة إلى فرع التكامل، وليس لديها commit مستقل ahead منه عند الجرد:

- `main`
- `feature/public-experience-v2`
- `fix/audit-2026-10-07-360-regressions`
- `fix/audit-2026-10-07-p0`
- `fix/audit-update1-release-admission-20261008`
- `release/linux-ubuntu2404-standalone-candidate-20261010`
- `release/unified-v1.0.1`
- `release/v1.0.0`
- `release/v1.0.1-delivery-pack`
- `review/pulsex-shutdown-gate-r22-20261010`
- `review/pulsex-sqlite-url-win-r23-20261010`
- `review/pulsex-two-version-requirements-20261013`

**ليست هذه قائمة فروع للحذف التلقائي.** أي نموذج محلي أو بيانات خارج Git تحتاج فحصًا مستقلاً.

## فروع متباعدة في التاريخ (13)
لا يصح دمج كل التزام منها آليًا؛ المصدر الأصلي قد يكون أقدم أو أكثر تغييرًا. يفصل ما حملناه في source-lock، ويحتاج الباقي diff/سيناريو قبل حسمه:

| الفرع | commits ahead عن التجميعي وقت الجرد | ملاحظة |
|---|---:|---|
| `audit/2026-10-05-structure-qa` | 30 | تاريخ تدقيق قديم؛ ملفات app وweb تستلزم مراجعة |
| `ci/windows11-verification-20261005` | 10 | مسار native Windows قديم |
| `codex/database-observability-safety-20261012` | 4 | نقلت أصول مراقبة PG والاختبارات من PR #22 |
| `docs/closure-evidence-20261006` | 1 | مستندات وأدلة فقط |
| `feat/guest-qr-offline-brand-sites` | 360 | فرع كبير قديم؛ لا يُدمج عميانياً |
| `feature/enterprise-adoption-compose-r1` | 14 | مصدر منفذ shared auth واختباراته من PR #14 |
| `feature/iam-consumer-adoption-v1` | 3 | نقلت عقود IAM من PR #13 |
| `feature/party-network-asset-consumer-v1` | 1 | نقلت manifest من PR #15 |
| `feature/useas-party-network-consumer-v1` | 4 | نقلت اختبارات وتكامل عقد SDK مع نسخة R15 |
| `fix/pulsex-party-evidence-r15-20261009` | 7 | نقلت SDK الأشد تحققًا واختباراته |
| `integration/shared-observability-20261011` | 1 | نقلت وحدة المصدر والـlock والتوثيق من PR #21 |
| `reuse-manifest-v1` | 1 | يحتاج مراجعة الإصدارات والعقود |
| `windows-native-gate-v1` | 21 | اختبارات native قديمة؛ لا تعتمد كاختبار لآخر SHA |

## ما لا يعنيه هذا الجرد
لا يعني دمج Git أن هناك عقد تشغيل Windows MSI أو Linux DEB أو APK، أو اختبارًا ميدانيًا، أو Builder/Live Wall موزعًا، أو ضمانًا بأن نسخة Windows المحلية `8586c6c` (568 ملفًا في تقرير المستخدم) استُوعبت؛ هذا المصدر غائب عن المستودع المتصل. PR #25 لا يزال DRAFT. تبقى جميع PRs المصدر قيد المراجعة حتى توحيد السيناريوهات والاعتماد.

## خطة الإغلاق المحافظة
فحص file-by-file + scenario-by-scenario للفروع المتباعدة، منع إعادة إدخال إصلاح أقدم مكان إصلاح أحدث، تشغيل اختبارات Diff E2E على Windows/Linux بنفس dataset، ثم الدمج الآمن إلى main بعد اجتياز CI على نفس SHA والتوقيع البشري المطلوب.
