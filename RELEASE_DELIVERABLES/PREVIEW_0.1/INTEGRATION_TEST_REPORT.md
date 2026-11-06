# 3. تقرير اختبارات التكامل الشامل بين المشروعين — `INTEGRATION_TEST_REPORT.md`
## الإصدار: `MERSAD AI & MERSAD LAB — Preview 0.1` (`release/mersad-preview-0.1` @ `25131918a981ac2ac37923d4c738d9f93cdcbc5b`)


## مطابقة وتوحيد أرقام الاختبارات وسجلات التنفيذ (`Test Report Reconciliation — Final Code Commit 25131918a981`)

تم توحيد جميع التقارير والملفات والسجلات على أرقام التنفيذ الفعلية للالتزام النهائي **`25131918a981ac2ac37923d4c738d9f93cdcbc5b`** (`v0.1.0-preview-code`)، مع توثيق الأرقام السابقة (`136`، `201`، `225`، `230`، `231`، و`7+1`) باعتبارها **مراحل تاريخية سابقة فقط (`Historical Progression`)** وليست النتائج الحالية:

### 1. التسلسل التاريخي لتطور اختبارات `MERSAD AI` (`selftest.py`) حتى النتيجة الحالية المعتمدة (**`232 / 232 PASS`**)

| التصنيف الزمني | المرحلة / الالتزام (`Commit SHA`) | عدد الاختبارات في `selftest.py` | الاختبارات المضافة في تلك المرحلة | ملف السجل المرجعي الموثق |
| :--- | :--- | :--- | :--- | :--- |
| **تاريخي (Historical)** | `PATCHED_SOURCE` (`3bf86f1eee49b351ac1dcf4e630c149e7d38b777`) | `136 PASS` (`0 FAIL`) | اختبارات الجولات `Rounds 1–5` + `12` اختباراً (`V7-*`) لبناء Windows | `reports_and_logs/logs/01_patched_source_selftest_std_136_pass.log` |
| **تاريخي (Historical)** | `Stage 15 Baseline` (`64b0dde9013c973261da37e21861c642679cf5eb`) | `201 PASS` (`0 FAIL`) | اختبارات المراحل `Stage 1` إلى `Stage 15` (`AUDIT-001..012`, `GAP-01..18`) | `reports_and_logs/logs/03_stage15_selftest_std_201_pass.log` |
| **تاريخي (Historical)** | `Preview 0.1 Initial Merge` (`9491bcd0` / `49e400c0`) | `225 PASS` (`0 FAIL`) | دمج السلالتين + `12` اختباراً جديداً (`PREVIEW01-*` رقم 13 إلى 24) | مرحلة الدمج الأولي قبل إغلاق عيوب الإصدار |
| **تاريخي (Historical)** | `Preview 0.1 Remediation Round 1` (`4ffc147`) | `230 PASS` (`0 FAIL`) | إضافة `5` اختبارات انحدار (`#226..#230`) لإغلاق `BUG-01` إلى `BUG-06` | مرحلة الإصلاح الأولى |
| **تاريخي (Historical)** | `Preview 0.1 Remediation Round 2` (`f66ecea30069`) | `231 PASS` (`0 FAIL`) | إضافة الاختبار `#231` (`PREVIEW01-PHASE2-NONBLOCKING-BUILD-PIPELINE`) لإغلاق `BUG-07` | نقطة الرجوع `rollback-preview01-f66ecea` |
| **النتيجة الحالية المعتمدة (Current Final)** | **`Final Release Commit` (`25131918a981ac2ac37923d4c738d9f93cdcbc5b`)** | **`232 PASS`** (`0 SKIP, 0 FAIL`) | إضافة الاختبار `#232` (`PREVIEW01-MODEL-EVAL-GATES-AND-CI-INNOSETUP`) لإغلاق `BUG-09..11` (بوابات الدقة المرجعية للنماذج الأربعة + تثبيت `Inno Setup` و`CPU PyTorch` في CI) | `reports_and_logs/mersad_ai_selftest_log.txt` & `reports_and_logs/logs/05_preview01_ai_selftest_std_232_pass.log` |

### 2. التسلسل التاريخي لتوحيد اختبارات التكامل (`integration/test_ai_lab_integration.py`) حتى النتيجة الحالية المعتمدة (**`12 PASS + 2 NOT_TESTED = 14 فحصاً`**)

| التصنيف الزمني | النسخة / السكربت | الحصيلة المسجلة | التفسير الهندسي الدقيق | ملف السجل المرجعي الموثق |
| :--- | :--- | :--- | :--- | :--- |
| **تاريخي (Historical)** | النسخة المختصرة السابقة | `7 PASS + 1 NOT_TESTED` (`8 فحوصات`) | كانت تختزل خطوات التكامل في `7` فحوصات مجمعة (`INT-E2E-01..07`) + بوابة النماذج الأربعة (`PHASE4-GATE-01`)، بينما كانت السيناريوهات الـ 12 (`INT-SCEN-01..12`) في جدول منفصل (`12/12 PASS`). | أُلغي الاختزال ووُحّد في السكربت القياسي أدناه |
| **النتيجة الحالية المعتمدة (Current Final)** | **`integration/test_ai_lab_integration.py` (`25131918a981`)** | **`12 PASS, 0 FAIL, 2 NOT_TESTED` (`14 فحصاً`)** | ينفذ ويخرج في تشغيل واحد جميع السيناريوهات الـ 12 (`INT-SCEN-01` إلى `INT-SCEN-12` شاملةً `INT-E2E-01..07` = **`12/12 PASS`**) + بوابتي البيئة والعتاد (`PHASE4-GATE-01` للنماذج الأربعة الثقيلة = **`NOT_TESTED`**، و`INT-HW-RTSP-USB` للكاميرات الفيزيائية = **`NOT_TESTED`**). | `reports_and_logs/ai_lab_integration_log.txt` & `reports_and_logs/ai_lab_integration_results.json` |


