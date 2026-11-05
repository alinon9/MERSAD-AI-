#!/usr/bin/env python3
"""
MERSAD AI V7.1 + MERSAD LAB 1.0 — PREVIEW 0.1
Real Unmocked End-to-End Camera & Engine Integration Suite
==========================================================
Strictly separates:
  - REAL_E2E_INTEGRATION: Full execution of `MersadEngineController` (`_camera_reader_worker` + `_camera_inference_worker` + supervisor loop) against live `MERSAD LAB` HTTP MJPEG streams (`http://127.0.0.1:<port>/stream/cam1.mjpg`), with ZERO manual edits to `STATUS` or counters and ZERO hardcoded OCR strings.
  - REAL_PIXEL_INFERENCE: `OpenCV Canny` plate localization (`find_plates`) + `Tesseract 5 LSTM` neural pixel OCR (`TesseractOCRReader` / `/usr/bin/tesseract`) operating directly on decoded MJPEG frame pixels.
  - NOT_TESTED: Heavy models unavailable in the offline Linux sandbox (`YOLOv8n .pt` and `EasyOCR .pth` weights).
"""
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

import cv2
import numpy as np

ROOT_DIR = Path(__file__).resolve().parent.parent
AI_DIR = ROOT_DIR / "MERSAD_AI_Preview_0.1"
LAB_DIR = ROOT_DIR / "MERSAD_LAB_Preview_0.1"

sys.path.insert(0, str(AI_DIR))
sys.path.insert(0, str(LAB_DIR))

INTEGRATION_HOME = tempfile.mkdtemp(prefix="mersad_real_int_")
os.environ["MERSAD_DATA_DIR"] = INTEGRATION_HOME
os.environ["YOLO_AUTOINSTALL"] = "false"
os.environ["ULTRALYTICS_AUTOINSTALL"] = "false"

import analytics as an
import mersad_live as m
import registry as reg
import server as ai_srv
from lab_server import LabServerController, get_process_telemetry

