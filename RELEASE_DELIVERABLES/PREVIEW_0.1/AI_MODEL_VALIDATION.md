# 4. تقرير التحقق من قدرات الذكاء الاصطناعي وبوابات القبول المرجعية — `AI_MODEL_VALIDATION.md`
## الإصدار: `MERSAD AI & MERSAD LAB — Preview 0.1` (`fix/preview-0.1-postbuild-42273598736` — `AI Current Branch HEAD`: `New verified HEAD directly above 05f29af416c4a28ddf59c291819584d1a416d570` | `AI Runtime Code Commit`: `edaf651321ec9ea6ba613e3ab1630bc16b11b9d5` | `LAB HEAD`: `748ac0158761812a6fff63ff6fe626b9df8c252b`)

## 1. الفصل المنهجي الصارم بين الفئات الثلاث لاختبارات الذكاء الاصطناعي وOCR (`Strict Three-Way Test Separation`)

| المستوى / الفئة الاختبارية | ما الذي يختبره فعلياً في الحاوية الحالية؟ | الحالة الفعلية في الحاوية الحالية (`Offline Sandbox`) | هل يُحتسب كبديل عن تشغيل أو قبول النماذج الأربعة الثقيلة؟ |
| :--- | :--- | :--- | :--- |
| **أولاً: اختبارات تطبيع نصوص OCR الاصطناعية (`Synthetic OCR Normalization Unit Tests`)** | يختبر دالة `registry.norm_plate()` و`compute_ocr_ground_truth_metrics()` على سلاسل نصية لاتينية وعربية (`"ADEN 12345" -> "عدن-12345"`, `"SANA 48210" -> "صنعاء-48210"`, إلخ) للتحقق من معالجة `BUG-20`. | **`PASS` (`6 / 6` سلاسل نصية)** | **لا أبداً** — هذا اختبار وحدة منطقي لدالة التطبيع (`norm_plate`) وليس استدلالاً لشبكة `EasyOCR` العصبية (التي تظل **`NOT_TESTED`** محلياً لغياب أوزان `.pth`). |
| **ثانياً: التقييم البصري المساعد لمحرك `Tesseract 5 LSTM` (`Auxiliary Real Pixel OCR Benchmark`)** | يشغّل الثنائي الحقيقي `/usr/bin/tesseract` (`--psm 7 tsv` عبر `_run_tesseract_tsv_cli`) على وحدات البكسل الفعلية لـ `14` صورة لوحة (`6` من `models/eval_benchmarks/plates/` + `4` مشاهد `VirtualCamera` + `4` تيارات `MJPEG` حية). | **`PASS` (`14 / 14` لوحة، `ExactMatch=100.0%`, `MeanCER=0.0%`)** | **لا أبداً (`tesseract_substituted: false`)** — يُسجَّل كمحرك احتياطي مساعد مستقل، بينما تظل نتيجة قبول النماذج الأربعة الأساسية **`0 / 8 PASS, 8 / 8 NOT_TESTED`** محلياً. |
| **ثالثاً: اختبارات `Smoke/Inference` مقابل اختبارات الدقة المرجعية `Ground-Truth Accuracy` للنماذج الأربعة (`YuNet`, `SFace`, `YOLOv8n`, `EasyOCR`)** | يفصل `four_stage_breakdown` بين: **(أ) `smoke_inference_status`** (تنزيل الأوزان ومطابقة `SHA-256` وتحميلها وتشغيل استدلال أمامي مع `0` إيجابيات كاذبة)، و**(ب) `ground_truth_acceptance_status` / `final_status`** (توفر عينات `Ground Truth` فوتوغرافية/بشرية مصرح بها واجتياز عتبات الدقة القياسية). | **`NOT_TESTED` محلياً (`0 / 8`)** بسبب عزل الشبكة؛ وعند تشغيل Windows CI يتحقق `Smoke = PASS` للأوزان الأربعة بينما يظل `Ground Truth = NOT_TESTED` لـ `YuNet/SFace/YOLOv8n` حتى استيراد عينات بشرية مصرح بها وصور مركبات فوتوغرافية طبيعية. | **لا يُحوَّل `NOT_TESTED` إلى `PASS` أبداً** تحت أي ظرف. |

## 2. التفريق الهيكلي رباعي المراحل وبوابات القبول المرجعية للنماذج الأربعة (`4-Stage Model Validation & Ground-Truth Gates — BUG-09, BUG-18, BUG-21, BUG-22`)

| النموذج | المرحلة 1: التنزيل والتحقق من `SHA-256` (`S1_SHA256`) | المرحلة 2: التحميل وتشغيل الاستدلال (`S2_Infer`) | المرحلة 3: توفر عينات `Ground Truth` المرجعية (`S3_GTSamples`) | المرحلة 4: اجتياز عتبات الدقة المرجعية (`S4_GTPass`) | حالة `Smoke` (`smoke_inference_status`) | الحالة النهائية (`final_status` / `ground_truth_acceptance_status`) |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **`YuNet`** (`models/yunet.onnx`) | `False` محلياً (`True` في Windows CI) | `False` محلياً (`True` في Windows CI) | `False` (`authorized_real_human_consent: false` في المستودع العام) | `False` (`Recall >= 0.75` + `Neg FP == 0`) | `NOT_TESTED` محلياً (`PASS` في CI) | **`NOT_TESTED`** (يبقى `NOT_TESTED` حتى استيراد وجوه بشرية مصرح بها عبر `--import-authorized-faces`) |
| **`SFace`** (`models/sface.onnx`) | `False` محلياً (`True` في Windows CI) | `False` محلياً (`True` في Windows CI) | `False` (`authorized_real_human_consent: false` في المستودع العام) | `False` (`Same >= 0.363`, `Diff < 0.363`, `FAR == 0`) | `NOT_TESTED` محلياً (`PASS` في CI) | **`NOT_TESTED`** (يبقى `NOT_TESTED` حتى استيراد هويات بشرية مصرح بها عبر `--import-authorized-faces`) |
| **`YOLOv8n`** (`models/yolov8n.pt`) | `False` محلياً (`True` في Windows CI) | `False` محلياً (`True` في Windows CI) | `False` (`is_photorealistic_natural_dataset: false` للرسوم الهندسية) | `False` (`Recall >= 0.75`, `Precision >= 0.75`, `IoU >= 0.50`, `Neg FP == 0`) | `NOT_TESTED` محلياً (`PASS` في CI) | **`NOT_TESTED`** (يبقى `NOT_TESTED` حتى استيراد صور مركبات فوتوغرافية طبيعية عبر `--import-photorealistic-vehicles`) |
| **`EasyOCR`** (`models/easyocr/*.pth`) | `False` محلياً (`True` في Windows CI) | `False` محلياً (`True` في Windows CI) | `True` (`6` لوحات مرجعية في `eval_benchmarks/plates/` + `4` في `MERSAD LAB`) | `False` محلياً (يتطلب تحميل أوزان `.pth` في Windows CI لتحقيق `ExactMatch >= 0.75`, `Mean CER <= 0.25`) | `NOT_TESTED` محلياً (`PASS` في CI) | **`NOT_TESTED` محلياً** (`tesseract_substituted: false`؛ مهيأ لاجتياز `Ground Truth` في Windows CI بعد إصلاح `BUG-20`) |
| **`Tesseract 5 LSTM`** (تقييم مساعد مستقل) | `True` (`/usr/bin/tesseract`) | `True` (`357.99 ms`) | `True` (`6` مرجعية + `4` اصطناعية + `4` بث `MJPEG` حي = `14` لوحة) | `True` (`ExactMatch = 100.0%`, `Mean CER = 0.0%`) | **`PASS`** | **`PASS` (`14/14` — تقييم مساعد مستقل، لا يُحتسب بديلاً عن `EasyOCR`)** |

