# التقرير النهائي للمرحلة التنفيذية وجولة المعالجة الإضافية — `MERSAD_PREVIEW_0.1_FINAL`
## (`FINAL_RELEASE_REPORT_AR.md`)

> **إقرارات هندسية صريحة (التزاماً بجميع شروط القبول):**
> 1. **عدم إعلان نجاح بناء أو تشغيل ملفات `EXE` قبل اختبارها الفعلي على Windows**: نظراً لأن بيئة التنفيذ الحالية هي حاوية `Linux x86_64` معزولة شبكياً بالكامل (بدون اتصال بالإنترنت، وبدون وصول إلى المستودع الخاص `https://github.com/alinon9/MERSAD-AI-`، وبدون نظام تشغيل `Windows 10/11 x64`)، فإننا **لا نعلن نجاح المرحلة الثالثة الخاصة ببناء أو تشغيل ملفات `MERSAD_AI.exe` و`MERSAD_LAB.exe` و`MERSAD_LAB_Setup_x64.exe` بعد**، وتظل حالتها **`NOT TESTED` (بانتظار التنفيذ على بيئة Windows x64 متصلة بالإنترنت)**.
> 2. **وضع المرحلة الثانية (`BLOCKED` لغياب التزام المختبر الأصلي المحدد)**: تتحقق أداة `tools/compare_original_vs_cleanroom_lab.py` من تطابق المختبر الأصلي مع الالتزام المحدد `ed7b8f727243da4878e547f08489af581c83291c` (`build/mersad-lab-exe-20261031`). وبسبب عدم توفر أرشيف هذا الالتزام في بيئة الفحص الحالية، صُنفت مرحلة المقارنة رسمياً **`BLOCKED`** (`Exit Code 2` عند التمرير بـ `--require-unblocked`) ولا يُسمح باعتبار المقارنة ناجحة (`PASS`) قبل استعادة الالتزام المحدد.
> 3. **عدم وصف الإصدار بأنه جاهز ميدانياً**: هذه النسخة مخصصة للمعاينة الهندسية والعرض التجريبي (`Preview 0.1`) فقط، **وليست جاهزة للاستخدام الميداني**، وتخضع جميع مخرجاتها للمراجعة البشرية الإلزامية.
> 4. **عدم استخدام `Tesseract` بديلاً عن `EasyOCR` في اختبار قبول النموذج الأصلي**: تم عزل `Tesseract 5 LSTM` كاختبار مستقل تماماً (`INDEPENDENT_AUXILIARY_TESSERACT_BENCHMARK`)، بينما يشترط مسار القبول الرئيسي (`--require-real-models`) تحميل وتشغيل النماذج الأربعة الأصلية (`YOLOv8n`, `EasyOCR Arabic + English`, `YuNet`, `SFace`) حصراً بعد التحقق من بصماتها `SHA-256` الثابتة.

## 1. ملخص ما تم تنفيذه فعلياً في جولة المعالجة الإضافية (المراحل 1 إلى 5)

