# 2. تقرير التدقيق الأمني الشامل — `SECURITY_AUDIT.md`
## الإصدار: `MERSAD AI & MERSAD LAB — Preview 0.1` (`fix/preview-0.1-postbuild-42273598736` — `AI Current Branch HEAD`: `New verified HEAD directly above 62b409e2327b86ad0720a526cb3ba8573821b09b` | `AI Runtime Code Commit`: `edaf651321ec9ea6ba613e3ab1630bc16b11b9d5` | `LAB HEAD`: `748ac0158761812a6fff63ff6fe626b9df8c252b`)

## الملخص التنفيذي للتدقيق الأمني
أُجري فحص أمني شامل (ساكن عبر تحليل شجرة الصياغة المجردة `AST` لـ **203 استعلامات SQLite**، وديناميكي عبر **10 اختبارات اختراق حية `SEC-AUDIT-01..10`** بالإضافة إلى **12 اختبار أمان في المختبر `LAB-SEC-01..12`** وجميع اختبارات الأمان في `selftest.py` البالغ مجموعها **`234 / 234 PASS`**):
- **عدد الثغرات الحرجة أو العالية المفتوحة (`Open Critical/High Vulnerabilities`)**: **`0`**.
- **الخصوصية وحوكمة البيانات البيومترية**: صفر بيانات أشخاص حقيقيين (`contains_real_human_biometric_pii: false` في `BENCHMARK_MANIFEST.json`)، اشتراط موافقة صريحة `consent=1`، طمس `100%` من الوجوه في تنبيهات المركبات وطمس وجوه المارة في تنبيهات الوجوه، واشتراط مراجعة بشرية موثقة (`requires_human_review=True`, `verification_policy="HUMAN_VERIFICATION_REQUIRED"`, `status="pending"`).

## 4. التدقيق الأمني الشامل (`Comprehensive Security Audit`) ونتائج الاختبارات الحية (البند الثاني)

تم فحص الكود المصدري سطراً بسطر في مشروعي `MERSAD AI` و`MERSAD LAB` وتشغيل اختبارات اختراق وتحقق أمنية حية (`SEC-AUDIT-01` إلى `SEC-AUDIT-10` بالإضافة إلى اختبارات `selftest.py` و`test_lab.py`). فيما يلي النتائج التفصيلية لكل محور من المحاور العشرة:

### المحور 1: إدارة كلمات المرور والرموز التشفيرية (`Password Management — PBKDF2/Bcrypt/Hash & Cryptographic Tokens`)
- **التحليل البرمجي الفعلي**:
  - صُمّم كل من `MERSAD AI` و`MERSAD LAB` كنظام تشغيل محلي أحادي المشغل (`Single-Operator Local Appliance`)، ولذلك **لا يستخدم النظام جدول حسابات مستخدمين بكلمات مرور نصية** ولا يخزن كلمات مرور مستخدمين في قاعدة البيانات (وبالتالي لا توجد حاجة أو استدعاء لـ `PBKDF2` أو `Bcrypt` لكلمات مرور المستخدمين في الإصدار الحالي).
  - بدلاً من كلمات المرور الثابتة القابلة للتخمين أو التسريب، يولد `MERSAD AI` عند كل إقلاع رمز جلسة عشوائياً عالي الإنتروبيا من مولد النظام التشفيري (`secrets.token_urlsafe(12)` — `96-bit` / `16` محرفاً في `server.py:39`)، ويولد `MERSAD LAB` رمز مصادقة عشوائياً (`secrets.token_urlsafe(16)` — `128-bit` في `lab_server.py:89`).
  - تتم جميع مقارنات الرموز والتواقيع بزمن ثابت (`Constant-Time Comparison`) عبر `secrets.compare_digest` (`server.py:159`, `lab_server.py:229`) و`hmac.compare_digest` (`mersad_live.py:1936`) لمنع هجمات التوقيت (`Timing Attacks`).
  - تُوقّع سجلات التدقيق وسجلات النماذج الموثوقة وتُعمّى معرّفات الأشخاص باستخدام مفتاح `HMAC-SHA256` بطول `32 بايت (256-bit)` يُولد عبر `secrets.token_bytes(32)` ويُحفظ في `.mersad_hmac.key` (`registry.py:304-354`).
