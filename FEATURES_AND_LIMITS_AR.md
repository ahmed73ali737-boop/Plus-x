# PulseX Windows 12 — الموجود والحدود

| المجال | الحالة |
|---|---|
| الأسئلة والاستبيانات والتصويت والتقييم | Automated regression coverage |
| Date/Time/DateTime semantic inputs | Automated/UI coverage |
| Admin/Organizations/Participants/Roles | Automated scope coverage |
| Guest phone identity + unique QR | Automated + PostgreSQL uniqueness/concurrency |
| Offline guest registration | Real Chromium IndexedDB/reconnect gate |
| Offline entrance scanner | Real Chromium queue/reconnect gate |
| Guest privacy | Public no-phone; scanner manifest no-phone; organizer scoped |
| Arabic/Persian phone digits | Automated normalization |
| Guest export | Scoped CSV + spreadsheet injection protection |
| 1000 guest capacity smoke | Automated; not production load certificate |
| Native PostgreSQL | Automated CI PASS is required per commit |
| PostgreSQL RLS | Not claimed; isolation is application-level |
| Additive migrations | checksum-tracked migration runner + PostgreSQL gate |
| Production bootstrap | one-time first Platform Admin + forced password change |
| Docker runtime | image build/import/migration-assets CI |
| Python/JS SDK | guest/admin/device operations gated |
| Tharawat / Easy / RTS | structurally distinct live experiences + brand-primary shell |
| Browser E2E | Linux + Windows hosted Chromium gates |
| Physical camera | EXTERNAL UAT |
| Physical two-device outage | EXTERNAL UAT |
| 5-day offline soak | EXTERNAL UAT |
| Real HTTPS/domain | EXTERNAL deployment |
| DAST/Pentest | EXTERNAL security sign-off |
| PITR/production restore policy | EXTERNAL operations sign-off |

راجع `GUEST_QR_360_COMPLETION_AR.md` للمصفوفة التفصيلية.