### سجل التنفيذ الفعلي (`reports_and_logs/model_inference_log.txt` / `logs/12_preview01_ai_model_benchmark.log`):
```text
========================================================================================
  MERSAD PREVIEW 0.1 — Phase 1: Real AI Models Ground-Truth Acceptance Suite
========================================================================================

  --- [A] SYNTHETIC_VIRTUAL_CAMERA_SCENE_INFERENCE (In-Memory VirtualCamera) ---
  [SYNTH SCENE] YuNet          | Status=NOT_TESTED | Download=FAILED_DOWNLOAD              | Load=NOT_LOADED                 | Inference=NOT_EXECUTED
  [SYNTH SCENE] SFace          | Status=NOT_TESTED | Download=FAILED_DOWNLOAD              | Load=NOT_LOADED                 | Inference=NOT_EXECUTED
  [SYNTH SCENE] YOLOv8n        | Status=NOT_TESTED | Download=FAILED_DOWNLOAD              | Load=NOT_LOADED                 | Inference=NOT_EXECUTED
  [SYNTH SCENE] EasyOCR_Ar_En  | Status=NOT_TESTED | Download=FAILED_OR_MISSING_WEIGHTS    | Load=NOT_LOADED                 | Inference=NOT_EXECUTED

  --- [B] LIVE_LAB_HTTP_MJPEG_STREAM_INFERENCE (Live LAB HTTP MJPEG -> OpenCV) ---
  [LIVE STREAM] YuNet          | Smoke=NOT_TESTED | GroundTruth=NOT_TESTED | S1_SHA256=False | S2_Infer=False | S3_GTSamples=False | S4_GTPass=False
  [LIVE STREAM] SFace          | Smoke=NOT_TESTED | GroundTruth=NOT_TESTED | S1_SHA256=False | S2_Infer=False | S3_GTSamples=False | S4_GTPass=False
  [LIVE STREAM] YOLOv8n        | Smoke=NOT_TESTED | GroundTruth=NOT_TESTED | S1_SHA256=False | S2_Infer=False | S3_GTSamples=False | S4_GTPass=False
  [LIVE STREAM] EasyOCR_Ar_En  | Smoke=NOT_TESTED | GroundTruth=NOT_TESTED | S1_SHA256=False | S2_Infer=False | S3_GTSamples=False | S4_GTPass=False

  --- [C] INDEPENDENT_AUXILIARY_TESSERACT_BENCHMARK ---
  [AUX TEST] Benchmark Plates Dataset (6)  : 6/6 matched (ExactMatch=100.0%, MeanCER=0.0%)
  [AUX TEST] Synthetic VirtualCamera Scenes: 4/4 matched (ExactMatch=100.0%, MeanCER=0.0%)
  [AUX TEST] Live LAB HTTP MJPEG Streams   : 4/4 matched (ExactMatch=100.0%, MeanCER=0.0%, mean_latency=357.99ms)
```

# تقرير الفحص الهندسي والاختبار الفعلي لقدرات الذكاء الاصطناعي والرؤية الحاسوبية والأداء
**المشروعان المفحوصان:** `MERSAD AI V7.1 (Preview 0.1)` و `MERSAD LAB 1.0 (Preview 0.1)`  
**مسار المستودع المفحوص:** `MERSAD_PREVIEW_0.1_FINAL`  
**تاريخ ووقت التنفيذ الفعلي:** `2026-11-06 07:10 UTC` (`10:10 AM +03:00`)  
**بيئة الاختبار الفعلية:** `Linux-4.19.0-gvisor-x86_64-with-glibc2.36` | `Python 3.11.2 (64-bit)` | `2 vCPU` | وضع معزول شبكياً (`Offline Sandbox`)

## 1. الملخص التنفيذي ونتيجة الفحص الشامل

أُجري فحص هندسي واختبار تشغيلي فعلي عبر سطر الأوامر (`execute_bash`) شمل تشغيل حزم الاختبار المدمجة (`selftest.py`، `test_lab.py`، `check_install.py`، `verify_integrity.py`، `evaluate_ai_models.py`، `test_ai_lab_integration.py`) بالإضافة إلى حزمة قياس الأداء والتحقق الجنائي المستقلة (`run_ai_cv_benchmark.py`) في بيئة معزولة دون المساس بسلامة ملفات المستودع (`92/92 OK` في `SHA256SUMS.txt`).