- **نتيجة الاختبار الأمني الحي (`SEC-AUDIT-01`)**: **PASS** (`token_len=16, hmac_key_bytes=32, constant_time_compare=True`).
- **التوصية المستقبلية**: في حال تحويل النظام مستقبلاً إلى بيئة متعددة المستخدمين (`Multi-User Enterprise Deployment`)، يجب إضافة جدول مستخدمين يعتمد تجزئة كلمات المرور عبر `Argon2id` أو `PBKDF2-HMAC-SHA256` (`>= 600,000 iterations`) مع `Salt` فريد لكل مستخدم.

### المحور 2: المصادقة والصلاحيات (`Authentication & Authorization / RBAC / API Tokens / Session Cookies`)
- **التحليل البرمجي الفعلي**:
  - **التحقق من الهوية (`Authentication`)**: تتحقق دالة `_auth()` في `server.py:129-179` من كل طلب وارد إلى الخادم عبر: معلمة الرابط `?k=TOKEN`، أو الكوكي `mersad_k`، أو الترويسة `X-Mersad-Token`. وفي `MERSAD LAB` تتحقق دالة `_check_auth()` (`lab_server.py:210-237`) من `X-Lab-Token` أو `Authorization: Bearer` أو الكوكي `mersad_lab_k`.
  - **أمان كوكيز الجلسة (`Session Cookies`)**: عند زيارة الرابط المحلي الأولي `GET /?k=TOKEN`، يصدر الخادم (`server.py:232-243`) إعادة توجيه `HTTP 302 Found` إلى `Location: /` مع زرع الكوكي `Set-Cookie: mersad_k=<token>; HttpOnly; SameSite=Strict; Path=/` وترويسة `Referrer-Policy: no-referrer`، مما يزيل الرمز فوراً من شريط عنوان المتصفح ويمنع قراءته عبر `JavaScript` (`HttpOnly`) أو إرساله في طلبات عابرة للمواقع (`SameSite=Strict`).
  - **نموذج الصلاحيات (`Authorization / RBAC`)**: يفصل النظام بين ثلاث طبقات صلاحية عملية:
    1. **صلاحية المشغل المحلي الموثق (`operator`)**: يمتلك صلاحية إدارة الكاميرات وقوائم المراقبة وتأكيد/تجاهل التنبيهات.
    2. **صلاحية مشغل غرفة العمليات عبر تيليجرام (`TELEGRAM_CHAT_ID`)**: يتحقق `notify.py:285-315` من تطابق `chat_id` للرسالة التفاعلية مع غرفة العمليات المصرّح بها، ويرفض أي ضغطة زر من معرّف غريب (`SEC: stranger's button press is rejected` في `selftest.py:911`).
    3. **صلاحية الإجراءات النظامية والنماذج (`system` / `admin`)**: يمنع المسار الشبكي `POST /api/plate_eval/register_model` (`server.py:506`, `mersad_live.py:2126`) نسخ أو تسجيل أي ملف `.pt` من خارج المجلد الموثوق `models/` (`allow_outside_copy=False`).
- **نتيجة الاختبار الأمني الحي (`SEC-AUDIT-02`, `P3-9`, `LAB-SEC-01`)**: **PASS** (`unauth=403, cookie='HttpOnly; SameSite=Strict', redirect='/', stranger_telegram_rejected=True`).

