# تقرير البناء والتوزيع الشامل — MERSAD AI V7.1 Stage 15 (`MERSAD_AI_V7_1_FINAL_BUILD_PACKAGE.zip`)

يُوثّق هذا التقرير ما تم إنجازه لتجهيز وبناء **MERSAD AI V7.1 — Stage 15** كنسخة تنفيذية لنظام `Windows 10/11 x64` (`MERSAD_AI.exe`) مع جميع ملفات `DLL` والنماذج الأربعة والموارد اللازمة، ومعالجة جميع نقاط المراجعة الهندسية والأمنية، إضافةً إلى نتائج الاختبارات الفعلية المنفذة على بيئة Linux وتلك المبرمجة للتنفيذ الآلي على Windows عبر `GitHub Actions` أو البناء المحلي.

---

## 1. ملخص ما تم إنجازه فعلياً ومعالجة ملاحظات المراجعة (Stage 15 Final Build Remediation)

1. **إصلاح منطق تسجيل Workflow والتشغيل المتكرر ومنع البناء المزدوج في (`PUSH_TO_GITHUB_AND_BUILD.bat`)**:
   - **دعم التشغيل الأول والتشغيل المتكرر فوق تاريخ المستودع الفعلي**: بدلاً من تنفيذ `git init` محلي يؤدي إلى خطأ `refusing to merge unrelated histories` عند وجود تاريخ سابق في المستودع البعيد، ينشئ السكربت نسخة عمل متزامنة (`.git_build_worktree`) عبر `git clone` (في التشغيل الأول) أو `git fetch origin --prune` (في التشغيل المتكرر)، ثم ينشئ أو يحدث فرع البناء `release/v7.1-stage15-win-x64` فوق تاريخ الفرع البعيد الفعلي (`origin/release/v7.1-stage15-win-x64` أو `origin/<default_branch>`) مع فحص `git merge --ff-only` واكتشاف أي تعارضات (`git diff --diff-filter=U`) والتوقف الآمن فوراً دون استخدام `--force` نهائياً.
   - **نسخ الملفات المحدثة دون فقد أي ملفات موجودة**: ينسخ السكربت ملفات المرحلة 15 المحدثة إلى `.git_build_worktree` دون حذف أي ملفات إضافية موجودة في المستودع.
   - **إصلاح منطق تسجيل `.github/workflows/windows-build.yml` على الفرع الافتراضي**: يتحقق السكربت برمجياً عبر `git cat-file -e origin/<default_branch>:.github/workflows/windows-build.yml` مما إذا كان ملف الـ Workflow موجوداً في الفرع الافتراضي (`main`/`master`). إذا لم يكن موجوداً في الفرع الافتراضي، يضيف السكربت ملف `.github/workflows/windows-build.yml` وحده في commit منفصل آمن فوق `origin/<default_branch>` دون المساس بأي ملف آخر في `main` ودون تجاوز حماية الفروع (وإذا كان الفرع الافتراضي محمياً، يعتمد تلقائياً على `push` trigger).
   - **منع تشغيل عمليتي بناء لنفس التحديث وتتبع `Run ID` المرتبط بـ `LOCAL_HEAD_SHA` حصراً**:
     - أُضيف قيد `concurrency` في `.github/workflows/windows-build.yml` لمنع تشغيل عمليتين متوازيتين على نفس الفرع.
     - يحسب السكربت بصمة الـ commit المحلي `LOCAL_HEAD_SHA` (`git rev-parse HEAD`). إذا تم دفع commit جديد، يفحص السكربت عبر `gh run list --json databaseId,headSha,status,conclusion` ما إذا كان `push` trigger قد أطلق بالفعل عملية بناء تحمل نفس `headSha == LOCAL_HEAD_SHA`، فلا يطلق `workflow_dispatch` مكرراً؛ أما إذا لم يُطلق البناء تلقائياً (مثلاً عند إعادة التشغيل على نفس الـ commit)، فيُطلقه عبر `gh workflow run` ثم يستعلم حصرياً عن الـ Run الذي يطابق `headSha == LOCAL_HEAD_SHA`، ويتحقق في الخطوة `[9/12]` من أن `RUN_HEAD_SHA == LOCAL_HEAD_SHA`.
   - **منع إعلان النجاح الكاذب والتحقق الصارم من المخرجات ورموز الخروج (`!ERRORLEVEL!`)**:
     - يتحقق السكربت بعد فك حزمة الـ Artifact من وجود `MERSAD_AI_RELEASE\MERSAD_AI\MERSAD_AI.exe` وجميع النماذج الأربعة (`yunet.onnx`, `sface.onnx`, `yolov8n.pt`, وأوزان `models\easyocr\*.pth` بعدد لا يقل عن ملفين) وملفات `.dll` المجمّعة (`>= 5` ملفات DLL) وملفات التشغيل (`RUN.bat`, `RUN_LAN.bat`, `VERIFY_AUDIT.bat`).
     - ينفّذ السكربت `MERSAD_AI.exe --verify-models` ثم `MERSAD_AI.exe --verify` ويفحص رمز الخروج (`!ERRORLEVEL!`) بعد كل أمر، ويتوقف فوراً برمز خطأ غير صفري دون عرض `SUCCESS` إذا فشل أي تحقق.

