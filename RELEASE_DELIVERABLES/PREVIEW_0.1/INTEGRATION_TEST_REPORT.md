# 3. تقرير اختبارات التكامل الشامل بين المشروعين — `INTEGRATION_TEST_REPORT.md`
## الإصدار: `MERSAD AI & MERSAD LAB — Preview 0.1` (`fix/preview-0.1-postbuild-42273598736` — `AI Current Branch HEAD`: `New verified HEAD directly above 850fbdb450ba98e09994c6b6b01b84e1a5e65fe6` | `AI Runtime Code Commit`: `edaf651321ec9ea6ba613e3ab1630bc16b11b9d5` | `LAB HEAD`: `748ac0158761812a6fff63ff6fe626b9df8c252b`)


## مطابقة وتوحيد مصدر الحقيقة وأرقام الاختبارات وسلسلة الالتزامات (`Forensic Source-of-Truth & Test Report Reconciliation`)

تم توحيد جميع الحزم المصدرية (`MERSAD_AI_Preview_0.1_Portable_Source.zip` و`MERSAD_LAB_Preview_0.1_Portable_Source.zip`) وحزمتي Git الجنائيتين (`mersad_preview_0_1_verifiable_history.bundle` و`mersad_lab_preview_0_1_verifiable_history.bundle`) والتقارير وسكربتات النشر على فرع الإصلاح المعتمد **`fix/preview-0.1-postbuild-42273598736`**، مع الفصل الصارم والدقيق بين الالتزامات والمراحل التاريخية:

### 1. سلسلة الالتزامات الجنائية الموثقة ونسب الإصلاحات (`Exact Commit Lineage & Attribution — BUG-01..BUG-49`)

> **قاعدة الفصل الجنائي الصارم بين التزامات Git (`Committed Git Tree`) وطبقة مخرجات الإصدار التوليدية (`Post-Commit Release Artifacts Layer — BUG-33..BUG-49`)**:
> تلتزم جميع تقارير وقوائم هذا الإصدار بعدم نسب أي تعديل إلى رقم التزام (`Commit SHA`) إلا إذا كان موجوداً فعلياً داخل شجرة ذلك الالتزام (`git show <SHA>`). وعليه، فإن التزام الفرع الحالي على رأس **`fix/preview-0.1-postbuild-42273598736`** (`New verified HEAD directly above 850fbdb450ba98e09994c6b6b01b84e1a5e65fe6` — `fix(ci,ui): harden fail-closed deployment, settling window, and dashboard readiness (BUG-40..45)`) يضم فعلياً في شجرة Git: (1) إزالة أي دفع للأوسمة (`tags`) وتحويل ملفي `.bat` إلى واجهات رقيقة تفوض التنفيذ بالكامل إلى `tools/deploy_and_run_github_actions.py` (`BUG-40`)، (2) الاستعلام المغلق عند الفشل (`Fail-Closed`) مع التصفح (`Pagination`) وخط الأساس الزمني `preflight_started_at_utc` (`BUG-41`)، (3) نافذة الاستقرار لكشف التشغيلات المكررة المتأخرة (`Duplicate-Detection Settling Window` — `BUG-42`)، (4) إصلاح بطاقة الجاهزية في `MERSAD_AI_Preview_0.1/dashboard.html` ومزامنة `MERSAD_AI_Preview_0.1_Portable_Source.zip` لإزالة القيمة الافتراضية `??100` وعرض المؤشرات الأربعة كافةً مع التعامل الصارم مع `null`/`0`/القيم غير الرقمية (`BUG-43`)، (5) الفحص المسبق لتطابق الفرع البعيد (`REMOTE_ALREADY_AT_LOCAL_HEAD_NO_NEW_PUSH_EVENT`) والتحقق من قابلية التقديم السريع (`Fast-Forward`) (`BUG-44`)، و(6) الفصل الصريح بين حساب وتسجيل بصمات `SHA-256` (`SHA256_CALCULATED_AND_RECORDED`) والتحقق المرجعي المستقل أو `Attestation` (`BUG-45`). أما التزام منطق الكود التشغيلي الأساسي لـ `MERSAD AI` (`mersad_live.py`, `registry.py`, `selftest.py`) فمثبت عند **`edaf651321ec9ea6ba613e3ab1630bc16b11b9d5`** (`v0.1.1-postbuild-reconciled-code` — محفوظ دون تحريك)، وتضم شجرة `HEAD` الحالية تحديث الواجهة `MERSAD_AI_Preview_0.1/dashboard.html` (`BUG-43`) متطابقاً `58/58` بايت-ببايت مع `MERSAD_AI_Preview_0.1_Portable_Source.zip`. وتُنتج القوائم التوليدية وحزمة Git المحدثة والأرشيف النهائي (`MANIFEST.json`, `SOURCE_TREE_MANIFEST.json`, `BUNDLE_MANIFEST.json`, `SHA256SUMS.txt`, `mersad_preview_0_1_verifiable_history.bundle`, `MERSAD_PREVIEW_0.1_FINAL_RELEASE_BUNDLE.zip`) بعد إنشاء الالتزام وتُصنف صراحةً كـ **طبقة مخرجات الإصدار التوليدية (`Post-Commit Generated Release Artifacts Layer`)** لمنع أي تحقق دائري للبصمات.

