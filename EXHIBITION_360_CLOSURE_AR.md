# PulseX — Exhibition 360 Closure Matrix

> هذه الوثيقة هي حدّ الحقيقة التنفيذي لمسار المعرض. لا يعني وجود الخاصية في الكود أنها Production Ready؛ الإغلاق يتطلب الدليل المذكور أمامها على نفس revision المرشح.

## 1. خط الأساس

- المنتج: PulseX — Live Experience & Insights Platform.
- نطاق المعرض: موقع الفعالية + مواقع الجهات + Guest QR + Gate/Scanner + Organizer/Admin + Kiosk/Mobile/QR + Offline/Sync + Analytics/Reports.
- مواقع العرض المميزة: ثروات، Easy، RTS.
- المبدأ: محرك بيانات وتفاعل مشترك، Presentation/Experience Layer مستقلة لكل علامة؛ لا إعادة بناء للـbackend لكل موقع.

## 2. طبقات الإغلاق 360°

| الطبقة | المطلوب | دليل الإغلاق الآلي | الحالة قبل الدليل النهائي |
|---|---|---|---|
| Experience Architecture | فصل تجربة المعرض عن الـpublic template العام | `web/exhibition.mjs` + brand CSS + browser journey | Implemented |
| RTS Website | Command Center/System Map/Capability Rail/brand visitor navigation/CTAs | `.expo-rts-*` + `browser_exhibition_sites.py` | Implemented, CI pending |
| Easy Website | Living Wallet/One-tap journey/services/brand visitor navigation/CTAs | `.expo-easy-*` + browser journey | Implemented, CI pending |
| Tharawat Website | Financial Perspective/Insight Horizon/Discovery Salon/brand visitor navigation | `.expo-tharawat-*` + browser journey | Implemented, CI pending |
| Responsive | Desktop + 390px mobile بدون horizontal overflow | Playwright screenshots/assertions | CI pending |
| Accessibility baseline | Semantic headings, keyboard-safe links/buttons, reduced motion | existing browser/components + reduced-motion CSS | Partially automated |
| Public Content | About/services/facts/media/offers/contact | public routes and browser smoke | Implemented |
| Surveys | semantic field types + branching + required validation + persistence | pytest/browser smoke | Verified on prior head; re-run required |
| Polls | submit + live results + offline boundary | browser/API tests | Verified on prior head; re-run required |
| Ratings/Notes | multi-criteria + notes + persistence | public/admin flows | Implemented |
| Leads/Contact | consent-separated follow-up | public API/UI | Implemented |
| Guest Identity | phone-normalized canonical guest + opaque guest number | guest regression | Verified on prior head; re-run required |
| Guest QR | QR resolves guest; phone excluded from QR URL | guest browser/API | Verified on prior head; re-run required |
| Scanner | manual/QR payload lookup + entry/exit/validate | guest browser journey | Verified on prior head; physical camera open |
| Anti-passback | duplicate entry prevention + valid exit/re-entry policy | guest browser journey | Verified on prior head; field verification open |
| Offline guest | provisional local guest → server reconciliation | guest browser journey | Verified on prior head; two-device field open |
| Offline check-in | local manifest/outbox → reconnect sync | IndexedDB/guest journey | Verified on prior head; multi-device outage open |
| First render resilience | IndexedDB cache must not block network render | stalled IndexedDB regression | Implemented, CI pending |
| Service Worker/PWA | shell + brand assets cached | `sw.js` v19 + offline component | Implemented, CI pending |
| Admin | scoped login/dashboard/content/questions/import/publish/results | browser smoke | Verified on prior head; re-run required |
| Organizer | guest directory/access policy/devices | guest browser | Verified on prior head; re-run required |
| Import | Excel/CSV preview + commit | browser/API tests | Verified on prior head; re-run required |
| API/SDK | HTTP API + JS/Python SDK smoke | CI SDK gates | Verified on prior head; re-run required |
| Security | auth/session/CSRF/scope/security headers | security smoke/native acceptance | Verified on prior head; RLS/pentest open |
| PostgreSQL | native application-path acceptance | PostgreSQL 18 CI gate | Verified on prior head; re-run required |
| Container | production image builds/imports/migrations assets | container-import gate | Verified on prior head; re-run required |
| Capacity — interaction | 1000 reads + 1000 submissions synthetic local smoke | `capacity_smoke.py` | Added to CI; not production certificate |
| Capacity — PostgreSQL | 1000 reads + 1000 submissions through FastAPI/SQLAlchemy/PostgreSQL | `postgres_capacity_smoke.py` | Added to CI; not production certificate |
| Capacity — exhibition topology | 70 participating entities + 700 repeated agency bundle reads | `exhibition_scale_smoke.py` | Added to CI; not production certificate |
| Capacity — guests | 1000 guest registrations smoke | `guest_capacity_smoke.py` | Verified on prior head; re-run required |
| Observability | health/live/ready + QA artifacts/logs | native/CI artifacts | Implemented |
| Deployment | real target environment + persistent PostgreSQL + secrets | deployment evidence | OPEN |
| Field/UAT | physical QR camera/kiosk/venue LAN/business users | signed field UAT | OPEN |
| Security external | DAST/pentest | external evidence | OPEN |
| Soak | 5-day offline/restore | field soak evidence | OPEN |

## 3. مواقع العلامات — حدود عدم القالب

### RTS
- هندسة بصرية داكنة/تقنية مستقلة.
- System Map ديناميكي، telemetry، capability nodes وrail.
- محتوى المعرض: Digital Transformation، FinTech & Payment Platforms، Payment & Collection، Integration & Platforms، Business Systems، Data/Automation/Insights، Accounting & Sales، Lending/Requests/Billing، Humanitarian & Donations، Exchange & Financial Products.
- CTA مباشر للاستكشاف والتصويت وGuest Pass، مع E2E للتصويت والنتيجة.

### Easy
- تجربة محفظة حية بدل Hero تقليدي.
- Phone surface وquick actions وone-tap journey.
- الخصوصية والرقم البديل، الحصالة والكسر المباشر، بطاقات Wi‑Fi، حسابات الأطفال، الدفع والتحويل، التقارير والسجل.
- CTA للتجربة والتصويت وGuest Pass، مع E2E للاستبيان والحفظ.

### ثروات
- Financial Perspective/Editorial language مستقلة عن Easy وRTS.
- Insight Horizon + Discovery Salon + live insights.
- منظومة رقمية، حلول مالية للأفراد والأعمال، ابتكار مالي، شراكات وتكاملات، بيانات ورؤى قابلة للتنفيذ.
- CTA للاستكشاف والتصويت وGuest Pass، مع E2E لطلب التواصل والموافقة.

## 4. القدرة — تفسير صحيح

الـsmoke الحالي يثبت أن التطبيق يستطيع تنفيذ حمل اصطناعي محلي bounded بدون أخطاء ضمن السيناريو المحدد. لا يثبت 1000 مستخدم بشري متزامن ولا يمثل شهادة إنتاج. الإغلاق الإنتاجي يتطلب PostgreSQL في بيئة مماثلة للإنتاج، عدد workers/replicas معلوم، قياسات p50/p95/p99، CPU/RAM، saturation، اختبار recovery، وهدف SLO واضح.

## 5. شروط Production Ready

لا تُرفع الحالة إلى Production Ready قبل نجاح جميع بوابات نفس revision، ثم إغلاق: PostgreSQL/RLS tenant isolation، multi-device venue outage/recovery، physical camera/kiosk، 5-day soak، load على بيئة مماثلة للإنتاج، DAST/pentest، field/business UAT، ونشر فعلي مع مراقبة واسترجاع.
