# 9. تقرير البناء والتغليف والنشر لنظام Windows x64 — `BUILD_AND_DEPLOYMENT_REPORT.md`
## الإصدار: `MERSAD AI & MERSAD LAB — Preview 0.1` (`release/mersad-preview-0.1` @ `25131918a981ac2ac37923d4c738d9f93cdcbc5b`)

## 1. معمارية البناء والتوزيع (`Windows x64 Packaging Architecture`)

تم تجهيز وتحصين منظومة بناء وتوزيع متكاملة وموحدة للمشروعين على نظام **Windows 10/11 (64-bit / x64)**:

| المكون / الحزمة | أداة البناء والمواصفات | المسار المصدري / السكربت | المسار الناتج عند البناء على Windows x64 | الحالة في بيئة الفحص الحالية |
| ----- | ----- | ----- | ----- | ----- |
| **`MERSAD_AI.exe`** | `PyInstaller 6.11.1` (`--onedir`) عبر `MERSAD_AI_Preview_0.1/mersad_ai.spec` | `MERSAD_AI_Preview_0.1/BUILD_EXE.bat` | `MERSAD_AI_Preview_0.1/dist/MERSAD_AI/MERSAD_AI.exe` | **`NOT TESTED` محلياً** (الحاوية `Linux x86_64` معزولة عن الإنترنت؛ سكربت البناء وسير عمل CI جاهزان ومحصنان) |
| **`MERSAD_LAB.exe`** | `PyInstaller 6.11.1` (`--onedir`) عبر `MERSAD_LAB_Preview_0.1/mersad_lab.spec` | `MERSAD_LAB_Preview_0.1/BUILD_LAB_EXE.bat` | `MERSAD_LAB_Preview_0.1/dist/MERSAD_LAB/MERSAD_LAB.exe` | **`NOT TESTED` محلياً** (الحاوية `Linux x86_64` معزولة؛ سكربت البناء وسير عمل CI جاهزان ومحصنان) |
| **`MERSAD_LAB_Setup_x64.exe`** | `Inno Setup 6` (`ISCC.exe`) عبر `MERSAD_LAB_Preview_0.1/installer/mersad_lab_setup.iss` | `MERSAD_LAB_Preview_0.1/installer/build_installer.ps1` | `MERSAD_LAB_Preview_0.1/dist/installer/MERSAD_LAB_Setup_x64.exe` | **`NOT TESTED` محلياً** (تمت إضافة التثبيت التلقائي لـ `Inno Setup` عبر `choco install innosetup` في CI) |
| **`MERSAD_AI_Portable_x64.zip`** (حزمة `.exe` المحمولة لـ Windows) | `Compress-Archive` لمجلد `dist\MERSAD_AI\*` شامل الأوزان الأربعة | `BUILD_AND_VERIFY_FINAL_WINDOWS_RELEASE.ps1` & `release-mersad-preview-0.1-windows.yml` | `MERSAD_AI_Preview_0.1/dist/portable/MERSAD_AI_Portable_x64.zip` | **`NOT TESTED` محلياً** (يُنتج تلقائياً في `Phase 3B` على Windows / GitHub Actions) |
| **`MERSAD_LAB_Portable_x64.zip`** (حزمة `.exe` المحمولة لـ Windows) | `Compress-Archive` لمجلد `dist\MERSAD_LAB\*` | `BUILD_AND_VERIFY_FINAL_WINDOWS_RELEASE.ps1` & `release-mersad-preview-0.1-windows.yml` | `MERSAD_LAB_Preview_0.1/dist/portable/MERSAD_LAB_Portable_x64.zip` | **`NOT TESTED` محلياً** (يُنتج تلقائياً في `Phase 3B` على Windows / GitHub Actions) |
| **`MERSAD_AI_Preview_0.1_Portable_Source.zip`** | حزمة مصدرية محمولة كاملة للنظام الرئيسي وسكربتات التشغيل | مرفقة وجاهزة في `RELEASE_DELIVERABLES/PREVIEW_0.1/` | `RELEASE_DELIVERABLES/PREVIEW_0.1/MERSAD_AI_Preview_0.1_Portable_Source.zip` | **`PASS` (`GENERATED & VERIFIED`)** |
| **`MERSAD_LAB_Preview_0.1_Portable_Source.zip`** | حزمة مصدرية محمولة كاملة لمختبر الكاميرات وسكربتات البناء والمثبت | مرفقة وجاهزة في `RELEASE_DELIVERABLES/PREVIEW_0.1/` | `RELEASE_DELIVERABLES/PREVIEW_0.1/MERSAD_LAB_Preview_0.1_Portable_Source.zip` | **`PASS` (`GENERATED & VERIFIED`)** |
| **`MERSAD_PREVIEW_0.1_FINAL_RELEASE_BUNDLE.zip`** | الحزمة الشاملة النهائية للإصدار التجريبي `Preview 0.1` شاملة المشروعين والتقارير العشرة وحزمة Git الجنائية | مرفقة وجاهزة في `RELEASE_DELIVERABLES/PREVIEW_0.1/` | `RELEASE_DELIVERABLES/PREVIEW_0.1/MERSAD_PREVIEW_0.1_FINAL_RELEASE_BUNDLE.zip` | **`PASS` (`GENERATED & VERIFIED`)** |

