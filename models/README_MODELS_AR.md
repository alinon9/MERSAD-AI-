# مجلد نماذج الذكاء الاصطناعي — MERSAD AI PREVIEW 0.1

يُحفظ داخل هذا المجلد أوزان النماذج الأربعة المعتمدة عند تشغيل `prefetch.py` أو `setup.bat` أو `BUILD_EXE.bat`:
1. `yunet.onnx` — كشف الوجوه (OpenCV Zoo HuggingFace Commit `39a1451d0f9b23fc4ebaed06a277127efa0374d0`)
   - SHA-256 الثابت الموثوق: `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`
2. `sface.onnx` — مطابقة الوجوه للمتطوعين المصرحين فقط (`consent=1`)
   - SHA-256 الثابت الموثوق: `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79`
3. `yolov8n.pt` — كشف المركبات والشاحنات (Ultralytics `v8.3.0`)
   - فحص أمان `_scan_pt_pickle_safety` + توقيع `.sha256` و `.trusted_models.json` (TOFU)
4. `easyocr/*.pth` — قارئ النصوص العربية والإنجليزية (`craft_mlt_25k.pth` + `arabic_g2.pth`)
   - فحص بنيوي مع تعطيل التحميل الحي (`download_enabled=False`)