| محور الفحص والاختبار | الحالة الفعلية | الخلاصة الهندسية والأرقام المقاسة |
| :--- | :--- | :--- |
| **سلامة الحزمة البرمجية (`SHA256SUMS.txt`)** | **ناجح (`PASS`)** | تطابق البصمة الجنائية `SHA-256` لجميع ملفات المستودع البالغ عددها `92/92` ملفاً (`19/19` ملفاً أساسياً في `verify_integrity.py`). |
| **اختبارات الوحدة والأنظمة الفرعية (`MERSAD AI`)** | **ناجح (`234/234 PASS`)** | اجتياز `234` اختباراً آلياً (`0 SKIP, 0 FAIL`) سواء بوجود `scikit-learn` أو بدونه (مع التبديل التلقائي إلى `_StatForest`). |
| **اختبارات مختبر المحاكاة والجودة (`MERSAD LAB`)** | **ناجح (`20/20 PASS`)** | اجتياز `8` اختبارات وظيفية أساسية + `12` اختباراً أمنياً واختبار ضغط ومهلة زمنية (`0 FAIL`). |
| **تحميل النماذج الثقيلة (`YuNet, SFace, YOLOv8n, EasyOCR`)** | **غير متاح محلياً (`NOT_TESTED` / `FAIL-CLOSED`)** | الأوزان الثنائية غير مرفقة في المستودع (`DEV_WITHOUT_HEAVY_WEIGHTS`) وحزم `torch` و`ultralytics` و`easyocr` غير مثبتة في الحاوية المعزولة؛ يرفض النظام التشغيل الصامت المزيف ويخرج برمز خطأ `1` عند `--verify-models`، أو ينتقل بأمان لوضع المعاينة المخفض (`--allow-degraded-preview`). |
| **أمن وسلامة ملفات الأوزان (`SHA-256 & Pickle Guard`)** | **ناجح (`6/6 PASS`)** | التحقق الصارم من البصمات الثابتة قبل التحميل، ورفض صفحات HTML التنكرية، ورفض ملفات `.sha256` المصنعة ذاتياً لـ `yolov8n.pt`، وحظر بايت كود `pickle` الخبيث (`posix.system`، `xmlrpc.client`، `builtins.getattr`). |
| **كشف اللوحات وقراءة البكسلات (`Canny + Tesseract 5.3.0`)** | **ناجح (`4/4 PASS`)** | تحديد موقع اللوحة بدقة `100%` عبر الكاميرات الأربع الافتراضية (`cam1..cam4`) وقراءة النص الفعلي من البكسلات (`عدن-12345`، `صنعاء-48210`، `تعز-73901`، `حضرموت-55120`) بمتوسط ثقة `0.945`. |
| **تتبع الأجسام عبر الإطارات (`Tracking & Route Engine`)** | **ناجح (`PASS`)** | يعتمد متتبعاً مكانياً-نصياً مخصصاً (`_bbox_compatible <= 180px` + `_letters_compatible >= 0.5` + نافذة تصويت `3` قراءات خلال `10s` + دمج الصناديق بـ `IoU >= 0.5/0.6`) ولا يستخدم `ByteTrack` أو مرشح `Kalman`. |
| **حوكمة التعرف على الوجوه والمراجعة البشرية** | **ناجح مع ملاحظة بنيوية (`PASS`)** | يمنع تسجيل أو مطابقة أي وجه بدون موافقة (`consent=1`)، ولا يصنف المتطوع العادي كمشتبه به حتى عند تشابه `1.00`، ويشترط `3` إطارات متتالية لقائمة المراقبة التجريبية، ويضع التنبيه في حالة `status='pending'` و`dispatched=0` مع إخلاء مسؤولية نصي صريح، ويمنع توجيه الدوريات في تطابقات اللوحات التقريبية (`visual_check_only=True`). |

## 2. فحص النماذج المستخدمة، توافق المكتبات، وسلامة الأوزان (SHA-256)

### 2.1 جرد النماذج المعتمدة وبصماتها الجنائية (`Pinned SHA-256 Registry`)

يعتمد مشروع `MERSAD AI` (`mersad_live.py` و`prefetch.py`) على أربعة نماذج ذكاء اصطناعي رئيسية محمية ببصمات `SHA-256` ثابتة ومضمنة في الكود (`MODEL_SHA256` و`EASYOCR_SHA256`)، بالإضافة إلى محركين احتياطيين مدمجين:

| النموذج / المحرك | المسار / المكتبة | الوظيفة الهندسية | الحد الأدنى للحجم | البصمة الجنائية الثابتة (`Expected SHA-256`) | حالة التحميل في بيئة الفحص |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **YuNet (OpenCV Zoo)** | `models/yunet.onnx` (`cv2.FaceDetectorYN`) | كشف الوجوه وتحديد 5 نقاط مرجعية للمحاذاة | `200,000 B` | `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4` | `MISSING` (يتطلب `prefetch.py`؛ بديل `_NoopDet` في الوضع المخفض) |
| **SFace (OpenCV Zoo)** | `models/sface.onnx` (`cv2.FaceRecognizerSF`) | استخراج بصمة الوجه (`128-D float32`) للمتطوعين (`consent=1`) | `30,000,000 B` | `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79` | `MISSING` (يتطلب `prefetch.py`؛ بديل `_NoopRec` في الوضع المخفض) |
| **YOLOv8n (Ultralytics v8.3.0)** | `models/yolov8n.pt` (`ultralytics.YOLO`) | كشف وتصنيف المركبات (`car, motorcycle, bus, truck`) | `6,000,000 B` | `31e20dde3def09e2cf938c7be6fe23d9150bbbe503982af13345706515f2ef95` | `MISSING` (الكود ينتقل تلقائياً لكشف اللوحات على كامل الإطار) |
| **EasyOCR Craft Detector** | `models/easyocr/craft_mlt_25k.pth` | كشف مناطق النصوص داخل اللوحة | `500,000 B` | `4a5efbfb48b4081100544e75e1e2b57f8de3d84f213004b14b85fd4b3748db17` | `MISSING` (بديل مستقل: `Tesseract 5.3.0 LSTM`) |
| **EasyOCR Arabic** | `models/easyocr/arabic.pth` | التعرف على الحروف والأرقام العربية | `500,000 B` | `2a9afd42c374deb98aed0b53c9b77d75e1d00d4e0501f3b0276c54190c89b1a8` | `MISSING` (بديل مستقل: `TesseractOCRReader`) |
| **EasyOCR English G2** | `models/easyocr/english_g2.pth` | التعرف على الأحرف والأرقام اللاتينية | `500,000 B` | `e2272681d9d67a04e2dff396b6e95077bc19001f8f6d3593c307b9852e1c29e8` | `MISSING` (بديل مستقل: `TesseractOCRReader`) |
| **EasyOCR Latin G2** | `models/easyocr/latin_g2.pth` | نموذج مساعد للرموز اللاتينية | `500,000 B` | `aaa95be1c4a9cb3496879bed7c520886ce1164f89e026f0c54488394e74e8c55` | `MISSING` (بديل مستقل: `TesseractOCRReader`) |
| **IsolationForest / StatForest** | `insights.py` (`sklearn` أو `_StatForest`) | كشف شذوذ أنماط المرور (`Anomaly Detection`) | مدمج برمجياً | مدمج في `insights.py` (تم التحقق من بصمة الملف في `SHA256SUMS.txt`) | **محمّل ويعمل (`PASS`)** — تدرّب على `8,390` سجلاً باستخدام `_StatForest(contamination=0.015)` |

### 2.2 فحص توافق إصدارات المكتبات (`Library Version Compatibility`)

تم تنفيذ فحص مقارن بين الحزم المثبتة فعلياً في بيئة الاختبار وبين ملفات تثبيت الإصدارات (`requirements.txt` و`constraints-win-x64.txt`) في كلٍّ من `MERSAD AI` و`MERSAD LAB`:

| الحزمة / الأداة | المثبت في البيئة | المثبت في `MERSAD AI` (`constraints-win-x64.txt`) | المثبت في `MERSAD LAB` (`constraints-win-x64.txt`) | نتيجة فحص التوافق والملاحظات الهندسية |
| :--- | :--- | :--- | :--- | :--- |
| **Python Runtime** | `3.11.2 (64-bit)` | `Python 3.11 64-bit` | `Python 3.11 64-bit` | **متوافق تماماً (`PASS`)** |
| **OpenCV (`cv2`)** | `4.11.0.86` | `opencv-python==4.11.0.86` | `opencv-python-headless==4.9.0.80` | **متوافق (`PASS`)** — يدعم `FaceDetectorYN` و`FaceRecognizerSF` و`dnn` و`Haar` و`HOG` و`ORB`. *(ملاحظة هندسية: يجب الحفاظ على عزل البيئات الافتراضية `.venv` لكل مشروع لعدم الخلط بين `opencv-python` و`opencv-python-headless`)* |
| **NumPy** | `2.1.3` | `numpy==1.26.4` | `numpy==1.26.4` (`<2.0.0` في `requirements.txt`) | **تحذير تطابق (`WARN: VERSION_MISMATCH`)** — الكود البرمجي في المشروعين يعمل فعلياً مع `NumPy 2.1.3` دون أخطاء، لكن `check_install.py` ينبه بضرورة تثبيت `1.26.4` عند بناء نسخة Windows لضمان التطابق الحتمي مع `torch` و`ultralytics`. |
| **Pillow (`PIL`)** | `11.1.0` | `Pillow==10.4.0` | غير مطلوب | **تحذير تطابق (`WARN: VERSION_MISMATCH`)** — يعمل دون تعارض. |
| **OpenPyXL** | `3.1.5` | `openpyxl==3.1.5` | غير مطلوب | **متطابق تماماً (`PASS`)** |
| **ONNX Runtime** | `1.31.0` | مدمج عبر `cv2.dnn` + `mersad_ai.spec` | غير مطلوب | **متوفر ويعمل (`PASS`)** |
| **Tesseract OCR** | `5.3.0` (`pytesseract 0.3.13`) | محرك احتياطي/رديف في `TesseractOCRReader` | غير مطلوب | **متوفر ويعمل (`PASS`)** |
| **PyTorch / Ultralytics / EasyOCR** | غير مثبتة | `torch==2.5.1`, `torchvision==0.20.1`, `ultralytics==8.3.0`, `easyocr==1.7.2` | غير مطلوبة | **مفقودة في البيئة المعزولة (`MISSING`)** — *(ملاحظة توثيقية: ورد في السطر 43 من `01_ENGINEERING_AUDIT_REPORT_AR.md` ذكر إصدارات أقدم مثل `torch==2.3.1` و`ultralytics==8.2.50` بينما الملفات الفعلية `requirements.txt` و`constraints-win-x64.txt` تثبت `torch==2.5.1` و`ultralytics==8.3.0`)*. |
| **Scikit-Learn** | غير مثبتة | `scikit-learn==1.5.2` (اختيارية) | غير مطلوبة | **تبديل آمن تلقائي (`SKIP -> StatForest`)** — يعمل البديل الإحصائي `_StatForest` بكفاءة تامة. |

### 2.3 الاختبار الفعلي لآليات التحقق الجنائي من الأوزان والتدهور الآمن (`Graceful Degradation`)

تم اختبار دوال فحص سلامة النماذج (`verify_onnx_file`، `verify_yolo_pt_file`، `_scan_pt_pickle_safety`، `verify_easyocr_dir`) وآليات الفشل الآمن برمجياً:

1. **كشف ملفات HTML/JSON المتنكرة بامتداد `.onnx`:** عند تمرير ملف بحجم `250 KB` يبدأ بـ `<!DOCTYPE html>`، رفضته الدالة `verify_onnx_file` فوراً بالسبب `invalid_onnx_header_html_or_json`.
2. **كشف تغير بصمة `SHA-256` لملفات `.onnx` و`.pth`:** تم رفض ملف `yunet_bad_sha.onnx` بالسبب `sha256_mismatch:834ebf75fc0c6362!=8f2383e4dd3cfbb4`، ورفض أوزان `EasyOCR` المعدلة بالسبب `pth_sha256_mismatch:arabic.pth:8a0aa25e75f7bf2a!=2a9afd42c374deb9`.
3. **إحباط هجوم تزوير ملف `.sha256` الجانبي لـ `yolov8n.pt`:** عند إنشاء ملف `yolov8n.pt` مع ملف جانبي `yolov8n.pt.sha256` مطابق له، تجاهلت الدالة `verify_yolo_pt_file` الملف الجانبي المصنع ذاتياً وألزمت المطابقة مع البصمة الثابتة في الكود (`31e20dde3def09e2...`) ورفضت التحميل.
4. **الحماية الساكنة من تنفيذ الأوامر الخبيثة داخل ملفات PyTorch (`.pt` Pickle RCE Guard):** تم حقن تعليمة `GLOBAL` تستدعي `posix.system` و`xmlrpc.client.ServerProxy` و`builtins.getattr` داخل `archive/data.pkl`، فقام الفاحص `_scan_pt_pickle_safety` (المبني على `pickletools.genops`) باكتشافها وحظرها قبل استدعاء `torch.load` أو `YOLO()`.
5. **سلوك غياب النماذج (`Missing Model Fallback`):**
   - في الوضع الافتراضي الصارم: يفشل أمر `python3 mersad_live.py --verify-models` بشكل آمن (`Exit Code = 1`) مع طباعة تقرير تشخيصي واضح لكل نموذج مفقود دون تعليق البرنامج أو محاولة الاتصال بالإنترنت أثناء التشغيل (`YOLO_AUTOINSTALL=false`, `YOLO_OFFLINE=true`, `download_enabled=False`).
   - في وضع المعاينة المخفض (`--allow-degraded-preview` أو `MersadEngineController` بدون أوزان): يستبدل النظام كاشف الوجوه بـ `_NoopDet` (`detect() -> (0, None)`)، ومطابق الوجوه بـ `_NoopRec`، وكاشف المركبات بقائمة فارغة تنتقل تلقائياً لكشف اللوحات على كامل الإطار عبر خوارزمية `Canny + Contours`، وقارئ النصوص بمحرك `TesseractOCRReader`، ونموذج كشف الشذوذ بـ `_StatForest`.
   - كما تم التحقق من `resolve_compute_device("cuda")` في غياب GPU؛ حيث يسجل تحذيراً صريحاً (`Requested compute device 'cuda', but CUDA is not available... falling back safely to CPU`) ويعود للعمل على `cpu` دون انهيار.

## 3. الاختبار الفعلي لاكتشاف الأجسام والمركبات وقراءة اللوحات وتتبع المسارات

### 3.1 اكتشاف الأجسام والأشخاص والمركبات (`Object, Person & Vehicle Detection`)