## 2. الإصلاحات الهندسية المنفذة على منظومة بناء Windows وGitHub Actions (`BUG-03`, `BUG-04`, `BUG-07`, `BUG-09`, `BUG-10`, `BUG-11`)

1. **إزالة مانع التوقف عند المرحلة الثانية (`WINDOWS BUILD BLOCKER — BUG-07`)**:
   * استبدال `--require-unblocked` بـ `--require-cleanroom-pass` في `BUILD_AND_VERIFY_FINAL_WINDOWS_RELEASE.ps1` و`.github/workflows/release-mersad-preview-0.1-windows.yml` بحيث يسجل غياب التزام المختبر الأصلي `ed7b8f72` بأمانة كـ `BLOCKED` دون إيقاف البناء قبل `Phase 3B` (`Test #231 — PASS`).
2. **التحقق الصريح وتثبيت `Inno Setup 6` (`ISCC.exe`) تلقائياً في GitHub Actions (`BUG-10`)**:
   * يفحص كل من `release-mersad-preview-0.1-windows.yml` و`build-mersad-lab-windows.yml` و`BUILD_AND_VERIFY_FINAL_WINDOWS_RELEASE.ps1` وجود `ISCC.exe` في `PATH` وفي `C:\Program Files (x86)\Inno Setup 6\ISCC.exe` و`C:\Program Files\Inno Setup 6\ISCC.exe`، وفي حال عدم وجوده ينفذ تلقائياً `choco install innosetup -y --no-progress` قبل مرحلة التجميع (`Test #232 — PASS`).
3. **تثبيت عجلات `PyTorch CPU` المتوافقة وتشغيل `check_install.py --verify-pip-deps` (`BUG-11`)**:
   * تثبيت `pip install torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cpu` قبل تثبيت `requirements.txt -c constraints-win-x64.txt`، ثم إزالة `opencv-python-headless` وإعادة تثبيت `opencv-python==4.11.0.86`، ثم التحقق عبر `python MERSAD_AI_Preview_0.1/check_install.py --verify-pip-deps`.