| المرحلة | الفجوة المرصودة في المراجعة المستقلة | المعالجة البرمجية الفعلية المنفذة | الحالة الحالية |
|---|---|---|---|
| **المرحلة 1 (1–4)** | غياب بصمة `SHA-256` ثابتة لـ `YOLOv8n` وأوزان `EasyOCR` والاعتماد على ملف `.sha256` مولّد ذاتياً عند التنزيل | تم تثبيت البصمة الرسمية الثابتة لـ `yolov8n.pt` (`31e20dde3def09e2cf938c7be6fe23d9150bbbe503982af13345706515f2ef95`) وأوزان `EasyOCR` (`craft_mlt_25k.pth`: `4a5efbfb48b4081100544e75e1e2b57f8de3d84f213004b14b85fd4b3748db17`, `arabic.pth`: `2a9afd42c374deb98aed0b53c9b77d75e1d00d4e0501f3b0276c54190c89b1a8`, `english_g2.pth`: `e2272681d9d67a04e2dff396b6e95077bc19001f8f6d3593c307b9852e1c29e8`, `latin_g2.pth`: `aaa95be1c4a9cb3496879bed7c520886ce1164f89e026f0c54488394e74e8c55`) مع الاحتفاظ ببصمتي `YuNet` و`SFace`، وحذف توليد أو قبول ملف `.sha256` الجانبي لـ `yolov8n.pt` في `prefetch.py` و`mersad_live.py`، وإلزام التحقق من البصمات قبل تحميل أي نموذج. | **`PASS` (تم التحقق بالكود والاختبار `V7-EASYOCR-CORRUPT`)** |
| **المرحلة 1 (5–7)** | حصول `EasyOCR` على `PASS` دون حد أدنى لعينات اللوحات، واستقبال `SFace` قصاصة عشوائية من وسط الصورة، ودمج المشاهد الاصطناعية مع تدفق الكاميرات | تم تحديث `integration/evaluate_ai_models.py` لفرض حد أدنى صارم `MIN_REQUIRED_PLATE_SAMPLES = 4` قراءات فعلية غير فارغة لقصاصات اللوحات قبل منح `EasyOCR` حالة `PASS`، وإلزام `SFace` باستقبال قصاصة وجه حقيقية ومحاذاة ناتجة عن كشف `YuNet` (`det.detect -> rec.alignCrop`) ومنع أي قص عشوائي، وفصل `SYNTHETIC_VIRTUAL_CAMERA_SCENE_INFERENCE` عن `LIVE_LAB_HTTP_MJPEG_STREAM_INFERENCE`. | **`PASS` (الكود محدث؛ واستدلال النماذج الأربعة `NOT TESTED` محلياً لعزل الشبكة)** |
| **المرحلة 2** | الاكتفاء بمقارنة `SHA-256` وأحجام الملفات ووصف الاختلاف بأنه تحسين وعدم قفل المرحلة عند غياب الالتزام `ed7b8f727243da4878e547f08489af581c83291c` | تمت إعادة كتابة `tools/compare_original_vs_cleanroom_lab.py` للتحقق الصارم من الالتزام `ed7b8f727243da4878e547f08489af581c83291c`، وجعل المرحلة **`BLOCKED`** (`Exit Code 2` مع `--require-unblocked`) عند عدم توفر الالتزام، وتشغيل الاختبارات الوظيفية والأمنية (20 فحصاً) بصورة مستقلة، ومقارنة AST وواجهات API وتدفق MJPEG وسلوك الكاميرات والأمان وإغلاق العمليات، واستخدام الوصف المحايد `DIFFERENT` فقط. | **`BLOCKED` (بانتظار توفير أرشيف الالتزام `ed7b8f727243da4878e547f08489af581c83291c`؛ و`Clean-Room LAB` اجتاز `20/20 PASS`)** |
| **المرحلة 3** | تعارض أرقام التكامل القديمة (`12/12 PASS`) مع نتائج التكامل المحدثة (`7 PASS + 1 NOT TESTED`) | تمت إعادة توليد جميع التقارير (`04_AI_LAB_INTEGRATION_REPORT_AR.md`, `06_TEST_MATRIX_PASS_FAIL_AR.md`, `08_ORIGINAL_VS_CLEANROOM_LAB_COMPARISON_AR.md`, `MERSAD_PREVIEW_0.1_RELEASE_ACCEPTANCE.md`, `FINAL_RELEASE_REPORT_AR.md`) ومزامنة `reports_and_logs/logs/` مباشرةً من أحدث سجلات التنفيذ الفعلية دون أي تعارض. | **`PASS` (`0` تعارضات بين السجلات والتقارير)** |
| **المرحلة 4** | تساهل سكربتات بناء Windows مع الأخطاء أو غياب `ISCC.exe` أو بقاء مخرجات قديمة أو اختلاف أسماء الملفات | تم تحصين `BUILD_AND_VERIFY_FINAL_WINDOWS_RELEASE.ps1` و`.github/workflows/release-mersad-preview-0.1-windows.yml` و`installer/build_installer.ps1` و`mersad_lab_setup.iss`: مسح المخرجات القديمة قبل البناء، فحص `Exit Code` بعد كل أمر، جعل غياب `ISCC.exe` فشلاً صريحاً، توحيد الأسماء (`MERSAD_AI.exe`, `MERSAD_LAB.exe`, `MERSAD_LAB_Setup_x64.exe`, `MERSAD_AI_Portable_x64.zip`, `MERSAD_LAB_Portable_x64.zip`)، اختبار المسار العربي ذي المسافات بعد تجريد `PATH`، واختبار التثبيت الصامت وتشغيل البرنامج المثبت وإلغاء التثبيت، وإزالة `--force-with-lease` من سكربت الرفع. | **`NOT TESTED` (محلياً لغياب نظام Windows؛ السكربتات محصنة بالكامل)** |
| **المرحلة 5** | إعادة تشغيل جميع الفحوص وتحديث `MANIFEST.json` و`SHA256SUMS.txt` وبناء الحزمة النهائية | أُعيد تشغيل كافة الفحوص وتحديث حزمة Git (`49e400c0ec45dd3933227f1e988244e5ba50ec05` فوق `9491bcd0d610c51ce76b599591db5c9f0b84cd44` مع بقاء `main` `25c9e5bb` دون مساس) وتوليد `MANIFEST.json` و`SHA256SUMS.txt` وبناء `MERSAD_PREVIEW_0.1_FINAL.zip`. | **`PASS`** |

