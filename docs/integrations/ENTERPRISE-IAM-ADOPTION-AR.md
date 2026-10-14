# Enterprise IAM — عقد مواءمة Plus-x

**الحالة:** `ADOPTION_CONTRACT_ONLY_NOT_RUNTIME_CONNECTED`. هذه وثيقة تحضير تكامل في فرع مراجعة، وليست ادعاء تشغيل IAM موحد في المنتج.

## المرجع الواحد
المصدر البرمجي والسياسات في `ahmed73ali737-boop/G-Factory/shared-platform`.
[مصفوفة التوافق المركزية](https://github.com/ahmed73ali737-boop/G-Factory/blob/feature/unified-iam-granular-access-v1/shared-platform/registry/iam-consumer-compatibility.v1.json).

**SystemKey:** `pulsex` — القواعد تُعرّف باسم النظام ولا تنتقل إلى التطبيقات الأخرى لمجرد تطابق اسم الحقل أو الإجراء.

## السلوك الذي يجب الحفاظ عليه
Organizer/event management requires scoped IAM and event-owner checks. Anonymous guest browsing, voting and registration remain governed by Event Policy, guest QR HMAC and anti-duplication; no mandatory KYC account.

المصادقة وسياق المستأجر: scoped organizer identity only for protected operations; anonymous participation uses event guest identifier, never raw phone in URL.

الموارد المحلية: `event`، `participation`، `experience`، `kiosk`، `vote`.
الأوامر المرجعية: `event.configure`، `guest.vote`، `offline.gate.sync`.

## منع ازدواجية وحدود الملكية
Do NOT create a new global User/Party master from guest QR; do NOT treat IndexedDB offline manifest as a permanent IAM authority.

تظل U-SEAS IAM هوية الأشخاص والجلسات، وU-SEAS PartyCustomer هوية الأطراف وKYC، وG.Content مالك المستندات، وG.Authorization قرار الصلاحيات المشترك، وG.Workflow/G-015 إجراءات الاعتماد. التطبيق يحتفظ فقط بحقوق مجاله ومراجع المصادر وبياناته التشغيلية الخاصة.

## قاعدة التكامل
`Access Allowed = EnterpriseIAMValidated AND CurrentProductDomainRulesPass`

الاستثناءات المسموحة للوصول العام تقتصر على سيناريوهات ضيف معلن عنها بسياسة المنتج، ولا تنقل أي صلاحية إدارية. يُعاد التحقق عند التنفيذ؛ لا يُعتمد إخفاء زر أو شاشة أو حالة طرفية كصلاحية.

## أقرب شريحة دمج لاحقة
Bind organizer/admin permission checks via OIDC/IAM, preserve guest UX and QR; perform actual device pairing/attestation and expiry at sync authorization boundary.

تُحسم الموافقات البشرية للأمن والتصميم قبل تنشيط الصلاحيات الجديدة، ويكون الإدماج بخيار تشغيل وCanary ثم Rollback حتى لا تتغير سلوكيات المنتج القائم دون اختبار.

## متطلبات القبول 360
Actor → Tenant/Party/Scope → Channel/Terminal → Screen/Section/Field → API → Domain Check → Policy Decision → Workflow (if required) → DB/RLS → Audit → Negative Tests → SIT → UAT → Evidence.

الحالات المركزية المطلوب اختبارها: PX-001، PX-002، PX-003.

**غير مثبت:** استهلاك حزمة NuGet، تشغيل موفر OIDC، ربط قاعدة البيانات، اختبارات موحدّة على المنتج أو قبول إنتاجي.