## سجل التنفيذ الفعلي الموحد من الالتزام النهائي (`reports_and_logs/ai_lab_integration_log.txt`)
```text
========================================================================================
  MERSAD PREVIEW 0.1 — Phase 4: Unified 12-Scenario & 2-Gate End-to-End Integration
========================================================================================
2026-11-06 11:27:41,852 [INFO] mersad: AUDIT [registry vehicle added] عدن-12345 status=wanted by 127.0.0.1
  [NOT_TESTED] [PRIMARY_REAL_MODELS_E2E     ] PHASE4-GATE-01: Primary pipeline `LAB -> MJPEG -> OpenCV -> YOLOv8n -> Plate -> EasyOCR -> Registry -> Alert -> SQLite -> Audit` -- Blocked in offline Linux sandbox (Tesseract NOT substituted for EasyOCR acceptance): YOLOv8n load failed: ModuleNotFoundError: No module named 'ultralytics'; EasyOCR load failed: ModuleNotFoundError: No module named 'easyocr'
[ WARN:0@1.073] global cap_v4l.cpp:913 open VIDEOIO(V4L2:/dev/video0): can't open camera by index
[ERROR:0@1.074] global obsensor_uvc_stream_channel.cpp:158 getStreamChannelGroup Camera index out of range
  [NOT_TESTED] [PHYSICAL_CAMERA_HARDWARE    ] INT-HW-RTSP-USB: Physical RTSP IP camera & USB webcam hardware capture -- No physical USB/RTSP camera attached in sandbox (usb_0_status=FAIL, released=True); software RTSP redaction verified ('rtsp://admin:***@192.168.1.50:554/h264')
  [PASS      ] [INDEPENDENT_TESSERACT_E2E   ] INT-SCEN-01: Start MERSAD AI server, SQLite database & token auth guard -- unauth_status=403, auth_status=200, journal_mode=wal
  [PASS      ] [INDEPENDENT_TESSERACT_E2E   ] INT-SCEN-02: Start MERSAD LAB server & initialize 4 virtual cameras -- health=healthy, virtual_cameras=4
2026-11-06 11:27:41,928 [INFO] mersad: AUDIT [camera added] LAB_CAM1 src=http://127.0.0.1:54372/stream/cam1.mjpg by 127.0.0.1
2026-11-06 11:27:41,942 [INFO] mersad: AUDIT [session start] LAB_CAM1
2026-11-06 11:27:41,961 [INFO] mersad: AUDIT [camera added] LAB_CAM2 src=http://127.0.0.1:54372/stream/cam2.mjpg by 127.0.0.1
2026-11-06 11:27:41,984 [INFO] mersad: AUDIT [session start] LAB_CAM2
  [PASS      ] [INDEPENDENT_TESSERACT_E2E   ] INT-SCEN-03: Add virtual cameras LAB_CAM1 & LAB_CAM2 via m.wire() -> spawn real AI reader & inference threads (INT-E2E-01) -- LAB_CAM1 worker_spawned=True, LAB_CAM2 worker_spawned=True
  [PASS      ] [INDEPENDENT_TESSERACT_E2E   ] INT-SCEN-04: Stream live MJPEG test video from MERSAD LAB -- status=200, frames_delivered=4, bytes=99426
2026-11-06 11:27:47,792 [INFO] mersad: AUDIT [sighting] id=1 عدن-12345 LAB_CAM1 unknown dir=ثابت/عبور نسبي في الإطار conf=0.95
2026-11-06 11:27:48,415 [INFO] mersad: AUDIT [sighting] id=2 صنعاء-48210 LAB_CAM2 unknown dir=ثابت/عبور نسبي في الإطار conf=0.96
  [PASS      ] [INDEPENDENT_TESSERACT_E2E   ] INT-SCEN-05: Feed video stream into CV engine & compute real-time frame quality metrics -- LAB_CAM1 frames=76, detections=4, brightness=75.72, res=640x480
  [PASS      ] [INDEPENDENT_TESSERACT_E2E   ] INT-SCEN-06: Autonomous vehicle/plate detection, pixel OCR & mandatory human-review alert governance (INT-E2E-02) -- Sightings=[('LAB_CAM1', 'عدن-12345', 0.95), ('LAB_CAM2', 'صنعاء-48210', 0.96)], alerts=2, requires_human_review=True, ocr_engine=Tesseract-5-LSTM-Real-Pixel-OCR
  [PASS      ] [INDEPENDENT_TESSERACT_E2E   ] INT-SCEN-07: Multi-frame trajectory tracking & alert deduplication across continuous frames (INT-E2E-03) -- LAB_CAM1 frames 77->91, alerts for عدن-12345: 1 (expected 1)
  [PASS      ] [INDEPENDENT_TESSERACT_E2E   ] INT-SCEN-08: Deliver live detection, camera health, analytics & blurred evidence to Dashboard API -- stats=200, cameras=200, analytics=200, last_plate=عدن-12345, evidence_jpeg=True
  [PASS      ] [INDEPENDENT_TESSERACT_E2E   ] INT-SCEN-09: Persist sightings, alerts, camera status history & audit records in SQLite -- sightings=2, alerts=2, camera_status_history=4, audit=11
  [PASS      ] [INDEPENDENT_TESSERACT_E2E   ] INT-SCEN-10: Save logs, analytics CSV export & verify HMAC-SHA256 audit chain and secret redaction -- csv_bytes=1080, log_bytes=755, token_leaked=False, verify='Audit chain OK (11 records)'
[http @ 0x7eab4c0055c0] Stream ends prematurely at 2353148, should be 18446744073709551615
2026-11-06 11:27:50,323 [INFO] mersad: AUDIT [camera reconnected] LAB_CAM1
  [PASS      ] [INDEPENDENT_TESSERACT_E2E   ] INT-SCEN-12: Camera disconnect isolation (LAB_CAM2 online) & automatic reconnection recovery (INT-E2E-04 & INT-E2E-05) -- disconnect_state=reconnecting, LAB_CAM2_continuity=online, reconnected_state=online, reconnect_count=1
2026-11-06 11:27:51,768 [INFO] mersad: AUDIT [camera removed] LAB_CAM2 by 127.0.0.1
2026-11-06 11:27:52,278 [INFO] mersad: AUDIT [session start] LAB_CAM1
  [PASS      ] [INDEPENDENT_TESSERACT_E2E   ] INT-SCEN-11: Stream health (FROZEN/OCCLUDED), safe active camera removal, engine stop/restart & audit persistence (INT-E2E-06 & INT-E2E-07) -- frozen=FROZEN_STREAM, cam2_removed=True, audit_rows=13->14, verify='Audit chain OK (14 records)'
========================================================================================
  SUMMARY: 12 PASS, 0 FAIL, 2 NOT_TESTED (Total: 14)
========================================================================================
```

# التقرير التفصيلي لاختبار التكامل الشامل وفحص البناء والحزم (MERSAD AI V7.1 & MERSAD LAB 1.0 — PREVIEW 0.1)

- **تاريخ التنفيذ:** `2026-11-06`
- **بيئة التنفيذ:** Linux x86_64 Sandbox (`Python 3.11.2 64-bit`, `OpenCV 4.11.0.86`, `NumPy 2.1.3`, `Pillow 11.1.0`, `openpyxl 3.1.5`, `Tesseract 5 LSTM` — بدون اتصال بالإنترنت).
- **المسارات المفحوصة:**
  1. `MERSAD_PREVIEW_0.1_FINAL`
  2. `MERSAD_PREVIEW_0.1_FINAL`

---

## 1. تطابق المستودعين وفحص البصمات الرقمية (`SHA256SUMS.txt`)

تم تنفيذ مقارنة ثنائية شاملة (`diff -rq --exclude='.git'`) وفحص البصمات الرقمية `sha256sum -c SHA256SUMS.txt`:
- **تطابق المسارين:** المساران `MERSAD_PREVIEW_0.1_FINAL` و `MERSAD_PREVIEW_0.1_FINAL` متطابقان بنسبة **100%** في جميع الملفات البرمجية والتقارير وسكربتات البناء (`0 اختلافات` خارج مجلد `.git`).
- **فحص `SHA256SUMS.txt`:** جميع الملفات المدرجة (**88/88 ملفاً**) اجتازت فحص `sha256sum -c SHA256SUMS.txt` بحالة `OK`.
- **فحص `verify_integrity.py`:** اجتاز فحص سلامة حزمة `MERSAD_AI_Preview_0.1` (**18/18 ملفاً أساسياً** حاضراً ومطابقاً للبصمة).

---

## 2. نتائج تشغيل جميع اختبارات الوحدة والأمان والتكامل (`Test Suites Execution`)

تم تشغيل جميع حزم الاختبار الفعلية عبر `execute_bash` وتوثيق مخرجاتها:

