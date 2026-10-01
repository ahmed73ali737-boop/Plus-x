# PulseX Windows 07 — API & SDK

- OpenAPI: `ops/openapi.generated.json`
- Contract snapshot: `ops/api-contract-v1.json`
- Version: `0.7.0`
- Paths: 38
- Operations: 44
- Header: `X-PulseX-API-Version: 1`

## SDKs

### Python
`/sdk/python/pulsex_sdk`

يدعم health/login/me/logout/publicSite/collect/admin sites/save/publish/metrics/organizations إضافة إلى:
- `devices(site_id)`
- `create_device(site_id, name, device_type, app_version='')`
- `update_device(site_id, device_id, **changes)`
- `review_access_request(site_id, request_id, status)`

### JavaScript
`/sdk/javascript/index.mjs`

يحتوي المقابلات نفسها: `devices`, `createDevice`, `updateDevice`, `reviewAccessRequest`.

API contract snapshot داخل الاختبارات يمنع حذف endpoint حرج دون تحديث مقصود للعقد.
