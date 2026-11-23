(() => {
  "use strict";
  const byId = (id) => document.getElementById(id);
  const statusEl = () => byId("cam-manager-status");
  async function requestJson(path, method = "GET", payload) {
    const options = {method, credentials:"same-origin", cache:"no-store", headers:{}};
    if (payload !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(payload);
    }
    const response = await fetch(path, options);
    let data = {};
    try { data = await response.json(); } catch (_) {}
    if (!response.ok || data.ok === false) throw new Error(data.error || ("HTTP " + response.status));
    return data;
  }
  function setStatus(message, bad = false) {
    const el = statusEl();
    if (!el) return;
    el.textContent = message || "";
    el.style.color = bad ? "var(--er)" : "var(--mu)";
  }
  function statusLabel(value) {
    return value === "online" ? "متصلة" : value === "reconnecting" ? "جارٍ الاتصال" :
      value === "offline" ? "غير متصلة" : "الحالة غير معروفة";
  }
  async function refreshDevices() {
    const select = byId("cam-manager-device");
    if (!select) return;
    select.disabled = true;
    select.replaceChildren();
    const loading = document.createElement("option");
    loading.value = "";
    loading.textContent = "جارٍ البحث عن الكاميرات...";
    select.appendChild(loading);
    try {
      const result = await requestJson("/api/camera_devices");
      const devices = Array.isArray(result.devices) ? result.devices : [];
      select.replaceChildren();
      if (!devices.length) {
        const option = document.createElement("option");
        option.value = "";
        option.textContent = "لم يتم العثور على كاميرا جديدة";
        select.appendChild(option);
        setStatus("لم تظهر كاميرا جديدة. شغّل DroidCam Client في Windows ثم اضغط تحديث الكاميرات.", true);
      } else {
        for (const device of devices) {
          const option = document.createElement("option");
          option.value = String(device.source);
          option.textContent = device.label + " — " + device.resolution;
          select.appendChild(option);
        }
        setStatus("تم العثور على " + devices.length + " كاميرا متاحة.");
      }
    } catch (error) {
      select.replaceChildren();
      const failed = document.createElement("option");
      failed.value = "";
      failed.textContent = "تعذر فحص الكاميرات";
      select.appendChild(failed);
      setStatus("تعذر فحص الكاميرات: " + error.message, true);
    } finally { select.disabled = false; }
  }
  async function loadCameraList() {
    const host = byId("cam-manager-list");
    if (!host) return;
    host.textContent = "جارٍ تحميل الكاميرات...";
    try {
      const result = await requestJson("/api/cameras");
      const entries = Object.entries(result.cameras || {});
      host.replaceChildren();
      if (!entries.length) { host.textContent = "لا توجد كاميرات مرتبطة حاليًا."; return; }
      for (const [name, info] of entries) {
        const row = document.createElement("div");
        row.className = "fd";
        const meta = document.createElement("span");
        meta.textContent = name + " — " + statusLabel(info.status) +
          (Number(info.fps) > 0 ? " — " + Number(info.fps).toFixed(1) + " FPS" : "");
        row.appendChild(meta);
        const actions = document.createElement("span");
        actions.className = "act";
        const show = document.createElement("button");
        show.type = "button"; show.textContent = "عرض البث";
        show.addEventListener("click", () => {
          const video = byId("v");
          if (video) video.src = "/stream.mjpg?cam=" + encodeURIComponent(name) + "&view=" + Date.now();
          const label = byId("hcam");
          if (label) label.textContent = name;
          byId("cam-manager-dialog")?.close();
        });
        actions.appendChild(show);
        if (name !== "CAM1") {
          const remove = document.createElement("button");
          remove.type = "button"; remove.className = "er"; remove.textContent = "إزالة";
          remove.addEventListener("click", async () => {
            remove.disabled = true;
            try {
              await requestJson("/api/cameras/remove", "POST", {name});
              setStatus("تم طلب إزالة " + name + ".");
              await loadCameraList();
            } catch (error) {
              setStatus("تعذرت إزالة الكاميرا: " + error.message, true);
              remove.disabled = false;
            }
          });
          actions.appendChild(remove);
        }
        row.appendChild(actions); host.appendChild(row);
      }
    } catch (error) { host.textContent = "تعذر تحميل قائمة الكاميرات: " + error.message; }
  }
  function updateMode() {
    const mode = byId("cam-manager-mode")?.value || "device";
    if (byId("cam-manager-device-box")) byId("cam-manager-device-box").hidden = mode !== "device";
    if (byId("cam-manager-url-box")) byId("cam-manager-url-box").hidden = mode !== "url";
  }
  async function connectCamera() {
    const name = (byId("cam-manager-name")?.value || "PHONE_CAM2").trim();
    const mode = byId("cam-manager-mode")?.value || "device";
    const source = mode === "device" ? (byId("cam-manager-device")?.value || "") :
      (byId("cam-manager-url")?.value || "").trim();
    if (!name) return setStatus("اكتب اسمًا للكاميرا.", true);
    if (!source) return setStatus(mode === "device" ? "اختر كاميرا من القائمة أولًا." : "أدخل رابط بث الهاتف.", true);
    if (mode === "url" && !/^(https?|rtsps?):\/\//i.test(source))
      return setStatus("الرابط يجب أن يبدأ بـ http:// أو https:// أو rtsp://.", true);
    const button = byId("cam-manager-connect");
    if (button) button.disabled = true;
    setStatus("جارٍ ربط الكاميرا...");
    try {
      const result = await requestJson("/api/cameras/add", "POST", {name, source, spawn_worker:true});
      setStatus("تم إرسال طلب الربط: " + result.camera + " — " + statusLabel(result.status) +
        ". إذا لم يبدأ البث، تحقق من اتصال DroidCam ثم أعد المحاولة.");
      await loadCameraList();
    } catch (error) { setStatus("فشل ربط الكاميرا: " + error.message, true); }
    finally { if (button) button.disabled = false; }
  }
  function init() {
    const open = byId("cam-manager-open"), dialog = byId("cam-manager-dialog");
    if (!open || !dialog) return;
    open.addEventListener("click", async () => {
      if (!dialog.open) dialog.showModal();
      await Promise.all([refreshDevices(), loadCameraList()]);
    });
    byId("cam-manager-close")?.addEventListener("click", () => dialog.close());
    byId("cam-manager-refresh")?.addEventListener("click", refreshDevices);
    byId("cam-manager-connect")?.addEventListener("click", connectCamera);
    byId("cam-manager-mode")?.addEventListener("change", updateMode);
    updateMode(); loadCameraList();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, {once:true});
  else init();
})();