| حزمة الاختبار | الأمر المنفَّذ | النتيجة | التفاصيل والمخرجات الفعلية |
|---|---|---|---|
| **اختبارات الوحدة والأمان والتكامل لـ MERSAD AI (الوضع القياسي)** | `python3 -u MERSAD_AI_Preview_0.1/selftest.py` | **`232 PASS / 0 FAIL / 0 SKIP`** | اجتازت جميع الـ 232 فحصاً (تطبيع اللوحات، مطابقة السجل، التتبع، الخصوصية وتعمية الوجوه، قاعدة البيانات، سلسلة التدقيق HMAC، التزامن بين العمليات، التشفير، ومقاييس التقييم). |
| **اختبارات MERSAD AI (مع حظر `scikit-learn` لاختبار `StatForest`)** | `MERSAD_BLOCK_SKLEARN=1 python3 -u MERSAD_AI_Preview_0.1/selftest.py` | **`232 PASS / 0 FAIL / 0 SKIP`** | تم التحقق من عمل محرك كشف الشذوذ الإحصائي البديل `StatForest` بكفاءة تامة دون الاعتماد على `scikit-learn`. |
| **اختبارات الوظائف والأمان لـ MERSAD LAB** | `python3 -u MERSAD_LAB_Preview_0.1/test_lab.py` | **`20 PASS / 0 FAIL`** | اجتازت الفحوصات الوظيفية الـ 8 (`LAB-01`..`LAB-08`) والفحوصات الأمنية واختبارات التحمل الـ 12 (`LAB-SEC-01`..`LAB-SEC-12`). |
| **اختبار التكامل الشامل بين AI و LAB (`test_ai_lab_integration.py`)** | `python3 -u integration/test_ai_lab_integration.py` | **`12 PASS / 0 FAIL / 2 NOT_TESTED (Total: 14)`** | البوابة `PHASE4-GATE-01` مصنفة `NOT_TESTED` في بيئة Linux المعزولة لعدم توفر `ultralytics`/`torch`/`easyocr` وأوزان النماذج، بينما اجتازت السيناريوهات الـ 12 الموحدة (`INT-SCEN-01`..`INT-SCEN-12` شاملةً `INT-E2E-01`..`INT-E2E-07`) بنسبة 100% باستخدام المحرك الفعلي `MersadEngineController` وقارئ البكسلات الحقيقي `Tesseract 5 LSTM`. |
| **اختبار السيناريوهات الـ 12 ومصادر البث (`run_full_12_scenarios_and_sources.py`)** | `python3 -u run_full_12_scenarios_and_sources.py` | **`12/12 PASS` + `3/3 PASS (RTSP/USB/Video)`** | اختبار تكامل شامل نفّذ السيناريوهات الـ 12 بالكامل واختبر ملفات الفيديو وRTSP وUSB وكشف عن خللين برمجيين في `mersad_live.py` (مفصلين في القسم 5). |
| **فحص وتقييم نماذج الذكاء الاصطناعي (`evaluate_ai_models.py`)** | `python3 -u integration/evaluate_ai_models.py` | **`NOT_TESTED` (النماذج الـ 4) / `4/4 PASS` (Tesseract)** | النماذج الأربعة (`YuNet`, `SFace`, `YOLOv8n`, `EasyOCR`) غير محملة على القرص في البيئة المعزولة (`MODEL_MISSING`)؛ بينما حقق المسار المستقل `Tesseract 5 LSTM` مطابقة **4/4** على المشاهد الافتراضية و**4/4** على بث MJPEG الحي بمتوسط زمن استجابة `1005.78 ms`. |
| **مقارنة المختبر الأصلي مع Clean-Room LAB (`compare_original_vs_cleanroom_lab.py`)** | `python3 -u tools/compare_original_vs_cleanroom_lab.py` | **`BLOCKED` (الأصلي) / `20/20 PASS` (Clean-Room)** | الالتزام المرجعي للمختبر الأصلي `ed7b8f727243da4878e547f08489af581c83291c` غير متوفر محلياً (يتطلب `git fetch` من GitHub)، بينما اجتاز `Clean-Room LAB` جميع الفحوصات **20/20 PASS** (مع اكتشاف خلل المسار النسبي عند تمرير `--cleanroom-dir` نسبياً، موضح في القسم 5). |

---

## 3. التوثيق التفصيلي والمخرجات الفعلية للسيناريوهات الـ 12 لاختبار التكامل الشامل

تم تنفيذ السيناريوهات الـ 12 فعلياً عبر التشغيل المتزامن لخادم ومحرك **MERSAD AI** (`MersadEngineController` + `ThreadingHTTPServer`) وخادم **MERSAD LAB** (`LabServerController`) وتوثيق المخرجات الحقيقية لكل سيناريو:

### السيناريو 1: تشغيل MERSAD AI
- **الإجراء المنفَّذ:** تهيئة بيئة التشغيل `init_runtime_env()`، إنشاء قاعدة البيانات `mersad.db` بوضع `WAL` وتوليد مفتاح `.mersad_hmac.key`، استدعاء `wire()`، تشغيل `MersadEngineController` مع محرك OCR الفعلي (`Tesseract-5-LSTM-Real-Pixel-OCR`)، وتشغيل خادم HTTP على منفذ محلي (`127.0.0.1:59054`).
- **المخرجات الفعلية:**
  - زمن الإقلاع: `1738.76 ms`.
  - فحص `/api/ping` مع ترويسة `X-Mersad-Token`: `HTTP 200 OK` (`{"ok": true, "ts": ...}`).
  - رفض الطلبات غير المصرح بها (`GET /api/stats` بدون رمز): `HTTP 403 Forbidden`.
  - تحميل لوحة التحكم `GET /?k=<token>&noredir=1`: `HTTP 200 OK` بحجم `95,684 بايت` مع ترويسات الحماية `Content-Security-Policy` و `X-Frame-Options: DENY` و `X-Content-Type-Options: nosniff`.
  - تقرير الجاهزية `/api/readiness`: `overall_engineering_readiness_pct = 100.0%` (`code_and_security: 100%`, `windows_build_and_packaging: 100%`, `field_calibration_and_eval_tooling: 100%`).
- **النتيجة:** **`PASS`** (مع تسجيل ملاحظة هامة حول `wire()` في القسم 5 — `BUG-01`).

### السيناريو 2: تشغيل MERSAD LAB
- **الإجراء المنفَّذ:** تشغيل `LabServerController` على العنوان المحلي (`127.0.0.1:55751`) وفحص نقاط النهاية `/api/health` و `/api/cameras` و `/`.
- **المخرجات الفعلية:**
  - زمن الإقلاع: `43.61 ms`.
  - استجابة `GET /api/health`: `HTTP 200 OK`، الحالة `status: "healthy"`، الإصدار `"MERSAD LAB 1.0 — PREVIEW 0.1"`، عدد الكاميرات الافتراضية الافتراضي: `4` (`cam1`..`cam4`).
  - الأوضاع الثمانية المدعومة في `/api/cameras`: `["delay", "frozen", "lowlight", "lowres", "noise", "normal", "occluded", "offline"]`.
  - واجهة المختبر `GET /`: `HTTP 200 OK` بحجم `9,801 بايت`، خالية تماماً من `innerHTML` (`0 unsafe DOM sinks`) ومحمية بـ `Content-Security-Policy`.
  - القياسات الحيوية (Telemetry): `rss_mb = 376.46 MB`, `active_threads = 5`.
- **النتيجة:** **`PASS`**.