2. **ضمان توافق بنية الـ Artifact مع السكربت (`.github/workflows/windows-build.yml`)**:
   - يجهّز سير العمل مجلداً قياسياً `artifact_staging\MERSAD_AI\` يحتوي بداخله على `MERSAD_AI.exe` ومجلد `models\` وجميع ملفات `.dll` و `.pyd` وملفات التشغيل (`RUN.bat`, `RUN_LAN.bat`, `VERIFY_AUDIT.bat`) إلى جانب `artifact_staging\build_logs\`، ثم يرفعه عبر `actions/upload-artifact@v4` باسم **`MERSAD_AI_Windows_x64_Distribution`**.
   - عند تنزيل الـ Artifact عبر `gh run download` إلى `build_artifacts\`، يكون المسار `build_artifacts\MERSAD_AI\MERSAD_AI.exe` جاهزاً ومطابقاً تماماً لما ينسخه `PUSH_TO_GITHUB_AND_BUILD.bat` إلى المسار النهائي:
     **`MERSAD_AI_RELEASE\MERSAD_AI\MERSAD_AI.exe`**

3. **تحسين أدوات البناء والتشغيل المحلية (`setup.bat`, `BUILD_EXE.bat`, `VERIFY_AUDIT.bat`)**:
   - **`setup.bat`**: يكتشف تلقائياً إصدار Python المتوافق فعلياً (`Python 3.11 64-bit` أو `3.10–3.12 64-bit` عبر `py -3.11-64` / `py -3.11`) بحيث لا يفشل البناء إذا كان الجهاز يحتوي على `Python 3.13` أو `3.14` كإصدار افتراضي في `PATH`.
   - **`BUILD_EXE.bat`**: يبني `dist\MERSAD_AI\MERSAD_AI.exe` عبر `mersad_ai.spec`، ويتحقق من وجود النماذج الأربعة وملفات `.pth` (`>= 2`) وملفات `.dll` (`>= 5`)، ثم ينفّذ اختبار تشغيل فعلي (`Smoke Test`) على `dist\MERSAD_AI\MERSAD_AI.exe --verify-models` و `--verify` في مجلد بيانات مؤقت معزول مع فحص صارم لرمز الخروج `!ERRORLEVEL!`.

---

## 2. المراجعة الأمنية للنماذج الأربعة: التمييز الدقيق بين مستويات التحقق والموثوقية

التزاماً بالشفافية الأمنية، يميز النظام بوضوح تام بين ثلاث آليات مختلفة للتحقق من أوزان النماذج الأربعة في `mersad_live.py` و `prefetch.py` و `check_install.py`، **ولا يدّعي أن النموذج موثوق المصدر لمجرد توليد بصمته وحفظها محلياً بعد تنزيله**:

| النموذج | المسار داخل الحزمة | المصدر الفعلي المعتمد في المشروع (`mersad_live.py` / `prefetch.py`) | نوع التحقق ومستوى الضمان الأمني الفعلي |
| ----- | ----- | ----- | ----- |
| **1. YuNet (كشف الوجوه)** | `models/yunet.onnx` | `https://github.com/opencv/opencv_zoo/raw/0d61067727e22ed9fa2f7ef5ce81dac7a8d0fb8a/models/face_detection_yunet/face_detection_yunet_2023mar.onnx` | **1) بصمة `SHA-256` ثابتة موثوقة مدمجة في الكود (`Pinned Immutable SHA-256`)**: يتحقق `verify_onnx_file()` من تطابق الملف مع البصمة الثابتة `8f2383e4dd3cfbb4553bf0fb6cde5e5f80f5f70c6e595e3fd10e819a79d1527c` (`>= 200 KB`) ومن سلامة ترويسة ONNX الثنائية. هذا المستوى يكفل التحقق الكامل من هوية ومصدر النموذج الأصلي. |
| **2. SFace (مطابقة الوجوه)** | `models/sface.onnx` | `https://github.com/opencv/opencv_zoo/raw/0d61067727e22ed9fa2f7ef5ce81dac7a8d0fb8a/models/face_recognition_sface/face_recognition_sface_2021dec.onnx` | **1) بصمة `SHA-256` ثابتة موثوقة مدمجة في الكود (`Pinned Immutable SHA-256`)**: يتحقق `verify_onnx_file()` من تطابق الملف مع البصمة الثابتة `0ba9fbfa01b5270c96627c4ef784da85eab3da1e9bedf8ef69c25eb8d7e52275` (`>= 30 MB`) ومن ترويسة ONNX. هذا المستوى يكفل التحقق الكامل من هوية ومصدر النموذج الأصلي. |
| **3. YOLOv8n (كشف المركبات والشاحنات)** | `models/yolov8n.pt` | `https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8n.pt` | **2) فحص أمان Bytecode ساكن + بصمة `SHA-256` تُولَّد بعد أول تنزيل (`TOFU — Trust On First Use`)**: لا يحتوي الكود المصدري على بصمة `SHA-256` ثابتة مسبقة لـ `yolov8n.pt` (ما لم يمررها المشغّل صراحةً عبر المتغير البيئي `MERSAD_YOLO_SHA256`). عند أول تنزيل عبر HTTPS، يفحص `verify_yolo_pt_file()` بنية أرشيف PyTorch ZIP ويفحص جميع تعليمات Pickle ساكنةً عبر `_scan_pt_pickle_safety()` (قائمة بيضاء صارمة تمنع تنفيذ أي استدعاءات نظام أو وحدات خارجية)، ثم يحفظ البصمة المحسوبة في `yolov8n.pt.sha256` وفي `models/.trusted_models.json` الموقّع بـ `HMAC-SHA256`. **تنبيه أمني صريح**: تسجيل هذه البصمة بعد التنزيل الأول يحمي من التلف اللاحق (`Bit-rot`) أو الاستبدال المحلي غير المصرح به بعد التنزيل، لكنه **لا يُعدّ إثباتاً تشفيرياً مسبقاً لمصدر الملف الأصلي** إلا عند تزويد `MERSAD_YOLO_SHA256` ببصمة مرجعية معروفة مسبقاً. |
| **4. EasyOCR (قراءة اللوحات العربية والإنجليزية)** | `models/easyocr/*.pth` | `easyocr.Reader(["ar", "en"], model_storage_directory="models/easyocr")` | **3) التحقق البنيوي من ملفات الأوزان (`Structural & Header Integrity Check`)**: تُحمَّل أوزان الكاشف (`craft_mlt_25k.pth`) والمميز العربي/اللاتيني عبر مكتبة `EasyOCR`، وتتحقق الدالة `verify_easyocr_dir()` بنيوياً من عدم وجود ملفات تنزيل ناقصة (`.part`/`.tmp`)، ووجود ملفَي `.pth` على الأقل بحجم `>= 500 KB` لكل ملف، وصحة الترويسة السحرية لملف PyTorch (`PK\x03\x04` أو `\x80`). **تنبيه أمني صريح**: هذا الفحص يتحقق من اكتمال التنزيل وسلامة البنية الثنائية لملفات `.pth`، ولا يُمثّل مصادقة تشفيرية ببصمة `SHA-256` ثابتة مدمجة في الكود المصدري. |

