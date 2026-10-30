# سجل التغييرات — MERSAD AI V7.1 (المراحل 1–14 الموحدة)

- **الحصيلة النهائية لاختبارات `selftest.py`**: **`193 PASS, 0 SKIP, 0 FAIL`** (في الوضع القياسي ومع `MERSAD_BLOCK_SKLEARN=1`).
- **المرحلة 1 (`GAP-01, GAP-02, GAP-03, GAP-06`)**: إضافة `--verify-pip-deps`، واسترجاع `WAL -> DELETE` الآمن، وعزل `init_runtime_env()` عن الاستيراد، وحماية `insights.py` بـ `run_atomic_tx`.
- **المرحلة 2 (`GAP-04, GAP-05, GAP-07`)**: عزل `src='demo'` عن الرصد الحي افتراضياً، وترحيل `camera_links` رقم 6 مع عمود `via` وواجهة `/api/camera_links`، وتفعيل `--camera` في `check_install.py`.
- **المرحلة 3 (`GAP-09, GAP-10, GAP-11, GAP-15`)**: طمس 100% من الوجوه في تنبيهات المركبات، وضوابط `enroll_step`، وسلسلة التدقيق `HMAC-SHA256` (`h1:`)، ودالة `parse_curfew()`.
- **المرحلة 4 (`GAP-08, GAP-12, GAP-13, GAP-14, GAP-16`)**: الاستدلال غير الحاجب (`maxsize=1`)، وتأمين `Bus._lock`، وفهرسة `lookup_vehicle` (`idx_vehicles_status`)، وكشف `401/403` في `dashboard.html`، ودعم `--device` و`--gpu`.
- **المرحلة 5 (`GAP-17, GAP-18`)**: أداة التقييم المعيارية للوحات `--evaluate-plates`، وتوحيد `mersad_ai.spec` و`BUILD_EXE.bat` و`.github/workflows/windows-build.yml` (`pwsh` + `$env:RUNNER_TEMP`).
- **المرحلة 6 (`POST-GAP-01..05`)**: جدولة كشف الوجوه `FACE_DETECT_INTERVAL`، وإغلاق جميع قراءات `bus.alerts` تحت `bus._lock`، وتمرير `CUR_CAM` وعرض `m.error`/`m.warning` في `dashboard.html`، وقفل `_ENROLL_LOCK` واستبدال العينات القديمة، وعزل `FH` لكل كاميرا وتقليم `camera_status_history`.
- **المرحلة 7 (`POST-GAP-06..08`)**: دعم قص المركبة أولاً (`vyolo -> find_plates`) في `evaluate_plates_dataset()` (`--evaluate-plates`)، وتوحيد `RUN_LAN.bat` و`CHECK.bat`، وتوحيد جميع ملفات التوثيق والتقارير السبعة.
- **المرحلة 8 (`FINAL-OBS-01..05`)**: إغلاق مصنف `openpyxl` في `parse_file()`، وإضافة `_STATE_LOCK`/`_TRAIN_LOCK` في `insights.py` و`_FACE_STATE_LOCK` في `mersad_live.py`، وإرجاع JSON مهيكل لرموز HTTP 400/413 وتغليف دوال `dashboard.html` بـ `try/catch`.
- **المرحلة 9 (`POST8-OBS-01..05`)**: استرجاع `source_with_credentials` من `.mersad_secrets.json` في `check_camera_source()`، وإضافة `_RUNTIME_STATE_LOCK` في `mersad_live.py`، وإغلاق جميع مقابض الملفات والمقابس بـ `with` وإرجاع JSON 404 لمسارات `/api/*`، وربط `CAMERA_HISTORY.prune_history` تلقائياً.
- **المرحلة 10 (`REL-OBS-01..03`)**: توليد سكربتات تشغيل التوزيعة (`RUN.bat`, `RUN_LAN.bat`, `VERIFY_AUDIT.bat`) في `.github/workflows/windows-build.yml` بالتطابق مع `BUILD_EXE.bat`، وتوحيد مفتاح `vehicle_stage_enabled` في `--evaluate-plates`، وتوحيد سجل المراحل 1–14 على `193 PASS, 0 SKIP, 0 FAIL`.
- **المرحلة 11 (`STAGE11-CAL/PE/MANUAL`)**: إضافة واجهة ومحرك «معايرة روابط الكاميرات — Camera Link Calibration» الكامل (مع التحويل للثواني، والحد الأعلى، والمسافة، وعدد القياسات، وظروف المرور، ومصدر القياس، والتصدير/الاستيراد JSON/CSV، والربط بمحرك تتبع المسارات)، وإضافة قسم «تقييم ومعايرة اللوحات اليمنية — Yemeni Plate Evaluation» من داخل الواجهة (فحص المسار، رفع الملفات، اختيار `--plate-model`، تفعيل `--use-vehicle-detector`، الإلغاء الآمن، وفصل مقاييس الاكتشاف عن المحارف والمطابقة الكاملة)، وإضافة «تسجيل نتائج المعايرة اليدوية» المفصول تماماً بوسم `مدخلة يدوياً — غير متحقق منها` (`193 PASS, 0 SKIP, 0 FAIL`).
- **المرحلة 12 (`AUDIT-001..005`)**: التحصين الأمني لتحميل نماذج `.pt` عبر فحص بايت كود `pickle` (`_scan_pt_pickle_safety`) وسجل البصمات الموقع بـ `HMAC-SHA256` (`models/.trusted_models.json`)، ومنع `Path Traversal` في تقييم اللوحات (`_resolve_safe_dataset_image`)، وفصل المؤشرات الخمسة (`detection_precision`, `detection_recall`, `detection_f1`, `end_to_end_exact_match_rate`, `cropped_ocr_exact_match_rate`)، ومشاركة المحركات في الذاكرة (`_SHARED_ENGINES`)، وعزل نافذة `tkinter` في عملية فرعية (`--internal-browse-dialog`).
- **المرحلة 13 (`AUDIT-006..012`)**: إضافة تحديد معدل محاولات المصادقة (`Rate Limiting` في `server.py`)، ودعم رفع مجموعات التقييم على دفعات (`batch_id`) وتقليم `eval_uploads/`، وفرض حدود السرعة الفيزيائية (`0.5–260 km/h`) في `save_camera_link`، وإضافة تصدير تقارير التقييم الآلي (`/api/plate_eval/export`)، وتحرير الروابط مباشرة داخل تبويب `#t-calibration`، والبناء المباشر من `mersad_ai.spec` في `BUILD_EXE.bat`، وتفريد معرّفات الاختبارات بنسبة 100% (`193 PASS, 0 SKIP, 0 FAIL`).
- **المرحلة 14 (`STAGE14-01..05` — الجاهزية القصوى 100%)**: دعم أنظمة الملفات الشبكية/الافتراضية في `resolve_writable_appdir()` عبر `_is_sqlite_usable_dir()`، وإعادة الختم الآلي لسجل النماذج الموثوقة عبر `bootstrap_bundled_trusted_models()` عند نقل `dist\MERSAD_AI` لأي جهاز جديد، وإضافة المعايرة التلقائية لروابط الكاميرات من سجلات الرصد (`suggest_camera_links_from_sightings`)، والتوليد الآلي لملف `ground_truth.csv` لأي مجلد صور ميدانية (`init_ground_truth_for_folder`)، وإضافة مؤشر الجاهزية الشامل الحي (`GET /api/readiness` و`--readiness-report`) (`193 PASS, 0 SKIP, 0 FAIL`).