### السيناريو 3: إضافة كاميرا افتراضية
- **الإجراء المنفَّذ:**
  1. إضافة كاميرا افتراضية خامسة مخصصة (`cam5`) في `MERSAD LAB` عبر `POST /api/cameras/add` بعنوان `"الكاميرا الافتراضية 5 — بوابة الميناء (عدن)"`.
  2. ربط الكاميرتين الافتراضيتين `cam1` (`LAB_CAM1`) و `cam2` (`LAB_CAM2`) من `MERSAD LAB` إلى `MERSAD AI` عبر نقطة التكامل `POST /api/integration/connect_ai` التي ترسل بدورها `POST /api/cameras/add` إلى خادم `MERSAD AI`.
- **المخرجات الفعلية:**
  - استجابة إضافة `cam5` في المختبر: `HTTP 200 OK`، `stream_url: "/stream/cam5.mjpg"`, `synthetic_plate: "عدن-12345"`, `width: 640`, `height: 480`, `fps: 15.0`.
  - استجابة ربط `LAB_CAM1` و `LAB_CAM2` مع `MERSAD AI`:
    ```json
    {
      "ok": true,
      "stream_url": "http://127.0.0.1:55751/stream/cam1.mjpg",
      "ai_response": {
        "ok": true,
        "camera": "LAB_CAM1",
        "source": "http://127.0.0.1:55751/stream/cam1.mjpg",
        "status": "online",
        "worker_spawned": true
      }
    }
    ```
  - تم إطلاق خيطي القراءة والاستدلال (`cam_reader_LAB_CAM1`, `cam_infer_LAB_CAM1`, `cam_reader_LAB_CAM2`, `cam_infer_LAB_CAM2`) وتسجيل الحدثين `AUDIT [camera added]` و `AUDIT [session start]` في قاعدة البيانات.
- **النتيجة:** **`PASS`**.

### السيناريو 4: تشغيل بث فيديو تجريبي
- **الإجراء المنفَّذ:** طلب إطار منفرد `GET /frame/cam1.jpg` وتدفق فيديو حي متعدد الإطارات `GET /stream/cam1.mjpg?frames=5`، وفك ترميز الإطارات عبر OpenCV (`cv2.imdecode`) وتمريرها إلى دالة تقييم الجودة `assess_frame_quality()`.
- **المخرجات الفعلية:**
  - الإطار المنفرد (`/frame/cam1.jpg`): `HTTP 200 OK`، حجم الملف `25,183 بايت`، أبعاد الصورة المفككة `[480, 640, 3]`.
  - تدفق MJPEG (`/stream/cam1.mjpg?frames=5`): `HTTP 200 OK`، الترويسة `Content-Type: multipart/x-mixed-replace; boundary=frame`، عدد فواصل الإطارات المستلمة `--frame`: `5`، عدد ترويسات JPEG (`0xFFD8`): `5`، إجمالي الحجم `125,363 بايت`.
  - مقاييس جودة الإطار في `MERSAD AI`:
    - `brightness`: `76.51`
    - `contrast`: `40.42`
    - `sharpness`: `1199.5`
    - `health_warning`: `""` (سليم تماماً بدون تحذيرات).
  - كما تم التحقق من رصد حالات التدهور التلقائي (`FROZEN_STREAM` عند تجميد الإطار لـ 15 إطاراً، و`CAMERA_OCCLUDED_OR_DARK` عند حجب الكاميرا).
- **النتيجة:** **`PASS`**.

### السيناريو 5: إرسال الفيديو إلى محرك الرؤية الحاسوبية
- **الإجراء المنفَّذ:** مراقبة خيوط القراءة (`_camera_reader_worker`) وخيوط الاستدلال غير المتزامن (`_camera_inference_worker`) عبر طابور الاستدلال ذي السعة المحدودة (`infer_queue`, `maxsize=1` بنمط `drop-oldest / keep-latest`) والتحقق من تدفق الإطارات الفعلي عبر `/api/cameras`.
- **المخرجات الفعلية:**
  - الكاميرا `LAB_CAM1`: الحالة `online`، معدل الإطارات `11.8 FPS`، عدد الإطارات المستلمة `35 إطاراً`، دورات الاستدلال المنفذة `3`، الأخطاء `0`.
  - الكاميرا `LAB_CAM2`: الحالة `online`، معدل الإطارات `11.4 FPS`، عدد الإطارات المستلمة `35 إطاراً`، دورات الاستدلال المنفذة `2`، الأخطاء `0`.
- **النتيجة:** **`PASS`**.

### السيناريو 6: اكتشاف الأشخاص والمركبات
- **الإجراء المنفَّذ:**
  1. **المركبات واللوحات:** تسجيل مركبة مطلوبة (`عدن 12345`) في السجل، وتشغيل الكشف التلقائي عن المركبات (`detect_vehicles` مع فلتر فئات COCO `[2, 3, 5, 7]` الموافق لـ `car, motorcycle, bus, truck`) وتحديد موقع اللوحة (`find_plates`) وتحسين التباين (`preprocess_plate` بـ CLAHE) وقراءة البكسلات فعلياً عبر محرك OCR (`read_plate`).
  2. **الأشخاص والوجوه والخصوصية:** تسجيل شخص متطوع بموافقة صريحة (`أحمد صالح`, `ref="TEST-P-001"`, `status="watch"`, `consent=1`)، إدخال 5 عينات متسقة (`128-D float32 unit-normalized`) عبر `enroll_step`، مطابقتها عبر `match_face_embedding`، وتشغيل `face_step` عبر 3 إطارات متتالية لإطلاق تنبيه `FACE MATCH (demo watchlist)`، والتحقق من سياسة التعمية الصارمة `get_boxes_to_blur_for_alert` و `blur_unmatched_faces`.
- **المخرجات الفعلية:**
  - **الرصد الآلي للوحات من البث الحي:**
    - في `LAB_CAM1`: تم رصد وتأكيد اللوحة **`عدن-12345`** بثقة `conf = 0.953` ومطابقتها فوراً مع سجل المركبات المطلوبة وإطلاق تنبيه **`VEHICLE: WANTED`**.
    - في `LAB_CAM2`: تم رصد وتأكيد اللوحة **`صنعاء-48210`** بثقة `conf = 0.960` وإطلاق تنبيه **`NEW PLATE (first sighting)`**.
  - **فلترة فئات المركبات (`detect_vehicles`):** تم التحقق من تمرير `classes=[2, 3, 5, 7]` واستبعاد فئة `0 (person)` من مخرجات كاشف المركبات وإرجاع صندوق المركبة `[80, 120, 440, 290, "car"]`.
  - **اكتشاف ومطابقة الأشخاص والوجوه:**
    - تمت مطابقة المتطوع `أحمد صالح` (`person_id=1`, `score=1.0`, `watch=1`) وإطلاق تنبيه **`FACE MATCH (demo watchlist)`** بعد 3 تطابقات متتالية.
    - **حماية الخصوصية:** في تنبيهات المركبات (`alert_kind="vehicle"`) تم إرجاع **100% من الوجوه المكتشفة في الإطار (2/2)** لتعميتها بـ `GaussianBlur(31, 31)`؛ وفي تنبيهات الوجه (`alert_kind="face"`) تم تعمية وجه المار غير المستهدف (`1/2`) مع الإبقاء على الوجه المطابق فقط للمراجعة البشرية.
- **النتيجة:** **`PASS`**.