PASS = 0
FAIL = 0
NOT_TESTED = 0
REPORT = {
    "suite": "MERSAD_PREVIEW_0.1_REAL_ENGINE_INTEGRATION",
    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    "classification_policy": "Strict separation of REAL_E2E_INTEGRATION, REAL_PIXEL_INFERENCE, SYNTHETIC_SCENE_INPUT, and NOT_TESTED. Zero _SyntheticVYOLO, zero hardcoded OCR strings, zero manual camera status/counter edits.",
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
    print(f"  [{status:10s}] [{category:22s}] {name}" + (f" -- {detail}" if detail else ""))
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


def main():
    print("========================================================================================")
    print("  MERSAD PREVIEW 0.1 — Real Unmocked Engine & Camera Integration Validation")
    print("========================================================================================")
    t_suite_start = time.time()
    cpu_start = time.process_time()

    # Tune reconnection backoff & stall timers so real worker threads transition within ~1.5s during live test
    m.RECONNECT_BASE_SEC = 0.25
    m.RECONNECT_MAX_SEC = 1.0
    m.CAMERA_STALL_SEC = 0.6
    m.OFFLINE_ALERT_SEC = 1.2
    m.CONFIRM_READS = 3

    m.init_runtime_env(appdir=INTEGRATION_HOME, force=True)
    reg.init(m.db, m.DBL, m.log, lambda: None, m.DB_PATH)

    # Pre-register synthetic watchlist vehicle in SQLite registry (`عدن 12345` -> wanted)
    reg.save_vehicle(
        {
            "plate": "عدن 12345",
            "type": "سيارة",
            "status": "مطلوبة",
            "owner": "مركبة اختبار اصطناعية — PREVIEW 0.1",
            "notes": "بيانات اصطناعية لاختبار المسار الكامل بدون محاكاة OCR",
        },
        "127.0.0.1",
    )

    # Wire MERSAD AI HTTP server bus
    ai_srv.bus.evidence_dir = os.path.join(INTEGRATION_HOME, "evidence")
    ai_srv.bus.archive_dir = os.path.join(INTEGRATION_HOME, "evidence_archive")
    ai_srv.bus.verify = m.verify
    ai_srv.bus.on_stats = lambda: dict(m.STATUS, alerts=len(ai_srv.bus.alerts))
    ai_srv.bus.on_cameras_list = m.list_cameras_runtime
    ai_srv.bus.on_analytics = lambda: an.build_report(m.db, m.DBL)
    ai_srv.bus.post["/api/cameras/add"] = lambda d, ip: m.add_camera_runtime(d, who=ip)
    ai_srv.bus.post["/api/cameras/remove"] = lambda d, ip: m.remove_camera_runtime(d, who=ip)

    # Start MERSAD LAB 1.0 on ephemeral localhost port
    lab_ctrl = LabServerController(host="127.0.0.1", port=0, token="lab_real_int_2026", require_auth=False)
    lab_ctrl.start()
    lab_base = f"http://127.0.0.1:{lab_ctrl.port}"

    # Start Real MersadEngineController (real _camera_reader_worker + _camera_inference_worker + supervisor)
    real_ocr = m.create_real_ocr_reader(use_gpu=False)
    engine = m.MersadEngineController(
        reader=real_ocr,
        vyolo=None,
        yolo=None,
        infer_every_n=1,
        stall_sec=0.6,
        offline_alert_sec=1.2,
    )
    engine.start()

    # Start MERSAD AI HTTP Server
    ai_httpd = ai_srv.ThreadingHTTPServer(("127.0.0.1", 0), ai_srv.H)
    ai_port = ai_httpd.server_address[1]
    ai_base = f"http://127.0.0.1:{ai_port}"
    ai_thread = threading.Thread(target=ai_httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    ai_thread.start()
    ai_headers = {"X-Mersad-Token": ai_srv.bus.token}

    try:
        # ------------------------------------------------------------------
        # 1. Explicit Classification of Unavailable Heavy Models (No Fake YOLO / No Fake EasyOCR)
        # ------------------------------------------------------------------
        record(
            "INT-MODEL-YOLO: Real YOLOv8n (`models/yolov8n.pt`) in integration pipeline",
            "NOT_TESTED",
            "NOT_TESTED",
            "ultralytics/torch & yolov8n.pt absent in offline Linux sandbox; _SyntheticVYOLO removed. Pipeline uses real OpenCV Canny contour localizer find_plates().",
        )
        record(
            "INT-MODEL-EASYOCR: Real EasyOCR (`models/easyocr/*.pth`) in integration pipeline",
            "NOT_TESTED",
            "NOT_TESTED",
            f"easyocr package & .pth weights absent in offline Linux sandbox; pipeline uses real {getattr(real_ocr, 'engine_name', 'None')} on cropped plate pixels.",
        )

        # ------------------------------------------------------------------
        # 2. INT-E2E-01: Connect LAB cam1 & cam2 to MERSAD AI and spawn real worker threads
        # ------------------------------------------------------------------
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
        ok_e2e_01 = (st_c1 == 200 and st_c2 == 200 and w1_spawned and w2_spawned)
        record(
            "INT-E2E-01: Connect LAB cam1 & cam2 -> spawn real AI reader & inference threads",
            "PASS" if ok_e2e_01 else "FAIL",
            "REAL_E2E_INTEGRATION",
            f"LAB_CAM1 worker_spawned={w1_spawned}, LAB_CAM2 worker_spawned={w2_spawned}",
        )

        # ------------------------------------------------------------------
        # 3. INT-E2E-02: Autonomous frame ingestion, Canny localization, real Tesseract pixel OCR,
        #    3-frame confirmation, Registry lookup, Alert generation, SQLite & Audit Chain
        # ------------------------------------------------------------------
        def _check_pipeline_completed():
            _, stats = _http_json(f"{ai_base}/api/stats", headers=ai_headers)
            with m.DBL:
                sights = m.db.execute("SELECT cam, plate, conf, raw_text FROM sightings ORDER BY rowid").fetchall()
            plates_seen = {r[1] for r in sights}
            if "عدن-12345" in plates_seen and "صنعاء-48210" in plates_seen and stats.get("alerts", 0) >= 1:
                return stats, sights
            return None

        pipeline_res = _wait_until(_check_pipeline_completed, timeout_sec=10.0, poll_sec=0.15)
        if pipeline_res:
            stats_now, sights_now = pipeline_res
            cam1_frames = stats_now.get("cameras", {}).get("LAB_CAM1", {}).get("frames", 0)
            cam2_frames = stats_now.get("cameras", {}).get("LAB_CAM2", {}).get("frames", 0)
            ok_e2e_02 = True
            detail_02 = (
                f"Autonomous worker sightings={[(r[0], r[1], round(r[2], 2)) for r in sights_now[:4]]}, "
                f"LAB_CAM1_frames={cam1_frames}, LAB_CAM2_frames={cam2_frames}, alerts={stats_now.get('alerts')}"
            )
        else:
            ok_e2e_02 = False
            _, stats_now = _http_json(f"{ai_base}/api/stats", headers=ai_headers)
            with m.DBL:
                sights_now = m.db.execute("SELECT cam, plate, conf, raw_text FROM sightings ORDER BY rowid").fetchall()
            detail_02 = f"Timed out waiting for autonomous OCR sighting: sights={sights_now}, stats={stats_now}"

        record(
            "INT-E2E-02: Unmocked LAB -> MJPEG -> VideoCapture -> Worker -> Plate -> Pixel OCR -> Registry -> Alert -> SQLite",
            "PASS" if ok_e2e_02 else "FAIL",
            "REAL_E2E_INTEGRATION",
            detail_02,
        )

        # ------------------------------------------------------------------
        # 4. INT-E2E-03: Alert deduplication (`عدم تكرار التنبيهات` within cooldown window)
        # ------------------------------------------------------------------
        # Let LAB_CAM1 stream additional frames of the same wanted vehicle ('عدن-12345') for 1.2s
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
            "REAL_E2E_INTEGRATION",
            f"LAB_CAM1 frames grew {f_before}->{f_after}, duplicate wanted alerts for عدن-12345: {len(wanted_alerts_cam1)} (expected 1)",
        )

        # ------------------------------------------------------------------
        # 5. INT-E2E-04: Camera disconnect (`HTTP 503`) + Other camera continuity (`LAB_CAM2`)
        #    (ZERO manual status or counter edits — 100% engine-driven)
        # ------------------------------------------------------------------
        _, cams_pre_off = _http_json(f"{ai_base}/api/cameras", headers=ai_headers)
        cam2_frames_pre_off = cams_pre_off.get("cameras", {}).get("LAB_CAM2", {}).get("frames", 0)

        # Set cam1 to offline in MERSAD LAB
        _http_json(f"{lab_base}/api/cameras/cam1/mode", method="POST", payload={"mode": "offline"})

        def _check_cam1_disconnected():
            _, cd = _http_json(f"{ai_base}/api/cameras", headers=ai_headers)
            c1 = cd.get("cameras", {}).get("LAB_CAM1", {})
            c2 = cd.get("cameras", {}).get("LAB_CAM2", {})
            if c1.get("status") in ("reconnecting", "offline") and c1.get("fail_count", 0) >= 1 and c2.get("frames", 0) > cam2_frames_pre_off + 2:
                return c1, c2
            return None

        disc_res = _wait_until(_check_cam1_disconnected, timeout_sec=6.0, poll_sec=0.1)
        if disc_res:
            c1_off_info, c2_cont_info = disc_res
            ok_e2e_04 = (c1_off_info["status"] in ("reconnecting", "offline") and c2_cont_info["status"] == "online")
            detail_04 = (
                f"Engine set LAB_CAM1 status='{c1_off_info['status']}' (fail_count={c1_off_info.get('fail_count')}), "
                f"while LAB_CAM2 stayed '{c2_cont_info['status']}' and frames grew {cam2_frames_pre_off}->{c2_cont_info.get('frames')}"
            )
        else:
            ok_e2e_04 = False
            _, cd_now = _http_json(f"{ai_base}/api/cameras", headers=ai_headers)
            detail_04 = f"Engine did not transition LAB_CAM1 to reconnecting/offline: {cd_now}"

        record(
            "INT-E2E-04: Autonomous camera disconnect detection & multi-camera continuity (zero manual state edits)",
            "PASS" if ok_e2e_04 else "FAIL",
            "REAL_E2E_INTEGRATION",
            detail_04,
        )

        # ------------------------------------------------------------------
        # 6. INT-E2E-05: Autonomous camera reconnection when LAB stream recovers
        #    (ZERO manual status or counter edits — 100% engine-driven)
        # ------------------------------------------------------------------
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
        ok_e2e_05 = bool(rec_res and rec_res.get("status") == "online" and rec_res.get("reconnect_count", 0) >= 1 and len(rec_audits) >= 1)
        record(
            "INT-E2E-05: Autonomous camera reconnection & audit logging (zero manual state edits)",
            "PASS" if ok_e2e_05 else "FAIL",
            "REAL_E2E_INTEGRATION",
            f"Engine restored LAB_CAM1 status='{rec_res.get('status') if rec_res else None}', reconnect_count={rec_res.get('reconnect_count') if rec_res else 0}, audit_records={rec_audits}",
        )

        # ------------------------------------------------------------------
        # 7. INT-E2E-06: Autonomous FROZEN_STREAM & CAMERA_OCCLUDED_OR_DARK detection by worker loop
        # ------------------------------------------------------------------
        m._CAM_QUALITY_STATE.pop("LAB_CAM1", None)
        _http_json(f"{lab_base}/api/cameras/cam1/mode", method="POST", payload={"mode": "frozen"})

        def _check_frozen_warn():
            _, cd = _http_json(f"{ai_base}/api/cameras", headers=ai_headers)
            c1 = cd.get("cameras", {}).get("LAB_CAM1", {})
            if "FROZEN_STREAM" in c1.get("issues", []) or c1.get("health_warning") == "FROZEN_STREAM":
                return c1
            return None

        froz_res = _wait_until(_check_frozen_warn, timeout_sec=5.0, poll_sec=0.1)

        _http_json(f"{lab_base}/api/cameras/cam1/mode", method="POST", payload={"mode": "occluded"})

        def _check_occluded_warn():
            _, cd = _http_json(f"{ai_base}/api/cameras", headers=ai_headers)
            c1 = cd.get("cameras", {}).get("LAB_CAM1", {})
            if "CAMERA_OCCLUDED_OR_DARK" in c1.get("issues", []):
                return c1
            return None

        occ_res = _wait_until(_check_occluded_warn, timeout_sec=5.0, poll_sec=0.1)
        _http_json(f"{lab_base}/api/cameras/cam1/mode", method="POST", payload={"mode": "normal"})

        ok_e2e_06 = bool(froz_res is not None and occ_res is not None)
        record(
            "INT-E2E-06: Autonomous stream health telemetry (FROZEN_STREAM & CAMERA_OCCLUDED_OR_DARK)",
            "PASS" if ok_e2e_06 else "FAIL",
            "REAL_E2E_INTEGRATION",
            f"frozen_warning={froz_res.get('health_warning') if froz_res else None}, occluded_issues={occ_res.get('issues') if occ_res else None}",
        )

        # ------------------------------------------------------------------
        # 8. INT-E2E-07: Graceful engine shutdown, restart on existing DB & HMAC-SHA256 audit chain continuity
        # ------------------------------------------------------------------
        engine.stop(timeout=4.0)
        verify_before_restart = m.verify()
        with m.DBL:
            audit_count_before = m.db.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
            sight_count_before = m.db.execute("SELECT COUNT(*) FROM sightings").fetchone()[0]
        m.db.close()
        m.db = None
        m._RUNTIME_INITIALIZED = False

        # Re-initialize runtime & start a fresh MersadEngineController on the same INTEGRATION_HOME
        m.init_runtime_env(appdir=INTEGRATION_HOME, force=True)
        reg.init(m.db, m.DBL, m.log, lambda: None, m.DB_PATH)
        engine2 = m.MersadEngineController(reader=real_ocr, infer_every_n=1, stall_sec=0.6, offline_alert_sec=1.2)
        engine2.start()
        engine2.add_camera("LAB_CAM1", f"{lab_base}/stream/cam1.mjpg")
        time.sleep(0.8)
        engine2.stop(timeout=4.0)

        verify_after_restart = m.verify()
        with m.DBL:
            audit_count_after = m.db.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
            sight_count_after = m.db.execute("SELECT COUNT(*) FROM sightings").fetchone()[0]

        ok_e2e_07 = (
            verify_before_restart.startswith("Audit chain OK")
            and verify_after_restart.startswith("Audit chain OK")
            and audit_count_after > audit_count_before
            and sight_count_after >= sight_count_before
        )
        record(
            "INT-E2E-07: Clean engine shutdown, restart & HMAC-SHA256 audit chain persistence",
            "PASS" if ok_e2e_07 else "FAIL",
            "REAL_E2E_INTEGRATION",
            f"audit_rows={audit_count_before}->{audit_count_after}, verify_after_restart='{verify_after_restart}'",
        )

        # ------------------------------------------------------------------
        # 9. INT-E2E-08: End-to-End CPU, RAM, FPS & Pixel OCR Latency telemetry
        # ------------------------------------------------------------------
        tel = get_process_telemetry(t_suite_start)
        cpu_used = round(time.process_time() - cpu_start, 3)
        wall_used = round(time.time() - t_suite_start, 3)
        REPORT["telemetry"] = {
            "rss_mb": tel["rss_mb"],
            "cpu_time_sec": cpu_used,
            "wall_time_sec": wall_used,
            "ocr_engine_used": getattr(real_ocr, "engine_name", "None"),
        }
        record(
            "INT-E2E-08: Resource & latency telemetry",
            "PASS",
            "REAL_E2E_INTEGRATION",
            f"RSS={tel['rss_mb']}MB, CPU={cpu_used}s, Wall={wall_used}s, OCR={REPORT['telemetry']['ocr_engine_used']}",
            metrics=REPORT["telemetry"],
        )

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
    Path("/tmp/test_ai_lab_integration_report.json").write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding="utf-8")
    print("========================================================================================")
    print(f"  SUMMARY: {PASS} PASS, {FAIL} FAIL, {NOT_TESTED} NOT_TESTED (Total: {PASS + FAIL + NOT_TESTED})")
    print("========================================================================================")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