| المستودع / الطبقة | الفرع / الوسم (`Branch / Tag / Layer`) | المرجع / رقم الالتزام (`Commit SHA`) | الإصلاحات المنفذة فعلياً في هذا الالتزام / الطبقة | حالة المطابقة والتحقق |
| :--- | :--- | :--- | :--- | :--- |
| **طبقة مخرجات الإصدار التوليدية (`Post-Commit Generated Release Artifacts Layer`)** | فوق `HEAD` للفرع `fix/preview-0.1-postbuild-42273598736` (تُولَّد بعد إنشاء الالتزام لمنع التضمين الدائري للبصمة) | `MANIFEST.json`, `SOURCE_TREE_MANIFEST.json`, `BUNDLE_MANIFEST.json`, `SHA256SUMS.txt`, `mersad_preview_0_1_verifiable_history.bundle`, `MERSAD_PREVIEW_0.1_FINAL_RELEASE_BUNDLE.zip`, `MERSAD_BUG40_45_REMEDIATION_FINAL_REPORT.md` | توليد حزمة تاريخ Git المحدثة وقوائم البصمات الأربع والأرشيف النهائي والتقرير الختامي ومزامنة النسخ المنفصلة بايت-ببايت بعد إتمام التزام `HEAD` مباشرةً. | **`172 / 172 MATCH`** (`0 missing`, `0 hash mismatches`) |
| **`MERSAD AI Current Branch HEAD` (`BUG-40..45 Hardened`)** | **`fix/preview-0.1-postbuild-42273598736`** (`HEAD`) | **`New verified HEAD directly above 850fbdb450ba98e09994c6b6b01b84e1a5e65fe6`** (`fix(ci,ui): harden fail-closed deployment, settling window, and dashboard readiness (BUG-40..45)`) | **`BUG-40`..`BUG-45`**: إزالة دفع الأوسمة وتحويل `.bat` إلى واجهات رقيقة تفوض لـ Python (`BUG-40`)، والاستعلام المغلق عند الفشل مع التصفح (`PREFLIGHT_FAILED` — `BUG-41`)، ونافذة الاستقرار لكشف التكرار المتأخر (`BUG-42`)، وإصلاح بطاقة الجاهزية في `dashboard.html` دون أي افتراض `100%` (`BUG-43`)، ومعالجة `REMOTE_ALREADY_AT_LOCAL_HEAD_NO_NEW_PUSH_EVENT` وتباعد الفرع البعيد (`BUG-44`)، وإعادة تسمية حالة البصمات إلى `SHA256_CALCULATED_AND_RECORDED` وفصلها عن التحقق المرجعي المستقل (`BUG-45`). | **`17 / 17 Verified Workflow Paths in Git Commit`** + **`58 / 58 AI Source Match`** + **`34 / 34 Deployment Self-Tests PASS`** |
| **`MERSAD AI Previous Single-Run CI Commit`** | `fix/preview-0.1-postbuild-42273598736` (`HEAD~1`) | **`a1c53f32ff3c5c9ab995de2672ff29f2de13ea38`** (`fix(ci): make preview deployment single-run and reconcile readiness evidence`) | **`BUG-35`..`BUG-39`**: قصر تشغيل CI على محفز `push` فقط وإزالة `workflow_dispatch` و`run_extended_stress`، وتوحيد ترويسات التقارير وفصل مؤشرات الجاهزية التسعة. | الأب المباشر لالتزام `HEAD` الحالي (`HEAD~1`) |
| **`MERSAD AI Previous Preflight Commit`** | `fix/preview-0.1-postbuild-42273598736` (`v0.1.2-windows-ci-preflight-ready` — محفوظ في موضعه الأصلي) | **`05f29af416c4a28ddf59c291819584d1a416d570`** (`fix(preview): include lifecycle test and sync lab engine for Windows CI`) | **`BUG-34` + توحيد وثائق `BUG-28..33` داخل Git**: إضافة `integration/test_main_entrypoint_dynamic_camera_lifecycle.py` (`baba0f01...`) إلى شجرة Git، ومزامنة `MERSAD_LAB_Preview_0.1/sim_engine.py` (`4a073153...`) بايت-ببايت مع التزام المختبر `748ac0158761`. | السلف المباشر لـ `a1c53f32ff3c` (`HEAD~2`) |
| **`MERSAD AI Runtime Code Commit`** | `fix/preview-0.1-postbuild-42273598736` (`v0.1.1-postbuild-reconciled-code` & `audit-checkpoint-edaf6513` — محفوظان في موضعهما الأصلي) | **`edaf651321ec9ea6ba613e3ab1630bc16b11b9d5`** | **`BUG-27`** (فوق `BUG-01..26`): إصلاح دورة حياة الكاميرا الديناميكية عند تشغيل `MERSAD AI` عبر نقطة الدخول الحقيقية `main()` (`_MainLoopRuntimeController`، وتسجيل `_ACTIVE_ENGINE_CONTROLLER` قبل `start_server()`، وعزل `cam_stop_ev` لكل كاميرا — **`10/10 PASS`**)، وإضافة الاختبار `#234` (`PREVIEW01-MAIN-ENTRYPOINT-DYNAMIC-CAMERA-LIFECYCLE` — **`234 / 234 PASS`**) والسيناريو `INT-SCEN-13-MAIN-ENTRYPOINT-LIFECYCLE` (**`13 PASS, 0 FAIL, 2 NOT_TESTED`**). | التزام منطق المحرك الخلفي (`mersad_live.py`, `registry.py`, `selftest.py`) |
| **`MERSAD AI`** | `fix/preview-0.1-postbuild-42273598736` (`audit-checkpoint-7f35cb10`) | `7f35cb1007a229a72ac0cd1be61fd5a81eb891bd` | **`BUG-23`..`BUG-26`** (فوق `BUG-19..22`): مزامنة جميع ملفات `MERSAD_AI_Preview_0.1/` الـ 58 مع شجرة Git، وفصل `--verify` القرائي غير التدميري عن `--generate` في `prepare_safe_eval_benchmarks.py` (`BUG-25`)، وتحديث استهداف النشر (`BUG-24`)، وإضافة الاختبار `#233` (`PREVIEW01-SAFE-EVAL-BENCHMARKS-AND-NON-DESTRUCTIVE-VERIFY` — **`233 / 233 PASS` تاريخي**). | نقطة الرجوع الموحدة ما قبل `BUG-27` (`audit-checkpoint-7f35cb10`) |
| **`MERSAD AI`** | `fix/preview-0.1-postbuild-42273598736` (`audit-checkpoint-421ec318` / `audit-checkpoint-d965d713`) | `421ec3189fb6f569023c2a86e3f818bbf9ad1860` (كود: `d965d71317e3506e5dce9d316dc81cb8ae45e43b`) | **`BUG-19`..`BUG-22`**: إصلاحات ما بعد التشغيل السحابي `Run 42273598736` (`Tesseract` CLI TSV fallback، وتطبيع رموز المحافظات اللاتينية `_LATIN_GOV_TO_AR` في `registry.py`، وإنشاء `models/eval_benchmarks/`، وفصل `smoke_inference_status` عن `ground_truth_acceptance_status`). | سلف مباشر للالتزام `7f35cb1007a2` |
| **`MERSAD AI`** | `release/mersad-preview-0.1` (`v0.1.0-preview-code`) | `2c22280d84a5fcb7b709075f73b3073bcef0aff2` (كود: `25131918a981ac2ac37923d4c738d9f93cdcbc5b`) | **`BUG-01`..`BUG-11`** (في التزام الكود `25131918a981` — **`232 / 232 PASS` تاريخي**) + **`BUG-12`..`BUG-18`** (في التزام `2c22280d84a5`). | نقطة الأساس لفرع الإصدار قبل `Run 42273598736` |
| **`MERSAD AI`** | `main` (محفوظ دون أي تعديل) | `25c9e5bba30dc8f921675e12c23a53571be895c1` | الأرشيف المصدري الأصلي غير الممسوس (`Untouched Baseline`). | محفوظ `100%` |
| **`MERSAD LAB` (`Git HEAD`)** | **`fix/preview-0.1-postbuild-42273598736`** (`HEAD`) | **`748ac0158761812a6fff63ff6fe626b9df8c252b`** | **`BUG-22`**: تحديث `VirtualCamera.info()` في `sim_engine.py` بوسم `SYNTHETIC_2D_GEOMETRIC_INTEGRATION_STREAM` و`valid_for_photorealistic_dl_accuracy_benchmark=False` (**`20 / 20 PASS`**). | **`14 / 14 MATCH` (`100% Byte-for-Byte`)** مع `MERSAD_LAB_Preview_0.1_Portable_Source.zip` ومُثبت بـ `git cat-file -e` و`git bundle list-heads` |
| **`MERSAD LAB`** | `release/mersad-preview-0.1` | `e9284356f4d1a8205946d5893121c6f8a2f22012` | التزام الأساس لفرع الإصدار (`Clean-Room LAB 1.0`). | سلف مباشر لـ `748ac0158761` |
| **`MERSAD LAB`** | `main` & `rollback-stable-lab` | `1c56dcbf77d62b8d89863e04f215e12f162e9555` | نقطة الرجوع المستقرة للمختبر (`Untouched Baseline`). | محفوظ `100%` |

### 1B. مصفوفة فصل مؤشرات الجاهزية الهندسية والبرمجية عن الجاهزية الميدانية والإنتاجية (`Separated Readiness Indicators — BUG-39 & BUG-43`)

> **توضيح دلالة المؤشرات الأربعة في `/api/readiness` ولوحة المعلومات `dashboard.html` (`BUG-39 & BUG-43`)**:
> تعيد الدالة `build_readiness_report()` في `MERSAD_AI_Preview_0.1/mersad_live.py` وتعرض الدالة `renderReadinessScorecardHtml()` في `MERSAD_AI_Preview_0.1/dashboard.html` المؤشرات الأربعة صراحةً دون أي قيمة افتراضية `100%` عند غياب البيانات (حيث يُعرض `غير متاح (N/A)` لأي حقل غائب أو `null` أو غير رقمي، وتُعرض `0%` بدقة عند تساوي القيمة مع الصفر):
> 1. **`overall_engineering_readiness_pct = 100.0%`** (`SOURCE_AND_CI_PREFLIGHT_PREPARATION_PERCENT`): يقيس فقط اكتمال الكود المصدري وضوابط الأمان (`code_and_security = 100%`)، وملفات ومواصفات بناء Windows (`windows_build_and_packaging = 100%`)، وأدوات التقييم والمعايرة البرمجية (`field_calibration_and_eval_tooling = 100%`).
> 2. **`runtime_models_and_deps_readiness_pct = 0.0%`** (في الحاوية المعزولة): يقيس توفر الأوزان الأربعة الثقيلة على القرص (`models_ready_count = 0/4` في بيئة Sandbox المعزولة).
> 3. **`field_data_calibration_readiness_pct = 0.0%`** (في الحاوية المعزولة): يقيس اكتمال معايرة المسافات الميدانية وتشغيلات التقييم الميداني.
> 4. **`deployment_classification = "READY_FOR_LAPTOP_SETUP_AND_DEMO"`**: لا يتحول إلى `"READY_FOR_PRODUCTION"` في الخادم ولا في `dashboard.html` إلا إذا بلغت النسب الثلاث جميعاً `100.0%` معاً.