### المحور 3: حماية واجهات `API` (`API Protection — CSRF, Origin/Host Guard, Rate Limiting, DoS Caps`)
- **التحليل البرمجي الفعلي**:
  - **حماية `CSRF` و`Origin: null` و`DNS Rebinding`**:
    - في `MERSAD AI` (`server.py:342-372`): ترفض دالة `do_POST` أي طلب يحمل `Origin: null` (المرسل من `sandboxed iframe` أو `data:` URI)، وترفض أي `Origin` يختلف في المضيف أو المنفذ عن `Host` الفعلي (`Cross-Port CSRF Protection`)، وترفض طلبات `Content-Type: text/plain` المعتمدة على الكوكيز فقط دون ترويسة `X-Mersad-Token` أو `X-Filename` بكود `HTTP 403`.
    - في `MERSAD LAB` (`lab_server.py:140-209`): تتحقق دالة `_check_host_and_origin()` من أن ترويسة `Host` تنتمي حصراً إلى `localhost` / `127.0.0.1` (ما لم يُفعّل `--allow-lan`) لمنع هجمات `DNS Rebinding`، وتحظر `Origin: null` و`Sec-Fetch-Site: cross-site` بكود `HTTP 403`.
  - **تحديد معدل المحاولات (`Rate Limiting`)**: يحظر `server.py:132-178` أي عنوان `IP` يتجاوز `15` محاولة مصادقة فاشلة خلال `60` ثانية بكود `HTTP 429 Too Many Requests` مع ترويسة `Retry-After`.
  - **حدود الحمولة والتزامن والمقبس (`DoS Protection`)**:
    - مهلة مقبس صارمة `H.timeout = 15` ثانية (`server.py:130`).
    - سقف حجم طلبات `POST` في `MERSAD AI` بـ `5 MB` (`server.py:374-380` يرجع `HTTP 413`)، وفي `MERSAD LAB` بـ `10 MB` للصور و`50 MB` للفيديو (`lab_server.py:378-388` يرجع `HTTP 413`).
    - سقف مشتركي أحداث `SSE` بـ `max_subs = 32` (`server.py:86-95`)، وسقف عملاء البث المرئي `max_mjpeg_clients = 16` (`server.py:49, 387-392` يرجع `HTTP 429`).
    - سقف عمليات الرفع والتحليل المتزامنة في المختبر بـ `BoundedSemaphore(3)` (`lab_server.py:94, 390-396` يرجع `HTTP 429`)، ومهلة زمنية صارمة لمعالجة الفيديو (`lab_server.py:465-475` يرجع `HTTP 504`).
  - **ترويسات الأمان (`Security Headers`)**: يرسل كلا الخادمين `Content-Security-Policy` و`X-Content-Type-Options: nosniff` و`X-Frame-Options: DENY` (أو `SAMEORIGIN`) و`Referrer-Policy: no-referrer` و`Cache-Control: no-store`.
- **نتيجة الاختبار الأمني الحي (`SEC-AUDIT-03`, `STAGE15-GAP03`, `STAGE15-GAP04`, `PREVIEW01-CSRF-ORIGIN-NULL-AND-IMPORT`, `LAB-SEC-02..10`)**: **PASS**.

### المحور 4: فحص ثغرات حقن قواعد البيانات (`SQL Injection Audit — All 203 SQLite Queries`)
- **التحليل البرمجي الفعلي**:
  - أُجري مسح شامل لشجرة الصياغة المجردة (`AST Scan`) على جميع استدعاءات `execute` و`executemany` و`executescript` في كافة ملفات بايثون الإنتاجية، وبلغ عددها **`203` استدعاءات**:
    - **`186` استدعاءً** تستخدم سلاسل نصية ثابتة (`Constant String Literals`) مع تمرير كافة المتغيرات عبر المعلمات المربوطة (`?` Parameterized Placeholders).
    - **`17` استدعاءً** تستخدم نصوصاً مبنية ديناميكياً (`f-strings` أو متغيرات DDL)، وتم فحصها واحداً تلو الآخر سطراً بسطر:
      1. `analytics.py:25` (`PRAGMA table_info("{table}")`): يُستدعى حصراً بأسماء جداول ثابتة في الكود (`"sightings"`, `"alerts"` في السطرين `58-59`).
      2. `analytics.py:32, 76`: يدمج فقط عبارات ثابتة محددة مسبقاً (`class_expr`, `conf_expr`, `cam_expr`, `live_clause`) ويمرر التواريخ عبر `(start, now)` بمعلمات `?`.
      3. `insights.py:165`: يدمج تعبيرات أعمدة ثابتة (`COALESCE(via, '')`, إلخ) دون أي مدخل خارجي.
      4. `insights.py:827, 1043, 1213, 1226, 1321`: يدمج فقط `src_clause` الثابت (`" AND COALESCE(src, 'live') = 'live'"` أو `""`) و`plate_clause` الثابت (`" AND plate = ?"`) بينما تُمرر قيمة `plate` والزمن حصراً عبر معلمات `?` في `tuple(params)`.
      5. `mersad_live.py:2957`: دالة داخلية `q(sql, *a)` تُستدعى في الأسطر `2958-2964` بـ `7` جمل `SELECT COUNT(*)` ثابتة حرفياً مع تمرير الزمن عبر `?`.
      6. `registry.py:669, 729, 859, 917, 930, 948, 1002`: جمل `CREATE TABLE` و`ALTER TABLE` ثابتة حرفياً داخل مصفوفات ترحيل المخطط (`Schema Migrations`).
  - **الخلاصة الجنائية لـ `SQL Injection`**: **صفر (`0`)** استعلام يقوم بدمج مدخلات المستخدم نصياً داخل SQL.