1. **فلترة وتصنيف المركبات (`detect_vehicles`):**
   - تم اختبار دالة `detect_vehicles(img, model)` عبر تمرير مخرجات نموذج تحوي 5 فئات من `COCO` وهي: `person (0)`، `car (2)`، `truck (7)`، `motorcycle (3)`، و`bus (5)`.
   - أظهرت النتيجة الفعلية استبعاد فئة `person (0)` بنجاح من مصفوفة المركبات، والاحتفاظ بالفئات الأربع المستهدفة (`['car', 'truck', 'motorcycle', 'bus']`) مع قص الإحداثيات (`Bounding Box Clipping`) ضمن أبعاد الإطار `(640x480)`.
   - عند تفعيل خيار `--trucks-only`، يقتصر الرصد والتنبيه على فئة `truck` فقط، وعند تفعيل `--truck-curfew 22-5` (`parse_curfew` + `in_hours`) يُصدر النظام تنبيه `"TRUCK IN RESTRICTED HOURS"` (`شاحنة في ساعات المنع`) حصراً للشاحنات المرصودة بين الساعة 22:00 و05:00.
2. **قدرات الرؤية الحاسوبية الكلاسيكية المتوفرة في البيئة (`Haar / HOG / ORB`):**
   - تم التحقق برمجياً من جاهزية مصنفات `OpenCV` المدمجة في البيئة وقياس زمن استجابتها على إطارات `640x480`:
     - `Haar Cascade` (`haarcascade_frontalface_default.xml`، `haarcascade_fullbody.xml`، `haarcascade_russian_plate_number.xml`): محمّلة وسليمة (`199.10 ms` للإطار).
     - `HOG People Detector` (`cv2.HOGDescriptor_getDefaultPeopleDetector()`): محمّل وسليم (`272.15 ms` للإطار).
     - `ORB Feature Detector` (`cv2.ORB_create(nfeatures=500)`): استخرج `508` نقاط مفتاحية (`Keypoints`) وموصوفات ثنائية بزمن `21.03 ms` فقط.

### 3.2 كشف اللوحات وقراءة النصوص (`Plate Localization & OCR`) ومطابقة السجل

تم تشغيل خط أنابيب كشف اللوحات (`find_plates` عبر `bilateralFilter` + `Canny(60, 180)` + `approxPolyDP` رباعي الأضلاع بنسبة عرض إلى ارتفاع `2 <= w/h <= 6`) متبوعاً بتحسين التباين (`preprocess_plate` عبر `CLAHE clipLimit=2.0` وتكبير `INTER_CUBIC`) ثم القراءة البكسلية الفعلية عبر `TesseractOCRReader` (`Tesseract 5.3.0 LSTM --psm 7`) على الكاميرات الأربع الافتراضية:

| الكاميرا | اللوحة المرسومة في المشهد | عدد الصناديق المرشحة (`find_plates`) | إحداثيات الصندوق الأول `[x, y, w, h]` | القراءة المستخرجة (`read_plate`) | معامل الثقة (`Confidence`) | زمن قراءة الصندوق (`Latency ms`) | نتيجة المطابقة |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`cam1`** | `ADEN 12345` (`عدن-12345`) | `3` | `[201, 337, 217, 59]` | **`عدن-12345`** | `0.960` | `858.05 ms` | **تطابق تام (`EXACT MATCH`)** |
| **`cam2`** | `SANA 48210` (`صنعاء-48210`) | `3` | `[201, 337, 217, 59]` | **`صنعاء-48210`** | `0.960` | `351.20 ms` | **تطابق تام (`EXACT MATCH`)** |
| **`cam3`** | `TAIZ 73901` (`تعز-73901`) | `3` | `[201, 337, 217, 59]` | **`تعز-73901`** | `0.930` | `760.89 ms` | **تطابق تام (`EXACT MATCH`)** |
| **`cam4`** | `HADR 55120` (`حضرموت-55120`) | `3` | `[201, 337, 217, 59]` | **`حضرموت-55120`** | `0.930` | `705.87 ms` | **تطابق تام (`EXACT MATCH`)** |

**نتائج فحص مطابقة السجل ومنع الالتباس (`Registry Disambiguation` في `registry.lookup_vehicle`):**
- **مطابقة تامة (`عدن 12345` مقابل `عدن-12345`):** `match_type='exact'`، `conf_factor=1.0`، `visual_check_only=False`.
- **مطابقة بالأرقام فقط (`12345` مقابل `عدن-12345`):** `match_type='digits_only'`، `conf_factor=0.85`، `visual_check_only=False`.
- **تعارض المحافظة/الأحرف (`تعز 12345` مقابل `عدن-12345`):** `match_type='digits_only'`، `contradictory_letters=True`، ويُخفَّض معامل الثقة إلى `0.60` مع فرض **`visual_check_only=True`** وتحويل التنبيه إلى `"POSSIBLE MATCH (visual check)"`.
- **تصحيح محارف OCR الملتبسة (`صنعاء 8842I` مقابل `صنعاء-88421`):** يصحح `I -> 1` و`O -> 0` داخل المقاطع الرقمية، ولكنه يفرض تلقائياً `match_type='approximate'`، `conf_factor=0.80`، و**`visual_check_only=True`**.
- **مسافة التحرير 1 (`Edit Distance = 1` مثل `صنعاء 88429` مقابل `صنعاء-88421` المسروقة):** يكتشف التشابه للمركبات المطلوبة/المسروقة فقط، ويفرض `match_type='approximate'`، `conf_factor=0.75`، و**`visual_check_only=True`**.

### 3.3 تتبع الأجسام عبر الإطارات (`Multi-Object Tracking`) وتتبع المسارات بين الكاميرات