| المؤشر (`Indicator`) | الحالة (`Status`) | المعنى الدقيق والدليل الموثق |
| :--- | :---: | :--- |
| **`Source Code & Structural Verification`** | **`PASS`** | الكود المصدري وبنية المشروع وملفات البناء والـ Workflow (`1 Workflow File + 16 Required Paths = 17 Verified Paths`) مكتملة ومتطابقة `100% Byte-for-Byte` (`58/58 AI` و`14/14 LAB`؛ `SOURCE_AND_CI_PREFLIGHT_PREPARATION_PERCENT = 100.0%`). |
| **`Unit & Security Tests`** | **`PASS`** | اجتازت جميع اختبارات الوحدة والأمان (`234/234` في `MERSAD AI` بالوضع القياسي ووضع `MERSAD_BLOCK_SKLEARN=1`، و`19/19` في `verify_integrity.py`، و`20/20` في `MERSAD LAB`، و`10/10` في التدقيق الأمني الاختراقي الحي مع `203` استعلامات SQLite معلمة). |
| **`AI-LAB Software Integration`** | **`13 PASS + 2 NOT_TESTED`** | اجتازت جميع سيناريوهات التكامل البرمجي الـ 13 (`INT-SCEN-01`..`INT-SCEN-13` شاملةً نقطة الدخول الحقيقية `main()` بـ `10/10 PASS` لدورة الحياة) مع محرك `Tesseract 5 LSTM` المستقل (`14/14 PASS`)، بينما سُجلت بوابتي `PHASE4-GATE-01` و`INT-HW-RTSP-USB` كـ `NOT_TESTED`. |
| **`Windows Native Build`** | **`NOT_TESTED`** | بناء ملفات Windows التنفيذية الخمسة (`MERSAD_AI.exe`, `MERSAD_LAB.exe`, `MERSAD_LAB_Setup_x64.exe`, `MERSAD_AI_Portable_x64.zip`, `MERSAD_LAB_Portable_x64.zip`) لم يُنفذ داخل حاوية Linux المعزولة، وهو مهيأ للتنفيذ عبر GitHub Actions (`windows-latest`) بمحفز `push` فقط. |
| **`Four Heavy Models Acceptance`** | **`NOT_TESTED`** | تحميل وقبول النماذج الأربعة الثقيلة (`YuNet`, `SFace`, `YOLOv8n`, `EasyOCR`) مسجل `NOT_TESTED` محلياً (`runtime_models_and_deps_readiness_pct = 0.0%` في الحاوية المعزولة؛ ولا يُستبدل بـ `Tesseract`). |
| **`Physical RTSP/USB Cameras`** | **`NOT_TESTED`** | اختبار الكاميرات الفيزيائية الحقيقية (`INT-HW-RTSP-USB`) مسجل `NOT_TESTED` لعدم وجود عتاد كاميرات متصل بالحاوية الافتراضية (بينما اجتاز التحقق البرمجي لمعالجة المسارات وتنقيح بيانات الاعتماد `PASS`). |
| **`Field Calibration`** | **`NOT_TESTED`** | معايرة المسافات والسرعات الميدانية وجمع عينات الوجوه والمركبات الميدانية المصرح بها مسجلة `NOT_TESTED` (`field_data_calibration_readiness_pct = 0.0%`). |
| **`Two-Hour Field Soak`** | **`NOT_TESTED`** | اختبار التحمل الميداني المتواصل لمدة ساعتين (`2-Hour Field Soak`) على عتاد Windows 10/11 الحقيقي مع الكاميرات الفيزيائية والنماذج الأربعة مسجل `NOT_TESTED`. |
| **`Production Readiness`** | **`NOT ESTABLISHED`** | الجاهزية الإنتاجية أو الميدانية غير متحققة (`NOT ESTABLISHED` — `deployment_classification = "READY_FOR_LAPTOP_SETUP_AND_DEMO"`)؛ الإصدار الحالي هو معاينة هندسية (`Preview 0.1`) جاهزة لدفع الفرع وتشغيل بناء Windows CI بعد موافقة المستخدم. |

### 2. التسلسل التاريخي لتطور اختبارات `MERSAD AI` (`selftest.py`) حتى النتيجة الحالية المعتمدة (**`234 / 234 PASS`**)

| التصنيف الزمني | المرحلة / الالتزام (`Commit SHA`) | عدد الاختبارات في `selftest.py` | الاختبارات المضافة في تلك المرحلة | ملف السجل المرجعي الموثق |
| :--- | :--- | :--- | :--- | :--- |
| **تاريخي (Historical)** | `PATCHED_SOURCE` (`3bf86f1eee49b351ac1dcf4e630c149e7d38b777`) | `136 PASS` (`0 FAIL`) | اختبارات الجولات `Rounds 1–5` + `12` اختباراً (`V7-*`) لبناء Windows | `reports_and_logs/logs/01_patched_source_selftest_std_136_pass.log` |
| **تاريخي (Historical)** | `Stage 15 Baseline` (`64b0dde9013c973261da37e21861c642679cf5eb`) | `201 PASS` (`0 FAIL`) | اختبارات المراحل `Stage 1` إلى `Stage 15` (`AUDIT-001..012`, `GAP-01..18`) | `reports_and_logs/logs/03_stage15_selftest_std_201_pass.log` |
| **تاريخي (Historical)** | `Preview 0.1 Initial Merge` (`9491bcd0` / `49e400c0`) | `225 PASS` (`0 FAIL`) | دمج السلالتين + `12` اختباراً جديداً (`PREVIEW01-*` رقم 13 إلى 24) | مرحلة الدمج الأولي (`rollback-stable-9491bcd`) |
| **تاريخي (Historical)** | `Preview 0.1 Remediation Round 1` (`4ffc147`) | `230 PASS` (`0 FAIL`) | إضافة `5` اختبارات انحدار (`#226..#230`) لإغلاق `BUG-01` إلى `BUG-06` | مرحلة الإصلاح الأولى |
| **تاريخي (Historical)** | `Preview 0.1 Remediation Round 2` (`f66ecea30069`) | `231 PASS` (`0 FAIL`) | إضافة الاختبار `#231` (`PREVIEW01-PHASE2-NONBLOCKING-BUILD-PIPELINE`) لإغلاق `BUG-07` | نقطة الرجوع `rollback-preview01-f66ecea` |
| **تاريخي (Historical)** | `Release Branch Code Commit` (`25131918a981`) | `232 PASS` (`0 FAIL`) | إضافة الاختبار `#232` (`PREVIEW01-MODEL-EVAL-GATES-AND-CI-INNOSETUP`) لإغلاق `BUG-09..11` على الفرع `release/mersad-preview-0.1` | نقطة الرجوع `v0.1.0-preview-code` |
| **تاريخي (Historical)** | `Post-Build Reconciled Commit` (`7f35cb1007a229a72ac0cd1be61fd5a81eb891bd`) | `233 PASS` (`0 FAIL`) | توسيع `#232` وإضافة الاختبار `#233` (`PREVIEW01-SAFE-EVAL-BENCHMARKS-AND-NON-DESTRUCTIVE-VERIFY`) لإغلاق `BUG-19..26` | نقطة الرجوع `audit-checkpoint-7f35cb10` |
| **النتيجة الحالية المعتمدة (Current Final)** | **`Final Runtime Audit Commit` (`edaf651321ec9ea6ba613e3ab1630bc16b11b9d5` على `fix/preview-0.1-postbuild-42273598736`)** | **`234 PASS`** (`0 SKIP, 0 FAIL`) | إضافة الاختبار **`#234`** (`PREVIEW01-MAIN-ENTRYPOINT-DYNAMIC-CAMERA-LIFECYCLE`) لإغلاق **`BUG-27`** والتحقق من دورة حياة الكاميرا الديناميكية عبر نقطة الدخول الحقيقية `main()` (10 خطوات كاملة) | `reports_and_logs/mersad_ai_selftest_log.txt`, `reports_and_logs/logs/05_preview01_ai_selftest_std_234_pass.log` & `logs/05_preview01_ai_selftest_std_234_pass.log` |