- **نتيجة الاختبار الأمني الحي (`SEC-AUDIT-04`)**: **PASS** (تم حقن حمولات `' OR '1'='1` و`12345'; DROP TABLE vehicles; --` و`UNION SELECT` مباشرة في `save_vehicle` و`lookup_vehicle` و`list_rows` و`plate_path`؛ عُوملت كنصوص عادية وبقيت جميع الجداول الـ 13 سليمة 100%).

### المحور 5: الحماية من اختراق المسارات والروابط الرمزية (`Path Traversal & Symlink Abuse`)
- **التحليل البرمجي الفعلي**:
  - **تقديم صور الأدلة (`server.py:208-228` — `_serve_evidence`)**: يتحقق من أن اسم الملف يبدأ بـ `/evidence/`، ويستخدم `urllib.parse.unquote`، ويرفض فوراً أي مسار يحتوي على `/` أو `\` أو `..` أو يبدأ بـ `.`، ويبني المسار المطلق داخل مجلد `evidence/`، ويرفض الروابط الرمزية `os.path.islink(full)`، ويتحقق من `os.path.commonpath([root, real_full]) == root` قبل قراءة الملف.
  - **فحص وتقييم مجموعات بيانات اللوحات (`mersad_live.py:4775-4818` — `_resolve_safe_dataset_image`)**: يرفض المسارات المطلقة و`..` ويفحص كل مكوّن من مكونات المسار عبر `os.path.islink` ويتحقق من `os.path.commonpath` لضمان عدم قراءة أي ملف من خارج مجلد مجموعة البيانات.
  - **رفع ملفات التقييم (`mersad_live.py:5735-5828` — `stage_uploaded_eval_files`)**: يعقّم معرّف الدفعة `batch_id` وأسماء الملفات المرفوعة عبر `os.path.basename` وتعبير نمطي صارم، ويمنع كتابة أي ملف خارج `APPDIR/eval_uploads/<batch_id>/`.
- **نتيجة الاختبار الأمني الحي (`SEC-AUDIT-05`, `SEC: path traversal on /evidence/`, `STAGE12-AUDIT002`)**: **PASS** (`http_traversal_codes=[403, 403, 403], dataset_traversal_blocked=True`).

### المحور 6: منع تسريب الأسرار والمفاتيح (`Secrets & Keys Leakage Protection`)
- **التحليل البرمجي الفعلي**:
  - **حجب الأسرار من السجلات والواجهات (`notify.py:29-48` — `_redact`)**: تعترض دالة `_redact()` أي نص قبل كتابته في `mersad.log` أو سجل التدقيق أو إرجاعه في `JSON`، وتحذف رموز بوت تيليجرام (`bot<id>:<secret>` -> `bot<REDACTED_TOKEN>`) وكلمات مرور روابط الكاميرات (`rtsp://<TEST_USER>:<REDACTED_TEST_PASSWORD>@host` -> `rtsp://user:***@host`) ومعلمات `?token=` أو `?password=`.
  - **فصل الأسرار عن الإعدادات العامة (`mersad_live.py:3605-3725`)**: تُحفظ الأسرار في ملف مستقل `.mersad_secrets.json` وتُمسح تلقائياً من `mersad_config.json`. وإذا وُجد `TELEGRAM_TOKEN` في متغيرات بيئة النظام، لا يُكتب أبداً كنص صريح داخل `mersad_config.json` (`P1-G`, `P3-9`).
  - **صلاحيات الملفات الحساسة (`registry.py:209-354`)**: تُنشأ ملفات `.mersad_secrets.json` و`.mersad_hmac.key` و`models/.trusted_models.json` عبر `atomic_write_secret_bytes()` بصلاحيات `0o600` منذ لحظة فتح الواصف (`os.open(..., 0o600)`) على أنظمة `POSIX`، وعبر `PowerShell` و`icacls /inheritance:r` وقصر الصلاحية على `SID` المستخدم الحالي فقط على نظام `Windows` (`_set_windows_private_acl`).
  - **خلو المستودع من أسرار حقيقية**: تم فحص جميع ملفات المشروع وملفات `.bat` و`.yml` والتأكد من عدم وجود أي رمز `GitHub PAT` أو `Telegram Bot Token` حقيقي مدمج في الكود.