4. **توليد مشغلات التوزيع (`dist\MERSAD_AI\RUN.bat` و`RUN_LAN.bat` و`VERIFY_AUDIT.bat` — `BUG-04`)**:
   * توليد مشغلات تستدعي `MERSAD_AI.exe %*` مباشرةً داخل `dist\MERSAD_AI\` دون الاعتماد على `setup.bat` أو `venv`.

5. **تصحيح وتحصين سكربت النشر والتشغيل السحابي (`PUSH_CANDIDATE_9491BCD_TO_GITHUB_ACTIONS.bat` & `PUSH_RELEASE_PREVIEW_0_1_TO_GITHUB_ACTIONS.bat` & `tools/deploy_and_run_github_actions.py` — `BUG-12`)**:
   * استبدال الفرع التاريخي `preview/mersad-ai-lab-0.1-20261105` والالتزام القديم `9491bcd0` بفرع الإصدار النهائي المعتمد **`release/mersad-preview-0.1`** المتضمن التزام الكود **`25131918a981ac2ac37923d4c738d9f93cdcbc5b`** (`MERSAD AI`) و**`e9284356f4d1a8205946d5893121c6f8a2f22012`** (`MERSAD LAB`).
   * التحقق الآلي المسبق من عدم المساس بالفرع الرئيسي `main` (`25c9e5bba30dc8f921675e12c23a53571be895c1`)، ورفع الفرع بدون `--force` (`git push -u origin refs/heads/release/mersad-preview-0.1:refs/heads/release/mersad-preview-0.1`).
   * التحقق الفعلي من تطابق بصمة الالتزام المنشور على GitHub (`REMOTE_SHA`) مع `LOCAL_HEAD_SHA` عبر `git ls-remote origin refs/heads/release/mersad-preview-0.1` والتوقف فوراً عند أي اختلاف.
   * التحقق المسبق الصارم من تثبيت أداة `GitHub CLI (gh)` ومصادقتها (`gh auth status`) قبل البدء؛ وفي حال عدم تثبيتها أو عدم مصادقتها يتوقف السكربت فوراً برمز خطأ غير صفري (`exit /b 1`) ورسالة خطأ واضحة دون الادعاء بنجاح تشغيل البناء.
   * تشغيل `gh workflow run release-mersad-preview-0.1-windows.yml --ref release/mersad-preview-0.1` يدوياً، واستخراج `Run ID`، وانتظار اكتمال البناء عبر `gh run watch <RUN_ID> --exit-status`، وتنزيل المخرجات الخمسة عبر `gh run download <RUN_ID>`.
   * تم التحقق الفعلي من منطق السكربت عبر حزمة الاختبار الذاتي `python3 tools/deploy_and_run_github_actions.py --self-test` على مستودع Git محلي مجرد (`Bare Remote`) واجتاز **`8 / 8 PASS`** (السجل: `reports_and_logs/logs/15_github_actions_deployment_attempt.log`).

## 3. نتيجة محاولة الرفع وتشغيل `release-mersad-preview-0.1-windows.yml` من داخل بيئة الفحص الحالية وكيفية تشغيله على جهاز متصل

- **القيود التقنية الصارمة لبيئة الفحص الحالية:**
  1. بيئة التنفيذ الحالية هي حاوية `Linux x86_64` معزولة شبكياً بالكامل (`No Outbound Internet Access` في الطرفية).
  2. المستودع السحابي `https://github.com/alinon9/MERSAD-AI-` خاص (`Private Repository`) ويتطلب مصادقة حساب GitHub من جهاز متصل بالإنترنت لرفع الفرع `release/mersad-preview-0.1` وتشغيل `GitHub Actions`.
- **خطوات تشغيل البناء الفعلي على Windows 10/11 x64 أو عبر GitHub Actions:**
  1. **عبر GitHub Actions (سحابياً):** فك ضغط `MERSAD_PREVIEW_0.1_FINAL_RELEASE_BUNDLE.zip` على جهاز متصل بالإنترنت وشغّل:
     ```
     PUSH_CANDIDATE_9491BCD_TO_GITHUB_ACTIONS.bat
     ```
     (أو ارفع الفرع `release/mersad-preview-0.1` من الحزمة الجنائية `reports_and_logs/mersad_preview_0_1_verifiable_history.bundle` إلى GitHub)، وسيعمل Workflow `release-mersad-preview-0.1-windows.yml` تلقائياً لإنتاج واختبار الملفات الخمسة (`MERSAD_AI.exe`, `MERSAD_LAB.exe`, `MERSAD_LAB_Setup_x64.exe`, `MERSAD_AI_Portable_x64.zip`, `MERSAD_LAB_Portable_x64.zip`) في مسار عربي يحتوي على مسافات.
  2. **محلياً على جهاز Windows 10/11 x64:** شغّل:
     ```
     BUILD_ALL_WINDOWS_PREVIEW_0_1.bat
     ```
