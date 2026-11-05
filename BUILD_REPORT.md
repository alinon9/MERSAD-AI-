# ملحق البناء — V7.1 Hardened Operational Build

**لم يتم بناء V7.1 كملف EXE في بيئة هذه الجلسة.** الاختبارات المحلية نُفذت داخل Linux/Python 3.13.5. جرى تجهيز `BUILD_EXE.bat` و`setup.bat` و`mersad_ai.spec` و`.github/workflows/windows-build.yml` بحيث تشترط Python 3.11 x64، وتكرر الاختبارات، وتتحقق من سلسلة التدقيق والنماذج بعد البناء وبعد نقل مجلد التوزيع إلى مسار يحوي أحرفًا عربية ومسافات.

بقي بناء Windows نفسه واختباره على Windows 10/11 بوابة إصدار إلزامية؛ إعداد workflow لا يعني أنه نُفّذ أو أن EXE قد بُني.

هذا الملحق مستقل عن نتائج البناء التاريخية للإصدار الخامس الواردة أدناه.

---

# تقرير البناء والتوزيع على نظام Windows — MERSAD AI (`MERSAD_AI_FIXED_5.zip`)

يُوثّق هذا التقرير المواصفات الدقيقة لبيئة البناء والتشغيل المستهدفة على نظام Windows، والإصدارات المثبتة، وبنية حزمة التوزيع (`--onedir`)، وفصل المسارات بين الموارد الثابتة وبيانات المستخدم، وسير عمل التكامل المستمر (`CI`) المجهّز للبناء والاختبار الآلي على Windows.

> **إقرار شفافية إلزامي**: بيئة الفحص الحالية هي حاوية Linux (`Python 3.11.2 x86_64`) معزولة عن الإنترنت؛ لذلك **لم يتم بناء أو تشغيل `MERSAD_AI.exe` فعلياً على جهاز Windows داخل هذه الجلسة** (`تم الإصلاح لكن لم يُختبر على Windows`). بدلاً من الادعاء النظري، تم توحيد وتثبيت جميع سكربتات البناء (`BUILD_EXE.bat`, `setup.bat`, `mersad_ai.spec`, `constraints-win-x64.txt`) وإعداد سير عمل GitHub Actions متكامل (`.github/workflows/windows-build.yml`) لتنفيذ البناء والاختبار الفعلي على Windows Server x64.

---

## 1. مواصفات بيئة التشغيل والبناء المستهدفة (Single Source of Truth)

* **نظام التشغيل والبنية المستهدفة**: `Windows 10 / 11 / Server 2022 (64-bit / x64)`.
* **إصدار Python المرجعي المستهدف**: **`Python 3.11 (64-bit)`** (مدعوم برمجياً على `3.10–3.12 64-bit`، ومختبر فعلياً على `Python 3.11.2 64-bit`).
* **جدول الإصدارات المثبتة في `requirements.txt` و `constraints-win-x64.txt` و `setup.bat` و `BUILD_EXE.bat`**:

| الحزمة | الإصدار المثبت | الغرض وطريقة التثبيت |
|---|---|---|
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

---

## 2. بنية حزمة التوزيع (`--onedir` مقابل `--onefile`)

