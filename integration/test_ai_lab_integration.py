#!/usr/bin/env python3
"""
MERSAD AI V7.1 + MERSAD LAB 1.0 — PREVIEW 0.1
Phase 4: Final End-to-End Integration Validation Suite
======================================================
Strictly separates:
  1. PRIMARY ACCEPTANCE PIPELINE (`--require-real-models`):
     `LAB -> MJPEG -> OpenCV -> YOLOv8n -> Plate Detection -> EasyOCR -> Registry -> Alerts -> SQLite -> Audit`
     - Uses ONLY real `YOLOv8n` (`models/yolov8n.pt`) and real `EasyOCR` (`easyocr.Reader(['ar', 'en'])`).
     - NEVER substitutes Tesseract or Mock objects for YOLOv8n or EasyOCR.
     - Marked `NOT_TESTED` in the offline Linux sandbox where `ultralytics`/`torch`/`easyocr` are unavailable,
       and executed with strict `PASS/FAIL` enforcement on Windows x64 / GitHub Actions (`--require-real-models`).
  2. INDEPENDENT ENGINE & TRANSPORT PIPELINE (Auxiliary Test):
     Tests `MersadEngineController` (`_camera_reader_worker` + `_camera_inference_worker`), MJPEG streaming,
     camera disconnect (`HTTP 503`), multi-camera continuity, automatic reconnection, alert deduplication,
     `FROZEN_STREAM`/`CAMERA_OCCLUDED_OR_DARK` telemetry, and shutdown/restart SQLite HMAC-SHA256 audit continuity
     using the independent `Tesseract 5 LSTM` pixel OCR engine.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
AI_DIR = ROOT_DIR / "MERSAD_AI_Preview_0.1"
LAB_DIR = ROOT_DIR / "MERSAD_LAB_Preview_0.1"

sys.path.insert(0, str(AI_DIR))
sys.path.insert(0, str(LAB_DIR))

INTEGRATION_HOME = tempfile.mkdtemp(prefix="mersad_final_int_")
os.environ["MERSAD_DATA_DIR"] = INTEGRATION_HOME
os.environ["YOLO_AUTOINSTALL"] = "false"
os.environ["ULTRALYTICS_AUTOINSTALL"] = "false"

import analytics as an
import mersad_live as m
import prefetch as pf
import registry as reg
import server as ai_srv
from lab_server import LabServerController, get_process_telemetry

PASS = 0
FAIL = 0
NOT_TESTED = 0
REPORT = {
    "suite": "MERSAD_PREVIEW_0.1_PHASE4_FINAL_INTEGRATION",
    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    "checks": [],
    "telemetry": {},
}


def record(name: str, status: str, category: str, detail: str = "", metrics: dict = None):
    global PASS, FAIL, NOT_TESTED
    if status == "PASS":
        PASS += 1
    elif status == "NOT_TESTED":
        NOT_TESTED += 1
    else:
        FAIL += 1
    print(f"  [{status:10s}] [{category:28s}] {name}" + (f" -- {detail}" if detail else ""))
    entry = {"check": name, "status": status, "category": category, "detail": detail}
    if metrics:
        entry["metrics"] = metrics
    REPORT["checks"].append(entry)


def _http_json(url: str, method: str = "GET", payload: dict = None, headers: dict = None, timeout: float = 8.0):
    hdrs = dict(headers or {})
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as he:
        raw = he.read() if he.fp else b"{}"
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except Exception:
            parsed = {"raw": raw.decode("utf-8", errors="ignore")}
        return he.code, parsed


def _wait_until(predicate, timeout_sec: float = 8.0, poll_sec: float = 0.1):
    deadline = time.time() + timeout_sec
    last_val = None
    while time.time() < deadline:
        last_val = predicate()
        if last_val:
            return last_val
        time.sleep(poll_sec)
    return last_val


def load_strict_real_yolo_and_easyocr():
    """Attempt to load real YOLOv8n and real EasyOCR without any mock or Tesseract fallback."""
    vyolo = None
    eocr_reader = None
    errs = []
    yolo_path = AI_DIR / "models" / "yolov8n.pt"
    try:
        from ultralytics import YOLO
        if yolo_path.is_file():
            ok_y, r_y = pf.verify_yolo_pt_file(str(yolo_path), expected_sha256=pf.MODEL_SHA256["yolov8n.pt"])
            if not ok_y:
                raise RuntimeError(f"yolov8n.pt failed SHA-256 verification before load: {r_y}")
            vyolo = YOLO(str(yolo_path))
        else:
            errs.append("models/yolov8n.pt missing on disk")
    except Exception as e:
        errs.append(f"YOLOv8n load failed: {type(e).__name__}: {e}")

    easyocr_dir = AI_DIR / "models" / "easyocr"
    eocr_ok, eocr_reason = pf.verify_easyocr_dir(str(easyocr_dir))
    try:
        import easyocr
        if eocr_ok:
            eocr_reader = easyocr.Reader(["ar", "en"], gpu=False, model_storage_directory=str(easyocr_dir), download_enabled=False)
        else:
            errs.append(f"EasyOCR weights missing: {eocr_reason}")
    except Exception as e:
        errs.append(f"EasyOCR load failed: {type(e).__name__}: {e}")

    return vyolo, eocr_reader, errs


def main():
    ap = argparse.ArgumentParser(description="MERSAD Phase 4: Final End-to-End Integration Validation")
    ap.add_argument("--require-real-models", action="store_true", help="Require real YOLOv8n + real EasyOCR (no Tesseract fallback) to pass acceptance")
    args = ap.parse_args()

    print("========================================================================================")
    print("  MERSAD PREVIEW 0.1 — Phase 4: Final End-to-End Integration Validation")
    print("========================================================================================")
    t_suite_start = time.time()
    cpu_start = time.process_time()

    m.RECONNECT_BASE_SEC = 0.25
    m.RECONNECT_MAX_SEC = 1.0
    m.CAMERA_STALL_SEC = 0.6
    m.OFFLINE_ALERT_SEC = 1.2
    m.CONFIRM_READS = 3

    m.init_runtime_env(appdir=INTEGRATION_HOME, force=True)
    reg.init(m.db, m.DBL, m.log, lambda: None, m.DB_PATH)

    reg.save_vehicle(
        {
            "plate": "عدن 12345",
            "type": "سيارة",
            "status": "مطلوبة",
            "owner": "مركبة اختبار اصطناعية — PREVIEW 0.1",
            "notes": "بيانات اصطناعية لاختبار المسار الكامل",
        },
        "127.0.0.1",
    )

    ai_srv.bus.evidence_dir = os.path.join(INTEGRATION_HOME, "evidence")
    ai_srv.bus.archive_dir = os.path.join(INTEGRATION_HOME, "evidence_archive")
    ai_srv.bus.verify = m.verify
    ai_srv.bus.on_stats = lambda: dict(m.STATUS, alerts=len(ai_srv.bus.alerts))
    ai_srv.bus.on_cameras_list = m.list_cameras_runtime
    ai_srv.bus.on_analytics = lambda: an.build_report(m.db, m.DBL)
    ai_srv.bus.post["/api/cameras/add"] = lambda d, ip: m.add_camera_runtime(d, who=ip)
    ai_srv.bus.post["/api/cameras/remove"] = lambda d, ip: m.remove_camera_runtime(d, who=ip)

    lab_ctrl = LabServerController(host="127.0.0.1", port=0, token="lab_final_int_2026", require_auth=False)
    lab_ctrl.start()
    lab_base = f"http://127.0.0.1:{lab_ctrl.port}"

    # ----------------------------------------------------------------------
    # TRACK A: Primary Acceptance Pipeline (Strictly Real YOLOv8n + Real EasyOCR)
    # ----------------------------------------------------------------------
    real_vyolo, real_easyocr, real_model_errs = load_strict_real_yolo_and_easyocr()
    if real_vyolo is not None and real_easyocr is not None:
        active_vyolo = real_vyolo
        active_reader = real_easyocr
        pipeline_cat = "PRIMARY_REAL_MODELS_E2E"
        record(
            "PHASE4-GATE-01: Primary pipeline `LAB -> MJPEG -> OpenCV -> YOLOv8n -> Plate -> EasyOCR -> Registry -> Alert -> SQLite -> Audit`",
            "PASS",
            "PRIMARY_REAL_MODELS_E2E",
            "Real YOLOv8n and Real EasyOCR loaded and active in camera worker pipeline",
        )
    else:
        err_summary = "; ".join(real_model_errs)
        record(
            "PHASE4-GATE-01: Primary pipeline `LAB -> MJPEG -> OpenCV -> YOLOv8n -> Plate -> EasyOCR -> Registry -> Alert -> SQLite -> Audit`",
            "FAIL" if args.require_real_models else "NOT_TESTED",
            "PRIMARY_REAL_MODELS_E2E",
            f"Blocked in offline Linux sandbox (Tesseract NOT substituted for EasyOCR acceptance): {err_summary}",
        )
        active_vyolo = None
        active_reader = m.TesseractOCRReader()
        pipeline_cat = "INDEPENDENT_TESSERACT_E2E"

    engine = m.MersadEngineController(
        reader=active_reader,
        vyolo=active_vyolo,
        yolo=None,
        infer_every_n=1,
        stall_sec=0.6,
        offline_alert_sec=1.2,
    )
    engine.start()

    ai_httpd = ai_srv.ThreadingHTTPServer(("127.0.0.1", 0), ai_srv.H)
    ai_port = ai_httpd.server_address[1]
    ai_base = f"http://127.0.0.1:{ai_port}"
    ai_thread = threading.Thread(target=ai_httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    ai_thread.start()
    ai_headers = {"X-Mersad-Token": ai_srv.bus.token}

    try:
        # 1. Connect LAB cam1 & cam2 -> spawn real worker threads
        st_c1, d_c1 = _http_json(
            f"{lab_base}/api/integration/connect_ai",
            method="POST",
            payload={"ai_url": ai_base, "ai_token": ai_srv.bus.token, "cam_id": "cam1", "cam_name": "LAB_CAM1"},
        )
        st_c2, d_c2 = _http_json(
            f"{lab_base}/api/integration/connect_ai",
            method="POST",
            payload={"ai_url": ai_base, "ai_token": ai_srv.bus.token, "cam_id": "cam2", "cam_name": "LAB_CAM2"},
        )
        w1_spawned = d_c1.get("ai_response", {}).get("worker_spawned") is True
        w2_spawned = d_c2.get("ai_response", {}).get("worker_spawned") is True
        record(
            "INT-E2E-01: Connect LAB cam1 & cam2 -> spawn real AI reader & inference threads",
            "PASS" if (st_c1 == 200 and st_c2 == 200 and w1_spawned and w2_spawned) else "FAIL",
            pipeline_cat,
            f"LAB_CAM1 worker_spawned={w1_spawned}, LAB_CAM2 worker_spawned={w2_spawned}",
        )

        # 2. Autonomous frame ingestion, plate detection, pixel OCR, registry match, alert, SQLite & Audit
        def _check_pipeline_completed():
            _, stats = _http_json(f"{ai_base}/api/stats", headers=ai_headers)
            with m.DBL:
                sights = m.db.execute("SELECT cam, plate, conf, raw_text FROM sightings ORDER BY rowid").fetchall()
            plates_seen = {r[1] for r in sights}
            if "عدن-12345" in plates_seen and "صنعاء-48210" in plates_seen and stats.get("alerts", 0) >= 1:
                return stats, sights
            return None

        pipeline_res = _wait_until(_check_pipeline_completed, timeout_sec=20.0, poll_sec=0.15)
        if pipeline_res:
            stats_now, sights_now = pipeline_res
            ok_e2e_02 = True
            detail_02 = (
                f"Sightings={[(r[0], r[1], round(r[2], 2)) for r in sights_now[:4]]}, "
                f"alerts={stats_now.get('alerts')}, ocr_engine={getattr(active_reader, 'engine_name', 'EasyOCR')}"
            )
        else:
            ok_e2e_02 = False
            detail_02 = "Timed out waiting for autonomous worker sightings"

        record(
            "INT-E2E-02: Autonomous worker stream ingestion -> Plate -> Pixel OCR -> Registry -> Alert -> SQLite",
            "PASS" if ok_e2e_02 else "FAIL",
            pipeline_cat,
            detail_02,
        )

        # 3. Alert deduplication
        _, stats_before_dedup = _http_json(f"{ai_base}/api/stats", headers=ai_headers)
        f_before = stats_before_dedup.get("cameras", {}).get("LAB_CAM1", {}).get("frames", 0)
        time.sleep(1.2)
        _, stats_after_dedup = _http_json(f"{ai_base}/api/stats", headers=ai_headers)
        f_after = stats_after_dedup.get("cameras", {}).get("LAB_CAM1", {}).get("frames", 0)
        wanted_alerts_cam1 = [
            a for a in ai_srv.bus.alerts
            if a.get("cam") == "LAB_CAM1" and "12345" in str(a.get("subject", ""))
        ]
        ok_e2e_03 = (f_after > f_before + 3) and (len(wanted_alerts_cam1) == 1)
        record(
            "INT-E2E-03: Alert deduplication across continuous frames of same vehicle",
            "PASS" if ok_e2e_03 else "FAIL",
            pipeline_cat,
            f"LAB_CAM1 frames {f_before}->{f_after}, alerts for عدن-12345: {len(wanted_alerts_cam1)} (expected 1)",
        )

        # 4. Autonomous camera disconnect & other camera continuity
        _, cams_pre_off = _http_json(f"{ai_base}/api/cameras", headers=ai_headers)
        cam2_frames_pre_off = cams_pre_off.get("cameras", {}).get("LAB_CAM2", {}).get("frames", 0)
        _http_json(f"{lab_base}/api/cameras/cam1/mode", method="POST", payload={"mode": "offline"})

        def _check_cam1_disconnected():
            _, cd = _http_json(f"{ai_base}/api/cameras", headers=ai_headers)
            c1 = cd.get("cameras", {}).get("LAB_CAM1", {})
            c2 = cd.get("cameras", {}).get("LAB_CAM2", {})
            if c1.get("status") in ("reconnecting", "offline") and c1.get("fail_count", 0) >= 1 and c2.get("frames", 0) > cam2_frames_pre_off + 2:
                return c1, c2
            return None

        disc_res = _wait_until(_check_cam1_disconnected, timeout_sec=6.0, poll_sec=0.1)
        ok_e2e_04 = bool(disc_res and disc_res[0]["status"] in ("reconnecting", "offline") and disc_res[1]["status"] == "online")
        record(
            "INT-E2E-04: Autonomous camera disconnect detection & multi-camera continuity",
            "PASS" if ok_e2e_04 else "FAIL",
            pipeline_cat,
            f"LAB_CAM1={disc_res[0]['status'] if disc_res else None}, LAB_CAM2={disc_res[1]['status'] if disc_res else None}",
        )

        # 5. Autonomous camera reconnection
        _http_json(f"{lab_base}/api/cameras/cam1/mode", method="POST", payload={"mode": "normal"})

        def _check_cam1_reconnected():
            _, cd = _http_json(f"{ai_base}/api/cameras", headers=ai_headers)
            c1 = cd.get("cameras", {}).get("LAB_CAM1", {})
            if c1.get("status") == "online" and c1.get("reconnect_count", 0) >= 1:
                return c1
            return None

        rec_res = _wait_until(_check_cam1_reconnected, timeout_sec=6.0, poll_sec=0.1)
        with m.DBL:
            rec_audits = m.db.execute("SELECT action, ref FROM audit WHERE action='camera reconnected'").fetchall()
        ok_e2e_05 = bool(rec_res and rec_res.get("status") == "online" and len(rec_audits) >= 1)
        record(
            "INT-E2E-05: Autonomous camera reconnection & SQLite audit record",
            "PASS" if ok_e2e_05 else "FAIL",
            pipeline_cat,
            f"LAB_CAM1 status={rec_res.get('status') if rec_res else None}, reconnect_count={rec_res.get('reconnect_count') if rec_res else 0}",
        )

        # 6. Autonomous FROZEN_STREAM & CAMERA_OCCLUDED_OR_DARK detection
        m._CAM_QUALITY_STATE.pop("LAB_CAM1", None)
        _http_json(f"{lab_base}/api/cameras/cam1/mode", method="POST", payload={"mode": "frozen"})
        froz_res = _wait_until(
            lambda: (lambda cd: cd["cameras"]["LAB_CAM1"] if "FROZEN_STREAM" in cd.get("cameras", {}).get("LAB_CAM1", {}).get("issues", []) else None)(_http_json(f"{ai_base}/api/cameras", headers=ai_headers)[1]),
            timeout_sec=5.0,
            poll_sec=0.1,
        )
        _http_json(f"{lab_base}/api/cameras/cam1/mode", method="POST", payload={"mode": "occluded"})
        occ_res = _wait_until(
            lambda: (lambda cd: cd["cameras"]["LAB_CAM1"] if "CAMERA_OCCLUDED_OR_DARK" in cd.get("cameras", {}).get("LAB_CAM1", {}).get("issues", []) else None)(_http_json(f"{ai_base}/api/cameras", headers=ai_headers)[1]),
            timeout_sec=5.0,
            poll_sec=0.1,
        )
        _http_json(f"{lab_base}/api/cameras/cam1/mode", method="POST", payload={"mode": "normal"})
        record(
            "INT-E2E-06: Autonomous stream health telemetry (FROZEN_STREAM & CAMERA_OCCLUDED_OR_DARK)",
            "PASS" if (froz_res and occ_res) else "FAIL",
            pipeline_cat,
            f"frozen={froz_res.get('health_warning') if froz_res else None}, occluded={occ_res.get('issues') if occ_res else None}",
        )

        # 7. Clean engine shutdown, restart & HMAC-SHA256 audit chain continuity
        engine.stop(timeout=4.0)
        verify_before = m.verify()
        with m.DBL:
            audit_before = m.db.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
        m.db.close()
        m.db = None
        m._RUNTIME_INITIALIZED = False

        m.init_runtime_env(appdir=INTEGRATION_HOME, force=True)
        reg.init(m.db, m.DBL, m.log, lambda: None, m.DB_PATH)
        engine2 = m.MersadEngineController(reader=active_reader, vyolo=active_vyolo, infer_every_n=1, stall_sec=0.6, offline_alert_sec=1.2)
        engine2.start()
        engine2.add_camera("LAB_CAM1", f"{lab_base}/stream/cam1.mjpg")
        time.sleep(0.8)
        engine2.stop(timeout=4.0)
        verify_after = m.verify()
        with m.DBL:
            audit_after = m.db.execute("SELECT COUNT(*) FROM audit").fetchone()[0]

        ok_e2e_07 = verify_before.startswith("Audit chain OK") and verify_after.startswith("Audit chain OK") and audit_after > audit_before
        record(
            "INT-E2E-07: Clean engine shutdown, restart & HMAC-SHA256 audit chain persistence",
            "PASS" if ok_e2e_07 else "FAIL",
            pipeline_cat,
            f"audit_rows={audit_before}->{audit_after}, verify='{verify_after}'",
        )

        tel = get_process_telemetry(t_suite_start)
        REPORT["telemetry"] = {
            "rss_mb": tel["rss_mb"],
            "cpu_time_sec": round(time.process_time() - cpu_start, 3),
            "wall_time_sec": round(time.time() - t_suite_start, 3),
            "primary_real_models_executed": bool(real_vyolo is not None and real_easyocr is not None),
        }

    finally:
        try:
            engine.stop()
        except Exception:
            pass
        try:
            ai_httpd.shutdown()
            ai_httpd.server_close()
        except Exception:
            pass
        lab_ctrl.stop()
        try:
            if m.db:
                m.db.close()
        except Exception:
            pass
        shutil.rmtree(INTEGRATION_HOME, ignore_errors=True)

    REPORT["summary"] = {"passed": PASS, "failed": FAIL, "not_tested": NOT_TESTED, "total": PASS + FAIL + NOT_TESTED}
    (ROOT_DIR / "reports_and_logs" / "ai_lab_integration_results.json").write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding="utf-8")
    Path("/tmp/test_ai_lab_integration_report.json").write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding="utf-8")
    print("========================================================================================")
    print(f"  SUMMARY: {PASS} PASS, {FAIL} FAIL, {NOT_TESTED} NOT_TESTED (Total: {PASS + FAIL + NOT_TESTED})")
    print("========================================================================================")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