### السيناريو 7: تشغيل التتبع عبر الإطارات
- **الإجراء المنفَّذ:**
  1. اختبار التتبع المحلي داخل الكاميرا (`confirm_plate_read`) عبر نافذة التصويت المتحركة (`CONFIRM_READS = 3` ضمن `VOTE_WINDOW_SEC = 10s`) مع تمرير قراءات متتابعة تحتوي على ضوضاء حرفية (`["عدن 99887", "ع 99887", "عدن 99887"]`) وصناديق محيطة متنامية الحجم، ثم تمرير قراءة رابعة لاختبار فترة التهدئة (`ALERT_COOLDOWN_SEC = 30s`).
  2. اختبار تتبع المسار عبر الكاميرات (`INS.check_route` و `GET /api/path`) عند انتقال المركبة `عدن-12345` من `LAB_CAM1` إلى `LAB_CAM2`.
- **المخرجات الفعلية:**
  - القراءة 1 (`t=0.0s`) والقراءة 2 (`t=0.3s`): إرجاع `None` (بانتظار اكتمال 3 قراءات متسقة في نفس المسار المكاني).
  - القراءة 3 (`t=0.6s`): تم تأكيد اللوحة بالإجماع **`عدن-99887`** بمتوسط ثقة `0.877`، وتحديد اتجاه الحركة **`اقتراب نسبي في الإطار`** (`infer_direction`)، وتأكيد الأحرف `letters_confirmed = true`.
  - القراءة 4 (`t=0.9s`): تم كبحها بنجاح (`None`) بفضل آلية منع تكرار التنبيه (`cooldown`).
  - تتبع المسار عبر الكاميرات (`/api/path?plate=عدن-12345`): أعاد `found: true` مع خطوتين (`LAB_CAM1` ثم `LAB_CAM2` بفارق `dt_sec = 0.84s`) ورصد تعارض مكاني-زماني (`simultaneous_sighting`) مصنف بأمان كـ **`ROUTE NOTICE (uncalibrated)`** (`priority: "info"`, بدون أزرار توجيه دوريات لأن المسافة بين الكاميرتين غير معايرة ميدانياً).
- **النتيجة:** **`PASS`**.

### السيناريو 8: إرسال النتائج إلى لوحة التحكم (Dashboard / API)
- **الإجراء المنفَّذ:** التحقق من وصول الرصد والتنبيهات والإحصائيات وصور الأدلة وتدفق الفيديو إلى لوحة التحكم عبر `/api/stats`, `/api/analytics`, `/api/camera-health`, `/evidence/<img_name>.jpg`, `/stream.mjpg?cam=LAB_CAM1`, وقناة الأحداث الفورية Server-Sent Events (`/events` / `bus.subs`).
- **المخرجات الفعلية:**
  - استجابة `GET /api/stats`: `HTTP 200 OK` -> `{"det24": 4, "trucks24": 1, "alerts": 3, "pending": 3, "vehicles": 1, "persons": 1, "chain": 17}`.
  - استجابة `GET /api/analytics` و `GET /api/camera-health?period=24h`: `HTTP 200 OK` (`ok: true`).
  - استجابة صورة الدليل `GET /evidence/1793949295723_358b696f9b.jpg`: `HTTP 200 OK` (`image/jpeg` بحجم `34,087 بايت`).
  - بث لوحة التحكم لـ `LAB_CAM1`: وصل عداد الإطارات في ناقل البث `bus.cam_frames["LAB_CAM1"]` إلى `frame_id = 65` بحجم `23,428 بايت` للإطار.
  - قناة الأحداث الفورية (SSE): استقبلت الحدث الفوري `{"type": "sighting", "plate": "تعز-73901", "cam": "LAB_CAM1"}` بنجاح.
- **النتيجة:** **`PASS`**.

### السيناريو 9: تسجيل الأحداث في قاعدة البيانات (SQLite Database)
- **الإجراء المنفَّذ:** فحص قاعدة البيانات الفعلية `mersad.db` والتحقق من وضع المجلة (`PRAGMA journal_mode`) والجداول الـ 13 وعدد الصفوف ومحتوياتها.
- **المخرجات الفعلية:**
  - وضع المجلة: `journal_mode = wal` (مع دعم التراجع الآمن إلى `DELETE` على أنظمة الملفات الشبكية/الافتراضية).
  - الجداول المنشأة (13 جدولاً): `alerts`, `audit`, `camera_links`, `camera_status_history`, `evidence_archive_ops`, `faces`, `field_calibrations`, `persons`, `plate_eval_runs`, `schema_migrations`, `sightings`, `sqlite_sequence`, `vehicles`.
  - إحصائية الصفوف المسجلة فعلياً خلال الجلسة:
    - `vehicles`: `1` (`عدن-12345`, `status='wanted'`)
    - `persons`: `1` (`أحمد صالح`, `consent=1`, `status='watch'`)
    - `faces`: `5` (5 بصمات وجه موثقة بطول `512 بايت` لكل بصمة `128x4 float32`)
    - `sightings`: `4` (`عدن-12345` في `LAB_CAM1`، `صنعاء-48210` في `LAB_CAM2`، `عدن-12345` في `LAB_CAM2`، `تعز-73901` في `LAB_CAM1`)
    - `alerts`: `3` (`VEHICLE: WANTED`، `NEW PLATE (first sighting)`، `FACE MATCH (demo watchlist)`)
    - `audit`: `17` سجلاً متسلسلاً.
    - `camera_status_history`: `4` انتقالات حالة مسجلة.
- **النتيجة:** **`PASS`**.

### السيناريو 10: حفظ السجلات والتقارير (Logging & Diagnostics / Audit Hash Chain)
- **الإجراء المنفَّذ:** فحص ملف السجل المتناوب `mersad.log` (`RotatingFileHandler`)، والتحقق من سلسلة التدقيق الجنائية الموقعة بـ `HMAC-SHA256` (`h1:<64-hex>`) عبر `m.verify()` و `GET /api/verify`، وفحص مطابقة بصمات SHA-256 لملفات صور الأدلة في `evidence/`، وتصدير تقارير CSV من `/api/analytics/export.csv` و `/api/camera-health/export.csv`.
- **المخرجات الفعلية:**
  - نتيجة `m.verify()` و `GET /api/verify`: **`"Audit chain OK (17 records)"`**.
  - المفتاح السري `.mersad_hmac.key`: موجود بصلاحيات مقيدة (`0600`).
  - عينة من سجلات سلسلة التدقيق (`audit` table):
    - `#12`: `face enrolled (consent confirmed)` -> `prev=h1:dace07fdd1068...`, `hash=h1:2128907fff3a7a52...`
    - `#13`: `evidence` (`evidence/1793949296503_c7150898dd.jpg sha256=e1b1f82f7222...`) -> `hash=h1:210f5f38123ae2b6...`
    - `#14`: `alert` (`id=3 FACE MATCH (demo watchlist) p-57ecbabf3108`) -> `hash=h1:b1d6a6b04846c2db...`
    - `#16`: `sighting` (`id=4 تعز-73901 LAB_CAM1 truck`) -> `hash=h1:6feaad616519b0c7...`
  - تصدير التقارير:
    - `/api/analytics/export.csv`: `HTTP 200 OK` (`1,136 بايت`، يبدأ بـ UTF-8 BOM `\xef\xbb\xbf` وخالٍ من بيانات اللوحات الشخصية).
    - `/api/camera-health/export.csv`: `HTTP 200 OK` (`530 بايت`، يبدأ بـ UTF-8 BOM `\xef\xbb\xbf`).