- **نتيجة الاختبار الأمني الحي (`SEC-AUDIT-06`, `P1-D`, `P1-G`, `V7.1-WIN-ACL`)**: **PASS** (`redacted='rtsp://admin:***@192.168.1.50:554/live ... bot<REDACTED_TOKEN>', hmac_key_mode=0o600`).

### المحور 7: حماية قواعد البيانات وتشفير/تعمية البيانات الحساسة (`Database Protection & Sensitive Data Handling`)
- **التحليل البرمجي الفعلي**:
  - **أمان محرك `SQLite` (`registry.py:69-118, 734-805`)**: يفرض النظام وضع `WAL` على الأقراص المحلية ويتراجع بأمان إلى `DELETE` على المسارات الشبكية (`UNC`)، ويحظر قطعياً أوضاع `MEMORY` و`OFF`، ويحمي جميع المعاملات بقفل مشترك بين الخيوط والعمليات (`interprocess_db_lock` + `run_atomic_tx`).
  - **عزل مجلد البيانات (`mersad_live.py:75-158`)**: إذا كان مجلد تثبيت البرنامج للقراءة فقط (مثل `C:\Program Files\MERSAD_AI`) أو على نظام ملفات لا يدعم أقفال `SQLite`، ينتقل `APPDIR` تلقائياً إلى مجلد بيانات المستخدم المحلي المحمي بصلاحيات `0o700` (أو `%LOCALAPPDATA%\MERSAD_AI` مع `Windows Private ACL`).
  - **تعمية البيانات الشخصية (`Pseudonymization — registry.py:356-361`)**: لا تُسجل أسماء الأشخاص في جدول التدقيق `audit` أو السجلات النصية، بل تُحوّل عبر دالة `pseud(s)` التي تحسب `HMAC-SHA256` باستخدام `.mersad_hmac.key` وتُخرج معرّفاً معمّى بصيغة `p-<12-hex>`.
  - **تخزين المتجهات البيومترية (`mersad_live.py:1445-1466`)**: تُخزن متجهات الوجوه (`128-D float32`) كمصفوفة بايتات ثنائية خام بحجم ثابت (`512 bytes`) وتُقرأ عبر `np.frombuffer` مع التحقق من الأبعاد والطول، دون استخدام `pickle` نهائياً.
  - **حدود التشفير على القرص (`At-Rest Encryption Note`)**: قاعدة بيانات `mersad.db` هي قاعدة `SQLite3` قياسية محمية بصلاحيات نظام الملفات (`0o700` / `Windows User ACL`) وتعمية `HMAC` في سجل التدقيق، وليست مشفرة بالكامل بمحرك `SQLCipher`؛ لذلك يُوصى في البيئات الميدانية بتفعيل تشفير القرص (`Windows BitLocker`) على مجلد `%LOCALAPPDATA%\MERSAD_AI`.