### 3. التسلسل التاريخي لتوحيد اختبارات التكامل (`integration/test_ai_lab_integration.py`) حتى النتيجة الحالية المعتمدة (**`13 PASS + 2 NOT_TESTED = 15 فحصاً`**)

| التصنيف الزمني | النسخة / السكربت | الحصيلة المسجلة | التفسير الهندسي الدقيق | ملف السجل المرجعي الموثق |
| :--- | :--- | :--- | :--- | :--- |
| **تاريخي (Historical)** | النسخة المختصرة السابقة | `7 PASS + 1 NOT_TESTED` (`8 فحوصات`) | كانت تختزل خطوات التكامل في `7` فحوصات مجمعة (`INT-E2E-01..07`) + بوابة النماذج الأربعة (`PHASE4-GATE-01`). | أُلغي الاختزال ووُحّد في السكربت القياسي أدناه |
| **تاريخي (Historical)** | نسخة السيناريوهات الـ 12 (`7f35cb1007a2`) | `12 PASS + 2 NOT_TESTED` (`14 فحصاً`) | شملت السيناريوهات `INT-SCEN-01..12` عبر `MersadEngineController` + بوابتي `PHASE4-GATE-01` و`INT-HW-RTSP-USB`. | نقطة الرجوع `audit-checkpoint-7f35cb10` |
| **النتيجة الحالية المعتمدة (Current Final)** | **`integration/test_ai_lab_integration.py` (`edaf651321ec` & `748ac0158761`)** | **`13 PASS, 0 FAIL, 2 NOT_TESTED` (`15 فحصاً`)** | ينفذ ويخرج في تشغيل واحد جميع السيناريوهات الـ 13 (`INT-SCEN-01` إلى `INT-SCEN-13-MAIN-ENTRYPOINT-LIFECYCLE` شاملةً نقطة الدخول الحقيقية `main()` = **`13/13 PASS`**) + بوابتي البيئة والعتاد (`PHASE4-GATE-01` للنماذج الأربعة الثقيلة = **`NOT_TESTED`**، و`INT-HW-RTSP-USB` للكاميرات الفيزيائية = **`NOT_TESTED`**). | `reports_and_logs/ai_lab_integration_log.txt` & `reports_and_logs/ai_lab_integration_results.json` |

