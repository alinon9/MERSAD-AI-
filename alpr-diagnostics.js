/* Privacy-safe live ALPR diagnostics for the authenticated operations dashboard. */
(() => {
  "use strict";

  const host = document.getElementById("alpr-diag");
  const updatedLabel = document.getElementById("alpr-diag-updated");
  if (!host) return;

  const reasonLabels = {
    waiting_for_first_frame: "بانتظار أول إطار تحليل",
    processing_frame: "جارٍ تحليل الإطار",
    vehicle_boxes_found: "تم اكتشاف مركبة أو أكثر داخل الإطار",
    no_vehicle_boxes_full_frame_fallback: "لم يكتشف كاشف المركبات؛ يجري فحص الإطار كاملًا بحثًا عن لوحة",
    no_vehicle_boxes_full_frame_no_plate_candidates: "لم تُكتشف مركبة ولم يعثر فحص الإطار الكامل على منطقة لوحة مرشحة",
    skip_ocr_no_vehicle: "تجاوز النظام فحص اللوحات لأن كاشف المركبات لم يجد مركبة وإعداد تجاوز الإطار الكامل مفعّل",
    no_plate_candidates: "لم يعثر كاشف اللوحات على أي منطقة مرشحة",
    trucks_only_filter_skipped_all: "مرشح الشاحنات فقط تجاهل المركبات المكتشفة؛ لم يُنفذ OCR عليها",
    ocr_unavailable: "محرك OCR غير متاح في هذه الجلسة",
    ocr_no_result: "وجد النظام منطقة لوحة مرشحة، لكن OCR لم يستخرج نصًا مقبولًا",
    awaiting_multi_frame_confirmation: "تم استخراج قراءة أولية؛ ينتظر النظام قراءات متوافقة لتأكيدها",
    plate_confirmed: "اكتملت قراءة مؤكدة وفق شرط تعدد الإطارات",
    inference_exception: "حدث استثناء أثناء معالجة إطار؛ راجع سجل backend لمعرفة التفاصيل"
  };

  const stageLabels = {
    waiting: "بانتظار التحليل",
    vehicle_detection: "اكتشاف المركبات",
    plate_detection: "اكتشاف مناطق اللوحات",
    ocr: "قراءة النص OCR",
    confirmation: "تأكيد القراءة",
    inference_error: "خطأ في المعالجة"
  };

  function node(tag, className, text) {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (text !== undefined && text !== null) item.textContent = String(text);
    return item;
  }

  function metric(label, value) {
    const box = node("div", "alpr-metric");
    box.append(node("b", "", value === undefined || value === null ? "—" : value));
    box.append(node("span", "", label));
    return box;
  }

  function modelBadge(label, available) {
    return node("span", "chip " + (available ? "ok" : "wn"),
      label + ": " + (available ? "متاح" : "غير متاح"));
  }

  function render(payload) {
    const cameras = payload && payload.cameras && typeof payload.cameras === "object"
      ? payload.cameras : {};
    const names = Object.keys(cameras);
    const fragment = document.createDocumentFragment();

    if (!names.length) {
      fragment.append(node("p", "mu", "لا توجد كاميرات مضافة في جلسة المحرك الحالية."));
      host.replaceChildren(fragment);
      if (updatedLabel) updatedLabel.textContent = "لا توجد بيانات كاميرات";
      return;
    }

    names.sort().forEach((cameraName) => {
      const camera = cameras[cameraName] || {};
      const d = camera.alpr || {};
      const panel = node("div", "");
      panel.style.borderTop = "1px solid var(--ln)";
      panel.style.paddingTop = "10px";
      panel.style.marginTop = "10px";

      const header = node("div", "bar");
      header.append(node("strong", "", cameraName));
      header.append(node("span", "mu",
        (camera.status === "online" ? "متصل" : String(camera.status || "حالة غير معروفة"))
        + " · " + Number(camera.fps || 0).toFixed(1) + " fps"));
      panel.append(header);

      const reasonCode = String(d.last_reason_code || "waiting_for_first_frame");
      let stateClass = "alpr-state";
      if (reasonCode === "plate_confirmed") stateClass += " good";
      else if (reasonCode === "inference_exception" || reasonCode === "ocr_unavailable") stateClass += " bad";
      else if (reasonCode !== "waiting_for_first_frame" && reasonCode !== "processing_frame") stateClass += " warn";

      panel.append(node("div", stateClass,
        reasonLabels[reasonCode] || "حالة المعالجة: " + reasonCode));

      const grid = node("div", "alpr-grid");
      grid.append(metric("إطارات حلّلها محرك AI", d.frames_processed || 0));
      grid.append(metric("إطارات استبعدها فلتر الشاحنات", d.frames_filtered_by_trucks_only || 0));
      grid.append(metric("مربعات المركبات", d.vehicle_boxes_total || 0));
      grid.append(metric("مناطق اللوحات المرشحة", d.plate_candidates_total || 0));
      grid.append(metric("قصاصات أُرسلت إلى OCR", d.ocr_attempts || 0));
      grid.append(metric("نتائج OCR النصية", d.ocr_text_candidates || 0));
      grid.append(metric("قراءات مؤكدة", d.confirmed_reads || 0));
      grid.append(metric("قراءات بلا نتيجة OCR", d.ocr_no_result || 0));
      grid.append(metric("قراءات تنتظر التأكيد", d.pending_vote_count || 0));
      grid.append(metric("متوسط زمن التحليل", Number(d.mean_inference_ms || 0).toFixed(0) + " ms"));
      panel.append(grid);

      const models = node("div", "alpr-models");
      models.append(modelBadge("كاشف المركبات", !!d.vehicle_model_loaded));
      models.append(modelBadge("OCR", !!d.ocr_model_loaded));
      if (d.trucks_only_mode) models.append(node("span", "chip wn", "وضع الشاحنات فقط"));
      const detectorName = d.plate_detector_mode === "yolo_plate_model"
        ? "YOLO مخصص للوحات" : "Canny التقليدي";
      models.append(node("span", "chip mu", "كاشف اللوحة: " + detectorName));
      panel.append(models);

      const details = node("div", "mu");
      const stage = stageLabels[d.last_stage] || String(d.last_stage || "غير معروف");
      const confidence = d.last_ocr_confidence !== null && d.last_ocr_confidence !== undefined
        && Number.isFinite(Number(d.last_ocr_confidence))
        ? Math.round(Number(d.last_ocr_confidence) * 100) + "%" : "—";
      const time = d.updated_at
        ? new Date(Number(d.updated_at) * 1000).toLocaleTimeString()
        : "لم يبدأ";
      details.style.marginTop = "7px";
      details.textContent = "المرحلة الأخيرة: " + stage
        + " · آخر عدد مركبات: " + Number(d.last_vehicle_boxes || 0)
        + " · آخر مناطق لوحات: " + Number(d.last_plate_candidates || 0)
        + " · ثقة آخر OCR: " + confidence
        + " · آخر تحديث: " + time
        + " · أخطاء المعالجة: " + Number(d.errors || 0)
        + (d.last_error_type ? " · نوع آخر استثناء: " + String(d.last_error_type) : "");
      panel.append(details);

      fragment.append(panel);
    });

    host.replaceChildren(fragment);
    if (updatedLabel) {
      const generated = payload && payload.generated_at
        ? new Date(Number(payload.generated_at) * 1000).toLocaleTimeString() : "";
      updatedLabel.textContent = generated ? "تحديث " + generated : "مباشر";
    }
  }

  let busy = false;
  async function refresh() {
    if (busy || document.hidden) return;
    busy = true;
    try {
      const response = await fetch("/api/alpr-diagnostics", {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
        headers: { "Accept": "application/json" }
      });
      if (!response.ok) throw new Error("HTTP " + response.status);
      const payload = await response.json();
      if (!payload || payload.ok !== true) throw new Error("invalid diagnostics payload");
      render(payload);
    } catch (_error) {
      host.replaceChildren(node("p", "mu", "تعذر تحديث التشخيص الآن؛ تحقق من اتصال لوحة مرصاد ثم أعد المحاولة."));
      if (updatedLabel) updatedLabel.textContent = "تعذر التحديث";
    } finally {
      busy = false;
    }
  }

  refresh();
  window.setInterval(refresh, 3000);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refresh();
  });
})();