- **نتيجة الاختبار الأمني الحي (`SEC-AUDIT-07`, `P2-K`, `STAGE14-01`)**: **PASS** (`journal_mode=wal, pseudonymized_tag=p-025c1c4d79e0`).

### المحور 8: سلامة ملفات الإعدادات وحماية سجلات النظام (`Config Integrity & System Log Protection`)
- **التحليل البرمجي الفعلي**:
  - **سلسلة التدقيق التشفيرية غير القابلة للتعديل (`HMAC-SHA256 Audit Chain — mersad_live.py:278-308, 845-915`)**: يرتبط كل سجل في جدول `audit` بتوقيع السجل السابق عبر `h1:<hmac_sha256(prev|i|ts|action|ref)>` باستخدام المفتاح `.mersad_hmac.key`، كما تُسجل البصمة التشفيرية `SHA-256` لكل صورة دليل (`evidence/*.jpg`) داخل حقل `ref`. وتتحقق دالة `verify()` من سلامة السلسلة بالكامل ومن مطابقة بصمات كافة صور الأدلة النشطة والمؤرشفة على القرص، وترفض أي محاولة لخفض مستوى التوقيع (`Downgrade Attack` من `h1:` إلى هاش عادي) أو حذف المفتاح.
  - **سلامة سجل النماذج الموثوقة (`mersad_live.py:1911-2075`)**: يُحمى ملف `models/.trusted_models.json` بتوقيع `HMAC-SHA256` شامل يمنع حقن أو استبدال أي نموذج `.pt` على القرص دون كشفه.
  - **سلامة ختم بيئة التشغيل (`check_install.py:498-598`)**: يربط ملف `venv/.ready` بصمات `SHA-256` لملفات `requirements.txt` و`constraints-win-x64.txt` و`prefetch.py` وإصدارات الحزم وسلامة النماذج، ويرفض أي تعديل غير متزامن.
  - **سلامة حزمة الإصدار (`verify_integrity.py:1-105`)**: تتحقق أداة `verify_integrity.py` من وجود وبصمات `SHA-256` لجميع الملفات الـ 18 الأساسية.
- **نتيجة الاختبار الأمني الحي (`SEC-AUDIT-08`, `STAGE3-GAP11`, `INT-E2E-07`)**: **PASS** (`before='Audit chain OK (1 records)', on_tamper='TAMPERING DETECTED at record #0', restored='Audit chain OK (1 records)'`).

### المحور 9: صلاحيات الوصول إلى الكاميرات وتحديث المكتبات ذات الثغرات (`Camera Access Permissions & Dependency Security`)
- **التحليل البرمجي الفعلي**:
  - **حوكمة وصلاحيات الكاميرات**:
    - لا يفتح النظام أي كاميرا عند استيراد الوحدات أو تشغيل أدوات الفحص والتقييم (`_should_auto_init_runtime` في `mersad_live.py:633`).
    - عند فحص الكاميرا عبر `check_install.py --camera` (`check_install.py:406-495`)، يُفتح المصدر ضمن كتلة `try...finally` تضمن استدعاء `cap.release()` فوراً بعد قراءة إطار واحد، مع حجب أي بيانات اعتماد في الرابط.
    - تخضع جميع اتصالات `RTSP/HTTP` لمهلات زمنية صارمة (`OPENCV_FFMPEG_CAPTURE_OPTIONS = "rtsp_transport;tcp|stimeout;5000000|rw_timeout;5000000"` في `mersad_live.py:3685-3720`).
    - تتطلب مسارات إدارة الكاميرات الحية (`/api/cameras/add` و`/api/cameras/remove` في `server.py:456-467`) مصادقة المشغل الكاملة وحارس `CSRF`، وتُوثق كل عملية إضافة أو إزالة كاميرا في سجل التدقيق الموقع بـ `HMAC-SHA256` (`mersad_live.py:3068, 3458`).
  - **تثبيت المكتبات وحمايتها من الثغرات (`Dependency Pinning & Safe Deserialization`)**:
    - تُثبت جميع المكتبات بإصدارات محددة في `requirements.txt` و`constraints-win-x64.txt` (`numpy==1.26.4`, `opencv-python==4.11.0.86`, `Pillow==10.4.0`, `easyocr==1.7.2`, `ultralytics==8.3.0`, `openpyxl==3.1.5`, `scikit-learn==1.5.2`, `torch==2.5.1`, `torchvision==0.20.1`, `pyinstaller==6.11.1`).
    - يتم تعطيل الاتصال التلقائي بالإنترنت أو التثبيت الخفي في `Ultralytics` و`EasyOCR` عبر فرض `YOLO_AUTOINSTALL=false` و`ULTRALYTICS_AUTOINSTALL=false` و`YOLO_OFFLINE=true` (`mersad_live.py:42-45`) و`download_enabled=False` (`mersad_live.py:2425`).
    - تُفحص جميع ملفات `.pt` عبر محلل بايت كود `pickle` الساكن (`_scan_pt_pickle_safety` في `mersad_live.py:1795-1908`) قبل تمريرها إلى `torch`/`YOLO` لمنع ثغرات إلغاء التسلسل غير الآمن (`CWE-502`).
    - يُقيّد قارئ ملفات `.xlsx` (`registry.py:1466-1485`) بوضع `read_only=True, data_only=True` وسقف `10,000` صف مع إغلاق المصنف حتمياً في `finally`.
