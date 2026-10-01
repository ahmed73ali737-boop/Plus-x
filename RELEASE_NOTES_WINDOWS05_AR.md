# PulseX Windows 05 — Hardening & Refactoring Release

- فصل Security helpers وRequest middleware وAuth policy.
- فصل Scope/Access policy وAudit وPublishing/versioning.
- فصل Collection validation وAnalytics metrics من HTTP routes.
- فصل demo seeding عن application startup logic.
- خفض حجم route composition `server.py` مقارنة بـWindows 04.
- إضافة `/api/health/live` و`/api/health/ready`.
- إضافة `X-PulseX-API-Version: 1` وHSTS عند HTTPS.
- OpenAPI 0.5.0 regenerated.
- إضافة Python SDK وJavaScript SDK مع اختبارات.
- إضافة security hardening workload وcapacity smoke.
- تحديث/إصلاح UI component harness القديم.
- 119 pytest tests، و~90% app line coverage في آخر قياس.

هذه النسخة Hardening Candidate، وليست Production Sign-off؛ راجع قائمة BLOCKED في `PRODUCTION_READINESS_AR.md`.