---

## 3. الفصل الواضح بين الاختبارات المنفذة على Linux والاختبارات المبرمجة على Windows

> **إقرار شفافية هندسي دقيق**: بيئة التنفيذ الحالية هي حاوية **Linux x86_64 (`Python 3.11.2 64-bit`) معزولة تماماً عن الإنترنت الخارجي** ولا تمتلك اتصالاً شبكياً بـ `github.com` ولا مفسر Windows فرعياً لبناء ملفات PE/COFF (`MERSAD_AI.exe`). لذلك **لم يتم إنتاج ملف `MERSAD_AI.exe` الثنائي داخل حاوية Linux هذه**، بل تم تنفيذ جميع الاختبارات البرمجية والأمنية والهيكلية محلياً على Linux (بنسبة نجاح **100% — 201/201 PASS**)، وتجهيز منظومة البناء السحابية والمحلية الكاملة لتوليد `MERSAD_AI.exe` بضغطة واحدة على جهازك.

### أ) الاختبارات المنفذة والمتحقق منها فعلياً في هذه الجلسة على Linux (`Python 3.11.2 x86_64`)

| الاختبار / الفحص | الأمر المنفذ | النتيجة الفعلية على Linux |
| ----- | ----- | ----- |
| **ترجمة جميع وحدات المشروع (10 وحدات)** | `python3 -m compileall -q .` | **PASS** (صفر أخطاء صياغة في جميع ملفات `.py`) |
| **حزمة الاختبارات الشاملة (الوضع القياسي مع `scikit-learn`)** | `python3 selftest.py` | **PASS — `201 PASS, 0 SKIP, 0 FAIL`** (شاملاً اختبارات المراحل 1 إلى 15 و `193` معرّفاً تاريخياً + `8` اختبارات للمرحلة 15) |
| **حزمة الاختبارات الشاملة (وضع البديل الإحصائي بدون `scikit-learn`)** | `MERSAD_BLOCK_SKLEARN=1 python3 selftest.py` | **PASS — `201 PASS, 0 SKIP, 0 FAIL`** |
| **فحص صياغة جافاسكربت في لوحة التحكم (`dashboard.html`)** | `node --check` (مدمج داخل `selftest.py`) | **PASS** (جميع الدوال والأزرار الـ 66 سليمة) |
| **فحص تطابق منظومة البناء (`mersad_ai.spec`, `BUILD_EXE.bat`, `PUSH_TO_GITHUB_AND_BUILD.bat`, `windows-build.yml`)** | `check_install.verify_build_config_consistency()` | **PASS (`ok: True`)** — يشمل التحقق من استنساخ المستودع `.git_build_worktree`، وربط `LOCAL_HEAD_SHA`، وفحص `!VERIFY_MODELS_RC! NEQ 0`، وهيكلة `artifact_staging\MERSAD_AI\MERSAD_AI.exe` |
| **فحص السلسلة الجنائية (`HMAC-SHA256`) وعزل مسارات البيانات** | `python3 mersad_live.py --verify` | **PASS (`Audit chain OK`)** |
| **تقرير الجاهزية الهندسية الشامل (`--readiness-report`)** | `python3 mersad_live.py --readiness-report` | **PASS — `100.0%`** في جميع الركائز الهندسية الثلاث (`READY_100`) |

