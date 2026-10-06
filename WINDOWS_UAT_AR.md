# Windows 12 — قبول Windows والجهاز الفعلي

## ما يغطيه GitHub-hosted Windows
- Python full regression.
- Chromium component suite بقراءة UTF-8 صريحة.
- real HTTP browser E2E.
- Guest QR/offline browser journey.
- IndexedDB offline component.
- JS syntax/SDK ضمن المصفوفة ذات الصلة.

هذه أدلة Windows OS حقيقية على runner، لكنها ليست نفس جهاز المعرض.

## UAT على جهاز المعرض
| السيناريو | المطلوب |
|---|---|
| Start/paths with spaces | تشغيل بلا Admin وبلا قتل عمليات أخرى |
| Organizer/Agency scope | كل حساب يرى نطاقه فقط |
| Guest QR physical camera | QR من هاتف فعلي يقرأ بالتاب/USB scanner |
| Pair gate | manifest مجهز قبل فصل الشبكة |
| Offline gate | check-in يظل pending ثم sync بلا duplication |
| Same phone | LAN/shared server يعيد نفس G-number |
| Isolated new guest | يظهر P provisional فقط ثم يتصالح إلى G عند reconnect |
| Arabic phone digits | ٠١٢٣... و۰۱۲۳... تعمل |
| Restart | DB/manifest/outbox لا تضيع |
| Backup/restore | استعادة إلى بيئة منفصلة ومطابقة العدادات |
| 2 gates | تشغيل متزامن + reconciliation |
| 5 days | soak وتوثيق storage/browser updates |

لا يطلق للجمهور إذا فشل أي سيناريو حرج أو ظهرت بيانات هاتف على scanner/public page.