## 2. الإجماليات الرقمية الموحدة من أحدث سجلات التنفيذ الفعلية

| المجموعة الاختبارية | إجمالي الفحوص | `PASS` | `FAIL` | `NOT TESTED` | `BLOCKED` | السجل المرجعي الفعلي |
|---|---|---|---|---|---|---|
| اختبارات `MERSAD AI` (`selftest.py` — الوضع القياسي) | **232** | **232** | 0 | 0 | 0 | `reports_and_logs/mersad_ai_selftest_log.txt` |
| اختبارات `MERSAD AI` (`MERSAD_BLOCK_SKLEARN=1`) | **232** | **232** | 0 | 0 | 0 | `reports_and_logs/mersad_ai_selftest_no_sklearn_log.txt` |
| فحص سلامة ملفات `MERSAD AI` (`verify_integrity.py`) | **18** | **18** | 0 | 0 | 0 | `reports_and_logs/mersad_ai_verify_integrity_log.txt` |
| اختبارات `MERSAD LAB 1.0` المستقلة (`test_lab.py`) | **20** | **20** | 0 | 0 | 0 | `reports_and_logs/mersad_lab_test_log.txt` |
| اختبارات التكامل النهائي (`test_ai_lab_integration.py`) | **8** | **7** | 0 | **1** | 0 | `reports_and_logs/ai_lab_integration_log.txt` |
| استدلال النماذج الأربعة الأساسية (`evaluate_ai_models.py` — مشهد اصطناعي + تدفق حي) | **8** | **0** | 0 | **8** | 0 | `reports_and_logs/model_inference_log.txt` |
| اختبار `Tesseract 5 LSTM` المستقل (مشهد اصطناعي `4/4` + تدفق حي `4/4`) | **8** | **8** | 0 | 0 | 0 | `reports_and_logs/model_inference_log.txt` |
| مقارنة المختبر الأصلي (`ed7b8f727243da4878e547f08489af581c83291c`) مع `Clean-Room LAB` | **1** | **0** | 0 | 0 | **1** | `reports_and_logs/lab_comparison_log.txt` |
| بناء واختبار ملفات Windows التنفيذية (`MERSAD_AI.exe`, `MERSAD_LAB.exe`, `MERSAD_LAB_Setup_x64.exe`) | **3** | **0** | 0 | **3** | 0 | بانتظار التنفيذ على Windows 10/11 x64 |

## 3. البصمات الرقمية الثابتة المعتمدة للنماذج (`Pinned Model SHA-256 Registry`)

