# متطلبات النظام والتشغيل — MERSAD AI — PREVIEW 0.1

## 1. نظام التشغيل والمعمارية المدعومة
- **نظام التشغيل**: Windows 10 (64-bit) الإصدار 1909 أو أحدث، أو Windows 11 (64-bit).
- **المعمارية**: `x64 (AMD64)` حصرياً.
- **مكتبات النظام الأساسية**:
  - `Microsoft Visual C++ Redistributable 2015–2022 (x64)` (مطلوبة لتشغيل مكتبات OpenCV وPyTorch وONNX Runtime).

## 2. المواصفات المادية (Hardware Requirements)
| المكون | الحد الأدنى (Minimum — CPU Mode) | المواصفات الموصى بها (Recommended) |
|---|---|---|
| المعالج (CPU) | Intel Core i5 (الجيل الثامن+) أو AMD Ryzen 5 (4 أنوية) | Intel Core i7 / Ryzen 7 (8 أنوية أو أكثر) |
| الذاكرة العشوائية (RAM) | 8 GB RAM | 16 GB RAM (لتشغيل MERSAD AI + MERSAD LAB + 4 كاميرات) |
| المساحة التخزينية (Disk) | 5 GB مساحة حرة على قرص محلي `NTFS` | 20 GB مساحة حرة على قرص `SSD NVMe` محلي |
| بطاقة الرسوميات (GPU) | غير إلزامية (يعمل بالكامل على CPU) | NVIDIA GPU مع CUDA 11.8+ (اختياري لتسريع YOLOv8 وEasyOCR) |

## 3. متطلبات النماذج (AI Models)
يتطلب الوضع الكامل وجود الملفات الأربعة التالية داخل مجلد `models/` (يتم تنزيلها والتحقق من بصماتها `SHA-256` تلقائياً عبر `python prefetch.py --include-yolo` أو أثناء تشغيل `setup.bat` / `BUILD_EXE.bat`):
1. `models/yunet.onnx` (`SHA-256`: `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`)
2. `models/sface.onnx` (`SHA-256`: `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79`)
3. `models/yolov8n.pt` (`SHA-256`: `31e20dde3def09e9cf3eab8c9be6c13eb815ff4c445303f1a3c297e1c2b29f2e`)
4. `models/easyocr/` (أوزان `craft_mlt_25k.pth` + اللغتين العربية `ar` والإنجليزية `en`)

> **ملاحظة خاصة بالوضع التجريبي (`Degraded Preview Mode`)**: في حال الرغبة بمعاينة الواجهة والربط المعملي قبل اكتمال تنزيل النماذج، يمكن تمرير الخيار `--allow-degraded-preview`.