### ب) الاختبارات المبرمجة للتنفيذ التلقائي على Windows Runner (`windows-latest`) أو محلياً عبر `BUILD_EXE.bat`

| البند المطلوب | كيف يتم تنفيذه والتحقق منه تلقائياً على Windows |
| ----- | ----- |
| **1. نجاح تثبيت المكتبات ومعالجة التعارضات** | يثبّت `setup.bat` / `windows-build.yml` عجلات `PyTorch 2.5.1 CPU` والحزم المثبتة، ويحذف `opencv-python-headless` ويعيد تثبيت `opencv-python==4.11.0.86`، ثم يتحقق عبر `check_install.py --verify-pip-deps`. |
| **2. نجاح تحميل النماذج الأربعة والتحقق منها** | يقوم `prefetch.py` بتنزيل `yunet.onnx`, `sface.onnx`, `yolov8n.pt`, وأوزان `EasyOCR (ar+en)`، ثم يتحقق `check_install.py --strict` من البصمات والأحجام ويكتب `venv\.ready`. |
| **3. نجاح PyInstaller ووجود `MERSAD_AI.exe` الحقيقي** | يبني `pyinstaller --noconfirm --clean mersad_ai.spec` المجلد `dist\MERSAD_AI\MERSAD_AI.exe` ويفحص السكربت وجود الملف التنفيذي فعلياً. |
| **4. عدم وجود DLL مفقودة وتضمين الموارد** | يتحقق `windows-build.yml` و `PUSH_TO_GITHUB_AND_BUILD.bat` و `BUILD_EXE.bat` من وجود ملفات `.dll` (`>= 5`) و `.pyd` المجمّعة وأوزان `.pth` (`>= 2`) داخل `MERSAD_AI\` بالإضافة إلى `dashboard.html` و `README_AR.md`. |
| **5. إمكانية تحميل النماذج من حزمة التوزيع وعدم الاعتماد على مسارات جهاز التطوير** | ينسخ `windows-build.yml` محتويات `dist\MERSAD_AI\` إلى مجلد مؤقت يحتوي على مسافات وأحرف عربية (`$env:RUNNER_TEMP\اختبار مرصاد AI\نسخة التوزيع\MERSAD_AI`) مع توجيه `$env:MERSAD_DATA_DIR` لمجلد منفصل، ويشغّل `MERSAD_AI.exe --verify-models` و `MERSAD_AI.exe --verify` و `MERSAD_AI.exe --readiness-report --json` بدون وجود `venv`. |

---

# ملحق البناء التاريخي — V7 Operational Enhanced (`MERSAD_AI_V7_1_GOLD_RELEASE_SOURCE.zip`)

**لم يتم بناء V7 كملف EXE في هذه البيئة.** اختبار V7 المحلي اقتصر على التحليل البرمجي، واختبارات Python، وفحص صياغة JavaScript. أُضيفت الوحدات الجديدة إلى `mersad_ai.spec` و`BUILD_EXE.bat`، كما تم تحسين workflow على Windows ليوقف المهمة عند فشل فحوصات التثبيت أو الاختبار أو البناء؛ لكن لا بد من نجاح Windows CI وبناء `MERSAD_AI.exe` والتحقق منه قبل توزيع النسخة.

> **إقرار شفافية إلزامي**: بيئة الفحص الحالية هي حاوية Linux (`Python 3.11.2 x86_64`) معزولة عن الإنترنت؛ لذلك **لم يتم بناء أو تشغيل `MERSAD_AI.exe` فعلياً على جهاز Windows داخل هذه الجلسة** (`تم الإصلاح لكن لم يُختبر على Windows`). بدلاً من الادعاء النظري، تم توحيد وتثبيت جميع سكربتات البناء (`BUILD_EXE.bat`, `setup.bat`, `mersad_ai.spec`, `constraints-win-x64.txt`) وإعداد سير عمل GitHub Actions متكامل (`.github/workflows/windows-build.yml`) لتنفيذ البناء والاختبار الفعلي على Windows Server x64.

## 4. مواصفات بيئة التشغيل والبناء المستهدفة (Single Source of Truth)

* **نظام التشغيل والبنية المستهدفة**: `Windows 10 / 11 / Server 2022 (64-bit / x64)`.
* **إصدار Python المرجعي المستهدف**: **`Python 3.11 (64-bit)`** (مدعوم برمجياً على `3.10–3.12 64-bit`، ومختبر فعلياً على `Python 3.11.2 64-bit`).
* **جدول الإصدارات المثبتة في `requirements.txt` و `constraints-win-x64.txt` و `setup.bat` و `BUILD_EXE.bat`**:

| الحزمة | الإصدار المثبت | الغرض وطريقة التثبيت |
| ----- | ----- | ----- |
| `torch` | `2.5.1` (CPU) | محرك الشبكات العصبية لـ EasyOCR و YOLOv8 (`--index-url https://download.pytorch.org/whl/cpu`) |
| `torchvision` | `0.20.1` (CPU) | معالجة الصور لـ PyTorch (`--index-url https://download.pytorch.org/whl/cpu`) |
| `numpy` | `1.26.4` | العمليات المصفوفية المتوافقة مع OpenCV و PyTorch 2.5 |
| `opencv-python` | `4.11.0.86` | معالجة الفيديو، YuNet، SFace، ونافذة العرض المحلية (مع إزالة `opencv-python-headless`) |
| `Pillow` | `10.4.0` | معالجة الصور المطلوبة لـ EasyOCR و Torchvision |
| `easyocr` | `1.7.2` | قراءة اللوحات العربية والإنجليزية |
| `ultralytics` | `8.3.0` | تشغيل نموذج كشف المركبات والشاحنات `YOLOv8n` |
| `openpyxl` | `3.1.5` | استيراد وتصدير سجلات Excel (`.xlsx`) |
| `scikit-learn` | `1.5.2` | نموذج كشف الشذوذ `IsolationForest` (مع وجود بديل `StatForest` مدمج) |
| `pyinstaller` | `6.11.1` | أداة حزم وبناء توزيعة Windows (`--onedir`) |

