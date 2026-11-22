# تقرير إغلاق الأمن وجاهزية الإصدار — MERSAD AI

**تاريخ المراجعة:** 22 نوفمبر 2026  
**النطاق:** فرع `security/release-closure-aud006-20261122`  
**المرجع الأمني:** AUD-006 وAUD-005 وAUD-007 وAUD-009 وAUD-010 وAUD-014  
**الحالة:** تنفيذ المعالجات مكتمل مبدئيًا؛ القبول النهائي مشروط بنتائج Windows CI الأخيرة.

## 1. الملخص التنفيذي

عالجت هذه المرحلة مصدرين مباشرين لضعف سياسة المتصفح: لوحة AI الجذرية القديمة التي كانت تحتوي على معالجات أحداث inline، وواجهة LAB التي كانت تضع JavaScript داخل HTML وتسمح بـ `unsafe-inline` في `script-src`.

كما أضيفت طبقة DOM sanitization مركزية للوحة AI، وتشددت متطلبات تشغيل LAB على الشبكة المحلية بحيث لا يبدأ المستمع على LAN دون شهادة ومفتاح TLS صالحين، ورمز مشغّل، وقائمة مضيفين مسموحين.

**لا يمثل هذا التقرير اعتمادًا إنتاجيًا أو ميدانيًا.** يبقى قرار الإنتاج HOLD إلى حين اختبار شهادات نشر فعلية، واختبار LAN في بيئة ميدانية، وإغلاق قيود التوافق القديمة المذكورة في قسم المخاطر المتبقية.

## 2. AUD-006 — DOM-XSS وCSP

### 2.1 توحيد واجهات AI

- استبدال `dashboard.html` الجذرية القديمة بالواجهة الخارجية المستخدمة في `MERSAD_AI_Preview_0.1/dashboard.html`.
- أصبحت النسختان متطابقتين.
- أزيلت سمات أحداث HTML من النوع `on*` وأزيلت كتل JavaScript inline من الصفحتين.
- تُحمّل واجهة AI الآن بالترتيب: `purify.min.js` ثم `dompurify-guard.js` ثم `dashboard.js`.

### 2.2 حماية إدراج HTML

كشف المسح الساكن 89 موضعًا يستخدم `Element.innerHTML` في لوحة AI. لم يُعامل العدد على أنه 89 ثغرة مؤكدة؛ بل جرى إضافة حارس مركزي يلتف حول setter الخاص بـ `Element.prototype.innerHTML` ويمرر كل قيمة عبر DOMPurify قبل كتابتها إلى DOM.

- DOMPurify مثبت على الإصدار 3.4.18.
- أضيف ملف الترخيص الخاص بالمكتبة.
- عند دعم المتصفح لـ Trusted Types، ينشأ policy باسم `mersad-ui-html`.
- عند عدم دعم Trusted Types، يستمر الحارس في تنقية HTML عبر DOMPurify.
- أضيفت إلى CSP سياسة `trusted-types mersad-ui-html dompurify`.
- يرفض فحص الإغلاق أي استعمال لـ `outerHTML` أو `insertAdjacentHTML` أو `document.write` خارج نطاق الحماية الحالية.
- أضيف اختبار متصفح Edge headless يتأكد من إزالة معالجات الأحداث ووسوم script وروابط javascript من HTML محقون، مع المحافظة على محتوى HTML الآمن.

### 2.3 سياسة المحتوى

تستخدم خوادم AI وLAB الآن `script-src 'self'` من دون `'unsafe-inline'`. وأضيفت قيود `object-src 'none'` و`base-uri 'self'` و`form-action 'self'` و`frame-ancestors 'none'`.

**قيد متبقٍ:** ما زالت `style-src 'unsafe-inline'` موجودة لدعم التنسيقات الحالية. هذا لا يعيد السماح بالـ inline scripts، لكنه يعني أن CSP لم تصل بعد إلى سياسة صارمة خالية من inline styles.

## 3. TLS والمصادقة وLAN

### 3.1 خادم AI

- لا يسمح الربط بواجهة غير loopback دون ملفي `MERSAD_TLS_CERT` و`MERSAD_TLS_KEY`.
- يشترط قائمة مضيفين مسموحين تتضمن عنوان LAN الذي يخدمه الخادم.
- الحد الأدنى لإصدار TLS هو TLS 1.2.
- تضاف خاصية HSTS على الاتصالات المشفرة.
- تُستخدم بيانات اعتماد الجلسة في ملفات إعداد محلية بدل طباعتها في سجل التشغيل، وتستخدم خصائص Cookie من نوع HttpOnly وSameSite=Strict، وتضاف Secure عند HTTPS.

### 3.2 خادم LAB

