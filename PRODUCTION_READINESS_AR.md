# PulseX Windows 12 — Production Readiness

## Release Gate
`tools/production_gate.py` يتطلب:
- PostgreSQL URL.
- HTTPS PUBLIC_ORIGIN.
- SEED_DEMO=false.
- WEB_WORKERS >= 2.
- DB password غير placeholder.
- `GUEST_ID_SECRET` مستقلًا 32+ وغير placeholder.
- `BOOTSTRAP_ADMIN_EMAIL` حقيقيًا.
- evidence flags: native PostgreSQL / load / security / field offline.

الأعلام acknowledgements بعد التوقيع؛ ليست اختبارات بحد ذاتها.

## Startup sequence داخل Production image
1. Production configuration gate.
2. Checksum-tracked PostgreSQL migrations.
3. One-time Platform/Admin bootstrap إذا كانت القاعدة فارغة.
4. Application multi-worker start.

القاعدة الجزئية لا يعاد تهيئتها تلقائيًا؛ bootstrap يفشل ويتطلب مراجعة.

## Automated gates
- full pytest Linux/Windows.
- real browser Linux/Windows.
- Guest QR/offline focused gate.
- IndexedDB.
- native PostgreSQL + additive migrations + concurrent same-phone dedupe.
- 1000 guest capacity smoke.
- security bounded smoke.
- Python/JS SDK.
- API contract/OpenAPI.
- production Docker build/import/migration assets.

## Guest privacy
- HMAC-keyed server identity.
- final public QR does not contain phone.
- isolated offline ID random provisional P only.
- gate manifest excludes phone.
- completed guest/check-in outboxes are deleted after receipts.
- raw phone removed from reconciled local guest record.

## Still external before Production sign-off
- physical camera/scanner UAT.
- physical two/multi-device outage.
- venue LAN/local edge deployment.
- real HTTPS/domain.
- 5-day soak.
- independent DAST/Pentest.
- production backup restore/PITR/retention.
- business/field UAT signatures.

راجع `GUEST_QR_360_COMPLETION_AR.md`.