## سجل التنفيذ الفعلي الموحد من الالتزام النهائي (`reports_and_logs/ai_lab_integration_log.txt` / `logs/10_preview01_ai_lab_integration_real_engine.log`)
```text
========================================================================================
  MERSAD PREVIEW 0.1 — Phase 4: Unified 13-Scenario & 2-Gate End-to-End Integration
========================================================================================
2026-11-07 16:33:04,127 [INFO] mersad: AUDIT [registry vehicle added] عدن-12345 status=wanted by 127.0.0.1
  [NOT_TESTED] [PRIMARY_REAL_MODELS_E2E     ] PHASE4-GATE-01: Primary pipeline `LAB -> MJPEG -> OpenCV -> YOLOv8n -> Plate -> EasyOCR -> Registry -> Alert -> SQLite -> Audit` -- Blocked in offline Linux sandbox (Tesseract NOT substituted for EasyOCR acceptance): YOLOv8n load failed: ModuleNotFoundError: No module named 'ultralytics'; EasyOCR load failed: ModuleNotFoundError: No module named 'easyocr'
[ WARN:0@1.469] global cap_v4l.cpp:913 open VIDEOIO(V4L2:/dev/video0): can't open camera by index
[ERROR:0@1.469] global obsensor_uvc_stream_channel.cpp:158 getStreamChannelGroup Camera index out of range
  [NOT_TESTED] [PHYSICAL_CAMERA_HARDWARE    ] INT-HW-RTSP-USB: Physical RTSP IP camera & USB webcam hardware capture -- No physical USB/RTSP camera attached in sandbox (usb_0_status=FAIL, released=True); software RTSP redaction verified ('rtsp://admin:***@192.168.1.50:554/h264')
  [PASS      ] [INDEPENDENT_TESSERACT_E2E   ] INT-SCEN-01: Start MERSAD AI server, SQLite database & token auth guard -- unauth_status=403, auth_status=200, journal_mode=wal
  [PASS      ] [INDEPENDENT_TESSERACT_E2E   ] INT-SCEN-02: Start MERSAD LAB server & initialize 4 virtual cameras -- health=healthy, virtual_cameras=4
2026-11-07 16:33:05,099 [INFO] mersad: AUDIT [camera added] LAB_CAM1 src=http://127.0.0.1:52548/stream/cam1.mjpg by 127.0.0.1
2026-11-07 16:33:05,116 [INFO] mersad: AUDIT [session start] LAB_CAM1
2026-11-07 16:33:05,135 [INFO] mersad: AUDIT [camera added] LAB_CAM2 src=http://127.0.0.1:52548/stream/cam2.mjpg by 127.0.0.1
2026-11-07 16:33:05,159 [INFO] mersad: AUDIT [session start] LAB_CAM2
  [PASS      ] [INDEPENDENT_TESSERACT_E2E   ] INT-SCEN-03: Add virtual cameras LAB_CAM1 & LAB_CAM2 via m.wire() -> spawn real AI reader & inference threads (INT-E2E-01) -- LAB_CAM1 worker_spawned=True, LAB_CAM2 worker_spawned=True
  [PASS      ] [INDEPENDENT_TESSERACT_E2E   ] INT-SCEN-04: Stream live MJPEG test video from MERSAD LAB -- status=200, frames_delivered=4, bytes=99106
2026-11-07 16:33:09,175 [INFO] mersad: AUDIT [sighting] id=1 عدن-12345 LAB_CAM1 unknown dir=ثابت/عبور نسبي في الإطار conf=0.95
2026-11-07 16:33:09,683 [INFO] mersad: AUDIT [sighting] id=2 صنعاء-48210 LAB_CAM2 unknown dir=ثابت/عبور نسبي في الإطار conf=0.96
  [PASS      ] [INDEPENDENT_TESSERACT_E2E   ] INT-SCEN-05: Feed video stream into CV engine & compute real-time frame quality metrics -- LAB_CAM1 frames=53, detections=4, brightness=75.73, res=640x480
  [PASS      ] [INDEPENDENT_TESSERACT_E2E   ] INT-SCEN-06: Autonomous vehicle/plate detection, pixel OCR & mandatory human-review alert governance (INT-E2E-02) -- Sightings=[('LAB_CAM1', 'عدن-12345', 0.95), ('LAB_CAM2', 'صنعاء-48210', 0.96)], alerts=1, requires_human_review=True, ocr_engine=Tesseract-5-LSTM-Real-Pixel-OCR
  [PASS      ] [INDEPENDENT_TESSERACT_E2E   ] INT-SCEN-07: Multi-frame trajectory tracking & alert deduplication across continuous frames (INT-E2E-03) -- LAB_CAM1 frames 54->67, alerts for عدن-12345: 1 (expected 1)
  [PASS      ] [INDEPENDENT_TESSERACT_E2E   ] INT-SCEN-08: Deliver live detection, camera health, analytics & blurred evidence to Dashboard API -- stats=200, cameras=200, analytics=200, last_plate=عدن-12345, evidence_jpeg=True
  [PASS      ] [INDEPENDENT_TESSERACT_E2E   ] INT-SCEN-09: Persist sightings, alerts, camera status history & audit records in SQLite -- sightings=2, alerts=2, camera_status_history=4, audit=11
  [PASS      ] [INDEPENDENT_TESSERACT_E2E   ] INT-SCEN-10: Save logs, analytics CSV export & verify HMAC-SHA256 audit chain and secret redaction -- csv_bytes=1080, log_bytes=755, token_leaked=False, verify='Audit chain OK (11 records)'
[http @ 0x7ece800055c0] Stream ends prematurely at 1780860, should be 18446744073709551615
[ WARN:5@8.301] global cap.cpp:215 open VIDEOIO(FFMPEG): backend is generally available but can't be used to capture by name
2026-11-07 16:33:12,460 [INFO] mersad: AUDIT [camera reconnected] LAB_CAM1
  [PASS      ] [INDEPENDENT_TESSERACT_E2E   ] INT-SCEN-12: Camera disconnect isolation (LAB_CAM2 online) & automatic reconnection recovery (INT-E2E-04 & INT-E2E-05) -- disconnect_state=reconnecting, LAB_CAM2_continuity=online, reconnected_state=online, reconnect_count=1
2026-11-07 16:33:14,423 [INFO] mersad: AUDIT [camera removed] LAB_CAM2 by 127.0.0.1
2026-11-07 16:33:14,892 [INFO] mersad: AUDIT [session start] LAB_CAM1
  [PASS      ] [INDEPENDENT_TESSERACT_E2E   ] INT-SCEN-11: Stream health (FROZEN/OCCLUDED), safe active camera removal, engine stop/restart & audit persistence (INT-E2E-06 & INT-E2E-07) -- frozen=FROZEN_STREAM, cam2_removed=True, audit_rows=13->14, verify='Audit chain OK (14 records)'
2026-11-07 16:33:15,908 [WARNING] mersad: Running in degraded preview mode without face ONNX weights: Model directory 'models' is not writable
2026-11-07 16:33:15,914 [WARNING] mersad: Running in degraded preview mode with Tesseract 5 LSTM fallback OCR: No module named 'easyocr'
2026-11-07 16:33:15,916 [WARNING] mersad: Vehicle/truck detection off: No module named 'ultralytics'
Vehicle/truck detection off: No module named 'ultralytics'
2026-11-07 16:33:16,034 [WARNING] mersad: Face models unavailable in degraded preview mode: YuNet model failed pre-load SHA-256 verification: file_missing_or_symlink
Telegram alerts off (set TELEGRAM_TOKEN and TELEGRAM_CHAT_ID to enable).
2026-11-07 16:33:16,054 [INFO] mersad: AUDIT [session start] BOOT_CAM1

Dashboard URL (Local only — 127.0.0.1):
  http://127.0.0.1:17473/?k=main_ep_int_token_2026
  (لتفعيل الوصول من الجوالات على نفس الشبكة استخدم RUN_LAN.bat أو --host 0.0.0.0)

Faces are matched ONLY against volunteers who gave consent. Bystander faces in evidence photos are blurred.
2026-11-07 16:33:16,133 [INFO] mersad: AUDIT [camera added] LAB_DYN_CAM2 src=http://127.0.0.1:52548/stream/cam2.mjpg by 127.0.0.1
2026-11-07 16:33:16,153 [INFO] mersad: AUDIT [session start] LAB_DYN_CAM2
2026-11-07 16:33:17,644 [INFO] mersad: AUDIT [camera removed] LAB_DYN_CAM2 by 127.0.0.1
2026-11-07 16:33:17,690 [INFO] mersad: AUDIT [camera added] LAB_DYN_CAM3 src=http://127.0.0.1:52548/stream/cam3.mjpg by 127.0.0.1
2026-11-07 16:33:17,722 [INFO] mersad: AUDIT [session start] LAB_DYN_CAM3
  [PASS      ] [INDEPENDENT_TESSERACT_E2E   ] INT-SCEN-13-MAIN-ENTRYPOINT-LIFECYCLE: Natural main() entry point dynamic camera lifecycle (connect_ai -> worker_spawned=true -> MJPEG & inference -> remove without SIGSEGV -> add 2nd camera) -- add1_spawned=True, seq2=8, det2=1, stopped=True, cap_closed=True, add2_spawned=True, seq3=8, det3=1
2026-11-07 16:33:18,787 [INFO] mersad: AUDIT [sighting] id=3 عدن-12345 BOOT_CAM1 unknown dir=LAB_CAM1 ➔ BOOT_CAM1 (ثابت/عبور نسبي في الإطار) conf=0.95
2026-11-07 16:33:18,915 [INFO] mersad: AUDIT [session end] BOOT_CAM1
2026-11-07 16:33:18,920 [INFO] mersad: AUDIT [session end] LAB_DYN_CAM3
========================================================================================
  SUMMARY: 13 PASS, 0 FAIL, 2 NOT_TESTED (Total: 15)
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
- **فحص `SHA256SUMS.txt`:** جميع الملفات المدرجة (**جميع الملفات المدرجة في SHA256SUMS.txt**) اجتازت فحص `sha256sum -c SHA256SUMS.txt` بحالة `OK`.
- **فحص `verify_integrity.py`:** اجتاز فحص سلامة حزمة `MERSAD_AI_Preview_0.1` (**19/19 ملفاً أساسياً** حاضراً ومطابقاً للبصمة).

---

## 2. نتائج تشغيل جميع اختبارات الوحدة والأمان والتكامل (`Test Suites Execution`)

تم تشغيل جميع حزم الاختبار الفعلية عبر `execute_bash` وتوثيق مخرجاتها:

| حزمة الاختبار | الأمر المنفَّذ | النتيجة | التفاصيل والمخرجات الفعلية |
|---|---|---|---|
| **اختبارات الوحدة والأمان والتكامل لـ MERSAD AI (الوضع القياسي)** | `python3 -u MERSAD_AI_Preview_0.1/selftest.py` | **`234 PASS / 0 FAIL / 0 SKIP`** | اجتازت جميع الـ 234 فحصاً (تطبيع اللوحات، مطابقة السجل، التتبع، الخصوصية وتعمية الوجوه، قاعدة البيانات، سلسلة التدقيق HMAC، التزامن بين العمليات، التشفير، ومقاييس التقييم). |
| **اختبارات MERSAD AI (مع حظر `scikit-learn` لاختبار `StatForest`)** | `MERSAD_BLOCK_SKLEARN=1 python3 -u MERSAD_AI_Preview_0.1/selftest.py` | **`234 PASS / 0 FAIL / 0 SKIP`** | تم التحقق من عمل محرك كشف الشذوذ الإحصائي البديل `StatForest` بكفاءة تامة دون الاعتماد على `scikit-learn`. |
| **اختبارات الوظائف والأمان لـ MERSAD LAB** | `python3 -u MERSAD_LAB_Preview_0.1/test_lab.py` | **`20 PASS / 0 FAIL`** | اجتازت الفحوصات الوظيفية الـ 8 (`LAB-01`..`LAB-08`) والفحوصات الأمنية واختبارات التحمل الـ 12 (`LAB-SEC-01`..`LAB-SEC-12`). |
| **اختبار التكامل الشامل بين AI و LAB (`test_ai_lab_integration.py`)** | `python3 -u integration/test_ai_lab_integration.py` | **`13 PASS / 0 FAIL / 2 NOT_TESTED (Total: 15)`** | البوابة `PHASE4-GATE-01` مصنفة `NOT_TESTED` في بيئة Linux المعزولة لعدم توفر `ultralytics`/`torch`/`easyocr` وأوزان النماذج، بينما اجتازت السيناريوهات الـ 13 الموحدة (`INT-SCEN-01`..`INT-SCEN-13` شاملةً `INT-E2E-01`..`INT-E2E-07`) بنسبة 100% باستخدام المحرك الفعلي `MersadEngineController` وقارئ البكسلات الحقيقي `Tesseract 5 LSTM`. |
| **اختبار السيناريوهات الـ 12 ومصادر البث (`run_full_12_scenarios_and_sources.py`)** | `python3 -u run_full_12_scenarios_and_sources.py` | **`12/12 PASS` + `1/1 PASS (ملفات فيديو محلية)` + `2/2 PASS (تحقق برمجي فقط لـ RTSP/USB)` + `0/2 NOT_TESTED (كاميرات RTSP/USB فيزيائية — INT-HW-RTSP-USB)`** | اختبار تكامل شامل نفّذ السيناريوهات الـ 12 بالكامل واختبر ملفات الفيديو المحلية وتدفقات `HTTP MJPEG` الافتراضية والتحقق البرمجي من مسارات `RTSP` و`USB` (دون توصيل كاميرات `RTSP` أو `USB` فيزيائية حقيقية: `INT-HW-RTSP-USB = NOT_TESTED`). |
| **فحص وتقييم نماذج الذكاء الاصطناعي (`evaluate_ai_models.py`)** | `python3 -u integration/evaluate_ai_models.py` | **`NOT_TESTED` (النماذج الـ 4) / `14/14 PASS` (Tesseract: `6` مرجعية + `4` اصطناعية + `4` بث حي)** | النماذج الأربعة (`YuNet`, `SFace`, `YOLOv8n`, `EasyOCR`) غير محملة على القرص في البيئة المعزولة (`MODEL_MISSING`)؛ بينما حقق المسار المستقل `Tesseract 5 LSTM` مطابقة **6/6** على لوحات `eval_benchmarks/plates` و**4/4** على المشاهد الافتراضية و**4/4** على بث MJPEG الحي (`14/14` إجمالاً) بمتوسط زمن استجابة `357.99 ms`. |
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
  - تقرير الجاهزية `/api/readiness` (`SOURCE_AND_CI_PREFLIGHT_PREPARATION_PERCENT` — `BUG-39`): يعيد الحقل الهندسي البرمجي `overall_engineering_readiness_pct = 100.0%` (`code_and_security: 100%`, `windows_build_and_packaging: 100%`, `field_calibration_and_eval_tooling: 100%` — ويعبر حصراً عن جاهزية الكود وأدوات التقييم وإعداد البناء `SOURCE_AND_CI_PREFLIGHT_PREPARATION_PERCENT`)، بينما يسجل في نفس التقرير `runtime_models_and_deps_readiness_pct = 0.0%` (`models_ready_count = 0/4` في الحاوية المعزولة) و`field_data_calibration_readiness_pct = 0.0%` ويضبط `deployment_classification = "READY_FOR_LAPTOP_SETUP_AND_DEMO"` (وليس `"READY_FOR_PRODUCTION"`).
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

### السيناريو 13: دورة حياة الكاميرات الديناميكية عبر نقطة الدخول الطبيعية `main()` (`INT-SCEN-13-MAIN-ENTRYPOINT-LIFECYCLE` — إغلاق `BUG-27`)
- **الإجراء المنفذ (الخطوات العشر كاملة عبر نقطة الدخول الحقيقية `main()` المستخدمة في `MERSAD_AI.exe`):**
  1. تشغيل `MERSAD AI` عبر استدعاء الدالة الحقيقية `mersad_live.main()` (وليس إنشاء `MersadEngineController` يدوياً) على منفذ محلي مع كاميرا إقلاع أولية `BOOT_CAM1`.
  2. تشغيل خادم `MERSAD LAB` (`LabServerController`) وتجهيز الكاميرات الافتراضية الأربع.
  3. إضافة كاميرا ديناميكية جديدة `LAB_DYN_CAM2` من المختبر عبر `POST /api/integration/connect_ai`.
  4. التحقق من أن استجابة `MERSAD AI` تتضمن صراحةً `worker_spawned=true` (`ai_response.worker_spawned == True`).
  5. التحقق من أن خيط قراءة الكاميرا (`cam_reader_LAB_DYN_CAM2`) وخيط الاستدلال (`cam_infer_LAB_DYN_CAM2`) قد بدءا فعلياً في الخلفية (`is_alive() == True`).
  6. التحقق من تصاعد عداد الإطارات `latest_frame_seq` ووصول إطارات `MJPEG` الصالحة (`FFD8...FFD9`) من المسار `/stream.mjpg?cam=LAB_DYN_CAM2`.
  7. التحقق من تنفيذ دورة الاستدلال وتحديث قياسات حالة الكاميرا في `STATUS["cameras"]["LAB_DYN_CAM2"]` كما هو موثق حرفياً في `reports_and_logs/logs/20_main_entrypoint_dynamic_camera_lifecycle.json`: (`status = "online"`, `frames = 7`, `detections = 1`, `brightness = 75.7`, `contrast = 40.51`, `sharpness = 1210.71`, `resolution = "640x480"`, `fps = 0.0`, `last_plate = null` — حيث تم إثبات تشغيل الاستدلال وتحديث القياسات الحية، بينما لم يُثبت تمييز لوحة `OCR` في اختبار دورة الحياة السريع هذا).
  8. حذف الكاميرا `LAB_DYN_CAM2` أثناء التشغيل عبر `POST /api/cameras/remove`.
  9. التحقق من توقف خيطي القراءة والاستدلال (`not is_alive()`) وإغلاق `VideoCapture` (`cap is None`) بأمان تام دون أي انهيار `SIGSEGV`.
  10. إضافة كاميرا ثانية `LAB_DYN_CAM3` بعد الحذف عبر `POST /api/integration/connect_ai` والتحقق من `worker_spawned=true` وتدفق `MJPEG` (`latest_frame_seq = 8`, `mjpeg_ok = true`) وتنفيذ دورة الاستدلال وتحديث قياسات الكاميرا (`status = "online"`, `frames = 7`, `detections = 1`, `brightness = 75.88`, `contrast = 40.8`, `sharpness = 1178.67`, `resolution = "640x480"`, `fps = 0.0`, `last_plate = null` — دون ادعاء قراءة لوحة `OCR` في اختبار دورة الحياة هذا).
- **ملاحظة الفصل المنهجي الصارم (`BUG-31`)**: يحتفظ هذا الاختبار بنتيجة **`10 / 10 PASS` لدورة حياة الكاميرا الديناميكية (`Dynamic Camera Lifecycle`)** مع فصلها التام عن اختبارات تمييز اللوحات (`OCR Plate Recognition`)؛ كما يظل التقييم المستقل لمحرك `Tesseract 5 LSTM` مفصولاً تماماً عن بوابة قبول النموذج الأساسي `EasyOCR` التي تبقى بحالة **`NOT_TESTED`** حتى يُنفّذ اختبار `Ground-Truth` الفعلي للنموذج.
- **النتيجة:** **`PASS` (`10 / 10 Lifecycle Steps`)** (مُثبت في `reports_and_logs/logs/20_main_entrypoint_dynamic_camera_lifecycle.json` و`INT-SCEN-13-MAIN-ENTRYPOINT-LIFECYCLE` وفي الاختبار `#234` `PREVIEW01-MAIN-ENTRYPOINT-DYNAMIC-CAMERA-LIFECYCLE` داخل `selftest.py`).