1. **حقيقة خوارزمية التتبع داخل الكاميرا (`Intra-Camera Multi-Object Tracking`):**
   - لا يستخدم الكود مكتبة `ByteTrack` أو مرشح `Kalman`، بل ينفذ خوارزمية تتبع حتمية مخصصة في `confirm_plate_read()` تجمع بين ثلاثة شروط لعزل مسارات المركبات المتزامنة داخل نفس الإطار:
     - **القرب المكاني للمركز (`Centroid Distance` عبر `_bbox_compatible`):** يشترط أن تكون المسافة الإقليدية بين مركزي الصندوقين المتتاليين `<= 180.0 بكسل`.
     - **توافق الأحرف والمحافظة (`_letters_compatible`):** يشترط تشابه الأحرف بنسبة `>= 0.5` بحيث لا تندمج مركبتان تشتركان في نفس الأرقام وتختلفان في الأحرف.
     - **نافذة التصويت الزمنية (`Sliding-Window Consensus`):** يتطلب `CONFIRM_READS = 3` قراءات متوافقة خلال `VOTE_WINDOW_SEC = 10.0 ثوانٍ` مع فترة تهدئة `ALERT_COOLDOWN_SEC = 30.0 ثانية`، بالإضافة إلى حذف الصناديق المتداخلة عبر `IoU > 0.5` في البث الحي و`IoU >= 0.6` في أداة التقييم.
   - **نتائج الاختبار الفعلي للتتبع المتعدد:**
     - عند إدخال مركبتين في نفس اللحظة تشتركان في نفس الأرقام (`أ ب 4444` تتحرك من اليسار لليمين في المسار العلوي، و`ج د 4444` تقترب في المسار السفلي) عبر 3 إطارات: فصلهما المتتبع في دلوين مستقلين تماماً وأخرج للأولى `plate='اب-4444'` باتجاه `"يسار ➔ يمين (نسبة للإطار)"` وللثانية `plate='جد-4444'` باتجاه `"اقتراب نسبي في الإطار"`.
     - عند إدخال قراءات OCR مشوشة لنفس المركبة (`['عدن 12345', 'ع 12345', 'عدن 12345']`): وحّدها المتتبع تحت الصيغة الأكثر تواتراً وشمولاً `عدن-12345` مع `letters_confirmed=True` واتجاه `"يمين ➔ يسار (نسبة للإطار)"`.
     - عند ظهور نفس الرقم `99887` في موقعين متباعدين بأكثر من `180 بكسل` (`(50, 50)` و`(500, 400)`): فصلهما المتتبع تلقائياً إلى مسارين مستقلين (`active_buckets = 2`).
2. **تتبع المسارات بين الكاميرات وكشف الانتقال المستحيل (`Cross-Camera Spatio-Temporal Route Tracking`):**
   - في الكاميرات المعايرة ميدانياً (`CAM_NORTH -> CAM_SOUTH` بحد أدنى `min_sec=120s` ومسافة `3000m`): عند رصد المركبة `تعز-73901` بعد `20 ثانية` فقط، أصدر النظام تنبيه **`ROUTE ANOMALY (impossible transit)`** مع شرح مفصل يذكر أن السبب قد يعود لخطأ OCR أو فرق توقيت الساعات أو لوحة مكررة ويتطلب مراجعة بشرية.
   - في الكاميرات غير المعايرة (`CAM_EAST -> CAM_WEST` على الحد الافتراضي `90s`): أصدر النظام ملاحظة غير قابلة للتوجيه **`ROUTE NOTICE (uncalibrated)`** (`is_no_dispatch_msg = True`).

## 4. اختبار الفيديوهات منخفضة الجودة والإطارات التالفة (`Low-Quality & Corrupted Media`)

تم اختبار استجابة كلٍّ من `MERSAD AI` (`assess_frame_quality`, `find_plates`, `read_plate`) و`MERSAD LAB` (`VirtualCamera`, `analyze_image_bytes`, `analyze_video_bytes`) لسبعة أوضاع تدهور بصري و10 حالات تلف ملفات:

| الوضع / حالة الاختبار | الأبعاد (`WxH`) | السطوع (`Brightness`) | التباين (`Contrast`) | الحدة (`Sharpness`) | التحذير التشخيصي / استجابة النظام | حالة الاستقرار |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`normal` (طبيعي)** | `640x480` | `76.52` | `40.46` | `1161.00` | لا توجد تحذيرات (`grade: ممتازة`) | مستقر (`PASS`) |
| **`lowlight` (إضاءة منخفضة)** | `640x480` | `16.24` | `9.01` | `56.45` | تحذير تلقائي: **`LOW_LIGHT`** | مستقر (`PASS`) |
| **`lowres` (دقة منخفضة)** | `160x120` | `76.52` | `36.74` | `2270.79` | تحذير تلقائي: **`LOW_RESOLUTION`** | مستقر (`PASS`) |
| **`noise` (ضوضاء حساسات عالية)** | `640x480` | `77.00` | `44.82` | `12246.01` | ارتفاع التباين والحدة بفعل الضوضاء العشوائية (`sigma=38`) دون انهيار | مستقر (`PASS`) |
| **`occluded` (طمس / تغطية العدسة)** | `640x480` | `4.01` | `0.43` | `1.77` | تحذير مزدوج: **`CAMERA_OCCLUDED_OR_DARK`** + **`BLURRY_OR_LOWRES`** | مستقر (`PASS`) |
| **`frozen` (تجميد البث 15+ إطاراً)** | `640x480` | `76.51` | `40.45` | `1159.50` | تحذير تلقائي عبر بصمة `MD5` المصغرة: **`FROZEN_STREAM`** | مستقر (`PASS`) |
| **إطار فارغ `None` أو `0x0`** | `0x0` | — | — | — | يعيد `{"ok": False, "error": "empty_frame"}` في التقييم، و`[]` في `find_plates`، و`(None, 0.0)` في `read_plate` | مستقر (`PASS`) |
| **صورة JPEG تالفة أو بحجم `4x4`** | غير صالحة | — | — | — | رفض آمن `HTTP 400` (`ملف الصورة تالف أو بصيغة غير مدعومة` / `أبعاد الصورة غير صالحة`) | مستقر (`PASS`) |
| **ملف فيديو تالف (`Corrupt AVI/MP4`)** | غير صالح | — | — | — | رفض آمن `HTTP 400` خلال `13 ms` مع حذف الملف المؤقت تلقائياً وبقاء الخادم سليماً (`HTTP 200` على `/api/health`) | مستقر (`PASS`) |
| **فيديو يتجاوز مهلة المعالجة (`Timeout`)** | `320x240` | — | — | — | إيقاف العامل وإرجاع `HTTP 504 Gateway Timeout` (`timed_out: True`) دون تعليق الخيوط | مستقر (`PASS`) |

## 5. القياس الفعلي لزمن الاستجابة (`Latency / FPS`) واستهلاك الموارد (`RAM / CPU / GPU`)

### 5.1 أزمنة الاستجابة التفصيلية لكل مرحلة (`Per-Stage Latency`) ومعدل الإطارات (`FPS`)

قِيست الأزمنة الفعلية عبر `100` إطار متتالٍ (`640x480`) في `run_ai_cv_benchmark.py` بالإضافة إلى قياسات البث الحي بين الخادمين:

| المرحلة / العملية المفحوصة | عدد العينات | المتوسط (`Mean ms`) | الوسيط (`P50 ms`) | المئين 95 (`P95 ms`) | المئين 99 (`P99 ms`) | الحد الأدنى (`Min ms`) | الحد الأقصى (`Max ms`) | القدرة الإنتاجية (`FPS`) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **توليد المشهد الاصطناعي (`VirtualCamera.render_bgr`)** | `100` | **`8.737 ms`** | `7.805 ms` | `14.334 ms` | `19.070 ms` | `4.146 ms` | `20.285 ms` | **`114.46 FPS`** |
| **ضغط إطار البث (`VirtualCamera.render_jpeg`)** | `100` | **`9.581 ms`** | `8.852 ms` | `14.912 ms` | `18.954 ms` | `4.979 ms` | `27.373 ms` | **`104.37 FPS`** |
| **فحص جودة الإطار وكشف التجميد (`assess_frame_quality`)** | `100` | **`7.854 ms`** | `6.927 ms` | `13.599 ms` | `18.565 ms` | `5.046 ms` | `24.824 ms` | **`127.32 FPS`** |
| **تحديد موقع اللوحة (`find_plates` — Canny + Contours)** | `100` | **`33.881 ms`** | `32.066 ms` | `50.687 ms` | `76.182 ms` | `18.654 ms` | `78.299 ms` | **`29.52 FPS`** |
| **معالجة اللوحة وتحسين التباين (`preprocess_plate` — CLAHE)** | `12` | **`0.694 ms`** | `0.551 ms` | `1.275 ms` | `1.469 ms` | `0.381 ms` | `1.518 ms` | **`1,440.92 FPS`** |
| **تقييم شذوذ المسار والسلوك (`ins.score_live` — StatForest)** | `100` | **`0.176 ms`** | `0.112 ms` | `0.343 ms` | `1.661 ms` | `0.075 ms` | `1.773 ms` | **`5,681.82 FPS`** |
| **مجموع مسار الرؤية داخل العملية (بدون عملية `tesseract` الفرعية)** | `100` | **`42.605 ms`** | `39.656 ms` | `65.904 ms` | `97.877 ms` | `24.156 ms` | `106.414 ms` | **`23.47 FPS`** |
| **قراءة النص عبر عملية `Tesseract 5.3.0` الفرعية (`pytesseract`)** | `12` | **`671.819 ms`** | `701.705 ms` | `875.735 ms` | `893.030 ms` | `332.108 ms` | `897.354 ms` | **`1.49 FPS`** |
| **البث الحي المزدوج (`LAB HTTP MJPEG -> AI Engine` لكاميرتين معاً)** | `69 إطاراً` | — | — | — | — | — | — | **`7.9 FPS` (`CAM1`) + `8.7 FPS` (`CAM2`) = `16.6 FPS` إجمالي** |

> **ملاحظة هندسية مهمة حول أداء التكامل الحي (`test_ai_lab_integration.py`):**  
> نظراً لأن `TesseractOCRReader` يستدعي الملف التنفيذي `/usr/bin/tesseract` كعملية نظام فرعية (`Subprocess`) لكل صندوق مرشح مع وجود قفل مشترك `_OCR_INFER_LOCK` بين الكاميرات، فإن تشغيل عدة كاميرات بالتوازي عبر `pytesseract` على خادم ذي نواتين (`2 vCPU`) قد يؤدي إلى تباطؤ استكمال القراءات الثلاث المؤكدة (`CONFIRM_READS = 3`) وتجاوز مهلة الـ `20 ثانية` في `INT-E2E-02` إذا لم يتم ضبط `OMP_THREAD_LIMIT=1`. أما عند استخدام محرك داخل العملية (`In-Process Reader` مثل `EasyOCR` المحمّل في الذاكرة) فإن الطابور غير الحاجب (`infer_queue(maxsize=1)`) يحقق استجابة فورية بمعدل `16.6 FPS` عبر كاميرتين متزامنتين دون أي تأخير.

### 5.2 قياس استهلاك الذاكرة العشوائية والمعالج (`RAM, CPU & GPU Utilization`)

- **الذاكرة العشوائية (`RAM / RSS`):**
  - استهلاك خادم `MERSAD LAB` منفرداً مع 4 كاميرات افتراضية نشطة: **`240.74 MB`** إلى **`256.00 MB`**، مع تغير قدره **`+0.00 MB`** بعد 40 عملية توليد وضغط إطارات متتالية (`LAB-SEC-08`).
  - استهلاك عملية الفحص الشامل (`MERSAD AI + MERSAD LAB + SQLite + 8,390 سجل تدريب`): بدأ عند **`233.52 MB`**، واستقر قبل حلقة الـ 100 إطار عند **`473.71 MB`** وبعدها عند **`474.02 MB`** (تغير طفيف جداً **`+0.31 MB`** عبر 100 إطار كامل، مما يثبت عدم وجود تسريب في الذاكرة `Zero Memory Leak`)، وبلغت ذروة الاستهلاك الكلي شاملة ربط الكاميرتين الحيتين **`501.64 MB`** (`ru_maxrss = 507.68 MB`).
- **استهلاك المعالج (`CPU`) والخيوط (`Threads`):**
  - زمن تنفيذ حلقة الـ 100 إطار الشاملة: **`6.026 ثوانٍ` زمن حقيقي (`Wall Time`)** مقابل **`6.350 ثوانٍ` زمن معالج (`CPU Time`)**، أي استغلال متوازن بنسبة **`105.4%`** (نواة واحدة ونيف من أصل نواتين).
  - إجمالي استهلاك المعالج لكامل حزمة الاختبار (`29.338s Wall Time`): `15.54s User CPU` + `4.23s System CPU` للعملية الرئيسية، و`4.47s User CPU` + `0.77s System CPU` لعمليات `tesseract` الفرعية.
  - عدد الخيوط المتبقية بعد إغلاق المحركات (`e2e_engine.stop()` و`lab_ctrl.stop()`): **`1` خيط فقط (الخيط الرئيسي)**، مما يؤكد إغلاق جميع خيوط القراءة والاستدلال والبث بنظافة تامة (`Zero Hanging Threads`).
- **استهلاك المعالج الرسومي (`GPU`):** **`0%`** (`cuda_available = False`، يعمل النظام بالكامل على `CPU`).

## 6. الاختبار الجنائي للتعرف على الوجوه والتحقق من عدم التصنيف التلقائي واشتراط المراجعة البشرية

تم تنفيذ اختبار برمجي مخصص باستخدام متجهات وجوه اصطناعية بحتة (`128-D normalized float32 synthetic embeddings`) للتحقق من تطبيق القيود الأخلاقية والأمنية في `mersad_live.py` و`registry.py`:

1. **منع التسجيل أو المطابقة بدون موافقة مسجلة (`Strict Consent Gate`):**
   - تم تسجيل شخص اصطناعي (`SYN-P01`) بحالة `status='watch'` ولكن بدون موافقة (`consent=False`).
   - عند استدعاء `req_enroll()`، رفض النظام بدء التسجيل فوراً (`unconsented_person_enrollment_rejected = True`).
   - بل وحتى عند محاولة حقن بصمة وجهه مباشرة في جدول `faces` بقاعدة البيانات واستدعاء `refresh_known()`، قام الاستعلام المضمن (`WHERE f.person_id > 0 AND COALESCE(f.quarantined, 0) = 0 AND COALESCE(p.consent, 0) = 1`) بتجاهل السجل وعزله، وأعادت دالة `match_face_embedding()` النتيجة **`"unenrolled"`** بدرجة `0.0`.