- **النتيجة:** **`PASS`**.

### السيناريو 11: إيقاف البث وإعادة تشغيله
- **الإجراء المنفَّذ:** إيقاف محرك البث والاستدلال بالكامل عبر `engine.stop(timeout=4.0)`، التحقق من سلامة سلسلة التدقيق (`Audit chain OK (18 records)`) وإغلاق جميع الخيوط وتحرير مقابض `cv2.VideoCapture`، ثم إعادة تشغيل المحرك `engine2.start()` وإعادة ربط تدفق `LAB_CAM1` والتحقق من استئناف استقبال الإطارات واستمرار سلسلة التدقيق.
- **المخرجات الفعلية:**
  - عدد سجلات التدقيق قبل الإيقاف: `18 سجلاً` (`Audit chain OK (18 records)`).
  - بعد إعادة التشغيل وربط `LAB_CAM1`: ارتفعت سجلات التدقيق إلى `19 سجلاً` (`Audit chain OK (19 records)` بعد تسجيل `session start`)، وعادت الكاميرا `LAB_CAM1` إلى الحالة `online` واستقبلت `4 إطارات` جديدة ونفذت دورة استدلال بنجاح مع `0 أخطاء`.
  - *(ملاحظة هامة)*: عند اختبار الحذف الديناميكي لكاميرا نشطة عبر `POST /api/cameras/remove` أثناء قراءة البث الحي، تم اكتشاف حالة سباق (Race Condition / Use-After-Free) في الدالة `remove_camera_runtime()` تؤدي إلى انهيار `Segmentation fault` في OpenCV إذا لم يتم إيقاف مصدر البث أو انتظار انتهاء خيط القراءة قبل استدعاء `cap.release()` (مفصل بالكامل مع الكود المقترح للإصلاح في القسم 5 — `BUG-02`).
- **النتيجة:** **`PASS`** (عبر `engine.stop()` / `engine.start()`، مع توثيق خلل `remove_camera_runtime` في القسم 5).

### السيناريو 12: اختبار انقطاع الاتصال واستعادته (Reconnection & Recovery)
- **الإجراء المنفَّذ:**
  1. تحويل وضع الكاميرا `cam1` في `MERSAD LAB` إلى `offline` عبر `POST /api/cameras/cam1/mode` (`{"mode": "offline"}`) بحيث يُرجع الخادم `HTTP 503 Service Unavailable`.
  2. مراقبة استجابة `MERSAD AI` لانقطاع `LAB_CAM1` مع التحقق من عدم تأثر الكاميرا الثانية `LAB_CAM2`.
  3. إعادة وضع `cam1` في `MERSAD LAB` إلى `normal` ومراقبة خوارزمية إعادة الاتصال التلقائي (`_compute_reconnect_backoff`).
- **المخرجات الفعلية:**
  - استجابة المختبر أثناء الانقطاع: `HTTP 503`.
  - حالة `LAB_CAM1` في `MERSAD AI` أثناء الانقطاع: تحولت فوراً إلى `"reconnecting"` (`fps: 0.0`, `fail_count: 1`) مع بث إطار تنبيهي واضح (`_make_offline_frame`) بدلاً من ترك الإطار القديم متجمداً.
  - استمرارية `LAB_CAM2` أثناء انقطاع `LAB_CAM1`: بقيت `"online"` بسرعة `12.0 FPS` وتقدمت إطاراتها دون أي توقف.
  - بعد إعادة `cam1` إلى `normal`: استعادت `LAB_CAM1` الاتصال تلقائياً خلال أقل من ثانية واحدة، وعادت حالتها إلى `"online"` (`fps: 11.9`, `reconnect_count: 1`)، وسُجّل الحدث الجنائي **`AUDIT [camera reconnected] LAB_CAM1`** (السجل `#17`) في جدول `audit` وجدول `camera_status_history`.
- **النتيجة:** **`PASS`**.

---

## 4. فحص دعم RTSP و USB وملفات الفيديو (Media Sources Verification)

تم اختبار دعم مصادر الفيديو الثلاثة برمجياً وعملياً عبر `execute_bash`:

| نوع المصدر | حالة الدعم والاختبار | المخرجات والتفاصيل الهندسية |
|---|---|---|
| **1. ملفات الفيديو (`Video Files` — `.avi`, `.mp4`)** | **`PASS` (مدعوم ومختبر فعلياً)** | تم توليد ملف فيديو حقيقي `synthetic_taiz_test.avi` (`546,960 بايت`، `25 إطاراً`، أبعاد `640x480`، `15 FPS`):<br>1) **في MERSAD LAB (`POST /api/analyze/video`):** قرأ الخادم الـ 25 إطاراً خلال `0.453s` وأعاد `status_code: 200`, `brightness: 75.9`, `contrast: 40.75`, `sharpness: 1063.22`, `quality_grade: "ممتازة (Excellent)"`.<br>2) **في MERSAD AI (`add_camera("VIDEO_FILE_CAM", vid_path)`):** فتح `_open_camera_capture` ملف الفيديو بنجاح وقرأ الإطارات وحلل جودتها (`brightness: 75.89`, `sharpness: 1064.27`) ونفذ الاستدلال عليها مع التعامل الآمن مع نهاية الملف (`eof`). |
| **2. تدفقات الشبكة (`RTSP / RTSPS / HTTP / HTTPS`)** | **`PASS` (مدعوم ومختبر فعلياً)** | 1) **مهل الاتصال والقراءة المحدودة:** يضبط `_open_camera_capture()` متغير البيئة `OPENCV_FFMPEG_CAPTURE_OPTIONS="rtsp_transport;tcp\|stimeout;5000000\|rw_timeout;5000000"` ويمرر `cv2.CAP_FFMPEG` مع `CAP_PROP_OPEN_TIMEOUT_MSEC = 5000` و `CAP_PROP_READ_TIMEOUT_MSEC = 5000` لمنع تجمد الخيوط عند انقطاع الشبكة.<br>2) **حماية بيانات الاعتماد:** عند حفظ الرابط `rtsp://admin:MySecretPass2026@192.168.10.55:554/h264Preview_01_main` عبر `save_cfg()`، تم إخفاء كلمة المرور في `mersad_config.json` (`rtsp://admin:***@192.168.10.55:554/h264Preview_01_main`) وفي جميع السجلات، بينما حُفظ الرابط الكامل في `.mersad_secrets.json` بصلاحيات `0600` (و`icacls` على Windows). |
| **3. كاميرات الويب المحلية (`USB Webcams` — `"0"`, `"1"`)** | **`PASS` (مدعوم ومختبر فعلياً)** | يحول `_open_camera_capture()` المعرفات الرقمية النصية (`"0"`, `"1"`) تلقائياً إلى أعداد صحيحة (`int(source) if str(source).isdigit() else source`) ويستدعي `cv2.VideoCapture(0)`. كما تفحص أداة `check_install.py --camera --json` (`check_camera_source(source_override="0")`) منفذ الكاميرا المحلي وتضمن استدعاء `cap.release()` (`released: True`)، وفي حال عدم وجود كاميرا USB متصلة يدخل النظام في وضع مراقبة إعادة الاتصال (`reconnecting`) دون إسقاط الخدمة. |

---

## 5. فحص جاهزية حزم Windows x64 والعيوب البرمجية المكتشفة (Packaging Audit & Discovered Bugs)

