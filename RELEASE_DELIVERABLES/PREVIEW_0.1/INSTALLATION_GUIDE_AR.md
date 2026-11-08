# 8. دليل التثبيت والتشغيل الشامل باللغة العربية — `INSTALLATION_GUIDE_AR.md`
## الإصدار: `MERSAD AI & MERSAD LAB — Preview 0.1` (`fix/preview-0.1-postbuild-42273598736` — `AI Current Branch HEAD`: `New verified HEAD directly above eaf89c71b3b54de14a1c64bf862bb6e6eec321cc` | `AI Runtime Code Commit`: `edaf651321ec9ea6ba613e3ab1630bc16b11b9d5` | `LAB HEAD`: `748ac0158761812a6fff63ff6fe626b9df8c252b`)

# منظومة مرصاد الذكي ومختبر الكاميرات — `MERSAD AI — PREVIEW 0.1`
## الإصدار التجريبي الموحد لنظام Windows 10/11 x64

> **تنبيه تنظيمي وهندسي هام:**
> هذه الحزمة (**`MERSAD AI — PREVIEW 0.1`**) هي **نسخة معاينة هندسية وتجريبية موثقة (`Documented Engineering Preview`)** مخصصة للاختبار المعملي والتحقق من التكامل على أنظمة Windows 10/11 x64 باستخدام بيانات اصطناعية أو مصرح بها. **ليست إصداراً إنتاجياً نهائياً ولا نظاماً معتمداً للاستخدام الميداني التلقائي**، وجميع التنبيهات والمطابقات الصادرة عنها تخضع وجوباً للمراجعة البشرية (`Human-in-the-Loop`).

---

## 1. هيكل الحزمة الموحدة (`MERSAD_PREVIEW_0.1/`)

```text
MERSAD_PREVIEW_0.1/
├── LAUNCH_MERSAD_PREVIEW.bat                # مشغل موحد تفاعلي لتشغيل AI أو LAB أو كليهما معاً مع الربط التلقائي
├── BUILD_ALL_WINDOWS_PREVIEW_0_1.bat        # أداة بناء شاملة لملفي MERSAD_AI.exe و MERSAD_LAB.exe والمثبت على Windows x64
├── README_AR.md                             # دليل التشغيل والاستخدام والربط (هذا الملف)
├── MANIFEST.json                            # بيان رسمي بجميع ملفات الإصدار وأحجامها وبصمات SHA-256
├── SHA256SUMS.txt                           # قائمة بصمات SHA-256 القياسية لجميع ملفات الحزمة
├── MERSAD_AI_Preview_0.1/                   # نظام مرصاد الذكي (MERSAD AI V7.1 — PREVIEW 0.1)
│   ├── mersad_live.py                       # المحرك الرئيسي للرؤية الحاسوبية والتدقيق الجنائي
│   ├── server.py                            # خادم الويب المحلي المحصن وبث MJPEG/SSE
│   ├── registry.py                          # قاعدة بيانات المركبات والأشخاص المصرح بهم
│   ├── notify.py                            # نظام تنبيهات Telegram وقفل العمليات المسمى
│   ├── analytics.py                         # محرك التحليلات التشغيلية وتصدير CSV الآمن
│   ├── insights.py                          # محرك كشف الشذوذ وتتبع المسارات والبديل الإحصائي
│   ├── camera_history.py                    # سجل توافر وصحة الكاميرات
│   ├── dashboard.html                       # لوحة التحكم العربية التفاعلية
│   ├── prefetch.py                          # أداة تنزيل النماذج والتحقق الصارم من بصمات SHA-256
│   ├── check_install.py                     # أداة فحص جاهزية التثبيت والبيئة والنماذج
│   ├── verify_integrity.py                  # أداة التحقق الجنائي من سلامة ملفات النظام
│   ├── selftest.py                          # حزمة الاختبارات الآلية الشاملة (232 اختباراً)
│   ├── mersad_ai.spec & BUILD_EXE.bat       # إعدادات وسكربت بناء MERSAD_AI.exe عبر PyInstaller
│   ├── setup.bat, RUN.bat, RUN_LAN.bat      # سكربتات الإعداد والتشغيل على Windows 10/11 x64
│   ├── SYSTEM_REQUIREMENTS_AR.md            # متطلبات النظام والعتاد والنماذج
│   └── models/                              # مجلد النماذج الموثوقة (YuNet, SFace, YOLOv8n, EasyOCR)
├── MERSAD_LAB_Preview_0.1/                  # مختبر محاكاة الكاميرات وفحص الجودة (MERSAD LAB 1.0 — PREVIEW 0.1)
│   ├── sim_engine.py                        # محرك توليد المشاهد والمركبات واللوحات اليمنية الاصطناعية وفحص الجودة
│   ├── lab_server.py                        # خادم المختبر المحلي (127.0.0.1:8090) المحصن أمنياً
│   ├── index.html                           # واجهة التحكم العربية (خالية تماماً من innerHTML)
│   ├── test_lab.py                          # حزمة اختبارات المختبر الشاملة (20 اختباراً وظيفياً وأمنياً)
│   ├── mersad_lab.spec & BUILD_LAB_EXE.bat  # إعدادات وسكربت بناء MERSAD_LAB.exe
│   ├── RUN_LAB.bat                          # سكربت تشغيل المختبر
│   └── installer/                           # ملفات بناء مثبت Windows (Inno Setup .iss + PowerShell builder)
├── integration/                             # اختبارات التكامل الفعلي وتقييم النماذج
│   ├── test_ai_lab_integration.py           # 12 سيناريو تكامل فعلي بين MERSAD LAB و MERSAD AI
│   └── evaluate_ai_models.py                # تقييم النماذج الأربعة واللوحات اليمنية الاصطناعية
└── reports_and_logs/                        # التقارير الهندسية والأمنية وسجلات التنفيذ الفعلية
    ├── 01_ENGINEERING_AUDIT_REPORT_AR.md
    ├── 02_SECURITY_AUDIT_REPORT_AR.md
    ├── 03_MERSAD_LAB_BUG_REPORT_AR.md
    ├── 04_AI_LAB_INTEGRATION_REPORT_AR.md
    ├── 05_REMEDIATION_CHANGELOG_AR.md
    ├── 06_TEST_MATRIX_PASS_FAIL_AR.md
    ├── 07_KNOWN_LIMITATIONS_AND_FIELD_TESTS_AR.md
    └── logs/                                # 13 ملف سجل تنفيذ فعلي (.log و .json)
```