---

## 4. فحص دعم RTSP و USB وملفات الفيديو (Media Sources Verification — `BUG-32 Reconciled`)

> **فصل منهجي صارم بين التحقق البرمجي (`Software Verification`) واختبار العتاد الفيزيائي (`Physical Hardware Testing — BUG-32`)**:
> يفصل الجدول أدناه بدقة تامة بين ما جرى التحقق منه برمجياً عبر الاختبارات الآلية والمحاكاة (`PASS — تحقق برمجي فقط`) وبين ما لم يُختبر بعد على كاميرات `RTSP` أو `USB` فيزيائية حقيقية في بيئة الاختبار المعزولة (`NOT_TESTED — بوابة INT-HW-RTSP-USB = NOT_TESTED`). كما تُستخدم صيغ نائبة آمنة (`<REDACTED_TEST_PASSWORD>`) في جميع الأمثلة التوثيقية دون أي كلمات مرور نصية قابلة للاستخدام التشغيلي.

| نوع المصدر | التحقق البرمجي (`Software Verification`) | اختبار العتاد الفيزيائي (`Physical Device Testing — INT-HW-RTSP-USB`) | المخرجات والتفاصيل الهندسية الموثقة |
|---|---|---|---|
| **1. ملفات الفيديو المحلية (`Video Files` — `.avi`, `.mp4`)** | **`PASS` (مختبر فعلياً على ملف فيديو محلي مولد اصطناعياً)** | **غير منطبق (ملف برمجي محلي)** | تم توليد ملف فيديو حقيقي `synthetic_taiz_test.avi` (`546,960 بايت`، `25 إطاراً`، أبعاد `640x480`، `15 FPS`):<br>1) **في MERSAD LAB (`POST /api/analyze/video`):** قرأ الخادم الـ 25 إطاراً خلال `0.453s` وأعاد `status_code: 200`, `brightness: 75.9`, `contrast: 40.75`, `sharpness: 1063.22`, `quality_grade: "ممتازة (Excellent)"`.<br>2) **في MERSAD AI (`add_camera("VIDEO_FILE_CAM", vid_path)`):** فتح `_open_camera_capture` ملف الفيديو بنجاح وقرأ الإطارات وحلل جودتها (`brightness: 75.89`, `sharpness: 1064.27`) ونفذ الاستدلال عليها مع التعامل الآمن مع نهاية الملف (`eof`). |
| **2. تدفقات الكاميرات الافتراضية (`HTTP MJPEG Virtual Streams` — `MERSAD LAB`)** | **`PASS` (مختبر فعلياً عبر الشبكة المحلية `127.0.0.1`)** | **بث افتراضي محلي (`VirtualCamera` ثنائي الأبعاد)** | تم التحقق الفعلي من استقبال إطارات `HTTP MJPEG` الحية عبر `OpenCV VideoCapture` من `MERSAD LAB` (`LAB_CAM1..4` و`LAB_DYN_CAM2..3`)، واكتشاف انقطاع البث (`HTTP 503` -> `reconnecting`)، وإعادة الاتصال التلقائي التدريجي (`_compute_reconnect_backoff` -> `reconnect_count=1` في `INT-SCEN-12`). |
| **3. تدفقات كاميرات الشبكة (`RTSP / RTSPS`)** | **`PASS` (تحقق برمجي فقط — `Software-Only Verification`)** | **`NOT_TESTED` (لم يُختبر على كاميرا `RTSP` فيزيائية حقيقية؛ `INT-HW-RTSP-USB = NOT_TESTED`)** | **أ) ما تم التحقق منه برمجياً (`PASS`):**<br>1) **مهل الاتصال والقراءة المحدودة:** يضبط `_open_capture_with_timeouts()` متغير البيئة `OPENCV_FFMPEG_CAPTURE_OPTIONS="rtsp_transport;tcp\|stimeout;5000000\|rw_timeout;5000000"` ويمرر `cv2.CAP_FFMPEG` مع `CAP_PROP_OPEN_TIMEOUT_MSEC = 5000` و `CAP_PROP_READ_TIMEOUT_MSEC = 5000` (مُثبت عبر `Mock VideoCapture` في الاختبار `V7-RTSP-TIMEOUTS`).<br>2) **حجب وعزل بيانات الاعتماد:** عند تمرير صيغة رابط اختبارية غير صالحة للاستخدام التشغيلي `rtsp://<TEST_USER>:<REDACTED_TEST_PASSWORD>@<CAMERA_IP>:554/<STREAM_PATH>` عبر `save_cfg()` و`_redact_cam_source()`، يتم إخفاء كلمة المرور في `mersad_config.json` والسجلات وواجهات API لتصبح `rtsp://<TEST_USER>:***@<CAMERA_IP>:554/<STREAM_PATH>` بينما يُعزل الرابط في `.mersad_secrets.json` بصلاحيات `0600` (و`icacls` على Windows)؛ علماً بأن جميع اختبارات الحجب تستخدم سلاسل نصية وهمية اصطناعية (`Synthetic Dummy Strings`) ولا تستخدم أي بيانات اعتماد حقيقية (`P1-D`, `STAGE2-GAP07`, `STAGE9-OBS01`, `SEC-AUDIT-06`).<br>**ب) ما لم يُختبر فيزيائياً (`NOT_TESTED`):** لم يتم الاتصال بكاميرا `RTSP` فيزيائية حقيقية أو استقبال إطارات `RTSP` حقيقية منها أو اختبار انقطاع الشبكة الفيزيائي واستعادته (`INT-HW-RTSP-USB = NOT_TESTED`). |
| **4. كاميرات الويب المحلية (`USB Webcams` — `"0"`, `"1"`)** | **`PASS` (تحقق برمجي فقط — `Software-Only Verification`)** | **`NOT_TESTED` (لم يُختبر على كاميرا `USB` فيزيائية حقيقية؛ `INT-HW-RTSP-USB = NOT_TESTED`)** | **أ) ما تم التحقق منه برمجياً (`PASS`):** يحول `_open_camera_capture()` المعرفات الرقمية النصية (`"0"`, `"1"`) تلقائياً إلى أعداد صحيحة (`int(source) if str(source).isdigit() else source`) ويستدعي `cv2.VideoCapture(0)`؛ كما تفحص أداة `check_install.py --camera --json` (`check_camera_source(source_override="0")`) المنفذ المحلي وتتعامل بأمان مع عدم وجود كاميرا متصلة (`usb_0_status=FAIL`، `can't open camera by index`) مع ضمان استدعاء `cap.release()` (`released=True`) في كتلة `finally` والدخول في وضع `reconnecting` دون إسقاط الخدمة (`STAGE2-GAP07` و`INT-HW-RTSP-USB`).<br>**ب) ما لم يُختبر فيزيائياً (`NOT_TESTED`):** لم يتم توصيل كاميرا `USB` فيزيائية حقيقية أو فتحها بنجاح أو استقبال إطارات منها أو اختبار استقرارها وإغلاقها وإعادة توصيلها (`INT-HW-RTSP-USB = NOT_TESTED`). |

