# PulseX Windows 07 — Architecture

## التقسيم الحالي

```text
app/
├── domain.py                    # قواعد البيانات والمحتوى والإجابات
├── application/
│   ├── access.py                # scope/membership/participation policy
│   ├── access_request_service.py
│   ├── audit_service.py
│   ├── auth_service.py
│   ├── collection_service.py
│   ├── device_service.py
│   ├── public_service.py
│   └── publishing.py
├── infrastructure/
│   ├── repository.py
│   └── seed.py
├── api/
│   └── middleware.py
├── core/
│   ├── security.py
│   └── serialization.py
├── db.py
├── imports.py
├── xlsx_reader.py
└── server.py                    # HTTP composition and routes
```

هذه الجولة فصلت Public rendering، Device lifecycle وAccess-request workflow من `server.py`. ما يزال بعض Application Services يستخدم SQLAlchemy Connection/Tables مباشرة؛ لذلك المشروع **ليس Strict Clean Architecture/DDD كاملًا**. تحويله إلى Ports/Adapters + Repository interfaces + Unit of Work كامل سيكون إعادة هيكلة أوسع وليس شرطًا للتجربة القريبة ما دامت حدود الفصل والاختبارات واضحة.

## الضوابط

- Domain validation لا يثق بواجهة المستخدم.
- Draft/version snapshot قبل النشر.
- Application scope isolation عبر memberships/assignments/participations.
- Device token يخزن hash فقط في الخادم ويظهر raw token مرة واحدة عند الإنشاء.
- Offline submissions تعتمد UUID/idempotency receipts.
- Production Gate يمنع التشغيل باعتباره Production قبل قبول PostgreSQL والحمل والأمن وOffline الميداني.
