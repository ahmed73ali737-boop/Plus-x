# Guest QR / Offline / Brand Sites — 360° Completion Matrix

> الهدف: ربط كل متطلب بدليل تنفيذه واختباره. لا يعني وجود الكود وحده "Production Ready".

| المجال | المتطلب | التنفيذ / UI | API / DB | الدليل الآلي | الحالة |
|---|---|---|---|---|---|
| Guest Identity | هاتف واحد = زائر واحد | تسجيل/استرجاع من موقع الزائر ولوحة المنظم | `px_guests.phone_e164 UNIQUE` + HMAC phone hash | same-phone variants + PostgreSQL concurrent registration | Automated Gate |
| Privacy | QR لا يحتوي الهاتف ولا يشتق منه مباشرة | Guest Pass يعرض رقمًا عامًا فقط | HMAC keyed guest number عبر `GUEST_ID_SECRET` | keyed-ID tests + public lookup privacy | Automated Gate |
| Offline Registration | التسجيل أثناء الانقطاع | معرف محلي عشوائي `P-...` بلا QR نهائي، ثم reconcile تلقائي | `guest_outbox` → batch sync | real Chromium offline-register → reconnect → G/QR | Automated Gate |
| QR | QR لكل زائر | بطاقة كبيرة قابلة للمسح | PNG endpoint، EC level Q، quiet zone | QR PNG/API + browser image load | Automated Gate |
| Scanner | مسح QR/رقم يدوي | كاميرا BarcodeDetector + fallback يدوي | device-scoped manifest/check-ins | Chromium parser + device scope | Automated Gate; physical camera external |
| Gate Offline | دخول أثناء الانقطاع | manifest محلي + pending status + retry | IndexedDB checkin outbox/receipts | offline check-in → reconnect sync | Automated Gate |
| Idempotency | لا تكرار check-in | duplicate receipt واضح | `scan_id PK` | replay tests | Automated Gate |
| Device Privacy | البوابة لا تحمل أرقام الهواتف | scanner يعرض الاسم/الجهة/رقم الزائر فقط | manifest strips phone | manifest privacy test | Automated Gate |
| Queue Hygiene | لا تراكم البيانات المكتملة | pending فقط؛ backup يشمل جميع queues | receipt + delete accepted | browser asserts empty completed outboxes | Automated Gate |
| Organizer | دليل زوار + QR + سجل دخول | تبويب «الزوار و QR» | organizer/platform scope | role/API/browser tests | Automated Gate |
| Export | مصالحة ما بعد الفعالية | زر CSV | scoped CSV + formula-injection guard | export safety test | Automated Gate |
| Agency Isolation | الجهة لا ترى دليل الحدث | لا تبويب event guest لها | scope rejects guests/checkins/export/manifest | 403 tests | Automated Gate |
| Consent | موافقة صريحة للهاتف | checkbox إلزامي | validation | no-consent rejection | Automated Gate |
| Phone UX | صيغ يمنية + أرقام عربية/فارسية | tel LTR داخل RTL | normalized E.164-like | Arabic/Persian digit tests | Automated Gate |
| Capacity | 1000 زائر | — | 1000 registration + manifest + check-ins | `guest_capacity_smoke.py` | Automated Gate |
| PostgreSQL | native DB | — | additive migrations + unique/FK + concurrency | native PostgreSQL CI | Automated Gate |
| Migration | ترقية install سابق | — | checksum-tracked 002/003/004 | migration + rerun idempotency | Automated Gate |
| Bootstrap | أول مدير في Production | ملف credential مرة واحدة | Platform + first admin only on empty DB | bootstrap tests | Automated Gate |
| Password Safety | تغيير المؤقت إلزامي | force-password screen | `must_change_password` | bootstrap/login tests | Automated Gate |
| Security | headers/CSRF/origin/rate/size/path | — | middleware | security smoke | Automated Gate; pentest external |
| SDK | Python/JS integration | — | guest/admin/device methods | JS unit + Python real HTTP smoke | Automated Gate |
| API Contract | منع drift | — | OpenAPI + versioned route snapshot | contract tests/generator | Automated Gate |
| Container | image قابلة للتشغيل | — | runtime + migration assets packaged | Docker build/import gate | Automated Gate |
| Tharawat | موقع حي مخصص | premium live perspective/ticker | shared content engine | browser distinct-module test | Automated Gate |
| Easy | موقع حي مخصص | one-tap service live rail | shared content engine | browser distinct-module test | Automated Gate |
| RTS | موقع حي مخصص | system/data live metrics | shared content engine | browser distinct-module test | Automated Gate |
| Brand Shell | العلامة هي الأساس لا PulseX | brand header/footer + PulseX attribution | — | browser assertion | Automated Gate |
| Responsive UX | الهاتف بلا overflow | mobile guest + brand views | — | Chromium 390×844 | Automated Gate |
| Accessibility | focus/reduced motion/semantic fields | CSS/semantic inputs | — | contract/browser checks | Automated + field review recommended |
| Physical Camera | كاميرا هاتف/تاب فعلي | camera UI exists | — | لا يمكن إثبات hardware في hosted CI | EXTERNAL UAT |
| Two-device hard outage | بوابتان بلا إنترنت | local manifest/outbox exists | LAN/local server recommended | لا يحاكي CI قطعًا ماديًا لجهازين | EXTERNAL UAT |
| Venue LAN Edge | منع duplicate فورًا أثناء Internet outage | same UI | shared local PulseX/PostgreSQL | architecture supported, deployment-specific | EXTERNAL DEPLOYMENT |
| 5-day soak | استمرار طوال المعرض | storage persist requested | queue/retry exists | يحتاج أجهزة فعلية 5 أيام | EXTERNAL UAT |
| Real TLS/domain | QR من هواتف خارجية | PUBLIC_ORIGIN | Caddy HTTPS template | يحتاج domain/host حقيقي | EXTERNAL DEPLOYMENT |
| DAST/Pentest | فحص مستقل | — | — | bounded security smoke فقط | EXTERNAL SECURITY SIGN-OFF |
| Backup restore/PITR | استعادة Production | docs/basic dump | PostgreSQL | restore policy/provider-specific | EXTERNAL OPS SIGN-OFF |

## قاعدة الإغلاق

لا يدمج هذا الإصدار إلى `main` إلا بعد نجاح آخر commit في:
1. Focused Guest QR gate.
2. Linux core.
3. Windows core.
4. Real Chromium browser flow.
5. Native PostgreSQL.
6. Production container build/import.
7. SDK/API contract.

أما البنود الموسومة **EXTERNAL** فلا تتحول إلى PASS من CI؛ تحتاج محضر UAT/Deployment/Security فعلي.
