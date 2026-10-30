# ملحق التدقيق النهائي — MERSAD AI V7.1 (اكتمال المراحل 1–14)

- **الحصيلة النهائية لاختبارات التحقق الآلي (`selftest.py`)**: **`193 PASS, 0 SKIP, 0 FAIL`** (في كلا وضعي التشغيل القياسي و`MERSAD_BLOCK_SKLEARN=1`).
- **الأدوات والخيارات الموحدة في `V7.1`**: دعم `--verify`، و`--verify-models`، و`--evaluate-plates` (مع دعم قص المركبة أولاً `vyolo -> find_plates` عبر `--use-vehicle-detector` / `--vehicle-model`)، و`--device auto|cpu|cuda` / `--gpu`، وفحص `--camera` و`--verify-pip-deps` في `check_install.py`.
- **توحيد سكربتات التشغيل والبناء**: تطابق `RUN.bat` و`RUN_LAN.bat` في اشتراط `check_install.py --strict`، وتطابق `hiddenimports` في `mersad_ai.spec` و`BUILD_EXE.bat`، وعزل اختبارات الدخان لنسخة `MERSAD_AI.exe` في `.github/workflows/windows-build.yml` داخل `$env:RUNNER_TEMP`.

---

# تقرير التدقيق الهندسي والأمني الشامل — MERSAD AI (الجولة الخامسة النهائية — `MERSAD_AI_FIXED_5.zip`)

يُوثّق هذا التقرير نتائج المراجعة الهندسية للجولة الخامسة على `MERSAD_AI_FIXED_4.zip`، والتناقضات التي رُصدت وعُولجت، وخريطة مصدر الحقيقة للاعتماديات والنماذج، والجدول النهائي للإصلاحات والتحقق، مع الفصل الصريح بين ما تم التحقق منه فعلياً في بيئة الفحص الحالية وما يتطلب بيئة Windows أو كاميرات ونماذج ميدانية.

---

## 1. تدقيق التناقضات المرصودة في `MERSAD_AI_FIXED_4.zip` وكيفية إغلاقها

عند فحص ملفات `MERSAD_AI_FIXED_4.zip` سطراً بسطر قبل التعديل، تبيّن وجود التناقضات التالية وتم إغلاقها بالكامل في `MERSAD_AI_FIXED_5.zip`:

1. **تضارب إصدار `opencv-python` بين الكود والتقارير**:
   - كان `requirements.txt` و `setup.bat` يثبتان `opencv-python==4.11.0.86`، بينما كان `BUILD_REPORT.md` و `CHANGELOG.md` يذكران `opencv-python==4.10.0.84`.
   - **الحل**: اعتماد `opencv-python==4.11.0.86` كمصدر حقيقة موحد في `requirements.txt` و `constraints-win-x64.txt` و `setup.bat` و `check_install.py` وجميع التقارير.
2. **تضارب إصدار `ultralytics` بين الكود والتقارير**:
   - كان `requirements.txt` يثبت `ultralytics==8.3.0`، بينما كان `BUILD_REPORT.md` يذكر `ultralytics==8.3.70`.
   - **الحل**: اعتماد `ultralytics==8.3.0` كمصدر حقيقة موحد في جميع ملفات الاعتماديات والنماذج (`YOLO_RELEASE_VERSION = "v8.3.0"`) والتقارير.
3. **تثبيت `torch` و `torchvision` و `pyinstaller` بدون تحديد إصدارات**:
   - كان `setup.bat` ينفّذ `pip install torch torchvision` بدون إصدارات، وكان `BUILD_EXE.bat` ينفّذ `pip install pyinstaller` بدون إصدار بينما يذكر التقرير `pyinstaller==6.11.1`.
   - **الحل**: تثبيت `torch==2.5.1` و `torchvision==0.20.1` في `setup.bat` و `constraints-win-x64.txt`، وتثبيت `pyinstaller==6.11.1` في `BUILD_EXE.bat` و `constraints-win-x64.txt` و `check_install.py`.
4. **تجاوز إعداد البيئة بصمت بسبب `if exist "venv\.ready" exit /b 0`**:
   - كان `setup.bat` يكتب كلمة `ok` داخل `venv\.ready` ثم يتخطى الإعداد في كل مرة لاحقة حتى لو تغير `requirements.txt` أو حُذفت النماذج.
   - **الحل**: استبدال النص الثابت ببصمة JSON موثقة (`compute_env_manifest` في `check_install.py`) تربط `venv\.ready` بإصدار Python وبنية 64-bit وبصمات `SHA-256` لملفات `requirements.txt` و `constraints-win-x64.txt` و `prefetch.py` وإصدارات الحزم وسلامة جميع النماذج، مع حذف `.ready` قبل بدء أي تحديث وعدم كتابته إلا بعد اجتياز التحقق الكامل (`--write-ready`).