---


## حزمة التحسين التشغيلي V7 (2026-10-26)

| الملف | التغيير |
|---|---|
| `analytics.py` | تنفيذ قراءة فقط لتجميع الرصد الحي في آخر 24 ساعة ومقارنته بالفترة السابقة، واتجاه ساعي، وتوزيع الفئات والثقة، وصحة الكاميرات، وملخص التنبيهات والتوصيات. |
| `camera_history.py` | إضافة سجل مستمر لتحولات حالة الكاميرات، وحساب الموثوقية على فترات الحالة المرصودة دون اختراع تغطية أثناء توقف التطبيق أو بين جلساته. |
| `server.py` | إضافة واجهات API محمية للتحليلات، وتصدير CSV، وتقرير موثوقية الكاميرات. |
| `dashboard.html` | إضافة تبويبي «مركز القيادة» و«موثوقية الكاميرات» مع مخططات ومقاييس وفلاتر فترات وسجل تغيّر الحالة. |
| `mersad_live.py` | ربط أحداث بدء الكاميرا وإعادة الاتصال والتوقف بسجل الموثوقية، وعرض عدّاد إعادة الاتصال الفعلي. |
| `selftest.py` | إضافة اختبارات للخدمات الجديدة، وخصوصية التصدير، والحماية من حقن صيغ CSV، وواجهات API. |
| `check_install.py`, `BUILD_EXE.bat`, `mersad_ai.spec` | تضمين الوحدات الجديدة في فحوصات التشخيص وبناء Windows. |