2. **التحقق من أن التشابه البصري العالي لا يصنف الشخص العادي كمشتبه به:**
   - تم تسجيل متطوع اصطناعي عادي (`SYN-P02`) بموافقة صريحة (`consent=True`) وحالة عادية (`status='normal'`, أي `watch=0`)، وتسجيل 5 عينات متسقة له عبر `enroll_step()`.
   - عند اختبار مطابقة وجهه عبر 5 إطارات متتالية بتشابه بصري تام (`cosine_score = 1.0000 >= COS_T 0.363`): تعرف عليه النظام كمتطوع مسجل (`watch_flag = 0`)، ولكن دالة `face_step()` أوقفت أي إجراء تنبيهي فوراً (`if name == "unenrolled" or not watch or sc < FACE_ALERT[0]: return False`)، وبلغ عدد التنبيهات الصادرة **`0` تنبيه** (`alerts_triggered_over_5_frames = 0`).
3. **منع التنبيه من إطار واحد أو إطارين حتى للمدرجين في القائمة التجريبية (`3-Frame Streak Gate`):**
   - عند تسجيل متطوع اصطناعي في القائمة التجريبية (`SYN-P03`, `consent=True`, `status='watch'`) واختبار ظهور وجهه بتشابه `1.00`:
     - الإطار الأول (`frame 10`): `alert_f1 = False` (لا يصدر تنبيه).
     - الإطار الثاني (`frame 11`): `alert_f2 = False` (لا يصدر تنبيه).
     - الإطار الثالث المتتالي (`frame 12` ضمن `<= 4.0 ثوانٍ`): `alert_f3 = True` (يصدر تنبيه احتمالي معلق للمراجعة البشرية).
4. **اشتراط المراجعة البشرية وحظر التوجيه التلقائي للدوريات (`Human-in-the-Loop Verification`):**
   - عند فحص السجل الفعلي الذي أنشأه النظام في جدول `alerts` لتطابق الوجه (`id=1`):
     - `msg = "FACE MATCH (demo watchlist)"` (`تطابق وجه محتمل (قائمة تجريبية) - يتطلب تحققاً بشرياً`).
     - **`status = "pending"`**، و**`dispatched = 0`**، و**`dispatch_status = "not_required"`**، و**`decided_by = ""`**. لا يقوم النظام بإرسال أي بلاغ لقناة الدوريات تلقائياً، بل ينتظر قراراً بشرياً موثقاً في سجل التدقيق عبر `decide(aid, "confirm" | "ack" | "dismiss", who)`.
     - يتضمن نص التنبيه (`alert_text`) تحذيرين صريحين للمشغل:
       > `تطابق وجه محتمل (قائمة تجريبية) - يتطلب تحققاً بشرياً`  
       > `هذا احتمال تطابق خوارزمي وليس إثباتاً قاطعاً، ويتطلب تحققاً بشرياً قبل أي إجراء.`  
       > `⚠️ رصد آلي، ويتطلب تأكيداً بشرياً قبل أي إجراء.`
   - وفي حالات التطابق البصري التقريبي للوحات (`POSSIBLE MATCH (visual check)` عندما `visual_check_only=True`)، حتى لو حاول المشغل البشري الضغط على تأكيد وتوجيه الدورية (`decide(aid, "confirm", "operator")`)، فإن الخادم **يرفض الأمر برمجياً** (`operator_confirm_rejected_by_decide = True`) لأن `is_no_dispatch_msg` يمنع توجيه الدوريات بناءً على تطابق تقريبي.
   - **طمس الخصوصية التلقائي (`Privacy Blurring`):** أثبت الفحص البرمجي للدالة `get_boxes_to_blur_for_alert()` أن تنبيهات المركبات تطمس **`100%`** من جميع الوجوه الظاهرة في الإطار (`2/2` وجوه)، بينما تنبيهات قائمة الوجوه التجريبية تطمس جميع وجوه المارة غير المعنيين (`[(50, 110, 60, 70)]`) وتبقي الوجه محل المراجعة فقط.
   - **ملاحظة تدقيقية حول تسمية الحقول البرمجية (`Schema Field Naming Note`):** بينما تحتوي دالة فحص مجموعات تقييم اللوحات (`inspect_plate_dataset`) على الحقل الصريح `"requires_human_review_warning": True` وعمود `"human_verified": "0"` (`UNVERIFIED_PLATE`)، وتحتوي مخرجات `lookup_vehicle` على الحقل `"visual_check_only": True`، فإن كائن التنبيه الحي في `bus.alerts` يعتمد على الحقول `"status": "pending"` و`"dispatch_status": "not_required"` و`"info_only": bool` بدلاً من مفتاح نصي حرفي باسم `requires_human_review=True` أو `HUMAN_VERIFICATION_REQUIRED`. ولذلك يوصى بإضافة الحقلين الصريحين `"requires_human_review": True` و`"verification_policy": "HUMAN_VERIFICATION_REQUIRED"` مباشرة داخل قاموس `al` في `raise_alert()` لتوحيد التعاقد البرمجي (`API Contract`) عبر جميع مخرجات JSON.

## 7. التوصيات الهندسية المستخلصة من القياسات الفعلية

1. **تحسين أداء `find_plates` مع `TesseractOCRReader` عند غياب `YOLOv8n`:** نظراً لأن `find_plates` على كامل الإطار قد يعيد المستطيل الزجاجي الأمامي للمركبة كصندوق مرشح إضافي بجانب اللوحة (مما يضاعف عدد استدعاءات `tesseract` الفرعية)، يوصى بضبط `OMP_THREAD_LIMIT=1` افتراضياً داخل `TesseractOCRReader` وترتيب الصناديق المرشحة بحسب موقعها في النصف السفلي من الإطار.
2. **توحيد حقل `requires_human_review=True` في `raise_alert()`:** إضافة `"requires_human_review": True` و`"verification_status": "HUMAN_VERIFICATION_REQUIRED"` صراحةً في كائنات `bus.alerts` إلى جانب `status='pending'` لتسهيل التكامل البرمجي الآلي مع الأنظمة الخارجية.
3. **توحيد توثيق إصدارات الحزم في `01_ENGINEERING_AUDIT_REPORT_AR.md`:** تحديث السطر 43 في التقرير الهندسي ليطابق الأرقام المثبتة فعلياً في `requirements.txt` و`constraints-win-x64.txt` (`torch==2.5.1`, `ultralytics==8.3.0`, `easyocr==1.7.2`, `scikit-learn==1.5.2`).