---

## 5. فحص جاهزية حزم Windows x64 وسجل النتائج التاريخية المغلقة (Packaging Audit & Historical Findings — Closed in Preview 0.1)

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

### ثانياً: سجل نتائج التدقيق التاريخية وإغلاقها الهندسي النهائي (`Historical Audit Findings — Closed in Preview 0.1`)

> **تنبيه توثيقي (`Documentation Reconciliation — BUG-28`)**: يوثق هذا القسم كمرجع تاريخي العيوب البرمجية التي اكتُشفت خلال جولات التدقيق وتجارب التكامل، وكيف تم **إغلاقها جميعاً بالكامل (`CLOSED / PASS`)** مع تحديد رقم الالتزام (`Commit SHA`) الذي أغلق كل عيب واختبار الانحدار الذي يثبت إغلاقه. **لا يوجد أي عيب من هذه العيوب مفتوحاً في الالتزام النهائي `edaf651321ec9ea6ba613e3ab1630bc16b11b9d5`.**

| المعرّف | الوصف التاريخي للملاحظة المكتشفة أثناء التدقيق | الحالة الحالية | التزام الإغلاق الفعلي (`Closing Commit SHA`) | الإصلاح الهندسي المنفذ واختبار الانحدار المثبت |
| :--- | :--- | :---: | :--- | :--- |
| **`BUG-01`** (تاريخي — أُغلق) | إعادة تعيين القاموس `bus.post = { ... }` في السطر `3527` من `wire()` كانت تمسح مساري `/api/cameras/add` و`/api/cameras/remove` المضافين قبلها بـ 10 أسطر (`HTTP 404`). | **`CLOSED` (`PASS`)** | `25131918a981ac2ac37923d4c738d9f93cdcbc5b` (`release/mersad-preview-0.1`) | دُمج مسارا `/api/cameras/add` و`/api/cameras/remove` مباشرة داخل تعريف `bus.post` في `wire()`؛ مُثبت باختبار `PREVIEW01-WIRE-CAMERAS-POST` و`INT-SCEN-03`. |
| **`BUG-27`** (تاريخي — أُغلق) | في نقطة الدخول الطبيعية `main()` (`mersad_live.py`)، كانت الكاميرات تُدار في قاموس محلي `cam_states` دون تعيين `_ACTIVE_ENGINE_CONTROLLER`، وكان الخادم `start_server()` يبدأ قبل تهيئة المتحكم، مما كان يجعل `add_camera_runtime()` تعيد `worker_spawned=False` عند التشغيل عبر `main()`. كما كان استدعاء `import pytesseract` داخل الخيوط الخلفية يؤخر إنهاء الخيط أثناء `remove_camera_runtime()`. | **`CLOSED` (`PASS`)** | **`edaf651321ec9ea6ba613e3ab1630bc16b11b9d5`** (`fix/preview-0.1-postbuild-42273598736`) | تم بناء الصنف `_MainLoopRuntimeController` داخل `main()` وربطه بـ `_ACTIVE_ENGINE_CONTROLLER` قبل تشغيل `start_server()`، وتخصيص `cam_stop_ev` مستقل لكل كاميرا، واستخدام لقطة محمية بـ `_RUNTIME_STATE_LOCK` في حلقة `main()` مع إبقاء الخدمة حية عند بقاء `0` كاميرات، وإلغاء حجب `import pytesseract`؛ مُثبت باختبار `#234` (`PREVIEW01-MAIN-ENTRYPOINT-DYNAMIC-CAMERA-LIFECYCLE`) و`INT-SCEN-13-MAIN-ENTRYPOINT-LIFECYCLE`. |
| **`BUG-02`** (تاريخي — أُغلق) | حالة سباق (`Use-After-Free` / `SIGSEGV`) في `remove_camera_runtime()` عند استدعاء `cap.release()` قبل انتهاء خيط القراءة `_camera_reader_worker`. | **`CLOSED` (`PASS`)** | `25131918a981ac2ac37923d4c738d9f93cdcbc5b` & `edaf651321ec9ea6ba613e3ab1630bc16b11b9d5` | ضبط `stop_ev.set()` وتفريغ `infer_queue` وانتظار `reader_thread.join()` و`infer_thread.join()` قبل حيازة `with st["lock"]:` واستدعاء `cap.release()`؛ مُثبت باختبار `PREVIEW01-SAFE-CAMERA-REMOVE-NO-SEGFAULT` و`INT-SCEN-11` و`INT-SCEN-13`. |
| **`BUG-03`** (تاريخي — أُغلق) | عدم تحويل المسار النسبي `--cleanroom-dir` إلى مسار مطلق عبر `.resolve()` في `tools/compare_original_vs_cleanroom_lab.py`، وفصل المرحلة 2 غير المانعة للبناء (`BUG-07`). | **`CLOSED` (`PASS`)** | `25131918a981ac2ac37923d4c738d9f93cdcbc5b` (`release/mersad-preview-0.1`) | تحويل جميع المسارات إلى مطلقة عبر `.resolve()` وجعل غياب الأرشيف الأصلي `ed7b8f72` يسجل `BLOCKED` دون إيقاف بناء `Preview 0.1`؛ مُثبت باختبار `PREVIEW01-PHASE2-NONBLOCKING-BUILD-PIPELINE`. |
| **`BUG-04`** (تاريخي — أُغلق) | توليد مشغلات `RUN.bat` و`RUN_LAN.bat` الخاصة بـ `MERSAD_AI.exe` وإزالة `opencv-python-headless` وتوحيد `pyinstaller==6.11.1` وتثبيت `Inno Setup` تلقائياً في CI (`BUG-11`). | **`CLOSED` (`PASS`)** | `25131918a981ac2ac37923d4c738d9f93cdcbc5b` (`release/mersad-preview-0.1`) | توليد مشغلات التوزيع المخصصة لـ `MERSAD_AI.exe` وإزالة `opencv-python-headless` وتوحيد `pyinstaller==6.11.1`؛ مُثبت باختبار `PREVIEW01-UNIFIED-WIN-BUILD-LAUNCHERS` و`PREVIEW01-MODEL-EVAL-GATES-AND-CI-INNOSETUP`. |