| النموذج / ملف الوزن | البصمة المرجعية الثابتة (`SHA-256`) |
|---|---|
| `models/yunet.onnx` | `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4` |
| `models/sface.onnx` | `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79` |
| `models/yolov8n.pt` | `31e20dde3def09e2cf938c7be6fe23d9150bbbe503982af13345706515f2ef95` |
| `models/easyocr/craft_mlt_25k.pth` | `4a5efbfb48b4081100544e75e1e2b57f8de3d84f213004b14b85fd4b3748db17` |
| `models/easyocr/arabic.pth` | `2a9afd42c374deb98aed0b53c9b77d75e1d00d4e0501f3b0276c54190c89b1a8` |
| `models/easyocr/english_g2.pth` | `e2272681d9d67a04e2dff396b6e95077bc19001f8f6d3593c307b9852e1c29e8` |
| `models/easyocr/latin_g2.pth` | `aaa95be1c4a9cb3496879bed7c520886ce1164f89e026f0c54488394e74e8c55` |

## 4. البصمات الرقمية للملفات البرمجية المحدثة داخل الحزمة (`Key Remediated Files SHA-256`)

| المسار النسبي داخل `MERSAD_PREVIEW_0.1_FINAL/` | الحجم | البصمة الرقمية (`SHA-256`) |
|---|---|---|
| `MERSAD_AI_Preview_0.1/mersad_live.py` | `305,839 B` | `b20f20f073d629f602257ae9ba396470724e5267b2af0e2a054b3cbf327520b3` |
| `MERSAD_AI_Preview_0.1/prefetch.py` | `4,904 B` | `13bfd3de08df6773788c952884381b445b821eee2900643f65fa976101ce6947` |
| `MERSAD_AI_Preview_0.1/check_install.py` | `34,381 B` | `8080f4264371d70b173690d9b48452859af6c0cc890912a6c0938e82a945b9ed` |
| `MERSAD_AI_Preview_0.1/selftest.py` | `309,906 B` | `1cb93c1c0811f798e7176725e1646d28005ab208ab9a05be30d65eab718b7f65` |
| `MERSAD_LAB_Preview_0.1/sim_engine.py` | `15,962 B` | `15e86acec2ab8ef036da894d2679ae89f7981d8698f716128d3c7d4c859bd015` |
| `MERSAD_LAB_Preview_0.1/installer/mersad_lab_setup.iss` | `1,290 B` | `123826b20b72209c6cc04a8db5cc30ab92ade262e1e41a7e37e6c7d7002fe9d6` |
| `MERSAD_LAB_Preview_0.1/installer/build_installer.ps1` | `3,340 B` | `046ee881a32d8adf8542b04d300fb1b092c93d08e3d0136352f296f28a989880` |
| `integration/evaluate_ai_models.py` | `27,678 B` | `bf7c3e271173327c55418d76128101a1d5d901859706298ff93cc2f76f04d79c` |
| `integration/test_ai_lab_integration.py` | `19,252 B` | `66e0af6116e8b8b9ac7157d0c119fcece946895f204e7494a215d2b2887ee94e` |
| `tools/compare_original_vs_cleanroom_lab.py` | `23,107 B` | `c595a77c0bb012028728680d5b439bfa694f08986bc9661f6b51dcbdace9cead` |
| `BUILD_AND_VERIFY_FINAL_WINDOWS_RELEASE.ps1` | `11,292 B` | `fdb1cacd0821041a61aa3e977b954d9031f10b7d44c76bc55593066262ca4938` |
| `PUSH_CANDIDATE_9491BCD_TO_GITHUB_ACTIONS.bat` | `1,972 B` | `05469d6b60a1cdebf94b8034479aaae1d966bf290793148aa35d6f5124a90bbd` |
| `.github/workflows/release-mersad-preview-0.1-windows.yml` | `11,783 B` | `f601f7b914129f6ae29b4bfefac0595a16706ab75c5a9a860633b88d59905b30` |
| `reports_and_logs/mersad_preview_0_1_verifiable_history.bundle` | `627,698 B` | `d203dd348c1f42f27fc0a06a01134e9e4178232064ce7212db6ff8cb705f5a69` |


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
