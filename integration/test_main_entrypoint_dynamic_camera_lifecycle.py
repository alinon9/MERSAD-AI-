#!/usr/bin/env python3
"""
Standalone Regression Test for Critical Runtime Dynamic Camera Lifecycle via Natural `main()` Entry Point (BUG-27).
Tests all 10 required steps using the real `mersad_live.main()` entry point (as used in `MERSAD_AI.exe`),
NOT `MersadEngineController` directly:
  1. Launch MERSAD AI via natural `main()` entry point.
  2. Launch MERSAD LAB (`LabServerController`).
  3. Add a new camera from LAB via `POST /api/integration/connect_ai`.
  4. Verify AI response contains `worker_spawned=true`.
  5. Verify camera reader thread (`cam_reader_*`) and inference thread (`cam_infer_*`) actually started and are alive.
  6. Verify `latest_frame_seq` increases and live MJPEG frames arrive on `/stream.mjpg?cam=...`.
  7. Verify inference executes (`det_runs >= 1`) and `STATUS["cameras"][cam]` is updated with telemetry.
  8. Remove the camera at runtime via `POST /api/cameras/remove`.
  9. Verify reader and inference threads stop cleanly and `VideoCapture` is closed (`cap is None`) without SIGSEGV.
 10. Test adding a second camera (`LAB_DYN_CAM3`) after removal (even after all cameras were removed) and verify full streaming & inference.
"""
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
AI_DIR = ROOT_DIR / "MERSAD_AI_Preview_0.1"
LAB_DIR = ROOT_DIR / "MERSAD_LAB_Preview_0.1"
sys.path.insert(0, str(AI_DIR))
sys.path.insert(0, str(LAB_DIR))


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_main_entrypoint_dynamic_lifecycle_test() -> dict:
    import mersad_live as ml
    import registry as reg
    import lab_server as ls

    tmp_home = tempfile.mkdtemp(prefix="mersad_main_ep_lifecycle_")
    ai_port = _free_port()
    lab_port = _free_port()
    ai_token = "main_ep_tok_2026"
    lab_token = "lab_ep_tok_2026"

    lab_ctrl = ls.LabServerController(host="127.0.0.1", port=lab_port, token=lab_token).start()
    lab_port = lab_ctrl.port

    old_argv = sys.argv[:]
    old_data_dir = os.environ.get("MERSAD_DATA_DIR")
    os.environ["MERSAD_DATA_DIR"] = tmp_home

    # Ensure fresh runtime DB in tmp_home
    try:
        if getattr(ml, "db", None) is not None:
            ml.db.close()
    except Exception:
        pass
    ml.db = None
    ml._RUNTIME_INITIALIZED = False
    ml.init_runtime_env(appdir=tmp_home, force=True)
    reg.init(ml.db, ml.DBL, ml.log, lambda: None, ml.DB_PATH)

    sys.argv = [
        "mersad_live.py",
        "--source", f"http://127.0.0.1:{lab_port}/stream/cam1.mjpg",
        "--cam", "BOOT_CAM1",
        "--port", str(ai_port),
        "--token", ai_token,
        "--no-window",
        "--no-telegram-listener",
        "--allow-degraded-preview",
    ]

    steps = []
    main_exc = []

    def add_step(step_no: int, name: str, ok: bool, detail: dict):
        steps.append({"step": step_no, "name": name, "passed": bool(ok), "detail": detail})

    def _main_runner():
        try:
            ml.main()
        except BaseException as ex:
            main_exc.append(repr(ex))

    t_main = threading.Thread(target=_main_runner, daemon=True, name="mersad-main-ep-thread")
    t_main.start()

    try:
        # Step 1: Verify MERSAD AI booted via natural main() entry point
        ping_ok = False
        deadline = time.time() + 10.0
        while time.time() < deadline:
            try:
                r = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{ai_port}/api/ping?k={ai_token}", timeout=1.0).read())
                if r.get("ok") is True:
                    ping_ok = True
                    break
            except Exception:
                time.sleep(0.05)
        add_step(1, "Launch MERSAD AI via natural main() entry point", ping_ok and not main_exc and t_main.is_alive(), {"ai_port": ai_port, "ping_ok": ping_ok, "main_alive": t_main.is_alive(), "exceptions": main_exc})

        # Step 2: Verify MERSAD LAB is running and serving streams
        lab_health = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{lab_port}/api/health", timeout=2.0).read())
        add_step(2, "Launch MERSAD LAB and verify virtual camera streams", lab_health.get("ok") is True, {"lab_port": lab_port, "cameras_online": lab_health.get("cameras_online")})

        # Step 3 & 4: Add a new camera from LAB via POST /api/integration/connect_ai and verify worker_spawned=true
        req_conn1 = urllib.request.Request(
            f"http://127.0.0.1:{lab_port}/api/integration/connect_ai",
            data=json.dumps({
                "ai_url": f"http://127.0.0.1:{ai_port}",
                "ai_token": ai_token,
                "cam_id": "cam2",
                "cam_name": "LAB_DYN_CAM2",
            }).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Lab-Token": lab_token, "Origin": f"http://127.0.0.1:{lab_port}"},
            method="POST",
        )
        resp_conn1 = json.loads(urllib.request.urlopen(req_conn1, timeout=5.0).read().decode("utf-8"))
        ai_resp1 = resp_conn1.get("ai_response", {})
        add_step(3, "Add new camera LAB_DYN_CAM2 from LAB via POST /api/integration/connect_ai", resp_conn1.get("ok") is True and ai_resp1.get("ok") is True, resp_conn1)
        add_step(4, "Verify AI response includes worker_spawned=true", ai_resp1.get("worker_spawned") is True, ai_resp1)

        # Step 5: Verify camera reader & inference threads actually started
        st_cam2 = ml._ACTIVE_CAM_STATES.get("LAB_DYN_CAM2")
        rt_cam2 = st_cam2.get("reader_thread") if st_cam2 else None
        it_cam2 = st_cam2.get("infer_thread") if st_cam2 else None
        threads_started = bool(rt_cam2 is not None and rt_cam2.is_alive() and it_cam2 is not None and it_cam2.is_alive())
        add_step(5, "Verify camera reader_thread and infer_thread actually started", threads_started, {
            "reader_thread_name": getattr(rt_cam2, "name", None),
            "reader_alive": bool(rt_cam2 and rt_cam2.is_alive()),
            "infer_thread_name": getattr(it_cam2, "name", None),
            "infer_alive": bool(it_cam2 and it_cam2.is_alive()),
        })

        # Step 6 & 7: Verify latest_frame_seq increases, MJPEG frames arrive, and inference executes & updates STATUS
        seq_now, det_now, cam2_stat = 0, 0, {}
        deadline = time.time() + 10.0
        while time.time() < deadline and st_cam2 is not None:
            with st_cam2["lock"]:
                seq_now = st_cam2["latest_frame_seq"]
            with st_cam2["infer_lock"]:
                det_now = st_cam2["det_runs"]
            with ml._RUNTIME_STATE_LOCK:
                cam2_stat = dict(ml.STATUS.get("cameras", {}).get("LAB_DYN_CAM2", {}))
            if seq_now >= 8 and det_now >= 1 and cam2_stat.get("frames", 0) >= 6 and cam2_stat.get("detections", 0) >= 1:
                break
            time.sleep(0.05)

        with urllib.request.urlopen(f"http://127.0.0.1:{ai_port}/stream.mjpg?cam=LAB_DYN_CAM2&k={ai_token}", timeout=3.0) as mjpg_r:
            mjpg_chunk = mjpg_r.read(512)
        mjpg_ok = (b"image/jpeg" in mjpg_chunk and b"\xff\xd8" in mjpg_chunk)
        add_step(6, "Verify latest_frame_seq increments and MJPEG frames arrive", seq_now >= 8 and mjpg_ok, {"latest_frame_seq": seq_now, "mjpeg_header_and_soi_valid": mjpg_ok})
        add_step(7, "Verify inference executes and camera STATUS telemetry updates", det_now >= 1 and cam2_stat.get("status") == "online" and cam2_stat.get("frames", 0) >= 6 and cam2_stat.get("detections", 0) >= 1, cam2_stat)

        # Step 8 & 9: Delete camera during runtime and verify threads stop & VideoCapture closes without SIGSEGV
        req_rem1 = urllib.request.Request(
            f"http://127.0.0.1:{ai_port}/api/cameras/remove?k={ai_token}",
            data=json.dumps({"name": "LAB_DYN_CAM2"}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{ai_port}"},
            method="POST",
        )
        resp_rem1 = json.loads(urllib.request.urlopen(req_rem1, timeout=6.0).read().decode("utf-8"))

        # Removal signals the stop event and performs a bounded join. A YOLO or
        # OCR native call already in progress cannot be force-cancelled safely;
        # allow it to return, then verify the worker observes stop and exits.
        worker_shutdown_started = time.monotonic()
        worker_shutdown_deadline = worker_shutdown_started + 10.0
        while time.monotonic() < worker_shutdown_deadline:
            reader_alive = bool(rt_cam2 and rt_cam2.is_alive())
            infer_alive = bool(it_cam2 and it_cam2.is_alive())
            if not reader_alive and not infer_alive:
                break
            time.sleep(0.02)
        worker_shutdown_wait_seconds = time.monotonic() - worker_shutdown_started
        rt_stopped = not (rt_cam2 and rt_cam2.is_alive())
        it_stopped = not (it_cam2 and it_cam2.is_alive())
        with st_cam2["lock"]:
            cap_released = (st_cam2.get("cap") is None)
        with ml._RUNTIME_STATE_LOCK:
            removed_from_status = ("LAB_DYN_CAM2" not in ml.STATUS.get("cameras", {}))
        add_step(8, "Remove active camera LAB_DYN_CAM2 during runtime via POST /api/cameras/remove", resp_rem1.get("ok") is True and resp_rem1.get("removed") is True, resp_rem1)
        add_step(9, "Verify reader/infer threads stopped and VideoCapture released without SIGSEGV", rt_stopped and it_stopped and cap_released and removed_from_status, {
            "reader_thread_stopped": rt_stopped,
            "infer_thread_stopped": it_stopped,
            "worker_shutdown_wait_seconds": round(worker_shutdown_wait_seconds, 2),
            "infer_thread_alive_after_timeout": bool(it_cam2 and it_cam2.is_alive()),
            "videocapture_released_none": cap_released,
            "removed_from_status_dict": removed_from_status,
        })

        # Remove BOOT_CAM1 as well to prove main() stays alive even when 0 cameras remain before Step 10
        req_rem_boot = urllib.request.Request(
            f"http://127.0.0.1:{ai_port}/api/cameras/remove?k={ai_token}",
            data=json.dumps({"name": "BOOT_CAM1"}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{ai_port}"},
            method="POST",
        )
        urllib.request.urlopen(req_rem_boot, timeout=6.0).read()
        time.sleep(0.05)

        # Step 10: Add a second camera (LAB_DYN_CAM3) after removal and verify full streaming & inference
        req_conn2 = urllib.request.Request(
            f"http://127.0.0.1:{lab_port}/api/integration/connect_ai",
            data=json.dumps({
                "ai_url": f"http://127.0.0.1:{ai_port}",
                "ai_token": ai_token,
                "cam_id": "cam3",
                "cam_name": "LAB_DYN_CAM3",
            }).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Lab-Token": lab_token, "Origin": f"http://127.0.0.1:{lab_port}"},
            method="POST",
        )
        resp_conn2 = json.loads(urllib.request.urlopen(req_conn2, timeout=5.0).read().decode("utf-8"))
        ai_resp2 = resp_conn2.get("ai_response", {})
        st_cam3 = ml._ACTIVE_CAM_STATES.get("LAB_DYN_CAM3")
        seq3, det3, cam3_stat = 0, 0, {}
        deadline = time.time() + 10.0
        while time.time() < deadline and st_cam3 is not None:
            with st_cam3["lock"]:
                seq3 = st_cam3["latest_frame_seq"]
            with st_cam3["infer_lock"]:
                det3 = st_cam3["det_runs"]
            with ml._RUNTIME_STATE_LOCK:
                cam3_stat = dict(ml.STATUS.get("cameras", {}).get("LAB_DYN_CAM3", {}))
            if seq3 >= 8 and det3 >= 1 and cam3_stat.get("frames", 0) >= 6 and cam3_stat.get("detections", 0) >= 1:
                break
            time.sleep(0.05)
        with urllib.request.urlopen(f"http://127.0.0.1:{ai_port}/stream.mjpg?cam=LAB_DYN_CAM3&k={ai_token}", timeout=3.0) as mjpg_r3:
            mjpg_chunk3 = mjpg_r3.read(512)
        mjpg3_ok = (b"image/jpeg" in mjpg_chunk3 and b"\xff\xd8" in mjpg_chunk3)
        step10_ok = (
            t_main.is_alive()
            and resp_conn2.get("ok") is True
            and ai_resp2.get("worker_spawned") is True
            and seq3 >= 8
            and det3 >= 1
            and mjpg3_ok
            and cam3_stat.get("status") == "online"
        )
        add_step(10, "Add second camera LAB_DYN_CAM3 after removal and verify worker_spawned, MJPEG stream, and inference", step10_ok, {
            "ai_response": ai_resp2,
            "latest_frame_seq": seq3,
            "det_runs": det3,
            "mjpeg_ok": mjpg3_ok,
            "camera_status": cam3_stat,
        })
    finally:
        ml.STOP_MAIN_EVENT.set()
        t_main.join(timeout=5.0)
        lab_ctrl.stop()
        sys.argv = old_argv
        if old_data_dir is None:
            os.environ.pop("MERSAD_DATA_DIR", None)
        else:
            os.environ["MERSAD_DATA_DIR"] = old_data_dir
        try:
            if getattr(ml, "db", None) is not None:
                ml.db.close()
        except Exception:
            pass
        shutil.rmtree(tmp_home, ignore_errors=True)

    all_ok = len(steps) == 10 and all(s["passed"] for s in steps)
    return {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "test_suite": "MAIN_ENTRYPOINT_DYNAMIC_CAMERA_LIFECYCLE_10_STEPS",
        "entry_point_tested": "mersad_live.main() (natural EXE/CLI entry point, NOT direct MersadEngineController)",
        "all_passed": all_ok,
        "total_steps": len(steps),
        "passed_steps": sum(1 for s in steps if s["passed"]),
        "failed_steps": sum(1 for s in steps if not s["passed"]),
        "steps": steps,
    }


if __name__ == "__main__":
    rep = run_main_entrypoint_dynamic_lifecycle_test()
    out_json = ROOT_DIR / "reports_and_logs" / "logs" / "20_main_entrypoint_dynamic_camera_lifecycle.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(rep, indent=2, ensure_ascii=False))
    sys.exit(0 if rep["all_passed"] else 1)