---

## 6. الخلاصة النهائية وحالة الإغلاق الهندسي

1. **جاهزية التكامل الوظيفي والأمني ودورة الحياة الديناميكية عبر `main()`:** اجتازت جميع اختبارات الوحدة والأمان (**`234 / 234 PASS`** في `MERSAD AI` بالوضعين القياسي وبدون `sklearn`، و**`20 / 20 PASS`** في `MERSAD LAB`) وجميع السيناريوهات الوظيفية الـ 13 لاختبار التكامل الشامل (**`13 / 13 PASS`** شاملةً `INT-SCEN-13-MAIN-ENTRYPOINT-LIFECYCLE` عبر نقطة الدخول الطبيعية `main()`) بالإضافة إلى الاختبار الفعلي لملفات الفيديو المحلية وتدفقات `HTTP MJPEG` الافتراضية، والتحقق البرمجي من مسارات `RTSP` و`USB` (مع بقاء اختبار كاميرات `RTSP` و`USB` الفيزيائية الحقيقية في البوابة `INT-HW-RTSP-USB` بحالة `NOT_TESTED` محلياً).
2. **الأوزان الثقيلة والتجميع النهائي لـ Windows:** نظراً لأن بيئة الاختبار الحالية هي حاوية Linux معزولة عن الإنترنت، فإن تحميل وتشغيل النماذج الأربعة الثقيلة (`YOLOv8n`, `EasyOCR`, `YuNet`, `SFace`) وبناء ملفات `.exe` الخمسة عبر PyInstaller و Inno Setup مسجلة بأمانة كـ **`NOT_TESTED` محلياً** ومهيأة للتنفيذ على GitHub Actions (`windows-latest`) من الفرع المعتمد `fix/preview-0.1-postbuild-42273598736` عند الالتزام `edaf651321ec9ea6ba613e3ab1630bc16b11b9d5`.
3. **تأكيد إغلاق كافة ملاحظات التدقيق والمطابقة (`Audit & Documentation Closure Summary — BUG-01..BUG-49`):** جميع العيوب البرمجية المكتشفة في جولات التدقيق والتكامل وما بعد البناء (`BUG-01` إلى `BUG-27`) مغلقة برمجياً ومثبتة باختبارات انحدار آلية داخل التزام الكود النهائي `edaf651321ec9ea6ba613e3ab1630bc16b11b9d5` (و`748ac0158761812a6fff63ff6fe626b9df8c252b` للمختبر)، وجميع ملاحظات مطابقة التوثيق والقوائم التوصيفية والأرشيف (`BUG-28` إلى `BUG-45`) مغلقة ومتحقق منها آلياً في طبقة مخرجات الإصدار (`Release Artifacts Layer`).

