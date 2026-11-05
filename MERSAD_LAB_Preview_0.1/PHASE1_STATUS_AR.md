# حالة المرحلة الأولى والثالثة — MERSAD LAB 1.0 (PREVIEW 0.1)

| البند | الحالة | التفاصيل |
|---|---|---|
| محرك المحاكاة (`sim_engine.py`) | **PASS (مكتمل)** | يدعم 8 أوضاع كاميرا (`normal`, `lowlight`, `lowres`, `noise`, `occluded`, `frozen`, `delay`, `offline`) ولوحات يمنية اصطناعية |
| خادم المختبر (`lab_server.py`) | **PASS (مكتمل)** | ربط محلي `127.0.0.1`، حماية `Host/Origin/CSRF`، حدود حجم ومهلة وتزامن، إغلاق نظيف |
| واجهة المستخدم (`index.html`) | **PASS (مكتمل)** | واجهة عربية RTL خالية تماماً من `innerHTML` |
| الاختبارات الأساسية الثمانية (`LAB-01..08`) | **8 / 8 PASS** | JPEG, MJPEG, Health, Invalid Mode 400, Offline 503, OpenCV Capture, Image Upload, Video Upload |
| اختبارات الأمان والضغط الجديدة (`LAB-SEC-01..12`) | **12 / 12 PASS** | Auth 401, Host/Origin 403, CSRF 403, XSS/CSP, Zero innerHTML, Size 413, Corrupt Video 422, RAM/CPU Bounds, Concurrency 429, Timeout 504, Lifecycle & Port Release |
| ملفات بناء Windows EXE والمثبت | **PASS (مكتمل)** | `mersad_lab.spec`, `BUILD_LAB_EXE.bat`, `installer/mersad_lab_setup.iss`, GitHub Actions CI |