- **نتيجة الاختبار الأمني الحي (`SEC-AUDIT-09`, `STAGE1-GAP01`, `STAGE2-GAP07`, `PREVIEW01-XLSX-ROW-CAP`)**: **PASS**.

### المحور 10: التحقق من عدم استخدام بيانات أشخاص حقيقيين دون موافقة وعدم تفعيل مراقبة حقيقية دون تفويض قانوني واضح (`Privacy, Consent & Legal Authorization Compliance`)
- **التحليل البرمجي الفعلي**:
  - **منع استخدام أو مطابقة أي بيانات بيومترية بدون موافقة صريحة (`Explicit Consent Enforcement`)**:
    - في جدول `persons` (`registry.py:841`)، القيمة الافتراضية لحقل الموافقة هي `consent INTEGER DEFAULT 0`.
    - ترفض دالة `req_enroll()` (`mersad_live.py:1508-1528, 2906-2925`) ودالة `enroll_step()` (`mersad_live.py:1625-1645`) بدء أو حفظ أي بصمة وجه ما لم يكن سجل الشخص موجوداً ويحمل `consent == 1` صراحةً.
    - تقتصر دالة تحميل الوجوه المعروفة `refresh_known()` (`mersad_live.py:1470-1498`) على الاستعلام الشرطي الصارم:
      `WHERE f.person_id > 0 AND COALESCE(f.quarantined, 0) = 0 AND COALESCE(p.consent, 0) = 1`.
    - عند إلغاء موافقة أي شخص (`consent=False` في `registry.py:1158-1164`)، يحذف النظام فوراً جميع متجهات وجهه من جدول `faces` (`DELETE FROM faces WHERE person_id=?`) ويحدّث الذاكرة الحية في نفس اللحظة.
    - عند ترحيل قواعد البيانات القديمة (`migrate_legacy_faces` في `registry.py:541-620`)، يتم حجر أي بصمة وجه غير مرتبطة بموافقة صريحة (`quarantined=1, quarantine_reason='legacy_face_without_consent'`) واستبعادها نهائياً من المطابقة.
  - **خلو المشروعين من بيانات أشخاص حقيقيين**:
    - تم فحص جميع الملفات وقواعد البيانات والاختبارات في `MERSAD AI` و`MERSAD LAB`؛ لا توجد أي صور وجوه حقيقية أو أسماء مواطنين حقيقيين أو لوحات حقيقية مسربة، بل تعتمد كافة الاختبارات والمحاكاة في `MERSAD LAB` (`sim_engine.py:35-42`) و`insights.seed_demo()` على بيانات اصطناعية ومولدة برمجياً (`Synthetic Data`).
  - **طمس الوجوه تلقائياً لحماية الخصوصية (`Automated Face Blurring`)**:
    - تطمس دالة `get_boxes_to_blur_for_alert()` (`mersad_live.py:936-968`) **100% من الوجوه المرصودة** في جميع صور أدلة تنبيهات المركبات (`alert_kind="vehicle"`)، وتطمس جميع وجوه المارة غير المستهدفين في تنبيهات الوجوه (`alert_kind="face"`).
  - **منع التفعيل الميداني التلقائي واشتراط المراجعة البشرية (`Mandatory Human-in-the-Loop & Non-Production Guardrails`)**:
    - لا يتم إشعار الدوريات الميدانية (`patrols`) تلقائياً عند رصد أي تنبيه؛ بل يظل التنبيه في حالة انتظار (`pending`) داخل غرفة العمليات حتى يضغط المشغل البشري المصرّح له على زر التأكيد (`confirm`) بعد التحقق البصري من الصورة (`mersad_live.py:1395-1435`، مختبر في `selftest.py:907` `patrols NOT notified before human confirmation`).
    - تُحظر برمجياً عملية إرسال الدوريات للتنبيهات الاسترشادية غير المعايرة (`INFO_ONLY` / `ROUTE NOTICE (uncalibrated)`) أو المطابقات التقريبية غير المؤكدة (`P1-F` في `mersad_live.py:1402-1410`).
    - تنص وثائق الإصدار (`MERSAD_PREVIEW_0.1_RELEASE_ACCEPTANCE.md` و`07_KNOWN_LIMITATIONS_AND_FIELD_TESTS_AR.md`) ورسائل بدء التشغيل (`mersad_live.py:4270-4272`) صراحةً على أن النسخة تجريبية للمعاينة الهندسية والمعملية فقط ولا يجوز تشغيلها للمراقبة الحقيقية دون تفويض قانوني رسمي واختبار ميداني معتمد.