**محدودية المصدر:** أُنجز هذا التحديث فوق أرشيف المصدر المتاح `MERSAD_AI_FIXED_5.zip` مع إعادة تنفيذ ما تصفه ملاحظات V6 المرفقة؛ لم يكن أرشيف مصدر V6 نفسه ضمن الملفات المسلّمة.

---

## السجل التاريخي للإصدارات السابقة

MERSAD AI (الجولات 1 إلى 5 — `MERSAD_AI_FIXED_5.zip`)

يُوثّق هذا الملف سجل التغييرات الكامل عبر الجولات الخمس، مع تفصيل دقيق لتعديلات الجولة الخامسة النهائية (`MERSAD_AI_FIXED_4.zip` ➔ `MERSAD_AI_FIXED_5.zip`).

---

## أولاً: ملخص الملفات المعدّلة أو المضافة في الجولة الخامسة (`MERSAD_AI_FIXED_5.zip`)

| الملف | الإجراء | سبب التعديل في الجولة الخامسة |
|---|---|---|
| `requirements.txt` | مُعدّل | توحيد إصدارات مكتبات وقت التشغيل (`opencv-python==4.11.0.86`, `numpy==1.26.4`, `Pillow==10.4.0`, `easyocr==1.7.2`, `ultralytics==8.3.0`, `openpyxl==3.1.5`, `scikit-learn==1.5.2`) وإزالة أي تضارب مع التقارير وسكربتات التثبيت. |
| `constraints-win-x64.txt` | جديد | ملف قفل/قيود شامل لبيئة Windows x64 (`Python 3.11 64-bit`) يثبّت إصدارات `torch==2.5.1` و `torchvision==0.20.1` و `pyinstaller==6.11.1` وجميع مكتبات وقت التشغيل لضمان إعادة إنتاج البناء بدقة. |
| `setup.bat` | مُعدّل | إلغاء التجاوز الأعمى لـ `venv\.ready`؛ استدعاء `check_install.py --verify-ready` للتحقق من بصمة الاعتماديات وإصدار Python والنماذج؛ تثبيت إصدارات `torch==2.5.1` و `torchvision==0.20.1` صراحةً؛ إزالة `opencv-python-headless` وتثبيت `opencv-python==4.11.0.86`؛ تشغيل `pip check`؛ وإنشاء `venv\.ready` ذرياً عبر `check_install.py --write-ready` بعد نجاح جميع الخطوات فقط. |
| `BUILD_EXE.bat` | مُعدّل | تثبيت إصدار `pyinstaller==6.11.1` صراحةً؛ تشغيل `check_install.py --strict` و `selftest.py` و `pip check` مع إيقاف البناء فوراً عند أي خطأ؛ حفظ سجل البناء في `build_pyinstaller.log`؛ توليد سكربتات تشغيل التوزيع (`dist\MERSAD_AI\RUN.bat`, `RUN_LAN.bat`, `VERIFY_AUDIT.bat`)؛ والتحقق من وجود `dist\MERSAD_AI\MERSAD_AI.exe` وجميع النماذج قبل إعلان النجاح. |
| `mersad_ai.spec` | جديد | ملف مواصفات PyInstaller معياري لبناء حزمة `--onedir` (`COLLECT`) مع استبعاد `opencv-python-headless` وتضمين كافة الوحدات المحلية والواجهة. |
| `.github/workflows/windows-build.yml` | جديد | سير عمل GitHub Actions آلي لبيئة `windows-latest` (`Python 3.11 x64`) ينفّذ تثبيت البيئة النظيفة، وفحص `pip check`، وتشغيل الاختبارات، وتنزيل النماذج والتحقق منها، وبناء `MERSAD_AI.exe`، واختبار تشغيله من مسارات تحتوي على مسافات وأحرف عربية بدون `venv`. |
| `prefetch.py` | مُعدّل | استخدام محرك التنزيل الآمن `safe_download_model` بملفات `.part` مؤقتة، ومهلة زمنية للمقبس (`timeout=30s`)، وإعادة محاولة محدودة، والتحقق من حجم الملف وبصمة `SHA-256` وبنية أرشيف `PyTorch ZIP` لنموذج `yolov8n.pt` (من إصدار `v8.3.0` الثابت) وأوزان `EasyOCR`، مع عدم حذف أو استبدال أي نموذج سليم قائم عند فشل التنزيل. |
| `check_install.py` | مُعدّل | ترقية شاملة لتصنيف الفحوصات إلى (`CORE_LOGIC`, `PYTHON_ENV`, `REQUIRED_LIB`, `OPTIONAL_LIB`, `VERSION_MISMATCH`, `VERSION_CONFLICT`, `BUILD_REQ`, `MODEL_MISSING`, `MODEL_CORRUPT`, `MODEL_OK`)، وإدارة بصمة `venv/.ready` (`--verify-ready`, `--write-ready`, `--strict`, `--json`). |
| `mersad_live.py` | مُعدّل | فصل صارم بين مسار الموارد القابلة للقراءة فقط (`BUNDLE_DIR` / `INSTALL_DIR`) ومجلد بيانات المستخدم القابل للكتابة (`APPDIR` عبر `resolve_writable_appdir` الذي يسقط تلقائياً إلى `%LOCALAPPDATA%\MERSAD_AI` إذا كان مجلد تثبيت `EXE` غير قابل للكتابة)، وإضافة دوال `verify_onnx_file` و `verify_yolo_pt_file` و `verify_easyocr_dir` و `safe_download_model`. |
| `RUN.bat` | مُعدّل | استخدام `check_install.py --strict` لمنع بدء التشغيل الحي إذا كانت إحدى المكتبات الأساسية أو النماذج مفقودة أو تالفة. |
| `selftest.py` | مُعدّل | الاحتفاظ بجميع الـ 109 اختبارات من الجولات 1–4، وإضافة 5 مجموعات اختبار سلوكية شاملة للجولة الخامسة (`R5-DEPS`, `R5-ENV`, `R5-MODELS`, `R5-PATHS`, `R5-DIAG`) ليصبح المجموع **114 اختباراً ناجحاً (`114 PASS, 0 SKIP, 0 FAIL`)**. |
| `AUDIT_REPORT.md`, `TEST_REPORT.md`, `BUILD_REPORT.md`, `README_AR.md` | مُعدّل | مطابقة جميع أرقام الإصدارات وخطوات البناء ونتائج الاختبارات مع الكود الفعلي بنسبة 100%. |