5. **اعتماد تنزيل `yolov8n.pt` على الحجم فقط (`>= 1 MB`) وغياب المهلة الزمنية في `urlretrieve`**:
   - كان `prefetch.py` يتحقق من حجم `yolov8n.pt` فقط، ويستخدم `urlretrieve` بلا مهلة (`timeout`).
   - **الحل**: تنزيل `yolov8n.pt` من رابط الإصدار الثابت `v8.3.0` عبر `safe_download_model` بمهلة مقبس صريحة (`timeout=30s`) وإعادة محاولة محدودة، والتحقق من حجم الملف (`>= 6 MB`) ومن كونه أرشيف `PyTorch ZIP` سليم البنية يحتوي على `data.pkl` و `version` وأوزان صالحة (`verify_yolo_pt_file`) مع حفظ بصمته في `yolov8n.pt.sha256`، وعدم مسح أي نموذج سليم قائم إذا فشل تنزيل لاحق.

---

## 2. خريطة مصدر الحقيقة الموحدة (Single Source of Truth)

| العنصر | القيمة المعتمدة الموحدة | الملف المرجعي في المشروع |
|---|---|---|
| إصدار Python المستهدف | **Python 3.11 (64-bit / x64)** (اختُبر هنا على `Python 3.11.2 x86_64`) | `setup.bat`, `check_install.py`, `.github/workflows/windows-build.yml` |
| `torch` / `torchvision` (CPU) | `torch==2.5.1` / `torchvision==0.20.1` (`https://download.pytorch.org/whl/cpu`) | `constraints-win-x64.txt`, `setup.bat`, `check_install.py` |
| `numpy` | `numpy==1.26.4` | `requirements.txt`, `constraints-win-x64.txt`, `check_install.py` |
| `opencv-python` | `opencv-python==4.11.0.86` (مع إزالة `opencv-python-headless`) | `requirements.txt`, `constraints-win-x64.txt`, `setup.bat`, `check_install.py` |
| `Pillow` | `Pillow==10.4.0` | `requirements.txt`, `constraints-win-x64.txt`, `check_install.py` |
| `easyocr` | `easyocr==1.7.2` | `requirements.txt`, `constraints-win-x64.txt`, `check_install.py` |
| `ultralytics` | `ultralytics==8.3.0` | `requirements.txt`, `constraints-win-x64.txt`, `check_install.py` |
| `openpyxl` | `openpyxl==3.1.5` | `requirements.txt`, `constraints-win-x64.txt`, `check_install.py` |
| `scikit-learn` (اختياري مع بديل `StatForest`) | `scikit-learn==1.5.2` | `requirements.txt`, `constraints-win-x64.txt`, `check_install.py` |
| `pyinstaller` (أداة بناء الحزمة) | `pyinstaller==6.11.1` (نمط التوزيع: `--onedir` في `dist\MERSAD_AI\`) | `constraints-win-x64.txt`, `BUILD_EXE.bat`, `mersad_ai.spec`, `check_install.py` |
| نماذج الوجوه (`yunet.onnx`, `sface.onnx`) | OpenCV Zoo Commit `0d61067727e22ed9fa2f7ef5ce81dac7a8d0fb8a` + `MODEL_SHA256` | `mersad_live.py`, `prefetch.py`, `check_install.py` |
| نموذج المركبات (`yolov8n.pt`) | Ultralytics Release `v8.3.0` + `verify_yolo_pt_file` (فحص أرشيف PyTorch ZIP + بصمة `SHA-256`) | `mersad_live.py`, `prefetch.py`, `check_install.py` |

---

## 3. الجدول النهائي الشامل للإصلاحات والتحقق وتصنيف الحالة

| المشكلة | السبب الجذري | الملفات المعدلة | الإصلاح المنفذ | الاختبار والأمر المستخدم | النتيجة الفعلية | الدليل | التصنيف والحالة المتبقية |
|---|---|---|---|---|---|---|---|
| **1. تناقض إصدارات المكتبات وعدم تثبيت `torch` و `pyinstaller`** | اختلاف الأرقام بين `requirements.txt` (`4.11.0.86`, `8.3.0`) و `BUILD_REPORT.md` (`4.10.0.84`, `8.3.70`)، وترك `torch` و `pyinstaller` بلا إصدار في سكربتات `.bat`. | `requirements.txt`, `constraints-win-x64.txt`, `setup.bat`, `BUILD_EXE.bat`, `check_install.py`, التقارير | توحيد كافة الإصدارات في `requirements.txt` و `constraints-win-x64.txt` وتمرير `-c constraints-win-x64.txt` في `setup.bat` و `BUILD_EXE.bat`. | فحص `[R5-DEPS]` في `python3 selftest.py` | **PASS** | تطابق حرفي لجميع الإصدارات في السكربتات والتقارير واجتياز `[R5-DEPS]`. | **1. تم الإصلاح والتحقق الفعلي** (تثبيت الحزم الكامل على Windows: **2. تم الإصلاح لكن لم يُختبر على Windows** محلياً لكون الحاوية Linux معزولة؛ جُهّز له CI كامل). |
| **2. تخطي إعداد البيئة بصمت عند وجود `venv\.ready`** | كان `setup.bat` يفحص وجود الملف النصي `venv\.ready` (`"ok"`) فقط دون التحقق من تغير `requirements.txt` أو تلف النماذج. | `setup.bat`, `check_install.py` (`compute_env_manifest`, `verify_ready_stamp`, `write_ready_stamp`), `selftest.py` | ربط `venv\.ready` ببصمة `SHA-256` لملفات الاعتماديات وإصدار Python 64-bit والحزم المثبتة وسلامة النماذج، وحذف `.ready` قبل أي تثبيت وعدم كتابته إلا بعد نجاح التحقق الكامل. | فحص `[R5-ENV]` في `python3 selftest.py` | **PASS** | رفض `.ready` القديم (`"ok"`)، وحذف الختم عند غياب النماذج، وكشف تعديل `requirements.txt` أو تلف `yunet.onnx` فوراً. | **1. تم الإصلاح والتحقق الفعلي** |
| **3. تنزيل النماذج بلا مهلة واعتماد `yolov8n.pt` و `easyocr` على فحص سطحي** | استخدام `urlretrieve` بلا `timeout`، وفحص حجم `yolov8n.pt` فقط (`>= 1 MB`)، والاكتفاء بوجود أي ملف داخل `models/easyocr`. | `mersad_live.py`, `prefetch.py`, `check_install.py`, `selftest.py` | بناء `safe_download_model` بملف `.part` مؤقت ومهلة مقبس وإعادة محاولة، وفحص `Content-Length` و `SHA-256` وبنية أرشيف `PyTorch ZIP` (`verify_yolo_pt_file`) وفحص أوزان `.pth` لـ `EasyOCR` (`verify_easyocr_dir`)، مع حماية النموذج السليم القائم عند فشل التنزيل. | فحص `[R5-MODELS]` في `python3 selftest.py` (عبر خادم HTTP محلي يحاكي انقطاع التحميل والمهلة والبصمة الخاطئة والملف التالف) | **PASS** | رفض التحميل الجزئي والمهلة والبصمة الخاطئة وملف `.pt` غير الصالح، ونجاح إعادة المحاولة، والحفاظ على النموذج السليم القائم. | **1. تم الإصلاح والتحقق الفعلي** (التحميل الفعلي للأوزان الكبيرة من الإنترنت: **3. يحتاج إلى اختبار ميداني / CI متصل بالإنترنت**). |
| **4. بناء حزمة Windows (`--onedir`) وفصل مسار التثبيت القابل للقراءة فقط عن بيانات المستخدم** | كان `APPDIR` يفترض قابلية الكتابة في مجلد `MERSAD_AI.exe` (الذي قد يكون في `Program Files` غير القابل للكتابة)، وكان `BUILD_EXE.bat` لا ينسخ سكربتات تشغيل التوزيع أو يتحقق من المخرجات. | `mersad_live.py` (`resolve_writable_appdir`, `resolve_resource_path`), `BUILD_EXE.bat`, `mersad_ai.spec`, `.github/workflows/windows-build.yml`, `selftest.py` | فصل `BUNDLE_DIR`/`INSTALL_DIR` (للموارد والنماذج القابلة للقراءة فقط) عن `APPDIR` (الذي يسقط تلقائياً إلى `%LOCALAPPDATA%\MERSAD_AI` عند عدم قابلية الكتابة في مجلد التثبيت)، وتحديث `BUILD_EXE.bat` و `mersad_ai.spec` وإعداد سير عمل GitHub Actions لـ Windows. | فحص `[R5-PATHS]` في `python3 selftest.py` (تشغيل من مجلد تثبيت للقراءة فقط `0555` يحتوي على مسافات وأحرف عربية ومن مجلد عمل خارجي) | **PASS** | نجاح إنشاء وبقاء `mersad.db` و `.mersad_hmac.key` وسلسلة التدقيق في مجلد بيانات المستخدم عبر إعادات التشغيل دون لمس مجلد التثبيت المحمي. | **1. تم الإصلاح والتحقق الفعلي** لمنطق فصل المسارات؛ **2. تم الإصلاح لكن لم يُختبر على Windows** لبناء وتشغيل `MERSAD_AI.exe` الفعلي (بسبب كون الحاوية Linux). |
| **5. عدم تمييز `check_install.py` بين المكتبات الاختيارية والنماذج المفقودة والملفات التالفة** | كان `check_install.py` يطبع `FAIL` عاماً دون تفريق بين مكتبة اختيارية (`scikit-learn`) أو نموذج غير محمّل بعد في بيئة تطوير أو نموذج تالف. | `check_install.py`, `RUN.bat`, `selftest.py` | تصنيف الفحوصات إلى `CORE_LOGIC`, `PYTHON_ENV`, `REQUIRED_LIB`, `OPTIONAL_LIB`, `VERSION_MISMATCH`, `BUILD_REQ`, `MODEL_MISSING`, `MODEL_CORRUPT`, `MODEL_OK` مع سبب الفشل وطريقة المعالجة ودعم `--strict` و `--json`. | `python3 check_install.py` وفحص `[R5-DIAG]` في `python3 selftest.py` | **PASS** | عرض تصنيف دقيق لكل عنصر ونجاح `[R5-DIAG]`. | **1. تم الإصلاح والتحقق الفعلي** |
| **6. حماية إصلاحات الجولة الرابعة (`P0-A`, `P0-B`, `P1-C`, `P1-D`, `P1-E`)** | التحقق من عدم حدوث أي تراجع في عزل الهويات البيومترية أو حجز التوجيه أو إعادة اتصال الكاميرات أو حماية الأسرار والأرشيف بعد تعديلات الجولة الخامسة. | `registry.py`, `mersad_live.py`, `notify.py`, `selftest.py` | الحفاظ الكامل على منطق الجولة الرابعة وتشغيل جميع اختبارات الانحدار (109 اختبارات سابقة + 5 اختبارات للجولة الخامسة = 114 اختباراً). | `python3 selftest.py` و `MERSAD_BLOCK_SKLEARN=1 python3 selftest.py` | **PASS** (`114/114`) | اجتياز جميع الفحوصات الـ 114 (0 SKIP, 0 FAIL) في الوضعين. | **1. تم الإصلاح والتحقق الفعلي** |

---

## 7. تحديث المرحلة 3 (V7.1 Stage 3): ترقية سلسلة التدقيق إلى `HMAC-SHA256` (`h1:`) وإحكام الخصوصية

1. **سلسلة التدقيق الموقعة (`HMAC-SHA256`) وحدود التهديد**:
   - تعتمد الدالة `chain_hash()` صيغة `h1:<hmac_sha256>` المرتبطة بالمفتاح المحلي `.mersad_hmac.key` (`R._get_hmac_key()`)، بينما تتحقق `verify()` من السجلات الإرثية عبر `legacy_chain_hash()` دون إعادة كتابتها، وترفض فوراً أي محاولة لخفض المستوى (`downgrade attack`) أو التحقق عند غياب/تلف ملف المفتاح `.mersad_hmac.key`.
   - **توصيف أمني أمين**: تضمن هذه الآلية كشف التلاعب بالتسلسل أو محتوى السجلات أو ملفات الأدلة ضد التعديلات غير المصرح بها على قاعدة البيانات، لكنها لا تحل محل خادم سجل خارجي معزول (`Write-Once Remote Syslog / HSM`) في حال حصول مهاجم ذي صلاحيات نظام كاملة على كلٍّ من قاعدة البيانات وملف `.mersad_hmac.key` معاً.
2. **الفصل الصارم في طمس الوجوه وحماية جلسة التسجيل (`GAP-09`, `GAP-10`, `GAP-15`)**:
   - طمس 100% من الوجوه في جميع تنبيهات المركبات عبر `get_boxes_to_blur_for_alert(face_entries, alert_kind="vehicle")`.
   - ربط جلسة تسجيل الوجه بالكاميرا (`cam`)، واشتراط حجم وجه `>= 40x40`، وغياب وجه منافس بمساحة `>= 50%`، واتساق العينات (`cosine similarity >= 0.55`) مع إلغاء الجلسة بعد 5 محاولات غير متسقة.
   - التحقق الآمن من `--truck-curfew` عبر `parse_curfew()`، وإزالة `input()` الحاجب من حلقة الفيديو، وحساب `STATUS["fps"]` كمتوسط للكاميرات المتصلة.