- الربط غير المحلي يتطلب العلم `--allow-lan`.
- يتطلب `MERSAD_LAB_ALLOWED_HOSTS` ورمز LAB صريحًا.
- يتطلب `MERSAD_LAB_TLS_CERT` و`MERSAD_LAB_TLS_KEY` ويُرفض التشغيل عند فقدهما أو عدم وجود ملفيهما.
- يحمّل الخادم الشهادة ويغلف المقبس بـ TLS 1.2 على الأقل قبل بدء الاستماع.
- يُعرض رابط HTTPS ووضع الأمان الصحيحان في سجل التشغيل.
- يظل `/lab.js` موردًا ثابتًا بلا أسرار، ويظل التحقق من Host وOrigin وCSRF والمصادقة مطبقًا على المسارات المحمية.

### 3.3 التوافق القديم

لا يزال خادم AI يقبل `?k=` في طبقة المصادقة دعمًا لبعض العملاء الخارجيين القدامى. لا ينبغي تحويل ذلك إلى نمط تكامل جديد؛ ويجب إزالته بعد ترحيل جميع العملاء والاختبارات إلى Cookie الجلسة أو ترويسة المصادقة.

## 4. التغييرات في البناء والتغليف

- أضيف `lab.js` إلى حزمة PyInstaller والنسخة Portable والمثبت.
- أضيفت ملفات DOMPurify والحارس والترخيص إلى حزمة AI المجمدة والنسخة Portable.
- أضيفت فحوص وجود للملفات في Windows Release وPowerShell build.
- أضيف اختبار frozen EXE للتحقق من تقديم الصفحة وملفات JavaScript المطلوبة مع CSP وX-Content-Type-Options.
- أصبح ماسح DOM-XSS/CSP بوابة إلزامية في مساري Security Regression وWindows Release.

## 5. سجل التحقق

تُسجل النتائج النهائية مع أرقام GitHub Actions في هذا القسم بعد اكتمال أحدث تشغيلين على هذا الفرع:

| بوابة التحقق | الحالة |
|---|---|
| Batch 1 LAB SSRF/DNS/TLS/Auth | بانتظار أحدث Windows CI |
| Batch 2 LAB LAN/IPv6/Cookie/TLS | بانتظار أحدث Windows CI |
| LAB functional/security suite | بانتظار أحدث Windows CI |
| Batch 2 AI TLS/CSRF/Telegram/CSP | بانتظار أحدث Windows CI |
| DOM-XSS/CSP static closure scanner | بانتظار أحدث Windows CI |
| Edge headless DOMPurify runtime smoke | بانتظار أحدث Windows Release |
| AI self-test standard | بانتظار أحدث Windows CI |
| AI self-test without scikit-learn | بانتظار أحدث Windows CI |
| PyInstaller AI/LAB and installer lifecycle | بانتظار أحدث Windows Release |
| Post-upload artifact hash and runtime acceptance | بانتظار أحدث Windows Release |

**ملاحظة تاريخية:** أظهر تشغيل وسيط أن اختبار LAB-SEC-05 القديم كان يفحص HTML فقط، مع أن كود الواجهة نُقل عمدًا إلى `lab.js`. تم تحديث الاختبار ليفحص الملفين، ولم تُحذف قاعدة منع HTML insertion sinks أو تُضعف.

## 6. المخاطر والقيود المفتوحة

1. **اختبار LAN فعلي:** اختبارات CI تثبت تهيئة TLS ورفض الإعدادات غير الآمنة، لكنها لا تثبت نشر شهادة موثوقة على شبكة حقيقية أو اختبار أجهزة عميلة خارجية.
2. **العميل القديم `?k=`:** ما زال مقبولًا لأغراض التوافق؛ يلزم توثيق قائمة العملاء وترحيلهم ثم إزالة query-token authentication.
3. **Inline styles:** لا تزال `style-src 'unsafe-inline'` موجودة؛ يلزم ترحيل التنسيقات إلى CSS خارجي أو nonce/hash قبل فرض CSP أشد.
4. **المراجعة المستقلة:** اختبارات Regression المحلية وCI ليست بديلًا عن اختبار اختراق مستقل من طرف ثالث.
5. **الاستخدام الميداني:** لم يُجرَ في هذه المرحلة تقييم قانوني/خصوصية أو اختبار ميداني لأنظمة التعرف على الوجوه ولوحات المركبات أو ضوابط الوصول والاحتفاظ بالبيانات.

## 7. التوصية

حتى تثبت جميع بوابات Windows الحالية نجاحها، تظل الموافقة **HOLD**. بعد نجاحها يمكن النظر في قبول Preview 0.1 على نطاق تجريبي مضبوط، لكن الإنتاج والنشر الميداني يظلان غير معتمدين حتى إغلاق القيود المفتوحة أعلاه.

لم تُدمج هذه التغييرات إلى `main`.