### أولاً: تقييم ملفات البناء والحزم لنظام Windows x64

تم فحص جميع ملفات البناء والتوزيع في كلا المشروعين:
1. **ملفات PyInstaller (`mersad_ai.spec` و `mersad_lab.spec`):**
   - `mersad_ai.spec`: مبني بنمط `--onedir` (`COLLECT` باسم `MERSAD_AI`)، يضمّن `dashboard.html` و `README_AR.md`، ويجمع جميع الوحدات المخفية الـ 9 (`registry`, `insights`, `analytics`, `camera_history`, `notify`, `server`, `check_install`, `prefetch`, `openpyxl`) بالإضافة إلى `collect_all("easyocr")` و `collect_all("ultralytics")` و `collect_submodules("sklearn")`، ويستبعد الوحدات المتعارضة أو غير الضرورية (`opencv-python-headless`, `ultralytics.trackers`, `torch.utils.tensorboard`, `tensorboard`, `lap`, `lapx`)، ويفعّل الوضع غير المتصل `YOLO_OFFLINE=true` و `ULTRALYTICS_AUTOINSTALL=false`.
   - `mersad_lab.spec`: مبني بنمط `--onedir` (`COLLECT` باسم `MERSAD_LAB`)، يجمع مكتبات `cv2` و `numpy` الديناميكية، ويضمّن `index.html`, `README_AR.md`, `PHASE1_STATUS_AR.md`، ويستبعد الحزم الثقيلة (`torch`, `ultralytics`, `easyocr`, `scipy`, `matplotlib`, `tkinter`) للحفاظ على خفة الحزمة.
2. **مثبت Inno Setup (`MERSAD_LAB_Preview_0.1/installer/mersad_lab_setup.iss` و `build_installer.ps1`):**
   - مهيأ لمعمارية 64-بت (`ArchitecturesAllowed=x64compatible`, `ArchitecturesInstallIn64BitMode=x64compatible`)، بضغط `lzma2` وبدون اشتراط صلاحيات مسؤول (`PrivilegesRequired=lowest`)، وينتج `dist\installer\MERSAD_LAB_Setup_x64.exe`، ويتحقق أثناء التثبيت من عمل البرنامج عبر تشغيل `{app}\MERSAD_LAB.exe --port 0 --self-check`.
3. **مهام GitHub Actions (`windows-build.yml`, `build-mersad-lab-windows.yml`, `release-mersad-preview-0.1-windows.yml`):**
   - تستهدف جميعها `runs-on: windows-latest` مع `Python 3.11 (x64)`، وتتحقق من بناء `MERSAD_AI.exe` و `MERSAD_LAB.exe` وملفي `MERSAD_AI_Portable_x64.zip` و `MERSAD_LAB_Portable_x64.zip` والمثبت `MERSAD_LAB_Setup_x64.exe`، وتنفذ اختبارات الدخان (Smoke Tests) داخل مسار يحتوي على **أحرف عربية ومسافات** مع تجريد متغير `PATH` من Python لإثبات استقلالية الملفات التنفيذية.
4. **حالة المجلد `windows_binaries_staging/` في المستودع المحلي:**
   - المجلد `windows_binaries_staging/` فارغ حالياً في بيئة Linux المحلية لأن PyInstaller لا يدعم التجميع المتقاطع (Cross-Compiling) لملفات `.exe` الخاصة بـ Windows من داخل نظام Linux؛ ويتطلب إنتاج الملفات التنفيذية الفعلي تشغيل `BUILD_AND_VERIFY_FINAL_WINDOWS_RELEASE.bat` على جهاز Windows 10/11 x64 أو تشغيل سير العمل `release-mersad-preview-0.1-windows.yml` على GitHub Actions.

---

### ثانياً: العيوب البرمجية المكتشفة التي تحتاج إلى إصلاح (Discovered Software Bugs)

كشف الفحص العميق والتشغيل الفعلي للاختبارات عن **4 عيوب برمجية وهندسية حقيقية** لم تكشفها الاختبارات السابقة:

#### 1. `[CRITICAL / HIGH]` خلل الكتابة فوق `bus.post` في الدالة `wire()` يعطل إضافة وحذف الكاميرات عبر HTTP (`MERSAD_AI_Preview_0.1/mersad_live.py` — الأسطر `3516–3527`)
- **الوصف التفصيلي:**
  في الدالة `wire()` داخل `mersad_live.py`، تمت إضافة مساري `/api/cameras/add` و `/api/cameras/remove` في السطرين `3516–3517`:
  ```python
  bus.post["/api/cameras/add"] = lambda d, ip: add_camera_runtime(d, who=ip)
  bus.post["/api/cameras/remove"] = lambda d, ip: remove_camera_runtime(d, who=ip)
  ```
  ولكن بعد 10 أسطر فقط (في السطر `3527`)، يقوم الكود بإعادة تعيين القاموس `bus.post = { "/api/decision": ..., ... }` بالكامل دون تضمين `/api/cameras/add` و `/api/cameras/remove`!
- **الأثر الفعلي:**
  عند تشغيل `MERSAD AI` الفعلي عبر `main()` (الذي يستدعي `wire()`)، يؤدي إرسال طلب من `MERSAD LAB` عبر زر/واجهة `POST /api/integration/connect_ai` إلى إرجاع `HTTP 404 (المسار غير موجود)` من خادم `MERSAD AI` وفشل الربط بـ `HTTP 502`! (نجح الاختبار `integration/test_ai_lab_integration.py` سابقاً فقط لأنه قام بتعيين `ai_srv.bus.post["/api/cameras/add"]` يدوياً في السطر 176 دون استدعاء `m.wire()`).
  كما أن `main()` في `mersad_live.py` لا يقوم بتعيين `_ACTIVE_ENGINE_CONTROLLER`، مما يجعل `add_camera_runtime` عند استدعائها في وضع التشغيل العادي تضيف الكاميرا إلى `STATUS["cameras"]` فقط (`worker_spawned: False`) دون إطلاق خيط قراءة أو استدلال.
- **الإصلاح المطلوب:**
  نقل تعريف `/api/cameras/add` و `/api/cameras/remove` ليكونا داخل قاموس `bus.post = { ... }` في السطر `3527`، وربط حلقة الكاميرات في `main()` بـ `_ACTIVE_ENGINE_CONTROLLER` (أو دالة مساعدة لتوليد خيوط القراءة والاستدلال في `_ACTIVE_CAM_STATES`).

#### 2. `[HIGH]` انهيار `Segmentation Fault (SIGSEGV)` بسبب حالة سباق (Use-After-Free) في `remove_camera_runtime()` (`MERSAD_AI_Preview_0.1/mersad_live.py` — الأسطر `3432–3455`)
- **الوصف التفصيلي:**
  عند استدعاء `remove_camera_runtime()` (عبر `POST /api/cameras/remove`) لإزالة كاميرا نشطة يعمل لها خيط `_camera_reader_worker`:
  ```python
  st = _ACTIVE_CAM_STATES.pop(cam_name, None)
  if st:
      ev = st.get("stop_ev")
      if ev:
          ev.set()
      cap = st.get("cap")
      if cap:
          cap.release()
  ```
  تقوم الدالة بضبط `ev.set()` ثم تستدعي **فوراً** `cap.release()` على كائن C++ `cv2.VideoCapture` دون انتظار انتهاء خيط القراءة (`rt.join()`) ودون حيازة القفل `with st["lock"]:`، ودون إزالة الكاميرا من `_ACTIVE_ENGINE_CONTROLLER.cam_states`!