- **نتيجة الاختبار الأمني الحي (`SEC-AUDIT-10`, `P0-A`, `STAGE3-GAP09`, `SEC: revoking person consent`)**: **PASS**.

---

## 5. ملخص التوصيات الختامية وحالة الاعتماد النهائي (`Final Release Recommendations`)

1. **اعتماد الشجرة الموحدة `MERSAD_PREVIEW_0.1_FINAL` كمصدر وحيد (`Single Source of Truth`)**:
   - المصدر المعتمد الحالي هو الفرع `fix/preview-0.1-postbuild-42273598736` عند الالتزام النهائي `edaf651321ec9ea6ba613e3ab1630bc16b11b9d5` لمشروع `MERSAD AI` والالتزام `748ac0158761812a6fff63ff6fe626b9df8c252b` لمشروع `MERSAD LAB` (بينما يُحفظ الوسم `rollback-stable-9491bcd` كأثر رجوع تاريخي فقط ولا يُعتمد كفرع حالي).
2. **استكمال بوابة البناء والتشغيل على نظام `Windows 10/11 x64` متصل بالإنترنت**:
   - رفع حزمة التاريخ الجنائي `reports_and_logs/mersad_preview_0_1_verifiable_history.bundle` إلى المستودع وتشغيل `BUILD_AND_VERIFY_FINAL_WINDOWS_RELEASE.bat` لتنزيل أوزان النماذج الأربعة (`yolov8n.pt`, `EasyOCR`, `yunet.onnx`, `sface.onnx`) وبناء واختبار `MERSAD_AI.exe` و`MERSAD_LAB.exe` و`MERSAD_LAB_Setup_x64.exe` فعلياً على Windows.
3. **التحصينات الميدانية الاختيارية قبل الانتقال من `Preview` إلى `Production`**:
   - تفعيل تشفير القرص (`Windows BitLocker`) لحماية قاعدة بيانات `mersad.db` على القرص، وربط الخادم المحلي بوكيل عكسي يدعم `TLS/HTTPS` عند الحاجة إلى تشغيل وضع الشبكة المحلية (`LAN Mode`).