## 5. سجل التحقق الهندسي لمراحل الإصلاح (MERSAD AI V7.1 — Stages 1..15)

يُوثّق الجدول التالي بأمانة علمية حالة التحقق الفعلية لكل محور هندسي بعد إتمام المراحل 1 إلى 15، مع الفصل الصريح بين ما تم التحقق منه برمجياً في بيئة الفحص الآلية (`selftest.py` — **193 اختباراً تاريخياً + 8 اختبارات للمرحلة 15 = 201 اختباراً ناجحاً / 0 فشل**) وما يظل مصنفاً كـ **«غير متحقق منه ميدانياً»** لحين تشغيل البناء على جهاز Windows حقيقي وتجربة الكاميرات وعينة اللوحات اليمنية الميدانية:

| المحور الهندسي | المعرّفات | حالة التحقق البرمجي (`selftest.py`) | حالة التحقق الميداني / Windows الحقيقي |
| ----- | ----- | ----- | ----- |
| **توحيد الاعتماديات واسترجاع `WAL` وعزل الاستيراد والأقفال** | `GAP-01`, `GAP-02`, `GAP-03`, `GAP-06` | **متحقق منه برمجياً بالكامل** (`STAGE1-GAP01..06`) | جاهز للتشغيل على Windows؛ يتطلب تشغيل `setup.bat` على Windows حقيقي. |
| **ترحيل `camera_links` الحتمي وعزل `demo` وفحص `--camera`** | `GAP-04`, `GAP-05`, `GAP-07` | **متحقق منه برمجياً بالكامل** (`STAGE2-GAP04..07`) | يتطلب معايرة ميدانية لأزمنة الانتقال الحقيقية بين مواقع الكاميرات. |
| **طمس الوجوه (`100%` في تنبيهات المركبات) وضوابط التسجيل وسلسلة `HMAC-SHA256`** | `GAP-09`, `GAP-10`, `GAP-11`, `GAP-15` | **متحقق منه برمجياً بالكامل** (`STAGE3-GAP09..15`) | يتطلب اختبار إضاءة وزوايا الكاميرات الميدانية الفعلية. |
| **الاستدلال غير الحاجب (`maxsize=1`) وتزامن `Bus` وفهرسة `lookup_vehicle` ودعم `GPU/CPU`** | `GAP-08`, `GAP-12`, `GAP-13`, `GAP-14`, `GAP-16` | **متحقق منه برمجياً بالكامل** (`STAGE4-GAP08..16`) | دعم `CUDA` متحقق منه بمحاكاة `torch.cuda`؛ يتطلب جهازاً ببطاقة NVIDIA لتجربة التسريع الفعلي. |
| **أداة التقييم المعيارية للوحات اليمنية (`--evaluate-plates`)** | `GAP-17` | **متحقق منه برمجياً بالكامل** (`STAGE5-GAP17`: حساب `detection_recall`, `mean_iou`, `exact_match_rate`, `digits_match_rate`, `CER`, `latency_ms`) | **غير متحقق منه ميدانياً بعد**: لا توجد عينة صور لوحات يمنية حقيقية مرفقة في المستودع؛ للاستغناء عن كاشف الحواف الكلاسيكي (`Canny`) في الميدان يلزم توفير نموذج YOLO مخصص للوحات (`--plate-model`) مدرب على لوحات يمنية حقيقية. |
| **منظومة البناء السحابية والمحلية للمرحلة 15 (`PUSH_TO_GITHUB_AND_BUILD.bat`, `BUILD_EXE.bat`, `windows-build.yml`)** | `GAP-18`, `STAGE15-GAP01..08` | **متحقق منه برمجياً بالكامل** (`201/201 PASS`: تطابق `hiddenimports`، وصياغة PowerShell، وعزل `$env:MERSAD_DATA_DIR` داخل `$env:RUNNER_TEMP`، وأداة الرفع والبناء الآلي ذات الـ 12 خطوة) | **غير متحقق منه على Windows حقيقي داخل هذه الجلسة**: بيئة الفحص الحالية هي حاوية Linux معزولة عن الإنترنت؛ شغّل `PUSH_TO_GITHUB_AND_BUILD.bat` أو `BUILD_EXE.bat` على جهاز Windows 10/11 x64 لإنتاج `MERSAD_AI.exe`. |