---

## 2. دليل التشغيل السريع على Windows 10/11 x64

### الخيار أ: التشغيل التفاعلي الموحد (الموصى به للمعاينة والربط)
1. فك ضغط الحزمة `MERSAD_PREVIEW_0.1.zip` في مجلد محلي على قرص `NTFS` (مثل `C:\MERSAD_PREVIEW_0.1`).
2. انقر مرتين على **`LAUNCH_MERSAD_PREVIEW.bat`**.
3. اختر **`[3]`** لتشغيل **مختبر الكاميرات (`MERSAD LAB`)** على المنفذ `127.0.0.1:8090` وتشغيل **مرصاد الذكي (`MERSAD AI`)** على المنفذ `127.0.0.1:8000` مع ربط تدفق الكاميرا الافتراضية `http://127.0.0.1:8090/stream/cam1.mjpg` تلقائياً.

### الخيار ب: بناء ملفات `.exe` المستقلة ومثبت Windows محلياً
لبناء `MERSAD_AI.exe` و`MERSAD_LAB.exe` والحزمة المحمولة ومثبت Windows على جهاز Windows 10/11 x64 متصل بالإنترنت:
```bat
BUILD_ALL_WINDOWS_PREVIEW_0_1.bat
```
يقوم هذا السكربت تلقائياً بإنشاء بيئة افتراضية معزولة، وتثبيت الاعتماديات المثبتة في `constraints-win-x64.txt`، وتنزيل النماذج والتحقق من بصماتها `SHA-256` عبر `prefetch.py`، وتشغيل حزم الاختبارات الآلية المفصلة دون خلط بين عدد الحالات وعدد مرات التشغيل (`AI Standard: 234/234 PASS`، و`AI No-skLearn: 234/234 PASS`، و`verify_integrity: 19/19 PASS`، و`MERSAD LAB: 20/20 PASS`، و`Integration: 12 PASS + 2 NOT_TESTED`)، ثم إنتاج:
- `MERSAD_AI_Preview_0.1\dist\MERSAD_AI\MERSAD_AI.exe`
- `MERSAD_LAB_Preview_0.1\dist\MERSAD_LAB\MERSAD_LAB.exe`
- `MERSAD_LAB_Preview_0.1\dist\portable\MERSAD_LAB_Portable_x64.zip`
- `MERSAD_LAB_Preview_0.1\dist\installer\MERSAD_LAB_Setup_x64.exe` (عند توفر Inno Setup)

### الخيار ج: ربط الكاميرات الافتراضية من واجهة المختبر
1. افتح واجهة المختبر `http://127.0.0.1:8090` في المتصفح.
2. اختر وضع الكاميرا المطلوب (`طبيعي`, `إضاءة منخفضة`, `دقة منخفضة`, `تشويش`, `حجب العدسة`, `تجميد الإطار`, `تأخير البث`, أو `منقطع 503`).
3. في بطاقة **"ربط البث المباشر مع MERSAD AI V7.1"**، أدخل عنوان خادم مرصاد (`http://127.0.0.1:8000`) ورمز الجلسة ثم اضغط **"ربط الكاميرا بمرصاد"**.

