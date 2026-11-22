"use strict";
const MODES = [
  ["normal", "طبيعي (Normal)"],
  ["lowlight", "إضاءة منخفضة (Lowlight)"],
  ["lowres", "دقة منخفضة (Lowres)"],
  ["noise", "تشويش (Noise)"],
  ["occluded", "حجب العدسة (Occluded)"],
  ["frozen", "تجميد الإطار (Frozen)"],
  ["delay", "تأخير البث (Delay)"],
  ["offline", "منقطع 503 (Offline)"]
];

function labToken() {
  return document.getElementById("lab-token").value.trim();
}

function labAuthHeaders(headers = {}) {
  return Object.assign({}, headers, {"X-Lab-Token": labToken()});
}

function requireLabToken(output) {
  if (labToken()) return true;
  output.textContent = "يرجى إدخال رمز مصادقة المختبر أولاً (X-Lab-Token).";
  return false;
}

async function setCameraMode(camId, mode) {
  try {
    if (!requireLabToken(document.getElementById("health-summary"))) return;
    const res = await fetch("/api/cameras/" + encodeURIComponent(camId) + "/mode", {
      method: "POST",
      headers: labAuthHeaders({"Content-Type": "application/json"}),
      body: JSON.stringify({mode: mode})
    });
    const data = await res.json();
    await refreshState();
    return data;
  } catch (err) {
    console.error("Failed to set mode:", err);
  }
}

function buildCameraCard(cam) {
  const card = document.createElement("div");
  card.className = "card";

  const title = document.createElement("h2");
  title.textContent = cam.title_ar + " [" + cam.cam_id.toUpperCase() + "]";
  card.appendChild(title);

  const meta = document.createElement("div");
  meta.className = "status-line";
  meta.textContent = "الوضع: " + cam.mode + " | اللوحة الاصطناعية: " + cam.synthetic_plate + " | الدقة: " + cam.width + "x" + cam.height + " | FPS: " + cam.fps;
  card.appendChild(meta);

  const img = document.createElement("img");
  img.className = "cam-preview";
  img.alt = cam.cam_id;
  if (cam.mode === "offline") {
    img.src = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='640' height='480'><rect width='100%' height='100%' fill='%23120808'/><text x='50%' y='50%' fill='%23ff5252' font-size='22' text-anchor='middle'>OFFLINE (HTTP 503)</text></svg>";
  } else {
    img.src = cam.frame_url + "?t=" + Date.now();
  }
  card.appendChild(img);

  const ctrls = document.createElement("div");
  ctrls.className = "controls";
  for (const [mKey, mLabel] of MODES) {
    const btn = document.createElement("button");
    btn.textContent = mLabel;
    if (cam.mode === mKey) {
      btn.className = "active-mode";
    }
    btn.addEventListener("click", () => setCameraMode(cam.cam_id, mKey));
    ctrls.appendChild(btn);
  }
  card.appendChild(ctrls);
  return card;
}

async function refreshState() {
  try {
    const res = await fetch("/api/health", {cache: "no-store"});
    const d = await res.json();
    const summaryEl = document.getElementById("health-summary");
    if (d && d.ok) {
      const t = d.telemetry || {};
      summaryEl.textContent = "الحالة: متصل | الذاكرة: " + (t.rss_mb || 0) + " MB | زمن المعالج: " + (t.cpu_time_sec || 0) + "s | الخيوط النشطة: " + (t.active_threads || 0);
      const container = document.getElementById("cameras-container");
      container.replaceChildren();
      const cams = Object.values(d.cameras || {});
      for (const cam of cams) {
        container.appendChild(buildCameraCard(cam));
      }
    }
  } catch (err) {
    document.getElementById("health-summary").textContent = "تعذّر الاتصال بخادم المختبر.";
  }
}

document.getElementById("btn-analyze-img").addEventListener("click", async () => {
  const input = document.getElementById("img-input");
  const out = document.getElementById("img-result");
  if (!input.files || !input.files[0]) {
    out.textContent = "يرجى اختيار ملف صورة أولاً.";
    return;
  }
  if (!requireLabToken(out)) return;
  out.textContent = "جارٍ تحليل الصورة...";
  const fd = new FormData();
  fd.append("file", input.files[0]);
  try {
    const r = await fetch("/api/analyze/image", {method: "POST", headers: labAuthHeaders(), body: fd});
    const d = await r.json();
    out.textContent = JSON.stringify(d, null, 2);
  } catch (e) {
    out.textContent = "خطأ أثناء رفع الصورة.";
  }
});

document.getElementById("btn-analyze-vid").addEventListener("click", async () => {
  const input = document.getElementById("vid-input");
  const out = document.getElementById("vid-result");
  if (!input.files || !input.files[0]) {
    out.textContent = "يرجى اختيار ملف فيديو أولاً.";
    return;
  }
  if (!requireLabToken(out)) return;
  out.textContent = "جارٍ تحليل الفيديو...";
  const fd = new FormData();
  fd.append("file", input.files[0]);
  try {
    const r = await fetch("/api/analyze/video", {method: "POST", headers: labAuthHeaders(), body: fd});
    const d = await r.json();
    out.textContent = JSON.stringify(d, null, 2);
  } catch (e) {
    out.textContent = "خطأ أثناء رفع الفيديو.";
  }
});

document.getElementById("btn-connect-ai").addEventListener("click", async () => {
  const aiUrl = document.getElementById("ai-url").value.trim();
  const aiToken = document.getElementById("ai-token").value.trim();
  const camId = document.getElementById("ai-cam-select").value;
  const out = document.getElementById("ai-connect-result");
  if (!requireLabToken(out)) return;
  out.textContent = "جارٍ الاتصال بمرصاد الذكي...";
  try {
    const r = await fetch("/api/integration/connect_ai", {
      method: "POST",
      headers: labAuthHeaders({"Content-Type": "application/json"}),
      body: JSON.stringify({ai_url: aiUrl, ai_token: aiToken, cam_id: camId})
    });
    const d = await r.json();
    out.textContent = JSON.stringify(d, null, 2);
  } catch (e) {
    out.textContent = "تعذّر إرسال الطلب.";
  }
});

refreshState();
setInterval(refreshState, 3000);