يستخدم المشروع نمط **`--onedir`** (مجلد توزيع متكامل `dist\MERSAD_AI\`) وليس `--onefile`، للأسباب الهندسية التالية:
1. تجنب فك ضغط أكثر من `1.5 GB` من مكتبات `PyTorch` و `OpenCV` والنماذج في مجلد `_MEIPASS` المؤقت عند كل تشغيل (مما يبطئ الإقلاع ويستهلك مساحة القرص `C:\`).
2. السماح ببقاء مجلد النماذج `dist\MERSAD_AI\models\` قابلاً للفحص المباشر والتحقق من بصمات `SHA-256` دون إعادة فك ضغطه.

### تنبيه تشغيلي مهم حول نقل الحزمة
* الملف `dist\MERSAD_AI\MERSAD_AI.exe` **ليس ملفاً منفرداً مستقلاً بذاته خارج مجلده**؛ بل يعتمد على المكتبات الثنائية (`_internal\` أو `.dll` و `.pyd`) ومجلد `models\` الموجودة بجانبه داخل `dist\MERSAD_AI\`.
* عند نقل البرنامج إلى جهاز Windows آخر (لا يحتوي على Python)، **انسخ مجلد `dist\MERSAD_AI\` بالكامل** كما هو.

---

## 3. فصل المسارات (Read-Only Bundle مقابل Writable User Data)

حُلّت في الجولة الخامسة مشكلة صلاحيات الكتابة عند تثبيت البرنامج في مجلد محمي (مثل `C:\Program Files\MERSAD_AI\`):
1. **مسار الموارد القابلة للقراءة فقط (`BUNDLE_DIR` و `INSTALL_DIR`)**:
   - تُقرأ منه ملفات الواجهة (`dashboard.html`) والنماذج (`models/yunet.onnx`, `models/sface.onnx`, `models/yolov8n.pt`, `models/easyocr/`) عبر الدالة `resolve_resource_path()`.
2. **مسار بيانات المستخدم القابل للكتابة (`APPDIR`)**:
   - تحدده الدالة `resolve_writable_appdir()`؛ إذا كان مجلد التثبيت قابلاً للكتابة (وليس `_MEIPASS`) تُحفظ البيانات فيه، أما إذا كان مجلد التثبيت للقراءة فقط لحساب مستخدم عادي، يسقط النظام تلقائياً إلى مجلد بيانات المستخدم الدائم:
     - على Windows: `%LOCALAPPDATA%\MERSAD_AI\`
     - على Linux: `~/.local/share/mersad_ai/`
   - تُحفظ في `APPDIR` جميع البيانات المتغيرة: قاعدة البيانات `mersad.db`، مفتاح `.mersad_hmac.key`، ملف الأسرار `.mersad_secrets.json`، مجلد الأدلة `evidence/`، مجلد الأرشيف `evidence_archive/`، وسجل التشغيل `mersad.log`.

---

## 4. خطوات البناء على Windows (يدوياً أو عبر GitHub Actions CI)

### أ) البناء المحلي على جهاز Windows x64
1. ثبّت `Python 3.11 (64-bit)` من `python.org` مع تفعيل خيار `Add python.exe to PATH`.
2. فك ضغط `MERSAD_AI_FIXED_5.zip` وشغّل `BUILD_EXE.bat`.
3. سيقوم `BUILD_EXE.bat` تلقائياً بـ:
   - تشغيل `setup.bat` لإنشاء `venv` وتثبيت الحزم المثبتة وتحميل النماذج وإنشاء وثيقة الجاهزية `venv\.ready`.
   - تشغيل `check_install.py --strict` و `selftest.py` و `pip check`.
   - تثبيت `pyinstaller==6.11.1` وبناء `dist\MERSAD_AI\MERSAD_AI.exe` مع تسجيل المخرجات في `build_pyinstaller.log`.
   - نسخ `models\` وإنشاء سكربتات `dist\MERSAD_AI\RUN.bat` و `RUN_LAN.bat` و `VERIFY_AUDIT.bat` والتحقق من اكتمال جميع ملفات التوزيعة.

### ب) البناء والاختبار الآلي عبر GitHub Actions (`.github/workflows/windows-build.yml`)
* يتضمن الأرشيف ملف `.github/workflows/windows-build.yml` الجاهز للتشغيل الفوري على `windows-latest`، والذي يبني الحزمة ويختبر تشغيل `MERSAD_AI.exe --verify` من مسار يحتوي على مسافات وأحرف عربية (`C:\اختبار مرصاد AI\نسخة التوزيع\MERSAD_AI\MERSAD_AI.exe`) ويرفع مجلد التوزيع كأثر بناء (`Artifact`).
