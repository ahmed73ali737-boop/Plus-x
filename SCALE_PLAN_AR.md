# PulseX Windows 07 — Scale Plan

- Pilot: ~1,000 audience, target acceptance 250 concurrent.
- Event+: ~5,000 total, target 500 concurrent.
- Large: ~10,000 total, target 1,000 concurrent.
- Stretch: ~25,000 total, target 2,000 concurrent.

المثبت محليًا: 1,000 reads + 10,000 synthetic submissions على SQLite/single Uvicorn process/localhost دون write errors. هذا ليس شهادة concurrent users.

الاعتماد الحقيقي ينتقل إلى PostgreSQL + multi-worker + HTTPS + remote load generator، بالتدرج 250 → 500 → 1,000 → 2,000، ثم spike/soak/recovery.