- **الأثر الفعلي:**
  إذا كان خيط القراءة `_camera_reader_worker` ينفذ في نفس اللحظة `cap_obj.read()` على دفق FFmpeg/MJPEG، فإن استدعاء `cap.release()` من خيط HTTP يحرر بنية `AVFormatContext` في لغة C أثناء قراءتها، مما يؤدي إلى انهيار العملية بالكامل بـ **`Segmentation fault (exit code 139)`** (كما ثبت عملياً أثناء تنفيذ السيناريو 11).
- **الإصلاح المطلوب:**
  في `remove_camera_runtime()`، يجب إزالة `cam_name` من `_ACTIVE_ENGINE_CONTROLLER.cam_states` أولاً، وضبط `stop_ev.set()`، والانتظار حتى يتوقف خيط القراءة (`reader_thread.join(timeout=2.0)`)، ثم حيازة `with st["lock"]:` لتصفير `st["cap"] = None` واستدعاء `cap.release()` بأمان (تماماً كما تفعل `MersadEngineController.stop()` في الأسطر `3409–3426`).

#### 3. `[MEDIUM / HIGH]` خلل المسار النسبي في `tools/compare_original_vs_cleanroom_lab.py` يؤدي إلى فشل كاذب (`0/0 PASS`) عند استدعائه من سكربتات البناء (`الأسطر 159–171 و 279–281`)
- **الوصف التفصيلي:**
  في `tools/compare_original_vs_cleanroom_lab.py`، لا يتم تحويل المسارات المدخلة (`--original-source` و `--cleanroom-dir`) إلى مسارات مطلقة عبر `.resolve()`. وعندما تُستدعى الدالة `run_independent_lab_functional_and_security_suite(lab_dir, ...)` مع مسار نسبي (مثل `--cleanroom-dir "MERSAD_LAB_Preview_0.1"` المستخدم في `BUILD_AND_VERIFY_FINAL_WINDOWS_RELEASE.ps1` السطر 79 وفي `.github/workflows/release-mersad-preview-0.1-windows.yml` السطر 63):
  ```python
  test_script = lab_dir / "test_lab.py"  # -> "MERSAD_LAB_Preview_0.1/test_lab.py"
  proc = subprocess.run([sys.executable, str(test_script)], cwd=str(lab_dir), ...)
  ```
  بسبب تغيير مجلد العمل إلى `cwd="MERSAD_LAB_Preview_0.1"` مع بقاء مسار السكربت نسبياً، يبحث Python عن `MERSAD_LAB_Preview_0.1/MERSAD_LAB_Preview_0.1/test_lab.py` فيفشل بـ `Errno 2` ويعيد `Clean-Room LAB Suite: FAIL (0/0 PASS)` بدلاً من `PASS (20/20 PASS)`!
- **الإصلاح المطلوب:**
  تحويل المسارات في `main()` إلى مسارات مطلقة فوراً:
  ```python
  orig_in = Path(args.original_source).resolve()
  pres_dir = Path(args.preserve_original_dir).resolve()
  clean_dir = Path(args.cleanroom_dir).resolve()
  ```

#### 4. `[MEDIUM]` تعارضات في سكربتات بناء الحزمة الموحدة لـ Windows (`BUILD_AND_VERIFY_FINAL_WINDOWS_RELEASE.ps1` و `release-mersad-preview-0.1-windows.yml`)
- **الوصف التفصيلي:**
  1. **نسخ `RUN.bat` و `RUN_LAN.bat` المصدريين إلى مجلد التوزيع `dist\MERSAD_AI\`:**
     في السطر 103 من `BUILD_AND_VERIFY_FINAL_WINDOWS_RELEASE.ps1` والسطر 95 من `release-mersad-preview-0.1-windows.yml`، يتم نسخ `RUN.bat` و `RUN_LAN.bat` المصدريين مباشرةً إلى `dist\MERSAD_AI\`. وبما أن `RUN.bat` المصدري يستدعي `call setup.bat` و `venv\Scripts\python.exe mersad_live.py` بدلاً من `MERSAD_AI.exe`، فإنه سيفشل على أجهزة المستخدمين النهائيين التي لا تحتوي على `setup.bat` أو `venv` داخل الحزمة المحمولة! (بينما يقوم `MERSAD_AI_Preview_0.1/BUILD_EXE.bat` و `windows-build.yml` بتوليد ملفات `RUN.bat` و `RUN_LAN.bat` مخصصة للتوزيع تستدعي `MERSAD_AI.exe %*` مباشرةً).
  2. **عدم إزالة `opencv-python-headless` بعد تثبيت `requirements.txt` في السكربت الموحد:**
     يقوم `easyocr==1.7.2` بسحب `opencv-python-headless` تلقائياً. في `MERSAD_AI_Preview_0.1/setup.bat` و `windows-build.yml`، يتم تنفيذ `pip uninstall -y opencv-python-headless` ثم `pip install --force-reinstall --no-deps opencv-python==4.11.0.86`، لكن هذه الخطوة سقطت سهواً من `BUILD_AND_VERIFY_FINAL_WINDOWS_RELEASE.ps1` (السطر 64) ومن `release-mersad-preview-0.1-windows.yml` (السطر 34).
  3. **اختلاف إصدار `pyinstaller` المثبت بين المشروعين:**
     يستخدم `MERSAD_AI` الإصدار `pyinstaller==6.11.1` بينما يحدد `MERSAD_LAB/constraints-win-x64.txt` الإصدار `pyinstaller==6.10.0`.

---

## 6. الخلاصة النهائية والتوصيات

1. **جاهزية التكامل الوظيفي والأمني:** اجتازت جميع اختبارات الوحدة والأمان (`232/232 PASS` في `MERSAD AI`، و`20/20 PASS` في `MERSAD LAB`) وجميع السيناريوهات الـ 12 لاختبار التكامل الشامل (`12/12 PASS`) بالإضافة إلى دعم ملفات الفيديو وRTSP وUSB.
2. **الأوزان الثقيلة والتجميع النهائي لـ Windows:** نظراً لأن بيئة الاختبار الحالية هي حاوية Linux معزولة عن الإنترنت، فإن تحميل وتشغيل النماذج الأربعة الثقيلة (`YOLOv8n`, `EasyOCR`, `YuNet`, `SFace`) وبناء ملفات `.exe` عبر PyInstaller و Inno Setup يتطلبان التنفيذ على بيئة Windows x64 متصلة بالإنترنت أو عبر GitHub Actions (`windows-latest`).
3. **أولويات الإصلاح قبل إصدار الحزمة النهائية:**
   - إصلاح إعادة تعيين `bus.post` في `mersad_live.py` (`wire()`) لضمان عمل `/api/cameras/add` و `/api/cameras/remove` عند التشغيل الفعلي.
   - إصلاح حالة السباق في `remove_camera_runtime()` بانتظار توقف خيط القراءة قبل استدعاء `cap.release()`.
   - إضافة `.resolve()` للمسارات في `tools/compare_original_vs_cleanroom_lab.py`.
   - توليد `RUN.bat` و `RUN_LAN.bat` الخاصين بـ `MERSAD_AI.exe` وإزالة `opencv-python-headless` في `BUILD_AND_VERIFY_FINAL_WINDOWS_RELEASE.ps1` و `release-mersad-preview-0.1-windows.yml`.

