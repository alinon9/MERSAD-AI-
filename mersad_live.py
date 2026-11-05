#!/usr/bin/env python3
"""MERSAD AI - live prototype v3.5 + V7 operational analytics/reliability (lightweight, CPU only).
Camera -> vehicles/trucks (YOLOv8n) -> plates (OCR) | faces (consenting volunteers only)
-> pattern/trend analysis, path tracking & anomaly learning -> dashboard + Telegram alerts + SHA-256 audit log.

  python mersad_live.py --source 0                          # webcam
  python mersad_live.py --source http://PHONE_IP:8080/video # phone as IP camera
  python mersad_live.py --source rtsp://user:pass@IP/stream # surveillance camera
  python mersad_live.py --source 0 --source 1 --cam CAM1,CAM2 # multi-camera in one process
  python mersad_live.py --trucks-only --truck-curfew 22-5   # only trucks; alert if 22:00-05:00
  python mersad_live.py --host 0.0.0.0                      # enable LAN/phone access
  python mersad_live.py --no-window                         # headless (dashboard only)
  python mersad_live.py --no-telegram-listener              # disable getUpdates polling in secondary process
  python mersad_live.py --verify                            # check audit chain & evidence files
"""

# MERSAD_ULTRALYTICS_AUTOINSTALL_GUARD
import os as _mersad_env_os
_mersad_env_os.environ['YOLO_AUTOINSTALL'] = 'false'
import argparse, collections, hashlib, json, logging, logging.handlers, os, re, shutil, socket, sqlite3, stat, sys, threading, time, urllib.error, urllib.request, uuid, webbrowser, zipfile

BUNDLE_DIR = os.path.abspath(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))))
INSTALL_DIR = os.path.abspath(
    os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
)


def _is_dir_writable(dir_path):
    """Return True if dir_path is not PyInstaller _MEIPASS temp dir and current user can create/delete files in it."""
    if not dir_path:
        return False
    abs_d = os.path.abspath(dir_path)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass and os.path.abspath(meipass) == abs_d:
        return False
    try:
        # Root can create files in chmod 0555 directories on POSIX, but a normal
        # desktop user cannot. Respect the directory's declared mode for portable
        # install-path selection and deterministic read-only-install tests.
        if os.name != "nt":
            mode = stat.S_IMODE(os.stat(abs_d).st_mode)
            if mode & 0o222 == 0:
                return False
        os.makedirs(abs_d, exist_ok=True)
        probe = os.path.join(abs_d, f".mersad_write_probe_{os.getpid()}_{uuid.uuid4().hex[:6]}")
        with open(probe, "wb") as pf:
            pf.write(b"ok")
        os.remove(probe)
        return True
    except OSError:
        return False


def _default_user_data_dir():
    """Return OS-standard per-user persistent application data directory when install directory is read-only."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.abspath(os.path.join(base, "MERSAD_AI"))
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.abspath(os.path.join(base, "mersad_ai"))


def resolve_writable_appdir(preferred_dir=None, explicit_env=None):
    """Resolve persistent writable data directory (Stage 5d):
    - Never uses temporary _MEIPASS directory for database, keys, secrets, or evidence.
    - If MERSAD_DATA_DIR is explicitly set in environment, uses it directly (preserving fail-closed security tests).
    - Otherwise uses preferred_dir (INSTALL_DIR) if writable by current user, or falls back to per-user app data dir."""
    env_dir = explicit_env if explicit_env is not None else os.environ.get("MERSAD_DATA_DIR")
    if env_dir:
        return os.path.abspath(env_dir)
    cand = os.path.abspath(preferred_dir or INSTALL_DIR)
    if _is_dir_writable(cand):
        return cand
    fallback = _default_user_data_dir()
    os.makedirs(fallback, exist_ok=True)
    return fallback


def resolve_resource_path(rel_path):
    """Resolve bundled read-only assets before writable user data in frozen distributions.

    Source/dev runs retain APPDIR-first behavior so downloaded local models are reusable.
    Frozen --onedir builds prefer assets adjacent to the executable / PyInstaller bundle;
    otherwise a stale user-data models directory could shadow the assets validated for the EXE.
    """
    bases = (INSTALL_DIR, BUNDLE_DIR, APPDIR) if getattr(sys, "frozen", False) else (APPDIR, INSTALL_DIR, BUNDLE_DIR)
    for base in bases:
        if base:
            cand = os.path.join(base, rel_path)
            if os.path.exists(cand):
                return cand
    return os.path.join(APPDIR, rel_path)


APPDIR = resolve_writable_appdir()
os.makedirs(APPDIR, exist_ok=True)
if not os.environ.get("MERSAD_DATA_DIR"):
    os.environ["MERSAD_DATA_DIR"] = APPDIR
os.chdir(APPDIR)

# Record which Telegram env vars were pre-set in the OS environment BEFORE load_cfg() runs (P1-G)
_PREEXISTING_ENV = {
    env: os.environ.get(env, "")
    for env in ("TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_PATROL_CHAT_ID")
    if os.environ.get(env)
}
_SECRETS_FILE = ".mersad_secrets.json"

import cv2, numpy as np
from server import bus, start_server
import notify as _notify_mod
from notify import send_alert, start_listener, _redact as redact_url, UncertainDeliveryError
import registry as R


def _setup_logging(max_bytes=2_000_000, backup_count=3):
    logger = logging.getLogger("mersad")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    try:
        fh = logging.handlers.RotatingFileHandler(
            os.path.join(APPDIR, "mersad.log"), maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        logger.addHandler(fh)
    except OSError:
        pass
    return logger


logger = _setup_logging()

# P2-M: Pin OpenCV Zoo models to an immutable commit hash and verify SHA-256 digests
ZOO_COMMIT = "39a1451d0f9b23fc4ebaed06a277127efa0374d0"
ZOO = f"https://huggingface.co/opencv/opencv_zoo/resolve/{ZOO_COMMIT}/models/"
MODELS = {
    "yunet.onnx": ZOO + "face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "sface.onnx": ZOO + "face_recognition_sface/face_recognition_sface_2021dec.onnx"
}
MODEL_SHA256 = {
    "yunet.onnx": "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    "sface.onnx": "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79"
}
MODEL_MIN_BYTES = {
    "yunet.onnx": 200_000,
    "sface.onnx": 30_000_000,
    "yolov8n.pt": 6_000_000
}
YOLO_RELEASE_VERSION = "v8.3.0"
YOLO_MODEL_URL = f"https://github.com/ultralytics/assets/releases/download/{YOLO_RELEASE_VERSION}/yolov8n.pt" 
FONT, COS_T = cv2.FONT_HERSHEY_SIMPLEX, 0.363        # SFace cosine threshold
VCLS = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}   # Default COCO classes
VCLS_NAMES = {"car": "car", "automobile": "car", "sedan": "car", "suv": "car", "van": "car",
              "motorcycle": "motorcycle", "motorbike": "motorcycle", "bus": "bus", "truck": "truck", "lorry": "truck"}
AR = {
    "NEW PLATE (first sighting)": "لوحة غير مسجّلة (أول رصد)",
    "UNUSUAL HOUR (learned pattern)": "ساعة غير معتادة (نمط متعلَّم)",
    "TRUCK IN RESTRICTED HOURS": "شاحنة في ساعات المنع",
    "VEHICLE: WANTED": "مركبة مطلوبة",
    "VEHICLE: STOLEN": "مركبة مسروقة",
    "POSSIBLE MATCH (visual check)": "تطابق محتمل — تحقق بصري (أحرف متعارضة/ملتبسة أو مسافة تحرير)",
    "ANOMALY (learned pattern)": "شذوذ مكتشف بالتعلّم الآلي",
    "ROUTE ANOMALY (impossible transit)": "اشتباه تعارض مسار مكاني-زماني معاير (يتطلب مراجعة)",
    "ROUTE NOTICE (uncalibrated)": "ملاحظة مسار للعلم (حد افتراضي غير معاير)",
    "VEHICLE: EXPIRED": "ترخيص منتهي",
    "VEHICLE: WATCH": "مركبة تحت المراقبة",
    "FACE MATCH (demo watchlist)": "تطابق وجه محتمل (قائمة تجريبية) - يتطلب تحققاً بشرياً"
}
AID, ENR, FH, FA, KNOWN, EVID, WHY, TRACKS, FACE_ALERT = [0], {}, {}, {}, [], {}, {}, {}, [0.45]
CONFIRM_READS = 3
VOTE_WINDOW_SEC = 10.0
ALERT_COOLDOWN_SEC = 30.0
MIN_OCR_CONF = 0.35
DISPATCH_MAX_ATTEMPTS = 5
DISPATCH_RETRY_BASE_SEC = 30.0
DISPATCH_LEASE_SEC = 45.0
MIN_RETENTION_DAYS = 7.0
OFFLINE_ALERT_SEC = 10.0
RECONNECT_BASE_SEC = 0.5
RECONNECT_MAX_SEC = 15.0
MAX_RECONNECT_ATTEMPTS = 3
CAMERA_STALL_SEC = 2.0
STOP_MAIN_EVENT = threading.Event()
SESSION_ID = "sess-" + uuid.uuid4().hex[:8]
PROCESS_OWNER_ID = f"pid:{os.getpid()}:{SESSION_ID}"

DB_PATH = os.path.join(APPDIR, "mersad.db")
db = sqlite3.connect(DB_PATH, timeout=15.0, check_same_thread=False)
DBL = threading.RLock()
_DISPATCH_LOCK = threading.Lock()
_IN_FLIGHT_DISPATCH = set()
pseud = R.pseud


def chain_hash(prev, i, ts, action, ref):
    return hashlib.sha256(f"{prev}|{i}|{ts}|{action}|{ref}".encode("utf-8")).hexdigest()


def _log_in_tx(conn, action, ref=""):
    """Insert an audit record inside an already-active BEGIN IMMEDIATE transaction + interprocess lock (P0-E)."""
    r = conn.execute("SELECT i, hash FROM audit ORDER BY i DESC LIMIT 1").fetchone()
    i, prev = (r[0] + 1, r[1]) if r else (0, "0" * 64)
    ts = time.time()
    clean_ref = redact_url(ref)
    conn.execute("INSERT INTO audit VALUES(?,?,?,?,?,?)",
                 (i, ts, action, clean_ref, prev, chain_hash(prev, i, ts, action, clean_ref)))
    return i


def log(action, ref=""):
    """Atomically append a tamper-evident SHA-256 record to audit across threads and OS processes (P0-E)."""
    clean_ref = redact_url(ref)
    R.run_atomic_tx(db, DBL, lambda conn: _log_in_tx(conn, action, clean_ref), db_path=DB_PATH)
    logger.info("AUDIT [%s] %s", action, clean_ref)


R.init(db, DBL, log, lambda: refresh_known(), db_path=DB_PATH)
try:
    import insights as INS
    INS.init(db, DBL)
except Exception as e:
    INS = None
    logger.warning("Learning module off: %s", e)
    print("Learning module off:", e)

# Lightweight read-only analytics and persistent camera reliability history.
try:
    import analytics as ANALYTICS
    import camera_history as CAMERA_HISTORY
    CAMERA_HISTORY.init(db, DBL, db_path=DB_PATH)
except Exception as e:
    ANALYTICS = CAMERA_HISTORY = None
    logger.warning("Operational analytics/camera history off: %s", e)


HIGH = ("VEHICLE: WANTED", "VEHICLE: STOLEN", "FACE MATCH (demo watchlist)", "ROUTE ANOMALY (impossible transit)")
MID = ("VEHICLE: EXPIRED", "VEHICLE: WATCH", "TRUCK IN RESTRICTED HOURS", "ANOMALY (learned pattern)", "POSSIBLE MATCH (visual check)")
INFO_ONLY = ("ROUTE NOTICE (uncalibrated)",)
NO_DISPATCH_MSGS = ("ROUTE NOTICE (uncalibrated)", "POSSIBLE MATCH (visual check)")


def is_no_dispatch_msg(msg):
    """Derive whether an alert type forbids direct patrol dispatch from its message type (survives restarts, P1-F)."""
    return str(msg or "") in INFO_ONLY or str(msg or "") in NO_DISPATCH_MSGS


def _sync_alerts_from_db(reset_stuck_in_flight=False):
    """Synchronize bus.alerts and bus.failed_dispatches from SQLite across processes (P0-E, P1-F, P0-B).
    P0-B upgrades:
    - Never resets an 'in_flight' alert unless its lease has ACTUALLY expired ((now - dispatch_started_ts) >= DISPATCH_LEASE_SEC).
    - Normalizes legacy/unscheduled confirmed alerts (where dispatched=0 and next_retry_ts<=0) without ever re-sending 'sent' alerts."""
    now = time.time()
    with R.interprocess_db_lock(DB_PATH):
        R.migrate_db(db, DBL)

        def _sync_tx(conn):
            changed = False
            if reset_stuck_in_flight:
                expired = conn.execute(
                    "SELECT id, COALESCE(dispatch_owner,''), COALESCE(dispatch_started_ts,0) FROM alerts "
                    "WHERE status='confirm' AND COALESCE(dispatched,0)=0 AND dispatch_status='in_flight' "
                    "AND (? - COALESCE(dispatch_started_ts, 0)) >= ?",
                    (now, DISPATCH_LEASE_SEC)
                ).fetchall()
                for exp_id, exp_owner, exp_ts in expired:
                    cur = conn.execute(
                        "UPDATE alerts SET dispatch_status='pending', dispatch_started_ts=0, dispatch_owner='', next_retry_ts=? "
                        "WHERE id=? AND status='confirm' AND COALESCE(dispatched,0)=0 AND dispatch_status='in_flight' "
                        "AND COALESCE(dispatch_started_ts,0)=?",
                        (now, exp_id, exp_ts)
                    )
                    if cur.rowcount == 1:
                        _log_in_tx(conn, "dispatch lease expired recovered", f"id={exp_id} prev_owner={exp_owner} started_ts={exp_ts:.1f}")
                        changed = True

            # P0-B item 6: Normalize legacy confirmed rows that were never sent and lack a valid next_retry_ts
            legacy_rows = conn.execute(
                "SELECT id, msg, COALESCE(dispatch_status,''), COALESCE(dispatch_attempts,0), COALESCE(next_retry_ts,0) "
                "FROM alerts WHERE status='confirm' AND COALESCE(dispatched,0)=0 AND COALESCE(dispatch_status,'') NOT IN ('sent','in_flight','uncertain')"
            ).fetchall()
            for lid, lmsg, ldst, latt, lnext in legacy_rows:
                if is_no_dispatch_msg(lmsg):
                    continue
                att_i = int(latt or 0)
                nxt_f = float(lnext or 0.0)
                if ldst in ("", "not_required"):
                    conn.execute(
                        "UPDATE alerts SET dispatch_status='pending', next_retry_ts=? WHERE id=? AND COALESCE(dispatched,0)=0",
                        (now if nxt_f <= 0 else nxt_f, lid)
                    )
                    changed = True
                elif ldst == "pending" and nxt_f <= 0 and att_i < DISPATCH_MAX_ATTEMPTS:
                    conn.execute(
                        "UPDATE alerts SET next_retry_ts=? WHERE id=? AND dispatch_status='pending' AND COALESCE(dispatched,0)=0",
                        (now, lid)
                    )
                    changed = True
                elif ldst == "failed" and nxt_f <= 0 and att_i < DISPATCH_MAX_ATTEMPTS:
                    backoff = DISPATCH_RETRY_BASE_SEC * max(1, att_i)
                    conn.execute(
                        "UPDATE alerts SET next_retry_ts=? WHERE id=? AND dispatch_status='failed' AND COALESCE(dispatched,0)=0",
                        (now + backoff, lid)
                    )
                    changed = True
            return changed

        R.run_atomic_tx(db, DBL, _sync_tx, db_path=DB_PATH)

        mx = db.execute("SELECT COALESCE(MAX(id), 0) FROM alerts").fetchone()[0]
        AID[0] = max(AID[0], int(mx or 0))
        rows = db.execute(
            "SELECT id, msg, subject, ref, detail, cam, ts_str, img, status, dispatched, "
            "COALESCE(dispatch_status,'not_required'), COALESCE(repeat_count,1), COALESCE(notify_status,'pending') "
            "FROM alerts WHERE status='pending' ORDER BY id ASC"
        ).fetchall()
        f_rows = db.execute(
            "SELECT id, msg, subject, ref, detail, cam, ts_str, img, COALESCE(dispatch_status,'failed'), "
            "COALESCE(dispatch_attempts,0), COALESCE(next_retry_ts,0), COALESCE(last_error,''), COALESCE(dispatch_owner,'') "
            "FROM alerts WHERE status='confirm' AND COALESCE(dispatched,0)=0 "
            "AND COALESCE(dispatch_status,'failed') IN ('pending','in_flight','failed','uncertain') ORDER BY id DESC"
        ).fetchall()
    bus.alerts[:] = []
    for aid, msg, subj, ref, det, cam, ts_str, img, st, disp, dst, rep_cnt, n_st in rows:
        al = {
            "id": aid, "msg": msg, "subject": subj, "ref": ref, "detail": det or "", "cam": cam, "ts": ts_str,
            "img": img, "dispatch_status": dst, "repeat_count": int(rep_cnt or 1),
            "notify_status": n_st, "info_only": is_no_dispatch_msg(msg)
        }
        bus.alerts.append(al)
        if img:
            ev_p = os.path.join("evidence", img)
            if os.path.exists(ev_p):
                EVID[aid] = ev_p
    bus.failed_dispatches[:] = [
        {"id": r[0], "msg": r[1], "subject": r[2], "ref": r[3], "detail": r[4] or "", "cam": r[5], "ts": r[6], "img": r[7],
         "dispatch_status": r[8], "attempts": r[9], "next_retry_ts": r[10], "last_error": r[11], "dispatch_owner": r[12]}
        for r in f_rows
    ]


def _is_evidence_archivable(conn, bname):
    """Return (archivable: bool, reason: str) for an evidence image filename (P1-E).
    Strictly forbids archiving or deleting original evidence belonging to:
    - Any pending alert (status == 'pending'), OR
    - Any confirmed alert whose patrol dispatch has not completed (status == 'confirm' and dispatch_status != 'sent')."""
    if not bname:
        return False, "empty_filename"
    alert_rows = conn.execute(
        "SELECT id, status, COALESCE(dispatch_status,''), COALESCE(dispatched,0) FROM alerts WHERE img=?",
        (bname,)
    ).fetchall()
    for aid, st, dst, disp in alert_rows:
        if st == "pending":
            return False, f"alert_pending:id={aid}"
        if st == "confirm" and (dst != "sent" and int(disp or 0) != 1):
            return False, f"alert_dispatch_incomplete:id={aid}:status={dst}"
    return True, "ok"


def _recover_interrupted_archives():
    """Safely recover interrupted archive operations without ever deleting active or unverified evidence (P1-E):
    1) Never recovers based solely on a matching file in evidence_archive/: requires an active/recorded archive op
       in evidence_archive_ops or audit ('evidence archived').
    2) Strictly verifies that the alert associated with the evidence allows archiving (_is_evidence_archivable).
    3) Inspects realpath containment, forbids symlinks on both source and destination, and verifies SHA-256 of both files.
    4) On any ambiguity, unlogged copy, active alert, or hash discrepancy: preserves the original file in evidence/
       and records an 'archive recovery conflict' entry in the audit log for human review."""
    os.makedirs("evidence", exist_ok=True)
    if not os.path.isdir("evidence_archive"):
        return
    ev_root = os.path.realpath("evidence")
    arch_root = os.path.realpath("evidence_archive")

    with R.interprocess_db_lock(DB_PATH):
        R.migrate_db(db, DBL)
        ev_rows = {
            str(r[0]).partition(" sha256=")[0].strip(): str(r[0]).partition(" sha256=")[2].strip().split()[0]
            for r in db.execute("SELECT ref FROM audit WHERE action='evidence'").fetchall()
            if " sha256=" in str(r[0])
        }
        arch_logged = {
            str(r[0]).partition(" sha256=")[0].strip(): str(r[0]).partition(" sha256=")[2].strip().split()[0]
            for r in db.execute("SELECT ref FROM audit WHERE action='evidence archived'").fetchall()
            if " sha256=" in str(r[0])
        }
        conflict_logged = {
            str(r[0]).partition(" ")[0].strip()
            for r in db.execute("SELECT ref FROM audit WHERE action='archive recovery conflict'").fetchall()
        }
        op_rows = {
            r[0]: {"arch_rel": r[1], "sha256": r[2], "status": r[3], "who": r[4]}
            for r in db.execute("SELECT orig_rel, arch_rel, sha256, status, who FROM evidence_archive_ops").fetchall()
        }

    candidate_bnames = set()
    for fname in os.listdir("evidence_archive"):
        if fname.endswith(".jpg") and not fname.endswith(".part"):
            candidate_bnames.add(fname)
    for orig_r, op_info in op_rows.items():
        if op_info["status"] in ("in_progress", "logged"):
            candidate_bnames.add(os.path.basename(orig_r))

    for fname in sorted(candidate_bnames):
        orig_rel = f"evidence/{fname}"
        arch_rel = f"evidence_archive/{fname}"
        exp_h = ev_rows.get(orig_rel)
        op_info = op_rows.get(orig_rel)

        # 1. Symlink and path traversal check on both paths
        orig_is_link = os.path.lexists(orig_rel) and os.path.islink(orig_rel)
        arch_is_link = os.path.lexists(arch_rel) and os.path.islink(arch_rel)
        if orig_is_link or arch_is_link:
            if orig_rel not in conflict_logged:
                log("archive recovery conflict", f"{orig_rel} archive={arch_rel} reason=symlink_detected")
                conflict_logged.add(orig_rel)
            continue

        real_orig = os.path.realpath(orig_rel)
        real_arch = os.path.realpath(arch_rel)
        if os.path.commonpath([ev_root, real_orig]) != ev_root or os.path.commonpath([arch_root, real_arch]) != arch_root:
            if orig_rel not in conflict_logged:
                log("archive recovery conflict", f"{orig_rel} archive={arch_rel} reason=path_outside_root")
                conflict_logged.add(orig_rel)
            continue

        # 2. Must correspond to a known evidence record in audit
        if not exp_h:
            if orig_rel not in conflict_logged:
                log("archive recovery conflict", f"{orig_rel} archive={arch_rel} reason=no_evidence_audit_record")
                conflict_logged.add(orig_rel)
            continue

        # 3. Check if an archive operation was legitimately started/logged
        has_legit_op = bool(
            (op_info and op_info["status"] in ("in_progress", "logged", "completed") and op_info["sha256"] == exp_h)
            or (orig_rel in arch_logged and arch_logged[orig_rel] == exp_h)
        )
        if not has_legit_op:
            # Copy in evidence_archive/ appeared outside archive_old_evidence -> keep original and flag conflict!
            if orig_rel not in conflict_logged:
                log("archive recovery conflict", f"{orig_rel} archive={arch_rel} reason=uninitiated_external_archive_copy")
                conflict_logged.add(orig_rel)
            continue

        # 4. Check alert eligibility (never delete original if alert is pending or dispatch incomplete!)
        with R.interprocess_db_lock(DB_PATH):
            archivable, elig_reason = _is_evidence_archivable(db, fname)
        if not archivable:
            def _mark_abort(conn):
                conn.execute("UPDATE evidence_archive_ops SET status='conflict_active_alert' WHERE orig_rel=?", (orig_rel,))
                if orig_rel not in conflict_logged:
                    _log_in_tx(conn, "archive recovery conflict", f"{orig_rel} archive={arch_rel} reason={elig_reason}")
                    conflict_logged.add(orig_rel)
            R.run_atomic_tx(db, DBL, _mark_abort, db_path=DB_PATH)
            continue

        # 5. Check if process crashed before destination copy completed
        if not os.path.isfile(arch_rel):
            if os.path.isfile(orig_rel) and op_info and op_info["status"] == "in_progress":
                def _rb_pre(conn):
                    conn.execute("UPDATE evidence_archive_ops SET status='rolled_back_pre_copy' WHERE orig_rel=?", (orig_rel,))
                    _log_in_tx(conn, "archive recovery rolled back", f"{orig_rel} reason=interrupted_before_copy")
                R.run_atomic_tx(db, DBL, _rb_pre, db_path=DB_PATH)
            continue

        # 6. Verify SHA-256 of destination (and original if still present on disk)
        with open(arch_rel, "rb") as af:
            arch_h = hashlib.sha256(af.read()).hexdigest()
        orig_exists = os.path.isfile(orig_rel)
        orig_h = None
        if orig_exists:
            with open(orig_rel, "rb") as of:
                orig_h = hashlib.sha256(of.read()).hexdigest()

        if arch_h != exp_h or (orig_exists and orig_h != exp_h):
            def _mark_hash_conflict(conn):
                conn.execute("UPDATE evidence_archive_ops SET status='conflict_hash_mismatch' WHERE orig_rel=?", (orig_rel,))
                if orig_rel not in conflict_logged:
                    _log_in_tx(
                        conn,
                        "archive recovery conflict",
                        f"{orig_rel} archive={arch_rel} reason=hash_mismatch exp={exp_h[:12]} orig={(orig_h or 'none')[:12]} arch={arch_h[:12]}"
                    )
                    conflict_logged.add(orig_rel)
            R.run_atomic_tx(db, DBL, _mark_hash_conflict, db_path=DB_PATH)
            continue

        # 7. Valid interrupted archive of an eligible resolved alert with verified SHA-256 -> complete recovery!
        need_audit_log = orig_rel not in arch_logged
        need_op_complete = bool(op_info and op_info["status"] != "completed")
        if need_audit_log or orig_exists or need_op_complete:
            def _complete_rec(conn):
                if orig_rel not in arch_logged:
                    _log_in_tx(conn, "evidence archived", f"{orig_rel} archive={arch_rel} sha256={arch_h} by=startup_recovery")
                conn.execute(
                    "UPDATE evidence_archive_ops SET status='completed', completed_ts=? WHERE orig_rel=?",
                    (time.time(), orig_rel)
                )
            R.run_atomic_tx(db, DBL, _complete_rec, db_path=DB_PATH)
            if orig_exists:
                try: os.remove(orig_rel)
                except OSError: pass


_sync_alerts_from_db(reset_stuck_in_flight=True)
_recover_interrupted_archives()


def archive_old_evidence(retention_days=None, who="system", _allow_test_override=False):
    """Reversible, crash-safe evidence archiving (P1-H, P1-E):
    - Journals each archive operation in evidence_archive_ops before copying so _recover_interrupted_archives
      can distinguish legitimate interrupted archives from external/unlogged copies.
    - Strictly excludes evidence belonging to pending alerts or confirmed alerts with incomplete patrol dispatch.
    - Verifies realpath containment, forbids symlinks, checks SHA-256 before and after copy, and enforces >= 7d floor."""
    cfg_days = float(DEFAULTS.get("evidence_retention_days", 30))
    if os.path.exists("mersad_config.json"):
        try:
            cfg_days = float(json.load(open("mersad_config.json", encoding="utf-8")).get("evidence_retention_days", 30))
        except Exception:
            pass
    raw_days = float(retention_days if retention_days is not None else cfg_days)
    if raw_days <= 0:
        return {"archived": 0, "files": [], "skipped_active": 0}
    eff_days = raw_days if _allow_test_override else max(MIN_RETENTION_DAYS, raw_days)
    cutoff = time.time() - eff_days * 86400.0

    os.makedirs("evidence", exist_ok=True)
    os.makedirs("evidence_archive", exist_ok=True)
    ev_root = os.path.realpath("evidence")
    arch_root = os.path.realpath("evidence_archive")

    with R.interprocess_db_lock(DB_PATH):
        R.migrate_db(db, DBL)
        ev_rows = db.execute("SELECT ts, ref FROM audit WHERE action='evidence' ORDER BY i ASC").fetchall()
        already_arch = {
            str(r[0]).partition(" sha256=")[0].strip()
            for r in db.execute("SELECT ref FROM audit WHERE action IN ('evidence archived', 'evidence purged')").fetchall()
        }

    archived_files = []
    skipped_active = 0
    for ts, ref in ev_rows:
        if ts > cutoff or " sha256=" not in str(ref):
            continue
        rel_path, _, rest = str(ref).partition(" sha256=")
        rel_path = rel_path.strip()
        exp_hash = rest.strip().split()[0]
        bname = os.path.basename(rel_path)
        if rel_path in already_arch or not bname.endswith(".jpg") or "/" in rel_path[len("evidence/"):] or ".." in rel_path:
            continue

        with R.interprocess_db_lock(DB_PATH):
            archivable, _ = _is_evidence_archivable(db, bname)
        if not archivable:
            skipped_active += 1
            continue

        if os.path.islink(rel_path) or not os.path.isfile(rel_path):
            continue
        real_src = os.path.realpath(rel_path)
        if os.path.commonpath([ev_root, real_src]) != ev_root:
            continue
        with open(real_src, "rb") as ef:
            actual_hash = hashlib.sha256(ef.read()).hexdigest()
        if actual_hash != exp_hash:
            continue

        arch_rel = f"evidence_archive/{bname}"
        if os.path.lexists(arch_rel) and os.path.islink(arch_rel):
            continue
        real_dst = os.path.realpath(arch_rel)
        if os.path.commonpath([arch_root, real_dst]) != arch_root:
            continue

        # Stage 1: Record 'in_progress' in evidence_archive_ops before touching evidence_archive/
        def _start_op(conn):
            ok_elig, _ = _is_evidence_archivable(conn, bname)
            if not ok_elig:
                return False
            conn.execute(
                """INSERT INTO evidence_archive_ops(orig_rel, arch_rel, sha256, started_ts, completed_ts, who, status)
                   VALUES(?, ?, ?, ?, 0, ?, 'in_progress')
                   ON CONFLICT(orig_rel) DO UPDATE SET arch_rel=excluded.arch_rel, sha256=excluded.sha256,
                     started_ts=excluded.started_ts, completed_ts=0, who=excluded.who, status='in_progress'""",
                (rel_path, arch_rel, actual_hash, time.time(), str(who))
            )
            return True

        if not R.run_atomic_tx(db, DBL, _start_op, db_path=DB_PATH):
            skipped_active += 1
            continue

        tmp_dst = real_dst + f".part.{os.getpid()}"
        try:
            # Stage 2: Copy via temp file, verify SHA-256, and atomically replace destination
            shutil.copy2(real_src, tmp_dst)
            with open(tmp_dst, "rb") as af:
                copied_hash = hashlib.sha256(af.read()).hexdigest()
            if copied_hash != exp_hash:
                try: os.remove(tmp_dst)
                except OSError: pass
                R.run_atomic_tx(
                    db, DBL,
                    lambda c: c.execute("UPDATE evidence_archive_ops SET status='failed_copy_hash' WHERE orig_rel=?", (rel_path,)),
                    db_path=DB_PATH
                )
                continue
            os.replace(tmp_dst, real_dst)

            # Stage 3: Re-check eligibility and record 'evidence archived' in audit + status='logged'
            def _log_op(conn):
                ok_elig, _ = _is_evidence_archivable(conn, bname)
                if not ok_elig:
                    conn.execute("UPDATE evidence_archive_ops SET status='aborted_active_alert' WHERE orig_rel=?", (rel_path,))
                    return False
                _log_in_tx(conn, "evidence archived", f"{rel_path} archive={arch_rel} sha256={actual_hash} retention_days={eff_days} by={who}")
                conn.execute("UPDATE evidence_archive_ops SET status='logged' WHERE orig_rel=?", (rel_path,))
                return True

            if not R.run_atomic_tx(db, DBL, _log_op, db_path=DB_PATH):
                try: os.remove(real_dst)
                except OSError: pass
                skipped_active += 1
                continue

            # Stage 4: Remove original file and mark operation 'completed'
            os.remove(real_src)
            R.run_atomic_tx(
                db, DBL,
                lambda c: c.execute("UPDATE evidence_archive_ops SET status='completed', completed_ts=? WHERE orig_rel=?", (time.time(), rel_path)),
                db_path=DB_PATH
            )
            archived_files.append(rel_path)
            already_arch.add(rel_path)
        except OSError:
            if os.path.exists(tmp_dst):
                try: os.remove(tmp_dst)
                except OSError: pass
    return {"archived": len(archived_files), "files": archived_files, "skipped_active": skipped_active, "retention_days": eff_days}


def purge_archived_evidence(archive_retention_days=90, who="system", _allow_test_override=False):
    """Final irreversible deletion of already-archived evidence files after archive_retention_days (P1-H)."""
    eff_days = float(archive_retention_days) if _allow_test_override else max(30.0, float(archive_retention_days))
    cutoff = time.time() - eff_days * 86400.0
    if not os.path.isdir("evidence_archive"):
        return {"purged": 0, "files": []}
    arch_root = os.path.realpath("evidence_archive")
    with R.interprocess_db_lock(DB_PATH):
        arch_rows = db.execute("SELECT ts, ref FROM audit WHERE action='evidence archived' ORDER BY i ASC").fetchall()
        already_purged = {
            str(r[0]).partition(" sha256=")[0].strip()
            for r in db.execute("SELECT ref FROM audit WHERE action='evidence purged'").fetchall()
        }
    purged = []
    for ts, ref in arch_rows:
        if ts > cutoff or " sha256=" not in str(ref):
            continue
        orig_rel = str(ref).partition(" ")[0].strip()
        if orig_rel in already_purged:
            continue
        bname = os.path.basename(orig_rel)
        with R.interprocess_db_lock(DB_PATH):
            archivable, _ = _is_evidence_archivable(db, bname)
        if not archivable:
            continue
        arch_rel = f"evidence_archive/{bname}"
        exp_hash = str(ref).partition(" sha256=")[2].strip().split()[0]
        if os.path.islink(arch_rel) or not os.path.isfile(arch_rel):
            continue
        real_arch = os.path.realpath(arch_rel)
        if os.path.commonpath([arch_root, real_arch]) != arch_root:
            continue
        with open(real_arch, "rb") as af:
            actual_h = hashlib.sha256(af.read()).hexdigest()
        if actual_h != exp_hash:
            continue
        try:
            os.remove(real_arch)
            log("evidence purged", f"{orig_rel} archive={arch_rel} sha256={actual_h} by={who}")
            purged.append(orig_rel)
            already_purged.add(orig_rel)
        except OSError:
            pass
    return {"purged": len(purged), "files": purged}


def verify():
    """Verify both the SHA-256 audit hash chain AND the physical integrity of active and archived evidence files (P1-H, P1-E).
    - Active evidence: must exist in evidence/ (not a symlink) with matching SHA-256.
    - Archived evidence: must have an 'evidence archived' record AND exist in evidence_archive/ with matching SHA-256
      (unless also recorded in 'evidence purged')."""
    prev = "0" * 64
    with DBL:
        rows = db.execute("SELECT i, ts, action, ref, prev, hash FROM audit ORDER BY i").fetchall()
    archived_map = {}
    purged_map = {}
    for i, ts, ac, ref, p, h in rows:
        if p != prev or chain_hash(p, i, ts, ac, ref) != h:
            return f"TAMPERING DETECTED at record #{i}"
        if ac == "evidence archived" and " sha256=" in str(ref):
            rel_p = str(ref).partition(" ")[0].strip()
            arch_h = str(ref).partition(" sha256=")[2].strip().split()[0]
            archived_map[rel_p] = arch_h
        elif ac == "evidence purged" and " sha256=" in str(ref):
            rel_p = str(ref).partition(" ")[0].strip()
            purg_h = str(ref).partition(" sha256=")[2].strip().split()[0]
            purged_map[rel_p] = purg_h
        prev = h

    archived_ok = 0
    purged_ok = 0
    for i, ts, ac, ref, p, h in rows:
        if ac == "evidence" and " sha256=" in str(ref):
            rel_path, _, rest = str(ref).partition(" sha256=")
            rel_path = rel_path.strip()
            exp_hash = rest.strip().split()[0]
            bname = os.path.basename(rel_path)
            arch_path = f"evidence_archive/{bname}"

            if rel_path in purged_map and purged_map[rel_path] == exp_hash and rel_path in archived_map:
                purged_ok += 1
            elif rel_path in archived_map and archived_map[rel_path] == exp_hash:
                if not os.path.isfile(arch_path) or os.path.islink(arch_path):
                    return f"TAMPERING DETECTED: missing archived evidence file {arch_path} (record #{i})"
                with open(arch_path, "rb") as af:
                    arch_actual = hashlib.sha256(af.read()).hexdigest()
                if arch_actual != exp_hash:
                    return f"TAMPERING DETECTED: modified archived evidence file {arch_path} (record #{i})"
                if os.path.lexists(rel_path):
                    if os.path.islink(rel_path):
                        return f"TAMPERING DETECTED: symlink at evidence path {rel_path} (record #{i})"
                    with open(rel_path, "rb") as ef:
                        if hashlib.sha256(ef.read()).hexdigest() != exp_hash:
                            return f"TAMPERING DETECTED: modified evidence file {rel_path} (record #{i})"
                archived_ok += 1
            elif os.path.isfile(rel_path) and not os.path.islink(rel_path):
                with open(rel_path, "rb") as ef:
                    actual_hash = hashlib.sha256(ef.read()).hexdigest()
                if actual_hash != exp_hash:
                    return f"TAMPERING DETECTED: modified evidence file {rel_path} (record #{i})"
            else:
                return f"TAMPERING DETECTED: missing evidence file {rel_path} (record #{i})"
    parts = [f"{len(rows)} records"]
    if archived_ok:
        parts.append(f"{archived_ok} archived")
    if purged_ok:
        parts.append(f"{purged_ok} purged")
    return f"Audit chain OK ({', '.join(parts)})"


def blur_unmatched_faces(frame, unmatched_boxes):
    """Blur bystander/unmatched faces in evidence frames before saving to disk or sending to Telegram (P2-K)."""
    if frame is None or getattr(frame, "size", 0) == 0 or not unmatched_boxes:
        return frame
    out = frame.copy()
    H, W = out.shape[:2]
    for (x, y, bw, bh) in unmatched_boxes:
        x1, y1 = max(0, int(x)), max(0, int(y))
        x2, y2 = min(W, int(x + bw)), min(H, int(y + bh))
        if x2 > x1 + 4 and y2 > y1 + 4:
            roi = out[y1:y2, x1:x2]
            out[y1:y2, x1:x2] = cv2.GaussianBlur(roi, (31, 31), 15)
    return out


def alert_text(msg, subject, cam, ts, extra=""):
    """What the patrol / operator sees on the phone."""
    prio = "🔴 أولوية قصوى" if msg in HIGH else "🟠 أولوية متوسطة" if msg in MID else "🔵 للعلم"
    return (f"{prio} — مرصاد AI\n{AR.get(msg, msg)}\n🔎 {subject}{extra}\n📍 {cam} · 🕒 {ts}\n"
            f"⚠️ رصد آلي، ويتطلب تأكيداً بشرياً قبل أي إجراء.")


def raise_alert(msg, subject, cam, frame, ref=None, extra="", detail="", unmatched_faces=None):
    """Create or deduplicate an alert atomically across threads/processes (P0-E, P1-I, P2-K).
    - Deduplicates active pending alerts by (msg, ref), incrementing repeat_count instead of spamming new alerts.
    - Uses SQLite AUTOINCREMENT for alert IDs so concurrent OS processes never collide.
    - Cleans up temporary evidence file if the DB transaction fails."""
    now = time.time()
    ts = time.strftime("%H:%M:%S", time.localtime(now))
    ref = str(ref or subject)
    no_disp = is_no_dispatch_msg(msg)

    os.makedirs("evidence", exist_ok=True)
    safe_frame = blur_unmatched_faces(frame, unmatched_faces)
    if safe_frame is None or getattr(safe_frame, "size", 0) == 0:
        safe_frame = np.zeros((120, 320, 3), dtype=np.uint8)
    now_ms = int(now * 1000)
    tmp_name = f"{now_ms}_{uuid.uuid4().hex[:10]}.jpg"
    tmp_path = f"evidence/{tmp_name}"
    cv2.imwrite(tmp_path, safe_frame)
    with open(tmp_path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()

    def _tx(conn):
        R.migrate_db(conn, DBL)
        # P1-I: Check if a pending alert already exists for the same (msg, ref)
        existing = conn.execute(
            "SELECT id, COALESCE(repeat_count, 1) FROM alerts WHERE status='pending' AND msg=? AND ref=? ORDER BY id DESC LIMIT 1",
            (msg, ref)
        ).fetchone()
        if existing:
            ex_id, ex_rep = int(existing[0]), int(existing[1] or 1) + 1
            conn.execute(
                "UPDATE alerts SET repeat_count=?, last_seen_ts=?, ts_str=? WHERE id=?",
                (ex_rep, now, ts, ex_id)
            )
            _log_in_tx(conn, "alert repeat", f"id={ex_id} count={ex_rep} {msg} {ref}")
            return (ex_id, True, ex_rep, "")

        has_tg = bool(os.getenv("TELEGRAM_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))
        init_n_status = "pending" if has_tg else "not_configured"
        cur = conn.execute(
            "INSERT INTO alerts(ts, ts_str, msg, subject, ref, detail, cam, img, status, dispatched, "
            "dispatch_status, repeat_count, last_seen_ts, notify_status, notify_attempts) "
            "VALUES(?,?,?,?,?,?,?,?,'pending',0,'not_required',1,?,?,0)",
            (now, ts, msg, subject, ref, detail or "", cam, tmp_name, now, init_n_status)
        )
        aid = int(cur.lastrowid)
        _log_in_tx(conn, "evidence", f"{tmp_path} sha256={digest}")
        _log_in_tx(conn, "alert", f"id={aid} {msg} {ref}")
        return (aid, False, 1, tmp_name)

    try:
        aid, is_dup, rep_cnt, img_name = R.run_atomic_tx(db, DBL, _tx, db_path=DB_PATH)
    except Exception:
        if os.path.exists(tmp_path):
            try: os.remove(tmp_path)
            except OSError: pass
        raise

    if is_dup:
        if os.path.exists(tmp_path):
            try: os.remove(tmp_path)
            except OSError: pass
        _sync_alerts_from_db()
        bus.publish({"type": "alert_updated", "id": aid, "repeat_count": rep_cnt, "ts": ts})
        return aid

    AID[0] = max(AID[0], aid)
    EVID[aid] = tmp_path
    al = {
        "id": aid, "msg": msg, "subject": subject, "ref": ref, "detail": detail or "", "cam": cam, "ts": ts,
        "img": img_name, "dispatch_status": "not_required", "repeat_count": 1, "info_only": no_disp
    }
    _sync_alerts_from_db()
    bus.publish({"type": "alert", **al})

    btns = None if no_disp else [
        [("✅ تأكيد وتوجيه الدورية", f"c:{aid}"), ("📝 تسجيل فقط", f"a:{aid}")],
        [("❌ تجاهل (تحقق خاطئ)", f"d:{aid}")]
    ]
    if no_disp and msg == "POSSIBLE MATCH (visual check)":
        btns = [[("📝 تسجيل فقط", f"a:{aid}"), ("❌ تجاهل (تحقق خاطئ)", f"d:{aid}")]]

    def _on_ops_notify(ok, err_str):
        try:
            R.run_atomic_tx(
                db, DBL,
                lambda c: c.execute(
                    "UPDATE alerts SET notify_status=?, notify_attempts=COALESCE(notify_attempts,0)+1 WHERE id=?",
                    ("sent" if ok else ("not_configured" if err_str == "not_configured" else "failed"), aid)
                ),
                db_path=DB_PATH
            )
        except Exception:
            pass

    send_alert(
        alert_text(msg, subject, cam, ts, extra),
        tmp_path,
        buttons=btns,
        idempotency_key=f"ops_alert:{aid}",
        on_done=_on_ops_notify
    )
    return aid


def _refresh_failed_dispatches():
    _sync_alerts_from_db()
    bus.publish({"type": "failed_dispatches", "items": bus.failed_dispatches})


def _attempt_dispatch(aid, trigger="auto", is_manual=False, owner_id=None):
    """Execute one patrol dispatch attempt with an atomic SQLite lease ('in_flight' + dispatch_started_ts + dispatch_owner, P0-B).
    - Guarantees two processes/threads never own or send the same dispatch attempt simultaneously while the lease is valid.
    - Maintains lease heartbeat throughout network transmission.
    - Distinguishes uncertain timeout outcomes ('uncertain') from confirmed receipt ('sent') and definite failure ('failed')."""
    now = time.time()
    lease_owner = str(owner_id or f"{PROCESS_OWNER_ID}:att_{uuid.uuid4().hex[:6]}")

    def _claim_lease(conn):
        R.migrate_db(conn, DBL)
        row = conn.execute(
            "SELECT id, msg, subject, ref, detail, cam, ts_str, img, status, COALESCE(dispatched,0), "
            "COALESCE(dispatch_status,'pending'), COALESCE(dispatch_attempts,0), COALESCE(dispatch_started_ts,0), COALESCE(dispatch_owner,'') "
            "FROM alerts WHERE id=?",
            (aid,)
        ).fetchone()
        if not row:
            return None
        _, msg, subj, ref, det, cam, ts_s, img, st, disp_int, dst, att, started_ts, prev_owner = row
        if st != "confirm" or is_no_dispatch_msg(msg) or dst == "sent" or int(disp_int or 0) == 1:
            return None
        started_f = float(started_ts or 0.0)
        if dst == "in_flight" and (now - started_f) < DISPATCH_LEASE_SEC:
            return None
        if dst == "uncertain" and not is_manual:
            return None
        max_allowed = (DISPATCH_MAX_ATTEMPTS + 3) if is_manual else DISPATCH_MAX_ATTEMPTS
        if int(att or 0) >= max_allowed:
            return None
        if dst == "in_flight" and (now - started_f) >= DISPATCH_LEASE_SEC:
            _log_in_tx(conn, "dispatch lease expired recovered", f"id={aid} prev_owner={prev_owner} started_ts={started_f:.1f}")
        new_att = int(att or 0) + 1
        cur = conn.execute(
            "UPDATE alerts SET dispatch_status='in_flight', dispatch_started_ts=?, dispatch_attempts=?, dispatch_owner=? "
            "WHERE id=? AND status='confirm' AND COALESCE(dispatched,0)=0 AND COALESCE(dispatch_status,'pending')=? AND COALESCE(dispatch_started_ts,0)=?",
            (now, new_att, lease_owner, aid, dst, started_ts)
        )
        if cur.rowcount != 1:
            return None
        _log_in_tx(conn, "dispatch attempt", f"id={aid} attempt=#{new_att} owner={lease_owner} trigger={trigger} {msg} {ref}")
        return ({"id": aid, "msg": msg, "subject": subj, "ref": ref, "detail": det, "cam": cam, "ts": ts_s, "img": img}, new_att)

    claimed = R.run_atomic_tx(db, DBL, _claim_lease, db_path=DB_PATH)
    if not claimed:
        return False
    al, attempt_no = claimed

    ev_path = EVID.get(aid) or (os.path.join("evidence", al.get("img", "")) if al.get("img") else None)
    if ev_path and not os.path.exists(ev_path):
        ev_path = None

    # P0-B item 2: Renew lease heartbeat while send_alert is executing so an active slow transfer never loses its lease
    hb_stop = threading.Event()
    def _lease_heartbeat():
        interval = max(0.05, min(2.0, DISPATCH_LEASE_SEC * 0.35))
        while not hb_stop.wait(interval):
            try:
                R.run_atomic_tx(
                    db, DBL,
                    lambda c: c.execute(
                        "UPDATE alerts SET dispatch_started_ts=? WHERE id=? AND dispatch_status='in_flight' AND dispatch_owner=?",
                        (time.time(), aid, lease_owner)
                    ),
                    db_path=DB_PATH
                )
            except Exception:
                pass
    hb_thread = threading.Thread(target=_lease_heartbeat, daemon=True)
    hb_thread.start()

    idem_key = f"patrol_dispatch:{aid}:att:{attempt_no}"
    is_uncertain = False
    err_detail = ""
    ok = False
    try:
        res_send = send_alert(
            f"🚓 توجيه دورية (مؤكَّد من الضابط)\n{AR.get(al['msg'], al['msg'])}\n{al['subject']}\n"
            f"الكاميرا: {al['cam']}\nالوقت: {al['ts']}\n⚠️ بلاغ مبني على رصد آلي أكّده ضابط العمليات. "
            f"تحقّق بنفسك من المركبة أو الشخص قبل أي إجراء.",
            ev_path,
            "TELEGRAM_PATROL_CHAT_ID",
            sync=True,
            idempotency_key=idem_key
        )
        if res_send == "uncertain" or (isinstance(res_send, tuple) and len(res_send) >= 2 and res_send[1] == "uncertain"):
            ok = False
            is_uncertain = True
        else:
            ok = bool(res_send)
            meta = _notify_mod.LAST_SEND_OUTCOMES.get(idem_key) or {}
            if not ok and meta.get("uncertain"):
                is_uncertain = True
                err_detail = str(meta.get("error") or "")
    except (UncertainDeliveryError, TimeoutError, socket.timeout) as te:
        ok = False
        is_uncertain = True
        err_detail = redact_url(te)
    except Exception as ex:
        ok = False
        is_uncertain = _notify_mod._is_timeout_error(ex)
        err_detail = redact_url(ex)
    finally:
        hb_stop.set()

    final_status = ["failed"]

    def _finalize_lease(conn):
        cur_row = conn.execute(
            "SELECT COALESCE(dispatched,0), COALESCE(dispatch_status,''), COALESCE(dispatch_owner,'') FROM alerts WHERE id=?",
            (aid,)
        ).fetchone()
        if not cur_row:
            return
        cur_disp, cur_dst, cur_owner = cur_row
        # Never overwrite an alert that was already marked sent, and never allow an evicted lease owner to clobber a newer owner!
        if int(cur_disp or 0) == 1 or cur_dst == "sent":
            final_status[0] = "sent"
            return
        if cur_owner and cur_owner != lease_owner:
            final_status[0] = cur_dst
            return

        if ok and not is_uncertain:
            final_status[0] = "sent"
            conn.execute(
                "UPDATE alerts SET dispatched=1, dispatch_status='sent', dispatch_started_ts=0, dispatch_owner='', next_retry_ts=0, last_error='' WHERE id=?",
                (aid,)
            )
            _log_in_tx(conn, "dispatch sent", f"id={aid} attempt=#{attempt_no} owner={lease_owner} {al['msg']} {al['ref']}")
        elif is_uncertain:
            final_status[0] = "uncertain"
            u_msg = "نتيجة الإرسال غير محسومة بسبب انتهاء مهلة الشبكة — تحقق من وصول البلاغ للدوريات قبل الإعادة اليدوية"
            if err_detail:
                u_msg = f"{u_msg} ({err_detail[:80]})"
            conn.execute(
                "UPDATE alerts SET dispatched=0, dispatch_status='uncertain', dispatch_started_ts=0, dispatch_owner='', next_retry_ts=0, last_error=? WHERE id=?",
                (u_msg, aid)
            )
            _log_in_tx(conn, "dispatch uncertain", f"id={aid} attempt=#{attempt_no} owner={lease_owner} {al['msg']} {al['ref']}")
        else:
            final_status[0] = "failed"
            has_retries_left = attempt_no < DISPATCH_MAX_ATTEMPTS
            backoff = DISPATCH_RETRY_BASE_SEC * attempt_no
            next_ts = (time.time() + backoff) if has_retries_left else 0.0
            err_msg = (
                "تعذّر الوصول إلى قناة الدوريات (سيتم إعادة المحاولة تلقائياً)"
                if has_retries_left else "استُنفدت المحاولات التلقائية — يتطلب تدخلاً يدوياً"
            )
            conn.execute(
                "UPDATE alerts SET dispatched=0, dispatch_status='failed', dispatch_started_ts=0, dispatch_owner='', next_retry_ts=?, last_error=? WHERE id=?",
                (next_ts, err_msg, aid)
            )
            _log_in_tx(conn, "dispatch failed or skipped", f"id={aid} attempt=#{attempt_no} owner={lease_owner} retry_in={int(backoff) if has_retries_left else 0}s {al['msg']} {al['ref']}")

    def _finalize_and_sync(conn):
        _finalize_lease(conn)
        if final_status[0] == "sent":
            bus.failed_dispatches[:] = [x for x in bus.failed_dispatches if x.get("id") != aid]
        else:
            f_rows = conn.execute(
                "SELECT id, msg, subject, ref, detail, cam, ts_str, img, COALESCE(dispatch_status,'failed'), "
                "COALESCE(dispatch_attempts,0), COALESCE(next_retry_ts,0), COALESCE(last_error,''), COALESCE(dispatch_owner,'') "
                "FROM alerts WHERE status='confirm' AND COALESCE(dispatched,0)=0 "
                "AND COALESCE(dispatch_status,'failed') IN ('pending','in_flight','failed','uncertain') ORDER BY id DESC"
            ).fetchall()
            bus.failed_dispatches[:] = [
                {"id": r[0], "msg": r[1], "subject": r[2], "ref": r[3], "detail": r[4] or "", "cam": r[5], "ts": r[6], "img": r[7],
                 "dispatch_status": r[8], "attempts": r[9], "next_retry_ts": r[10], "last_error": r[11], "dispatch_owner": r[12]}
                for r in f_rows
            ]

    R.run_atomic_tx(db, DBL, _finalize_and_sync, db_path=DB_PATH)
    if final_status[0] == "sent":
        EVID.pop(aid, None)
    _refresh_failed_dispatches()
    bus.publish({"type": "dispatched", "id": aid, "ok": final_status[0] == "sent", "attempt": attempt_no,
                 "dispatch_status": final_status[0]})
    if final_status[0] != "sent" and (attempt_no == 1 or attempt_no == DISPATCH_MAX_ATTEMPTS or final_status[0] == "uncertain"):
        exhausted_note = (
            " (نتيجة غير محسومة بسبب مهلة الشبكة — راجع يدوياً!)"
            if final_status[0] == "uncertain"
            else (" (استُنفدت المحاولات التلقائية!)" if attempt_no >= DISPATCH_MAX_ATTEMPTS else "")
        )
        send_alert(
            f"⚠️ تنبيه غرفة العمليات: تعذّر تأكيد إيصال البلاغ #{aid} ({al['subject']}) إلى قروب الدوريات (المحاولة #{attempt_no}){exhausted_note}. "
            f"البلاغ محفوظ في قائمة «توجيهات لم تصل».",
            chat_env="TELEGRAM_CHAT_ID",
            sync=False,
            idempotency_key=f"ops_dispatch_warn:{aid}:{attempt_no}:{final_status[0]}"
        )
    return final_status[0] == "sent"


def dispatch(al_or_aid, trigger="auto", is_manual=False):
    """Trigger patrol dispatch in a background worker thread so decide(), Telegram listener, and camera loop never block."""
    aid = al_or_aid["id"] if isinstance(al_or_aid, dict) else int(al_or_aid)
    t = threading.Thread(target=_attempt_dispatch, args=(aid, trigger, is_manual), daemon=True)
    t.start()
    t.join(timeout=0.05)
    with DBL:
        r = db.execute("SELECT dispatched FROM alerts WHERE id=?", (aid,)).fetchone()
        return bool(r and r[0] == 1)


def retry_dispatch(aid, who="operator"):
    """Explicit manual retry policy for failed or uncertain patrol dispatches (P1-F, P0-B).
    Logs the manual retry request and executes an atomic dispatch attempt without resetting audit history."""
    now = time.time()
    with DBL:
        row = db.execute(
            "SELECT status, COALESCE(dispatched,0), COALESCE(dispatch_status,''), COALESCE(dispatch_attempts,0), COALESCE(dispatch_started_ts,0) "
            "FROM alerts WHERE id=?",
            (aid,)
        ).fetchone()
        if not row or row[0] != "confirm":
            return {"ok": False, "error": "التنبيه غير موجود أو غير مؤكّد"}
        if int(row[1] or 0) == 1 or row[2] == "sent":
            return {"ok": True, "already_sent": True, "dispatch_status": "sent"}
        if row[2] == "in_flight" and (now - float(row[4] or 0.0)) < DISPATCH_LEASE_SEC:
            return {"ok": False, "error": "توجد محاولة إرسال جارية حالياً لهذا البلاغ"}
        if int(row[3] or 0) >= DISPATCH_MAX_ATTEMPTS + 3:
            return {"ok": False, "error": "تجاوز البلاغ الحد الأقصى لمحاولات الإعادة اليدوية؛ تحقق من إعدادات تيليجرام والشبكة"}
    log("manual dispatch retry requested", f"id={aid} by {who}")
    ok = dispatch(aid, trigger=f"manual:{who}", is_manual=True)
    with DBL:
        st, att = db.execute("SELECT dispatch_status, dispatch_attempts FROM alerts WHERE id=?", (aid,)).fetchone()
    return {"ok": ok, "dispatch_status": st, "attempts": att}


def _find_due_dispatches(now=None):
    """Return list of confirmed alert IDs that are eligible for automatic dispatch or lease recovery (P0-B)."""
    if now is None:
        now = time.time()
    with DBL:
        rows = db.execute(
            "SELECT id, msg FROM alerts WHERE status='confirm' AND COALESCE(dispatched, 0) = 0 AND ("
            "  (COALESCE(dispatch_status,'pending') IN ('pending','failed') "
            "   AND COALESCE(dispatch_attempts,0) < ? "
            "   AND (COALESCE(next_retry_ts,0) <= 0 OR next_retry_ts <= ?)) "
            "  OR (dispatch_status='in_flight' AND (? - COALESCE(dispatch_started_ts,0)) >= ?)"
            ") ORDER BY id ASC",
            (DISPATCH_MAX_ATTEMPTS, now, now, DISPATCH_LEASE_SEC)
        ).fetchall()
    return [r[0] for r in rows if not is_no_dispatch_msg(r[1])]


def _dispatch_retry_loop(stop_event=None):
    """Background scheduler that:
    1) Picks up pending/failed dispatches (including attempts==0 and next_retry_ts==0, P0-B),
    2) Recovers expired in_flight leases without touching active valid leases,
    3) Periodically synchronizes alerts from SQLite across processes (P0-E) and runs scheduled archiving (P1-H)."""
    last_arch = time.time()
    while not (stop_event and stop_event.is_set()):
        try:
            now = time.time()
            _sync_alerts_from_db(reset_stuck_in_flight=False)
            due = _find_due_dispatches(now)
            for aid in due:
                if stop_event and stop_event.is_set():
                    break
                _attempt_dispatch(aid, trigger="auto_retry", is_manual=False)

            if now - last_arch > 3600:
                last_arch = now
                archive_old_evidence(who="periodic_scheduler")
        except Exception as e:
            logger.debug("Retry loop error: %s", e)
        time.sleep(0.25)


def decide(aid, action, who):
    """Human decision (keyboard, dashboard, or Telegram).
    Rejects 'confirm' on INFO_ONLY / POSSIBLE MATCH alerts on the server (P1-F)."""
    if action not in ("confirm", "ack", "dismiss") or not str(who or "").strip():
        return False

    def _tx(conn):
        R.migrate_db(conn, DBL)
        row = conn.execute("SELECT id, msg, subject, ref, detail, cam, ts_str, img, status FROM alerts WHERE id=?", (aid,)).fetchone()
        if not row or row[8] != "pending":
            return None
        msg = row[1]
        if action == "confirm" and is_no_dispatch_msg(msg):
            return False
        disp_st = "pending" if action == "confirm" else "not_required"
        # Schedule immediate retry fallback (now + 1.5s) in case the process crashes before worker thread starts (P1-F)
        next_rt = (time.time() + 1.5) if action == "confirm" else 0.0
        conn.execute(
            "UPDATE alerts SET status=?, decided_by=?, decided_ts=?, dispatch_status=?, next_retry_ts=? WHERE id=? AND status='pending'",
            (action, str(who), time.time(), disp_st, next_rt, aid)
        )
        _log_in_tx(conn, "operator " + action, f"id={aid} {msg} {row[3]} by {who}")
        return {"id": row[0], "msg": msg, "subject": row[2], "ref": row[3], "detail": row[4], "cam": row[5], "ts": row[6], "img": row[7], "disp_st": disp_st}

    res = R.run_atomic_tx(db, DBL, _tx, db_path=DB_PATH)
    if not res:
        return False
    _sync_alerts_from_db()
    bus.publish({"type": "resolved", "id": aid, "action": action, "dispatch_status": res["disp_st"]})
    if action == "confirm":
        _refresh_failed_dispatches()
        dispatch(res, trigger=f"confirm:{who}")
    else:
        EVID.pop(aid, None)
    return True


# ---------- faces: strict person_id identity isolation, consent enforcement, matching (P0-A) ----------
class KnownFace(tuple):
    """3-tuple (name, emb, watch) with .person_id and .ref attributes so 3-tuple unpacking remains compatible while isolating identity."""
    def __new__(cls, name, emb, watch, person_id=0, ref=""):
        obj = super().__new__(cls, (name, emb, int(watch)))
        obj.person_id = int(person_id or 0)
        obj.ref = str(ref or "")
        return obj


class FaceMatchResult(tuple):
    """3-tuple (name, score, watch) with .person_id and .ref attributes."""
    def __new__(cls, name, score, watch, person_id=0, ref=""):
        obj = super().__new__(cls, (name, float(score), int(watch)))
        obj.person_id = int(person_id or 0)
        obj.ref = str(ref or "")
        return obj


def validate_embedding(emb):
    """Verify face feature vector is a valid 128-D float32 array with non-zero finite norm."""
    if emb is None:
        return None
    arr = np.asarray(emb, dtype=np.float32).reshape(1, -1)
    if arr.shape != (1, 128) or not np.all(np.isfinite(arr)):
        return None
    norm = float(np.linalg.norm(arr))
    if norm < 1e-6:
        return None
    return arr / norm


def refresh_known():
    """Load face embeddings ONLY by joining faces.person_id == persons.id where p.consent == 1 and f.quarantined == 0 (P0-A).
    Never allows consent of a homonymous person to authorize embeddings belonging to another person_id or quarantined legacy row."""
    with R.interprocess_db_lock(DB_PATH):
        R.migrate_db(db, DBL)
        R.migrate_legacy_faces(db)
        db.commit()
        rows = db.execute(
            "SELECT p.id, p.name, COALESCE(p.ref, ''), f.emb, CASE WHEN p.status='watch' THEN 1 ELSE 0 END "
            "FROM faces f "
            "JOIN persons p ON p.id = f.person_id "
            "WHERE f.person_id > 0 AND COALESCE(f.quarantined, 0) = 0 AND COALESCE(p.consent, 0) = 1"
        ).fetchall()
    valid = []
    active_keys = set()
    for pid, n, ref, b, w in rows:
        if not b or len(b) != 128 * 4:
            continue
        emb = validate_embedding(np.frombuffer(b, np.float32))
        if emb is not None:
            valid.append(KnownFace(n, emb, int(w), person_id=pid, ref=ref))
            active_keys.add(f"id:{pid}")
            active_keys.add(n)
    KNOWN[:] = valid
    for k in list(FH):
        if k not in active_keys:
            FH.pop(k, None)
    bus.publish({"type": "people"})


def req_enroll(name_or_id, watch=False, who="operator", ref="", person_id=None):
    """Start face enrollment bound to a specific unambiguous person_id (P0-A item 3)."""
    if ENR.get("req"):
        return False
    p = R.get_person(name=name_or_id, ref=ref, person_id=person_id)
    if not p or not p.get("consent"):
        return False
    ENR["req"] = {
        "person_id": int(p["id"]),
        "name": p["name"],
        "ref": p.get("ref", ""),
        "watch": bool(p.get("status") == "watch" or watch),
        "who": who,
        "samples": [],
        "t0": time.time()
    }
    return True


def enroll_step(emb=None):
    """Called every frame; collects 5 validated 128-D embeddings and binds them strictly to er['person_id'] (P0-A)."""
    er = ENR.get("req")
    if not er:
        return
    if time.time() - er["t0"] > 30:
        ENR["req"] = None; bus.publish({"type": "enroll", "n": -1}); return
    norm_emb = validate_embedding(emb)
    if norm_emb is None:
        return
    er["samples"].append(norm_emb.astype(np.float32).tobytes())
    bus.publish({"type": "enroll", "n": len(er["samples"])})
    if len(er["samples"]) >= 5:
        target_pid = int(er.get("person_id") or 0)

        def _save_samples(conn):
            R.migrate_db(conn, DBL)
            if target_pid > 0:
                p = conn.execute(
                    "SELECT id, name, COALESCE(ref,''), COALESCE(status,'normal'), COALESCE(consent,0) "
                    "FROM persons WHERE id=? AND COALESCE(consent,0)=1",
                    (target_pid,)
                ).fetchone()
            else:
                p_all = conn.execute(
                    "SELECT id, name, COALESCE(ref,''), COALESCE(status,'normal'), COALESCE(consent,0) "
                    "FROM persons WHERE name=? AND COALESCE(consent,0)=1",
                    (er["name"],)
                ).fetchall()
                p = p_all[0] if len(p_all) == 1 else None
            if p:
                pid, p_name, p_ref, p_status, _ = p
                w_flag = int(p_status == "watch" or er.get("watch"))
                for s in er["samples"]:
                    conn.execute(
                        "INSERT INTO faces(name, emb, watch, person_id, quarantined, quarantine_reason) VALUES(?,?,?,?,0,'')",
                        (p_name, s, w_flag, pid)
                    )
                _log_in_tx(
                    conn,
                    "face enrolled (consent confirmed)",
                    f"{pseud(f'{pid}:{p_name}')} id={pid} ref={p_ref} watch={w_flag} by {er['who']}"
                )

        R.run_atomic_tx(db, DBL, _save_samples, db_path=DB_PATH)
        ENR["req"] = None
        refresh_known()


def match_face_embedding(emb, rec=None):
    """Match a 128-D embedding against consented KNOWN embeddings and return FaceMatchResult(name, score, watch, person_id, ref) (P0-A)."""
    q = validate_embedding(emb)
    if q is None or not KNOWN:
        return FaceMatchResult("unenrolled", 0.0, 0, person_id=0, ref="")
    best_name, best_sc, best_wl, best_pid, best_ref = "unenrolled", 0.0, 0, 0, ""
    for item in KNOWN:
        nm, k_emb, w = item[0], item[1], item[2]
        pid = getattr(item, "person_id", 0)
        ref = getattr(item, "ref", "")
        if rec is not None and hasattr(rec, "match"):
            s = float(rec.match(q, k_emb, cv2.FaceRecognizerSF_FR_COSINE))
        else:
            s = float((q @ k_emb.T).item())
        if s >= COS_T and s > best_sc:
            best_name, best_sc, best_wl, best_pid, best_ref = nm, s, w, pid, ref
    return FaceMatchResult(best_name, best_sc, best_wl, person_id=best_pid, ref=best_ref)


def face_step(name, sc, watch, frame, cam, frame_idx=0, unmatched_faces=None, person_id=None, ref=None):
    """Watchlist check keyed by internal person_id so two homonymous persons never share streak/cooldown state (P0-A item 6)."""
    if isinstance(name, FaceMatchResult):
        if person_id is None:
            person_id = name.person_id
        if ref is None:
            ref = name.ref
        name = name[0]
    if name == "unenrolled" or not watch or sc < FACE_ALERT[0]:
        return False
    pid_val = int(person_id or 0)
    if pid_val <= 0:
        for item in KNOWN:
            if item[0] == name and getattr(item, "person_id", 0) > 0:
                pid_val = int(item.person_id)
                if not ref:
                    ref = getattr(item, "ref", "")
                break
    identity_key = f"id:{pid_val}" if pid_val > 0 else str(name)
    now = time.time()
    prev_cnt, prev_ts, prev_f = FH.get(identity_key, (0, 0.0, -999))
    is_consec = (now - prev_ts <= 4.0) and (frame_idx <= 0 or (frame_idx - prev_f) <= 12)
    cnt = prev_cnt + 1 if is_consec else 1
    FH[identity_key] = (cnt, now, frame_idx)
    if cnt >= 3 and now - FA.get(identity_key, 0.0) > ALERT_COOLDOWN_SEC:
        FA[identity_key] = now
        FH[identity_key] = (0, now, frame_idx)
        disp_subj = f"{name} [{ref}] (تشابه {sc:.2f})" if ref else f"{name} (تشابه {sc:.2f})"
        alert_ref = pseud(f"{pid_val}:{name}") if pid_val > 0 else pseud(name)
        raise_alert(
            "FACE MATCH (demo watchlist)",
            disp_subj,
            cam,
            frame,
            ref=alert_ref,
            extra="\nهذا احتمال تطابق خوارزمي وليس إثباتاً قاطعاً، ويتطلب تحققاً بشرياً قبل أي إجراء.",
            unmatched_faces=unmatched_faces
        )
        return True
    return False


# ---------- vehicles / trucks / plates / trajectories ----------
def verify_onnx_file(path, expected_sha256=None, min_bytes=50_000):
    """Verify that an ONNX model file exists, is not a symlink, meets minimum size, has valid binary header, and matches SHA-256."""
    if not path or not os.path.isfile(path) or os.path.islink(path):
        return False, "file_missing_or_symlink"
    sz = os.path.getsize(path)
    if sz < min_bytes:
        return False, f"file_too_small:{sz}<{min_bytes}"
    h = hashlib.sha256()
    with open(path, "rb") as f:
        head = f.read(64)
        if not head or head.startswith((b"<!DOCTYPE", b"<html", b'{"error"')):
            return False, "invalid_onnx_header_html_or_json"
        h.update(head)
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    digest = h.hexdigest()
    if expected_sha256 and digest.lower() != expected_sha256.lower():
        return False, f"sha256_mismatch:{digest[:16]}!={expected_sha256[:16]}"
    return True, f"verified_onnx(size={sz}, sha256={digest[:12]}...)"


def verify_yolo_pt_file(path, expected_sha256=None, min_bytes=6_000_000):
    """Verify that a YOLOv8 PyTorch .pt checkpoint is a valid, uncorrupted PyTorch ZIP archive with data.pkl & tensor storage,
    and matches expected SHA-256 (or sidecar .sha256 if present) (Stage 4b)."""
    if not path or not os.path.isfile(path) or os.path.islink(path):
        return False, "file_missing_or_symlink"
    sz = os.path.getsize(path)
    if sz < min_bytes:
        return False, f"file_too_small:{sz}<{min_bytes}"
    sidecar = f"{path}.sha256"
    if not expected_sha256 and os.path.isfile(sidecar):
        try:
            expected_sha256 = open(sidecar, "r", encoding="utf-8").read().strip().split()[0]
        except Exception:
            pass
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    digest = h.hexdigest()
    if expected_sha256 and digest.lower() != expected_sha256.lower():
        return False, f"sha256_mismatch:{digest[:16]}!={expected_sha256[:16]}"
    if not zipfile.is_zipfile(path):
        return False, "not_a_valid_pytorch_zip_checkpoint"
    try:
        with zipfile.ZipFile(path, "r") as zf:
            names = zf.namelist()
            has_pkl = any(n.endswith("data.pkl") for n in names)
            has_data = any("/data/" in n or n.endswith("version") for n in names)
            if not (has_pkl and has_data):
                return False, "missing_pytorch_archive_entries(data.pkl/data)"
            bad_member = zf.testzip()
            if bad_member is not None:
                return False, f"corrupt_zip_entry:{bad_member}"
    except Exception as e:
        return False, f"zip_error:{e}"
    return True, f"verified_pytorch_checkpoint(size={sz}, sha256={digest[:12]}...)"


def verify_easyocr_dir(easyocr_dir="models/easyocr"):
    """Verify that EasyOCR model directory contains intact detector and recognizer .pth weights and no partial .part files (Stage 4d)."""
    if not easyocr_dir or not os.path.isdir(easyocr_dir) or os.path.islink(easyocr_dir):
        return False, "directory_missing"
    entries = os.listdir(easyocr_dir)
    partials = [fn for fn in entries if fn.endswith((".part", ".tmp", ".download"))]
    if partials:
        return False, f"incomplete_partial_files:{partials}"
    pth_files = [fn for fn in entries if fn.endswith(".pth")]
    if len(pth_files) < 2:
        return False, f"no_pth_files(found={len(pth_files)}, required>=2_detector_and_recognizer)"
    valid_pths = []
    for fn in pth_files:
        fp = os.path.join(easyocr_dir, fn)
        if not os.path.isfile(fp) or os.path.islink(fp):
            return False, f"invalid_pth_entry:{fn}"
        sz = os.path.getsize(fp)
        if sz < 500_000:
            return False, f"pth_too_small:{fn}({sz}B)"
        with open(fp, "rb") as f:
            magic = f.read(8)
        if not (magic.startswith(b"PK\x03\x04") or magic.startswith(b"\x80")):
            return False, f"corrupt_pth_header:{fn}"
        valid_pths.append(fn)
    return True, f"verified_{len(valid_pths)}_pth_weights({','.join(sorted(valid_pths))})"



def verify_runtime_model_assets(models_dir=None):
    """Verify all bundled weights without downloading anything at runtime.

    Frozen EXE builds must be self-contained: if any required model is absent or
    damaged, startup fails with a report instead of unexpectedly requiring the
    internet or writing model files under a protected installation directory.
    """
    root = os.path.abspath(models_dir or resolve_resource_path("models"))
    checks = []
    for filename in MODELS:
        path = os.path.join(root, filename)
        ok, reason = verify_onnx_file(
            path,
            expected_sha256=MODEL_SHA256.get(filename),
            min_bytes=MODEL_MIN_BYTES.get(filename, 50_000),
        )
        checks.append({"model": filename, "ok": bool(ok), "reason": str(reason)})
    yolo_path = os.path.join(root, "yolov8n.pt")
    ok_yolo, reason_yolo = verify_yolo_pt_file(
        yolo_path, min_bytes=MODEL_MIN_BYTES.get("yolov8n.pt", 6_000_000)
    )
    checks.append({"model": "yolov8n.pt", "ok": bool(ok_yolo), "reason": str(reason_yolo)})
    ok_easy, reason_easy = verify_easyocr_dir(os.path.join(root, "easyocr"))
    checks.append({"model": "easyocr/Arabic+English", "ok": bool(ok_easy), "reason": str(reason_easy)})
    return all(item["ok"] for item in checks), checks


def create_offline_easyocr_reader(easyocr_module=None, model_storage_directory=None):
    """Create the OCR reader only from prevalidated bundled/local weights.

    Runtime model downloads are deliberately disabled. A missing or damaged model
    is reported as an actionable startup error instead of attempting an invisible
    network download or writing to a protected installation directory.
    """
    if easyocr_module is None:
        import easyocr as easyocr_module
    model_dir = model_storage_directory or resolve_resource_path(os.path.join("models", "easyocr"))
    model_dir = os.path.abspath(model_dir)
    valid, reason = verify_easyocr_dir(model_dir)
    if not valid:
        raise RuntimeError(
            f"EasyOCR Arabic/English model weights are missing or invalid ({reason}) at '{model_dir}'. "
            "Run prefetch.py or BUILD_EXE.bat while connected to the internet, then retry. "
            "Runtime downloads are disabled."
        )
    try:
        return easyocr_module.Reader(
            ["ar", "en"], gpu=False,
            model_storage_directory=model_dir,
            download_enabled=False,
        )
    except TypeError as exc:
        raise RuntimeError(
            "The installed EasyOCR Reader does not support download_enabled=False. "
            "Install the pinned EasyOCR version from requirements.txt."
        ) from exc


def _bounded_camera_timeout_ms(env_name, default=5000):
    try:
        value = int(os.environ.get(env_name, default))
    except (TypeError, ValueError):
        value = default
    return max(1000, min(60000, value))


NETWORK_CAMERA_OPEN_TIMEOUT_MS = _bounded_camera_timeout_ms("MERSAD_CAMERA_OPEN_TIMEOUT_MS", 5000)
NETWORK_CAMERA_READ_TIMEOUT_MS = _bounded_camera_timeout_ms("MERSAD_CAMERA_READ_TIMEOUT_MS", 5000)


def _open_camera_capture(source):
    """Open a camera source; network URLs use bounded FFmpeg open/read timeouts.

    Opening is called only from each camera's dedicated reader thread, so a slow
    or unreachable RTSP/HTTP camera cannot delay other cameras or server startup.
    """
    source_value = int(source) if str(source).isdigit() else source
    if isinstance(source_value, str) and source_value.strip().lower().startswith((
        "rtsp://", "rtsps://", "http://", "https://"
    )):
        if not all(hasattr(cv2, key) for key in ("CAP_FFMPEG", "CAP_PROP_OPEN_TIMEOUT_MSEC", "CAP_PROP_READ_TIMEOUT_MSEC")):
            raise RuntimeError("This OpenCV build lacks bounded network-camera timeout support; install the pinned OpenCV package.")
        params = [
            int(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC), int(NETWORK_CAMERA_OPEN_TIMEOUT_MS),
            int(cv2.CAP_PROP_READ_TIMEOUT_MSEC), int(NETWORK_CAMERA_READ_TIMEOUT_MS),
        ]
        try:
            return cv2.VideoCapture(source_value, cv2.CAP_FFMPEG, params)
        except (TypeError, cv2.error) as exc:
            raise RuntimeError(
                "OpenCV could not create a network camera capture with bounded timeouts; "
                "the source will be retried without blocking the main service."
            ) from exc
    return cv2.VideoCapture(source_value)


def safe_download_model(filename, url, target_dir="models", min_bytes=50_000, expected_sha256=None, timeout=30.0, retries=3, validator_fn=None):
    """Download a model file safely to a temporary .part file with socket timeout, bounded retries, disk-space check,
    size/Content-Length check, SHA-256 verification, and structural validation before atomically replacing target (Stage 4c).
    Guarantees an existing valid model file is NEVER deleted or overwritten if a download fails."""
    os.makedirs(target_dir, exist_ok=True)
    target = os.path.join(target_dir, filename)

    def _validate_candidate(p):
        if not os.path.isfile(p) or os.path.islink(p):
            return False, "missing_or_symlink"
        sz = os.path.getsize(p)
        if sz < min_bytes:
            return False, f"size_too_small:{sz}<{min_bytes}"
        if expected_sha256:
            h = hashlib.sha256()
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            dig = h.hexdigest()
            if dig.lower() != expected_sha256.lower():
                return False, f"sha256_mismatch:expected={expected_sha256[:16]}!=got={dig[:16]}"
        if validator_fn is not None:
            res = validator_fn(p)
            if isinstance(res, tuple):
                return bool(res[0]), str(res[1])
            return bool(res), ("ok" if res else "validator_rejected")
        return True, f"verified(size={sz})"

    if os.path.isfile(target):
        ok_ex, reason_ex = _validate_candidate(target)
        if ok_ex:
            return True, f"already_verified:{reason_ex}", target

    if target_dir == "models":
        bundled = resolve_resource_path(os.path.join("models", filename))
        if bundled != target and os.path.isfile(bundled):
            ok_b, reason_b = _validate_candidate(bundled)
            if ok_b:
                return True, f"already_verified_bundled:{reason_b}", bundled

    if not _is_dir_writable(target_dir):
        raise PermissionError(f"Model directory '{target_dir}' is not writable")
    try:
        free_b = shutil.disk_usage(target_dir).free
        if free_b < max(min_bytes * 2, 10_000_000):
            raise OSError(f"Insufficient disk space in '{target_dir}' ({free_b} bytes free)")
    except OSError as e:
        if "Insufficient disk space" in str(e):
            raise

    tmp_path = f"{target}.part.{os.getpid()}.{uuid.uuid4().hex[:6]}"
    last_err = None
    for attempt in range(1, max(1, int(retries)) + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "MERSAD-AI-ModelFetcher/3.5"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                cl_hdr = resp.headers.get("Content-Length")
                exp_len = int(cl_hdr) if (cl_hdr and cl_hdr.isdigit()) else None
                written = 0
                with open(tmp_path, "wb") as tf:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        tf.write(chunk)
                        written += len(chunk)
                    tf.flush()
                    os.fsync(tf.fileno())
                if exp_len is not None and written != exp_len:
                    raise RuntimeError(f"Truncated download for {filename}: got {written} of {exp_len} bytes")

            ok_dl, reason_dl = _validate_candidate(tmp_path)
            if not ok_dl:
                raise RuntimeError(f"Verification failed for downloaded {filename}: {reason_dl}")

            os.replace(tmp_path, target)
            return True, f"downloaded_and_verified:{reason_dl}", target
        except Exception as e:
            last_err = e
            if os.path.exists(tmp_path):
                try: os.remove(tmp_path)
                except OSError: pass
            if attempt < retries:
                time.sleep(min(2.0, 0.25 * attempt))
            else:
                break
    raise RuntimeError(f"Failed to download and verify '{filename}' from {url} after {retries} attempts: {last_err}") from last_err


def fetch_models(verify_hash=True, timeout=30.0, retries=3):
    """Ensure OpenCV Zoo ONNX models exist and pass SHA-256 & ONNX verification (Stage 4)."""
    os.makedirs("models", exist_ok=True)
    for f, u in MODELS.items():
        exp_sha = MODEL_SHA256.get(f) if verify_hash else None
        min_b = MODEL_MIN_BYTES.get(f, 10_000)
        safe_download_model(
            filename=f,
            url=u,
            target_dir="models",
            min_bytes=min_b,
            expected_sha256=exp_sha,
            timeout=timeout,
            retries=retries,
            validator_fn=lambda p, es=exp_sha, mb=min_b: verify_onnx_file(p, expected_sha256=es, min_bytes=mb),
        )


def _get_vehicle_class_ids(model):
    """Determine numeric class IDs for vehicle categories to pass to YOLO classes= filter (P2-8)."""
    names = getattr(model, "names", None)
    if isinstance(names, dict):
        ids = [int(k) for k, v in names.items() if str(v).strip().lower() in VCLS_NAMES]
        if ids:
            return sorted(ids)
    elif isinstance(names, (list, tuple)):
        ids = [i for i, v in enumerate(names) if str(v).strip().lower() in VCLS_NAMES]
        if ids:
            return sorted(ids)
    return list(VCLS.keys())


def _resolve_vclass(cls_id, model):
    """Resolve vehicle class name safely across standard COCO or custom YOLO weights."""
    names = getattr(model, "names", None)
    if isinstance(names, (dict, list)):
        try:
            raw_name = str(names[int(cls_id)]).strip().lower()
            if raw_name in VCLS_NAMES:
                return VCLS_NAMES[raw_name]
        except (IndexError, KeyError, ValueError, TypeError):
            pass
    return VCLS.get(int(cls_id))


def detect_vehicles(img, model):
    """YOLOv8n: car / motorcycle / bus / truck -> [(x, y, w, h, class)]."""
    if not model or img is None or getattr(img, "size", 0) == 0:
        return []
    H, W = img.shape[:2]
    target_classes = _get_vehicle_class_ids(model)
    res_list = model(img, imgsz=480, conf=0.35, classes=target_classes, verbose=False)
    if not res_list:
        return []
    r = res_list[0]
    out = []
    for b, c in zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist()):
        vcls = _resolve_vclass(c, model)
        if not vcls:
            continue
        x1, y1 = max(0, int(b[0])), max(0, int(b[1]))
        x2, y2 = min(W, int(b[2])), min(H, int(b[3]))
        if x2 > x1 and y2 > y1:
            out.append((x1, y1, x2 - x1, y2 - y1, vcls))
    return out


def find_plates(img, yolo=None):
    """YOLO plate model if provided, else classic OpenCV rectangle search."""
    if img is None or getattr(img, "size", 0) == 0:
        return []
    H, W = img.shape[:2]
    if yolo:
        out = []
        for b in yolo(img, verbose=False)[0].boxes.xyxy.tolist():
            x1, y1 = max(0, int(b[0])), max(0, int(b[1]))
            x2, y2 = min(W, int(b[2])), min(H, int(b[3]))
            if x2 > x1 and y2 > y1:
                out.append((x1, y1, x2 - x1, y2 - y1))
        return out
    g = cv2.bilateralFilter(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), 9, 60, 60)
    cs, _ = cv2.findContours(cv2.Canny(g, 60, 180), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in sorted(cs, key=cv2.contourArea, reverse=True)[:15]:
        x, y, w, h = cv2.boundingRect(c)
        if w > 80 and h > 0 and 2 <= w / h <= 6 and \
           len(cv2.approxPolyDP(c, 0.03 * cv2.arcLength(c, True), True)) == 4:
            out.append((x, y, w, h))
    return out[:3]


def preprocess_plate(crop):
    """Enhance plate crop contrast (CLAHE) and upscale small crops before OCR."""
    if crop is None or getattr(crop, "size", 0) == 0:
        return None
    h, w = crop.shape[:2]
    if h < 8 or w < 16:
        return None
    img = crop
    if h < 48:
        scale = 48.0 / h
        img = cv2.resize(img, (max(16, int(w * scale)), 48), interpolation=cv2.INTER_CUBIC)
    if img.ndim == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        eq = clahe.apply(gray)
        return cv2.cvtColor(eq, cv2.COLOR_GRAY2BGR)
    return img


def read_plate(reader, crop, min_conf=MIN_OCR_CONF):
    """Read Arabic/English plate text, normalize without merging distinct lettered plates, and validate confidence."""
    proc = preprocess_plate(crop)
    if proc is None or reader is None:
        return None, 0.0
    try:
        res = reader.readtext(proc)
    except Exception as e:
        logger.debug("OCR readtext error: %s", e)
        return None, 0.0
    if not res:
        return None, 0.0
    raw_txt = " ".join(str(r[1]) for r in res if len(r) >= 3 and float(r[2]) >= min_conf * 0.7).strip()
    norm = R.norm_plate(raw_txt)
    digits_only, _ = R.split_plate(norm)
    conf = float(np.mean([float(r[2]) for r in res if len(r) >= 3])) if res else 0.0
    if 3 <= len(digits_only) <= 8 and conf >= min_conf:
        return norm, conf
    return None, 0.0


def infer_direction(pts):
    """Estimate smoothed frame-relative movement trajectory from bounding box sequence [(cx, cy, area), ...]."""
    if not pts or len(pts) < 2:
        return "عبور نسبي في الإطار"
    mid = max(1, len(pts) // 2)
    first_half = pts[:mid]
    second_half = pts[mid:]
    x0 = float(np.median([p[0] for p in first_half]))
    y0 = float(np.median([p[1] for p in first_half]))
    a0 = float(np.median([p[2] for p in first_half]))
    x1 = float(np.median([p[0] for p in second_half]))
    y1 = float(np.median([p[1] for p in second_half]))
    a1 = float(np.median([p[2] for p in second_half]))
    dx, dy = x1 - x0, y1 - y0
    if (a0 > 0 and (a1 - a0) / a0 > 0.12) or dy > 18:
        return "اقتراب نسبي في الإطار"
    if (a0 > 0 and (a0 - a1) / a0 > 0.12) or dy < -18:
        return "ابتعاد نسبي في الإطار"
    if dx > 20:
        return "يسار ➔ يمين (نسبة للإطار)"
    if dx < -20:
        return "يمين ➔ يسار (نسبة للإطار)"
    return "ثابت/عبور نسبي في الإطار"


class ConfirmedRead(tuple):
    """2-tuple (conf, direction) with .plate and .letters_confirmed attributes."""
    def __new__(cls, conf, direction, plate="", letters_confirmed=True):
        obj = super().__new__(cls, (conf, direction))
        obj.conf = conf
        obj.direction = direction
        obj.plate = plate
        obj.letters_confirmed = letters_confirmed
        return obj


def _bbox_compatible(b1, b2, max_dist=180.0):
    """Check if two bounding boxes (x, y, w, h) belong to the same local vehicle track in the camera frame (P0-A)."""
    if b1 is None or b2 is None:
        return True
    cx1, cy1 = b1[0] + b1[2] / 2.0, b1[1] + b1[3] / 2.0
    cx2, cy2 = b2[0] + b2[2] / 2.0, b2[1] + b2[3] / 2.0
    dist = ((cx1 - cx2) ** 2 + (cy1 - cy2) ** 2) ** 0.5
    return dist <= max_dist


def _letters_compatible(l1, l2):
    """Return True if two normalized letter strings are compatible within the same vehicle track (e.g. 'عدن' and 'ع' or '').
    Returns False if both have known letters that contradict each other (e.g. 'اب' vs 'جد', or 'صنعاء' vs 'عدن')."""
    if not l1 or not l2:
        return True
    return R._letter_similarity(l1, l2) >= 0.5


def confirm_plate_read(plate, conf, bbox, now, votes, tracks, last_seen,
                       confirm_reads=CONFIRM_READS, window_sec=VOTE_WINDOW_SEC, cooldown_sec=ALERT_COOLDOWN_SEC):
    """Track-aware, letter-compatible sliding-window multi-frame plate confirmation (P0-A):
    - Groups reads ONLY when they belong to the same vehicle track (compatible bounding box + compatible letters + same core digits).
    - Keeps 'أب-4444' and 'جد-4444' in completely separate vote buckets even if seen in the same window.
    - Groups noisy OCR reads of the same vehicle (['عدن 12345', 'ع 12345', 'عدن 12345']) and selects the consensus form."""
    if not plate or conf < MIN_OCR_CONF:
        return None
    digits_key, cur_letters = R.split_plate(plate)
    if not digits_key:
        return None
    norm_form = R.norm_plate(plate)

    # Prune expired reads across all track buckets
    for k in list(votes.keys()):
        cleaned_v = []
        for item in votes[k]:
            t, c = item[0], item[1]
            f_str = item[2] if len(item) > 2 else k
            b_prev = item[3] if len(item) > 3 else None
            if now - t <= window_sec:
                cleaned_v.append((t, c, f_str, b_prev))
        if cleaned_v:
            votes[k] = cleaned_v
        else:
            votes.pop(k, None)
            tracks.pop(k, None)

    # Find a compatible active bucket for this read (same digits + compatible letters + spatially close bbox)
    matched_bucket = None
    for b_key, items in votes.items():
        b_digits, _ = R.split_plate(b_key)
        if b_digits != digits_key or not items:
            continue
        last_bbox = items[-1][3]
        if not _bbox_compatible(last_bbox, bbox):
            continue
        existing_letters = [R.split_plate(it[2])[1] for it in items if R.split_plate(it[2])[1]]
        if all(_letters_compatible(cur_letters, ex_l) for ex_l in existing_letters):
            matched_bucket = b_key
            break

    if matched_bucket is None:
        base_bucket = norm_form if cur_letters else digits_key
        matched_bucket = base_bucket
        idx = 2
        while matched_bucket in votes:
            matched_bucket = f"{base_bucket}#{idx}"
            idx += 1

    votes.setdefault(matched_bucket, []).append((now, float(conf), norm_form, bbox))
    if bbox is not None:
        x, y, bw, bh = bbox
        tracks.setdefault(matched_bucket, []).append((x + bw / 2.0, y + bh / 2.0, float(bw * bh)))

    if len(votes[matched_bucket]) >= confirm_reads:
        grp = votes[matched_bucket]
        counts = collections.Counter(f_str for _, _, f_str, _ in grp)
        best_form = max(counts.keys(), key=lambda s: (counts[s], len(s)))
        if now - last_seen.get(best_form, 0.0) <= cooldown_sec:
            return None
        votes.pop(matched_bucket, None)
        pts = tracks.pop(matched_bucket, [])
        cm = float(np.mean([c for _, c, _, _ in grp]))
        win_digits, win_letters = R.split_plate(best_form)
        letters_confirmed = bool(win_letters) and counts[best_form] >= 2
        if cm >= MIN_OCR_CONF:
            last_seen[best_form] = now
            return ConfirmedRead(cm, infer_direction(pts), plate=best_form, letters_confirmed=letters_confirmed)
    return None


def in_hours(hr, cur):
    s, e = cur
    return (hr >= s or hr < e) if s > e else (s <= hr < e)


def register(d, conf, cam, vc="unknown", curfew=None, direction="عبور نسبي في الإطار", raw_text="", session_id=None, letters_confirmed=True):
    """Store sighting, look the plate up in the registry, track path & learn habits.
    - Filters previous sightings strictly by COALESCE(src,'live')='live' so demo data never pollutes 'NEW PLATE' or 'UNUSUAL HOUR' (P2-L).
    - Downgrades contradictory/ambiguous/approximate registry matches to 'POSSIBLE MATCH (visual check)' (P0-B)."""
    now = time.time(); hr = time.localtime(now).tm_hour
    d = R.norm_plate(d) or str(d)
    digits_key, letters_key = R.split_plate(d)
    sess = SESSION_ID if session_id is None else str(session_id)
    v = R.lookup_vehicle(d)
    if v and v.get("conf_factor", 1.0) < 1.0:
        conf = round(float(conf) * float(v["conf_factor"]), 3)

    # Identity is confirmed for cross-camera route tracking if letters are not contradictory/ambiguous
    id_confirmed = bool(letters_confirmed) and not (v and v.get("visual_check_only"))

    def _insert_sighting(conn):
        R.migrate_db(conn, DBL)
        # P2-L: Strictly filter COALESCE(src,'live')='live' and exact canonical plate
        rows = conn.execute(
            "SELECT ts FROM sightings WHERE plate=? AND COALESCE(src,'live')='live'",
            (d,)
        ).fetchall()
        cur = conn.execute(
            "INSERT INTO sightings(ts, cam, plate, conf, vclass, src, direction, raw_text, session_id) VALUES(?,?,?,?,?,'live',?,?,?)",
            (now, cam, d, conf, vc, direction, raw_text or d, sess)
        )
        return rows, (cur.lastrowid or 0)

    rows, cur_id = R.run_atomic_tx(db, DBL, _insert_sighting, db_path=DB_PATH)

    route_str, conflict_rec = (
        INS.check_route(d, cam, now, conf=conf, cur_id=cur_id, session_id=sess, identity_confirmed=id_confirmed)
        if INS and hasattr(INS, "check_route") else (None, None)
    )
    eff_dir = f"{route_str} ({direction})" if route_str and route_str not in direction else direction
    if eff_dir != direction:
        R.run_atomic_tx(db, DBL, lambda c: c.execute("UPDATE sightings SET direction=? WHERE rowid=?", (eff_dir, cur_id)), db_path=DB_PATH)
    log("sighting", f"id={cur_id} {d} {cam} {vc} dir={eff_dir} conf={conf:.2f}")

    why_str = INS.score_live(d, cam, vc, now, conf=conf, cur_id=cur_id, check_conflict=False, session_id=sess, identity_confirmed=id_confirmed) if INS else None
    if conflict_rec:
        why_str = conflict_rec["why"]
    if why_str:
        WHY[d] = why_str

    # P0-B: If registry match has contradictory letters, ambiguity, or edit-distance-1 approximation -> visual check only!
    if v and v["status"] != "normal" and v.get("visual_check_only"):
        WHY[d] = v.get("match_note", "تطابق محتمل — تحقق بصري")
        return "POSSIBLE MATCH (visual check)", v

    if v and v["status"] in ("wanted", "stolen"):
        return "VEHICLE: " + v["status"].upper(), v
    if conflict_rec and conflict_rec.get("calibrated"):
        return "ROUTE ANOMALY (impossible transit)", v
    if v and v["status"] != "normal":
        return "VEHICLE: " + v["status"].upper(), v
    if vc == "truck" and curfew and in_hours(hr, curfew):
        return "TRUCK IN RESTRICTED HOURS", v
    if conflict_rec and not conflict_rec.get("calibrated"):
        return "ROUTE NOTICE (uncalibrated)", v
    if not v and not rows:
        return "NEW PLATE (first sighting)", v
    if len(rows) >= 5 and all(time.localtime(r[0]).tm_hour != hr for r in rows if r[0]):
        return "UNUSUAL HOUR (learned pattern)", v
    if why_str:
        return "ANOMALY (learned pattern)", v
    return None, v


def vinfo(v):
    """(vehicle text safe for Telegram, same + owner + match_note for the private dashboard)"""
    if not v: return "", ""
    note = v.get("match_note", "")
    note_tag = f"({note})" if note and v.get("match_type") != "exact" else ""
    base = " · ".join(x for x in (v.get("model", ""), v.get("color", ""), note_tag) if x)
    priv = " · ".join(x for x in (base, ("المالك: " + v["owner"]) if v.get("owner") else "") if x)
    return base, priv


def enroll_api(d, ip):
    """Start live face enrollment for a specific consented person (identified by id/person_id, ref, or unique name, P0-A)."""
    raw_id = d.get("id") if d.get("id") is not None else d.get("person_id")
    pid = int(raw_id) if str(raw_id or "").isdigit() and int(raw_id) > 0 else None
    ref = str(d.get("ref", "")).strip()
    name = str(d.get("name", "")).strip()
    p = R.get_person(name=name, ref=ref, person_id=pid)
    if not p:
        if name and not pid and not ref:
            same_name = [x for x in R.list_rows("persons", name) if x["name"] == name]
            if len(same_name) > 1:
                return {"ok": False, "error": "يوجد أكثر من شخص بهذا الاسم؛ حدد المعرّف (id) أو الرقم المرجعي (ref)"}
        return {"ok": False, "error": "الشخص غير موجود في السجل"}
    if not p["consent"]:
        return {"ok": False, "error": "لا توجد موافقة مسجّلة لهذا الشخص"}
    if not req_enroll(p["name"], p["status"] == "watch", ip, ref=p.get("ref", ""), person_id=p["id"]):
        return {"ok": False, "error": "عملية تسجيل أخرى جارية"}
    return {"ok": True, "person_id": p["id"]}


def ins_act(fn, name):
    def h(d, ip):
        if not INS: return {"ok": False, "error": "وحدة التحليل غير متاحة"}
        r = fn(); log("learning model: " + name, f"n={r.get('n', 0)} by {ip}"); return r
    return h


def tg_press(data, who):
    """A decision tapped on a phone in the operations room (Telegram)."""
    act, _, aid = str(data or "").partition(":")
    action = {"c": "confirm", "a": "ack", "d": "dismiss"}.get(act)
    if not action or not aid.isdigit(): return "طلب غير صالح"
    if not decide(int(aid), action, who): return "سبق البتّ في هذا التنبيه أو الإجراء غير متاح"
    return {"confirm": "جارٍ الإرسال إلى الدوريات...", "ack": "تم التسجيل", "dismiss": "تم التجاهل"}[action]


STATUS = {"fps": 0.0, "cam": "", "t0": time.time(), "cameras": {}}


def stats():
    """Numbers for the dashboard ribbon and status chips. Safe on empty or legacy databases."""
    now = time.time(); t = time.localtime(now); mid = now - (t.tm_hour * 3600 + t.tm_min * 60 + t.tm_sec)
    _sync_alerts_from_db()
    with DBL:
        q = lambda sql, *a: int(db.execute(sql, a).fetchone()[0] or 0)
        d = {"det24": q("SELECT COUNT(*) FROM sightings WHERE ts IS NOT NULL AND ts>? AND COALESCE(src,'live')='live'", now - 86400),
             "trucks24": q("SELECT COUNT(*) FROM sightings WHERE ts IS NOT NULL AND ts>? AND vclass='truck' AND COALESCE(src,'live')='live'", now - 86400),
             "alerts": q("SELECT COUNT(*) FROM audit WHERE action='alert' AND ts>?", mid),
             "confirmed": q("SELECT COUNT(*) FROM audit WHERE action='operator confirm' AND ts>?", mid),
             "dismissed": q("SELECT COUNT(*) FROM audit WHERE action='operator dismiss' AND ts>?", mid),
             "failed_dispatches": q("SELECT COUNT(*) FROM alerts WHERE status='confirm' AND COALESCE(dispatched,0)=0 AND COALESCE(dispatch_status,'failed') IN ('pending','in_flight','failed','uncertain')"),
             "vehicles": q("SELECT COUNT(*) FROM vehicles"), "persons": q("SELECT COUNT(*) FROM persons"), "chain": q("SELECT COUNT(*) FROM audit")}
    tg_cfg = bool(os.getenv("TELEGRAM_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))
    tg_conn = bool(tg_cfg and _notify_mod.TELEGRAM_STATUS.get("connected", True))
    d.update(
        pending=len(bus.alerts), fps=STATUS["fps"], cam=STATUS["cam"], cameras=STATUS.get("cameras", {}),
        uptime=int(now - STATUS["t0"]), telegram=tg_cfg, telegram_connected=tg_conn,
        telegram_error=_notify_mod.TELEGRAM_STATUS.get("last_error", ""),
        learning=bool(INS and INS.M["model"])
    )
    return d


def wire():
    bus.on_stats = stats
    bus.verify, bus.on_list, bus.on_template, bus.on_import = verify, R.list_rows, R.template, R.import_file

    def _analytics_report():
        if not ANALYTICS:
            return {"ok": False, "error": "التحليلات غير متاحة"}
        with DBL:
            return ANALYTICS.build_report(db, STATUS.get("cameras", {}))

    def _camera_health_report(period="24h"):
        if not CAMERA_HISTORY:
            return {"ok": False, "error": "سجل صحة الكاميرات غير متاح"}
        with DBL:
            return CAMERA_HISTORY.build_report(db, STATUS.get("cameras", {}), period=period)

    bus.on_analytics = _analytics_report
    bus.on_analytics_export = (lambda: ANALYTICS.export_csv(_analytics_report())) if ANALYTICS else (lambda: b"\xef\xbb\xbf")
    bus.on_camera_health = _camera_health_report
    bus.on_camera_health_export = (lambda period="24h": CAMERA_HISTORY.export_csv(_camera_health_report(period))) if CAMERA_HISTORY else (lambda period="24h": b"\xef\xbb\xbf")
    bus.on_insights = INS.summary if INS else (lambda: {"model": {"ready": False, "type": "none", "reason": "module_disabled"}, "forecast": None, "anomalies": [], "corridors": [], "paths": []})
    bus.on_path = INS.plate_path if INS and hasattr(INS, "plate_path") else (lambda p: {"ok": False, "error": "غير متاح"})
    bus.post = {
        "/api/decision": lambda d, ip: {"ok": bool(d.get("action") in ("confirm", "ack", "dismiss") and str(d.get("id", "")).isdigit() and decide(int(d["id"]), d["action"], ip))},
        "/api/retry_dispatch": lambda d, ip: retry_dispatch(int(d["id"]), ip) if str(d.get("id", "")).isdigit() else {"ok": False, "error": "معرّف غير صالح"},
        # P1-H: /api/archive_evidence ignores any user-supplied retention_days and strictly uses configured retention (>= 7 days)
        "/api/archive_evidence": lambda d, ip: {"ok": True, **archive_old_evidence(retention_days=None, who=f"api:{ip}", _allow_test_override=False)},
        "/api/insights/train": ins_act(lambda: INS.train(), "train"),
        "/api/insights/seed": ins_act(lambda: INS.seed_demo(), "seed demo history"),
        "/api/insights/clear": ins_act(lambda: INS.clear_demo(), "clear demo history"),
        "/api/vehicle": R.save_vehicle,
        "/api/vehicle/delete": lambda d, ip: R.delete("vehicles", d.get("key", ""), ip),
        "/api/person": R.save_person,
        "/api/person/delete": lambda d, ip: R.delete("persons", d.get("key", ""), ip),
        "/api/enroll": enroll_api
    }


DEFAULTS = {
    "source": "0", "cam": "CAM1", "host": "127.0.0.1", "allow_lan": False, "port": 8000,
    "trucks_only": False, "truck_curfew": "", "face_score": 0.45,
    "evidence_retention_days": 30, "open_browser": True, "first_run_done": False, "dashboard_token": "",
    "telegram_token": "", "telegram_chat_id": "", "telegram_patrol_chat_id": "", "camera_links": {}
}


def _load_secrets_file():
    """Load secrets safely, enforcing POSIX modes or restricted Windows ACLs (P1-D)."""
    if not os.path.lexists(_SECRETS_FILE):
        return {}
    if os.path.islink(_SECRETS_FILE):
        logger.error("Security error: %s is a symbolic link; refusing to load secrets", _SECRETS_FILE)
        return {}
    if os.name == "nt":
        try:
            R._set_windows_private_acl(os.getcwd(), is_dir=True)
            R._set_windows_private_acl(_SECRETS_FILE, is_dir=False)
        except OSError as e:
            logger.error("Security error: cannot protect Windows secrets ACL: %s", redact_url(e))
            return {}
    if os.name == "posix":
        try:
            st_mode = stat.S_IMODE(os.stat(_SECRETS_FILE).st_mode)
            if (st_mode & 0o077) != 0:
                os.chmod(_SECRETS_FILE, 0o600)
        except OSError:
            pass
    try:
        with open(_SECRETS_FILE, encoding="utf-8") as sf:
            data = json.load(sf)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.error("Corrupt or unreadable secrets file %s: %s", _SECRETS_FILE, redact_url(e))
        return {}


def _save_secrets_file(sec_dict):
    """Atomically write .mersad_secrets.json with 0600 permissions from birth (P1-D).
    Never leaves a partial or world-readable file on interruption."""
    payload = json.dumps(sec_dict, indent=2, ensure_ascii=False).encode("utf-8")
    R.atomic_write_secret_bytes(_SECRETS_FILE, payload)


def save_cfg(cfg):
    """Save configuration to mersad_config.json safely (P1-G, P1-D):
    - Never writes telegram_token in plaintext into mersad_config.json.
    - If a file-sourced token exists (and didn't come from preexisting OS env), migrates/preserves it in .mersad_secrets.json (0600).
    - Redacts any RTSP/HTTP passwords before writing source to mersad_config.json if stored in secrets."""
    safe_cfg = {k: v for k, v in cfg.items() if not str(k).startswith("_")}
    sec = _load_secrets_file()
    tok_val = str(safe_cfg.get("telegram_token") or "").strip()
    env_tok = _PREEXISTING_ENV.get("TELEGRAM_TOKEN", "")
    if tok_val and tok_val != env_tok:
        sec["telegram_token"] = tok_val
        _save_secrets_file(sec)
    safe_cfg["telegram_token"] = ""

    src_val = str(safe_cfg.get("source") or "")
    if re.search(r"(?:rtsp|rtsps|http|https)://[^:/\s]+:[^@/\s]+@", src_val, flags=re.IGNORECASE):
        sec["source_with_credentials"] = src_val
        _save_secrets_file(sec)
        safe_cfg["source"] = redact_url(src_val)

    tmp_cfg = f".mersad_config.json.tmp.{os.getpid()}"
    try:
        with open(tmp_cfg, "w", encoding="utf-8") as cf:
            json.dump(safe_cfg, cf, indent=2, ensure_ascii=False)
            cf.flush()
            os.fsync(cf.fileno())
        os.replace(tmp_cfg, "mersad_config.json")
    finally:
        if os.path.exists(tmp_cfg):
            try: os.remove(tmp_cfg)
            except OSError: pass


def load_cfg():
    """Load mersad_config.json and .mersad_secrets.json while tracking the origin of each credential (P1-G, P1-D).
    Never loses a file-configured token when save_cfg() is called, and never overwrites preexisting OS env vars."""
    cfg = dict(DEFAULTS)
    sec = _load_secrets_file()
    file_had_token = False
    file_tok_val = ""
    try:
        if os.path.exists("mersad_config.json"):
            with open("mersad_config.json", encoding="utf-8") as cf:
                loaded = json.load(cf)
                if loaded.get("telegram_token"):
                    file_had_token = True
                    file_tok_val = str(loaded["telegram_token"]).strip()
                cfg.update(loaded)
        else:
            save_cfg(DEFAULTS)
    except Exception as e:
        logger.warning("Config problem (using defaults): %s", redact_url(e))
        print("Config problem (using defaults):", redact_url(e))

    if file_had_token:
        warn_msg = (
            "WARNING: Telegram token found in plaintext in mersad_config.json. "
            "Migrating token to restricted '.mersad_secrets.json' (mode 0600) and clearing plaintext from mersad_config.json."
        )
        logger.warning(warn_msg)
        print(warn_msg)
        sec["telegram_token"] = file_tok_val
        _save_secrets_file(sec)
        cfg["telegram_token"] = ""
        save_cfg(cfg)

    # Restore credentials from .mersad_secrets.json if not overridden
    if sec.get("source_with_credentials") and "***" in str(cfg.get("source", "")):
        cfg["source"] = sec["source_with_credentials"]

    eff_token = _PREEXISTING_ENV.get("TELEGRAM_TOKEN") or sec.get("telegram_token") or cfg.get("telegram_token") or ""
    if eff_token:
        os.environ["TELEGRAM_TOKEN"] = str(eff_token)
    for k, env in (("telegram_chat_id", "TELEGRAM_CHAT_ID"), ("telegram_patrol_chat_id", "TELEGRAM_PATROL_CHAT_ID")):
        val = _PREEXISTING_ENV.get(env) or cfg.get(k) or sec.get(k) or ""
        if val:
            os.environ[env] = str(val)

    if cfg.get("allow_lan") and cfg.get("host") == "127.0.0.1":
        cfg["host"] = "0.0.0.0"
    if INS and cfg.get("camera_links"):
        INS.configure_topology(cfg["camera_links"])
    return cfg


def _make_offline_frame(cam_name, status_str="RECONNECTING"):
    """Generate an explicit status frame when a camera is offline/reconnecting so stale frames are never shown as live (P0-D, P1-C)."""
    f = np.full((360, 640, 3), 24, dtype=np.uint8)
    bar_color = (0, 0, 150) if status_str.upper() == "OFFLINE" else (0, 110, 180)
    cv2.rectangle(f, (0, 0), (640, 50), bar_color, -1)
    cv2.putText(f, f"{cam_name}: CAMERA {status_str.upper()}", (20, 34), FONT, 0.8, (255, 255, 255), 2)
    cv2.putText(f, "Stream interrupted - attempting automatic reconnection...", (20, 180), FONT, 0.6, (180, 190, 210), 1)
    cv2.putText(f, time.strftime("%Y-%m-%d %H:%M:%S"), (20, 320), FONT, 0.55, (120, 130, 150), 1)
    return cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 70])[1].tobytes()


def _compute_reconnect_backoff(fail_count):
    """Bounded exponential backoff for camera reconnection (P1-C):
    Increases exponentially up to MAX_RECONNECT_ATTEMPTS, then continues retrying at a bounded ceiling (RECONNECT_MAX_SEC)
    without ever permanently abandoning the camera."""
    fc = max(1, int(fail_count or 1))
    exp_power = min(fc - 1, max(1, MAX_RECONNECT_ATTEMPTS))
    raw_backoff = RECONNECT_BASE_SEC * (2 ** exp_power)
    return min(float(RECONNECT_MAX_SEC), float(raw_backoff))


def _camera_reader_worker(st, stop_ev):
    """Dedicated per-camera reader thread (P1-C):
    - Isolates blocking VideoCapture() open and .read() calls so a slow or hung RTSP stream never stalls other cameras.
    - Continuously attempts reconnection with bounded exponential backoff until stop_ev is set or finite test EOF is reached."""
    src_spec = st["src"]
    while not stop_ev.is_set() and not STOP_MAIN_EVENT.is_set():
        with st["lock"]:
            if st["eof"]:
                break
            cap_obj = st["cap"]
            next_rc = st["next_reconnect_ts"]

        if cap_obj is None:
            now_w = time.time()
            if now_w < next_rc:
                time.sleep(min(0.01, max(0.002, next_rc - now_w)))
                continue
            new_cap = None
            try:
                new_cap = _open_camera_capture(src_spec)
                is_op = bool(new_cap and new_cap.isOpened())
                ok_re, frame_re = (new_cap.read() if is_op else (False, None))
            except Exception as e:
                logger.debug("Camera %s reconnect exception: %s", st["cam"], redact_url(e))
                ok_re, frame_re = False, None

            if ok_re and frame_re is not None and getattr(frame_re, "size", 0) > 0:
                if stop_ev.is_set() or STOP_MAIN_EVENT.is_set():
                    try:
                        if new_cap is not None:
                            new_cap.release()
                    except Exception:
                        pass
                    break
                with st["lock"]:
                    st["cap"] = new_cap
                    st["latest_frame"] = frame_re
                    st["latest_frame_seq"] += 1
                    st["last_frame_ts"] = time.time()
                    st["read_failed"] = False
                    st["fail_count"] = 0
                    st["just_reconnected"] = True
            else:
                is_eof = bool(new_cap is not None and getattr(new_cap, "eof", False))
                try:
                    if new_cap is not None:
                        new_cap.release()
                except Exception:
                    pass
                with st["lock"]:
                    if is_eof:
                        st["eof"] = True
                        break
                    st["fail_count"] += 1
                    st["next_reconnect_ts"] = time.time() + _compute_reconnect_backoff(st["fail_count"])
                    st["read_failed"] = True
            continue

        # Pace fast in-memory sources so main loop can process each frame without skipping, while never blocking slow sources
        wait_start = time.time()
        while not stop_ev.is_set() and not STOP_MAIN_EVENT.is_set():
            with st["lock"]:
                unconsumed = st["latest_frame_seq"] > st["last_processed_seq"]
            if not unconsumed or (time.time() - wait_start) >= 0.04:
                break
            time.sleep(0.002)

        try:
            ok, frame = cap_obj.read()
        except Exception as e:
            logger.debug("Camera %s read exception: %s", st["cam"], redact_url(e))
            ok, frame = False, None

        if ok and frame is not None and getattr(frame, "size", 0) > 0:
            with st["lock"]:
                st["latest_frame"] = frame
                st["latest_frame_seq"] += 1
                st["last_frame_ts"] = time.time()
                st["read_failed"] = False
        else:
            is_eof = bool(getattr(cap_obj, "eof", False))
            try:
                cap_obj.release()
            except Exception:
                pass
            now_fail = time.time()
            with st["lock"]:
                st["cap"] = None
                st["read_failed"] = True
                if is_eof:
                    st["eof"] = True
                    break
                if st["status"] == "online":
                    st["disconnected_since"] = now_fail
                    st["fail_count"] = 1
                    st["next_reconnect_ts"] = now_fail + _compute_reconnect_backoff(1)
                else:
                    st["fail_count"] += 1
                    st["next_reconnect_ts"] = now_fail + _compute_reconnect_backoff(st["fail_count"])


def main():
    global SESSION_ID, PROCESS_OWNER_ID
    STOP_MAIN_EVENT.clear()
    cfg = load_cfg()
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", action="append", help="Camera source(s); can be passed multiple times or comma-separated")
    ap.add_argument("--cam", default=cfg["cam"], help="Camera ID(s); comma-separated when using multiple sources")
    ap.add_argument("--host", default=cfg.get("host", "127.0.0.1"), help="Bind address (default 127.0.0.1; use 0.0.0.0 for LAN)")
    ap.add_argument("--plate-model", help="optional YOLO plate detector .pt")
    ap.add_argument("--trucks-only", action="store_true", default=cfg["trucks_only"])
    ap.add_argument("--no-vehicles", action="store_true")
    ap.add_argument("--truck-curfew", default=cfg["truck_curfew"], help="restricted hours for trucks, e.g. 22-5")
    ap.add_argument("--port", type=int, default=cfg["port"])
    ap.add_argument("--token")
    ap.add_argument("--face-score", type=float, default=cfg["face_score"], help="min cosine similarity to raise a face alert")
    ap.add_argument("--retention-days", type=float, default=cfg.get("evidence_retention_days", 30))
    ap.add_argument("--no-window", action="store_true")
    ap.add_argument("--no-telegram-listener", action="store_true", help="Do not start getUpdates polling in this process")
    a = ap.parse_args()

    sources_raw = a.source if a.source else [str(cfg["source"])]
    sources = [s.strip() for part in sources_raw for s in str(part).split(",") if s.strip()]
    cams = [c.strip() for c in str(a.cam).split(",") if c.strip()] or ["CAM1"]
    while len(cams) < len(sources):
        cams.append(f"CAM{len(cams) + 1}")

    # P1-G: Only prompt interactively on the VERY FIRST run (not after unattended reboot)
    if len(sys.argv) == 1 and sys.stdin and sys.stdin.isatty() and not cfg.get("first_run_done"):
        s = input(f"Camera source [{redact_url(sources[0])}]  (0 = laptop webcam | http://PHONE_IP:8080/video | rtsp://...): ").strip()
        if s:
            sources = [x.strip() for x in s.split(",") if x.strip()]
            cfg["source"] = s
        lan_q = input(f"هل تسمح للجوالات على نفس الواي فاي بفتح اللوحة؟ Allow phones on same Wi-Fi? (y/n) [{'y' if cfg.get('allow_lan') else 'n'}]: ").strip().lower()
        if lan_q in ("y", "yes", "نعم"):
            cfg["allow_lan"] = True
            a.host = cfg["host"] = "0.0.0.0"
        elif lan_q in ("n", "no", "لا"):
            cfg["allow_lan"] = False
            a.host = cfg["host"] = "127.0.0.1"
        cfg["first_run_done"] = True
        save_cfg(cfg)

    if len(sources) > 1:
        SESSION_ID = "multi:" + uuid.uuid4().hex[:8]
    else:
        SESSION_ID = "sess-" + uuid.uuid4().hex[:8]
    PROCESS_OWNER_ID = f"pid:{os.getpid()}:{SESSION_ID}"

    if a.retention_days and a.retention_days >= MIN_RETENTION_DAYS:
        archive_old_evidence(a.retention_days, who="startup")

    curfew = tuple(map(int, a.truck_curfew.split("-"))) if a.truck_curfew else None
    if getattr(sys, "frozen", False):
        models_ok, model_checks = verify_runtime_model_assets()
        if not models_ok:
            issues = "; ".join(f"{x['model']}: {x['reason']}" for x in model_checks if not x["ok"])
            raise RuntimeError(
                "Bundled AI model verification failed. Runtime downloads are disabled for the EXE. "
                "Rebuild or restore the complete dist\\MERSAD_AI\\models directory while online. " + issues
            )
    else:
        fetch_models()
    import easyocr
    easyocr_dir = resolve_resource_path(os.path.join("models", "easyocr"))
    reader = create_offline_easyocr_reader(easyocr, easyocr_dir)
    yolo = vyolo = None
    try:
        from ultralytics import YOLO
        if a.plate_model:
            yolo = YOLO(a.plate_model)
        if not a.no_vehicles:
            yolo_p = resolve_resource_path(os.path.join("models", "yolov8n.pt"))
            vyolo = YOLO(yolo_p if os.path.exists(yolo_p) else "yolov8n.pt")
    except Exception as e:
        logger.warning("Vehicle/truck detection off: %s", e)
        print("Vehicle/truck detection off:", e)
    trucks_only = a.trucks_only and vyolo is not None
    yunet_p = resolve_resource_path(os.path.join("models", "yunet.onnx"))
    sface_p = resolve_resource_path(os.path.join("models", "sface.onnx"))
    det = cv2.FaceDetectorYN.create(yunet_p, "", (320, 320), 0.8)
    rec = cv2.FaceRecognizerSF.create(sface_p, "")
    if a.token:
        bus.token = a.token
    elif cfg.get("dashboard_token"):
        bus.token = str(cfg["dashboard_token"])
    FACE_ALERT[0] = a.face_score
    if INS:
        threading.Thread(target=INS.train, daemon=True).start()
    wire()
    _sync_alerts_from_db(reset_stuck_in_flight=True)
    stop_ev = threading.Event()
    threading.Thread(target=_dispatch_retry_loop, args=(stop_ev,), daemon=True).start()
    if not a.no_telegram_listener and start_listener(tg_press, stop_event=stop_ev):
        print("Telegram buttons active: decisions can be made from the phone.")
    refresh_known()
    srv = start_server(a.port, host=a.host)
    if cfg.get("open_browser") and not a.no_window:
        webbrowser.open(f"http://127.0.0.1:{a.port}/?k={bus.token}")
    if not (os.getenv("TELEGRAM_TOKEN") and os.getenv("TELEGRAM_CHAT_ID")):
        print("Telegram alerts off (set TELEGRAM_TOKEN and TELEGRAM_CHAT_ID to enable).")

    # P0-D & P1-C: Independent per-camera state, continuous reconnection, & non-blocking reader threads
    cam_states = {}
    reader_threads = []
    now_init = time.time()
    for src_item, cam_name in zip(sources, cams):
        # Do not open cameras synchronously here: RTSP/HTTP open can block for
        # seconds. Each independent reader thread owns its open/read/reconnect loop.
        cap_obj = None
        is_open = False
        is_eof = False
        red_s = redact_url(src_item)
        logger.info("Camera reader scheduled for asynchronous connection: %s (%s)", red_s, cam_name)

        init_status = "reconnecting"
        st = {
            "cam": cam_name,
            "src": src_item,
            "lock": threading.Lock(),
            "cap": cap_obj,
            "status": init_status,
            "n": 0,
            "det_runs": 0,
            "votes": {},
            "tracks": {},
            "last_seen": {},
            "last_plate": None,
            "boxes": [],
            "vboxes": [],
            "fail_count": 0,
            "consec_errors": 0,
            "disconnected_since": now_init,
            "next_reconnect_ts": now_init,
            "offline_alert_sent": False,
            "fps": 0.0,
            "reconnect_count": 0,
            "fps_t": now_init,
            "fps_n": 0,
            "latest_frame": None,
            "latest_frame_seq": 0,
            "last_processed_seq": 0,
            "last_frame_ts": 0.0,
            "read_failed": True,
            "just_reconnected": False,
            "ever_online": False,
            "logged_session_start": False,
            "eof": is_eof
        }
        if not is_open:
            bus.set_frame(_make_offline_frame(cam_name, "reconnecting"), cam=cam_name, status="reconnecting")
            bus.publish({"type": "camera_status", "cam": cam_name, "status": "reconnecting"})
        cam_states[cam_name] = st
        if CAMERA_HISTORY:
            CAMERA_HISTORY.record_status(cam_name, st["status"], reason="startup", force=True)

    STATUS["cam"] = ",".join(cam_states.keys())
    STATUS["cameras"] = {
        k: {"status": v["status"], "fps": 0.0, "frames": 0, "detections": 0, "errors": 0, "fail_count": v["fail_count"], "reconnect_count": v.get("reconnect_count", 0)}
        for k, v in cam_states.items()
    }
    for cam_name, st in cam_states.items():
        bus.set_frame(_make_offline_frame(cam_name, "reconnecting"), cam=cam_name, status="reconnecting")
        bus.publish({"type": "camera_status", "cam": cam_name, "status": "reconnecting"})
        rt = threading.Thread(target=_camera_reader_worker, args=(st, stop_ev), daemon=True, name=f"cam_reader_{cam_name}")
        rt.start()
        reader_threads.append(rt)

    print("Faces are matched ONLY against volunteers who gave consent. Bystander faces in evidence photos are blurred.")

    t_faces = 0.0
    gui_enabled = not a.no_window
    try:
        while not STOP_MAIN_EVENT.is_set():
            any_alive = False
            processed_any_frame = False
            now_loop = time.time()
            for cam_name, st in cam_states.items():
                with st["lock"]:
                    just_rec = st["just_reconnected"]
                    if just_rec:
                        st["just_reconnected"] = False
                    has_new_frame = st["latest_frame_seq"] > st["last_processed_seq"]
                    frame = st["latest_frame"] if has_new_frame else None
                    if has_new_frame:
                        st["last_processed_seq"] = st["latest_frame_seq"]
                    is_eof = st["eof"]
                    read_failed = st["read_failed"]
                    last_f_ts = st["last_frame_ts"]
                    fail_cnt = st["fail_count"]

                if just_rec:
                    # The first successful connection is not counted as a recovery.
                    # Subsequent successful connections after the camera was online are.
                    if st.get("ever_online", False):
                        st["reconnect_count"] = int(st.get("reconnect_count", 0)) + 1
                    st["ever_online"] = True
                    if not st["logged_session_start"]:
                        st["logged_session_start"] = True
                        log("session start", cam_name)
                    st["status"] = "online"
                    if CAMERA_HISTORY:
                        CAMERA_HISTORY.record_status(cam_name, "online", reason="camera_reconnected")
                    st["offline_alert_sent"] = False
                    st["disconnected_since"] = 0.0
                    log("camera reconnected", cam_name)
                    bus.publish({"type": "camera_status", "cam": cam_name, "status": "online"})

                if not has_new_frame or frame is None or getattr(frame, "size", 0) == 0:
                    stalled = (last_f_ts > 0 and (now_loop - last_f_ts) >= CAMERA_STALL_SEC)
                    if read_failed or stalled or st["status"] != "online":
                        if st["status"] == "online":
                            st["disconnected_since"] = now_loop
                            st["status"] = "reconnecting"
                            if CAMERA_HISTORY:
                                CAMERA_HISTORY.record_status(cam_name, "reconnecting", reason="stream_stalled" if stalled else "read_failed")
                            bus.set_frame(_make_offline_frame(cam_name, "reconnecting"), cam=cam_name, status="reconnecting")
                            bus.publish({"type": "camera_status", "cam": cam_name, "status": "reconnecting"})
                        elif st["disconnected_since"] > 0 and (now_loop - st["disconnected_since"]) >= OFFLINE_ALERT_SEC and not st["offline_alert_sent"]:
                            st["status"] = "offline"
                            if CAMERA_HISTORY:
                                CAMERA_HISTORY.record_status(cam_name, "offline", reason="offline_timeout")
                            st["offline_alert_sent"] = True
                            bus.set_frame(_make_offline_frame(cam_name, "offline"), cam=cam_name, status="offline")
                            bus.publish({"type": "camera_status", "cam": cam_name, "status": "offline"})
                            log("camera offline", cam_name)
                            send_alert(
                                f"⚠️ انقطاع بث الكاميرا {cam_name} لأكثر من {int(OFFLINE_ALERT_SEC)} ثوانٍ.",
                                chat_env="TELEGRAM_CHAT_ID",
                                sync=False,
                                idempotency_key=f"cam_off:{cam_name}:{int(st['disconnected_since'])}"
                            )
                        elif st["status"] in ("reconnecting", "offline"):
                            # Keep status frame fresh so old camera frames are never mistaken for a live feed (P1-C item 6)
                            bus.set_frame(_make_offline_frame(cam_name, st["status"]), cam=cam_name, status=st["status"])

                    STATUS["cameras"][cam_name] = {
                        "status": st["status"], "fps": st["fps"] if st["status"] == "online" else 0.0,
                        "frames": st["n"], "detections": st["det_runs"], "errors": st["consec_errors"],
                        "fail_count": fail_cnt, "reconnect_count": st.get("reconnect_count", 0)
                    }
                    if not is_eof:
                        any_alive = True
                    continue

                any_alive = True
                processed_any_frame = True
                st["status"] = "online"
                if CAMERA_HISTORY:
                    CAMERA_HISTORY.record_status(cam_name, "online", reason="frame_received")
                st["n"] += 1
                st["fps_n"] += 1
                if now_loop - st["fps_t"] >= 2.0:
                    st["fps"] = round(st["fps_n"] / (now_loop - st["fps_t"]), 1)
                    st["fps_t"], st["fps_n"] = now_loop, 0
                    STATUS["fps"] = st["fps"]

                # P0-D: Per-frame exception guard with consecutive error counter so a single frame error never kills the program
                try:
                    H, W = frame.shape[:2]
                    view = frame.copy()
                    det.setInputSize((W, H))
                    _, fs = det.detect(frame)
                    fs = fs if fs is not None else []
                    main_face, names, unmatched_face_boxes = None, [], []
                    face_entries = []
                    for f in fs:
                        x, y, bw, bh = map(int, f[:4])
                        raw_emb = rec.feature(rec.alignCrop(frame, f))
                        m_res = match_face_embedding(raw_emb, rec=rec)
                        name, sc, wl = m_res[0], m_res[1], m_res[2]
                        pid_m = getattr(m_res, "person_id", 0)
                        ref_m = getattr(m_res, "ref", "")
                        names.append(name)
                        if name == "unenrolled":
                            unmatched_face_boxes.append((x, y, bw, bh))
                        face_entries.append((x, y, bw, bh, name, sc, wl, raw_emb, pid_m, ref_m))
                        if main_face is None or bw * bh > main_face[1]:
                            main_face = (raw_emb, bw * bh)

                    for (x, y, bw, bh, name, sc, wl, _, pid_m, ref_m) in face_entries:
                        face_step(name, sc, wl, frame, cam_name, frame_idx=st["n"],
                                  unmatched_faces=unmatched_face_boxes, person_id=pid_m, ref=ref_m)
                        cv2.rectangle(view, (x, y), (x + bw, y + bh), (255, 160, 0), 2)
                        cv2.putText(view, f"{name} {sc:.2f}" if sc else name, (x, max(15, y - 6)), FONT, .55, (255, 160, 0), 2)

                    enroll_step(main_face[0] if main_face and st["n"] % 4 == 0 else None)
                    if now_loop - t_faces > 1.0:
                        t_faces = now_loop
                        bus.publish({"type": "faces", "n": len(fs), "names": sorted({x for x in names if x != "unenrolled"})})

                    # P0-D: Use per-camera frame counter st["n"] % 6 == 0 so every camera gets equal detection scheduling!
                    if st["n"] % 6 == 0:
                        st["det_runs"] += 1
                        st["boxes"], st["vboxes"] = [], detect_vehicles(frame, vyolo)
                        now_f = time.time()
                        for (vx, vy, vw, vh, vc) in (st["vboxes"] or [(0, 0, W, H, "unknown")]):
                            if trucks_only and vc != "truck":
                                continue
                            oy = vy + int(vh * .35) if vc != "unknown" else 0
                            sub = frame[oy:vy + vh, vx:vx + vw]
                            if sub.size == 0:
                                continue
                            for (x, y, bw, bh) in find_plates(sub, yolo):
                                x, y = x + vx, y + oy
                                d, c = read_plate(reader, frame[y:y + bh, x:x + bw])
                                st["boxes"].append((x, y, bw, bh, d))
                                if not d:
                                    continue
                                confirmed = confirm_plate_read(d, c, (x, y, bw, bh), now_f, st["votes"], st["tracks"], st["last_seen"])
                                if confirmed:
                                    cm, direction = confirmed[0], confirmed[1]
                                    win_plate = getattr(confirmed, "plate", d) or d
                                    l_conf = getattr(confirmed, "letters_confirmed", True)
                                    st["last_plate"] = win_plate
                                    msg, v = register(win_plate, cm, cam_name, vc, curfew, direction, raw_text=d,
                                                      session_id=SESSION_ID, letters_confirmed=l_conf)
                                    base, detail = vinfo(v)
                                    bus.publish({"type": "sighting", "plate": win_plate, "cam": cam_name, "vclass": vc, "direction": direction,
                                                 "ts": time.strftime("%H:%M:%S"), "conf": round(cm, 2),
                                                 "model": v["model"] if v else "", "status": v["status"] if v else "",
                                                 "match_note": v.get("match_note", "") if v else ""})
                                    if msg:
                                        if msg.startswith(("ANOMALY", "ROUTE", "POSSIBLE")):
                                            detail = " · ".join(x for x in (detail, WHY.get(win_plate, "")) if x)
                                        raise_alert(msg, win_plate, cam_name, frame, detail=detail,
                                                    extra=f"\nنوع المركبة: {vc}\nالاتجاه/المسار: {direction}"
                                                    + (f"\nالسيارة: {base}" if base else "")
                                                    + (f"\nالسبب: {WHY[win_plate]}" if msg.startswith(("ANOMALY", "ROUTE", "POSSIBLE")) and win_plate in WHY else ""),
                                                    unmatched_faces=unmatched_face_boxes)
                                    if INS and INS.M["since"] >= 100:
                                        INS.M["since"] = 0
                                        threading.Thread(target=INS.train, daemon=True).start()

                    for (x, y, bw, bh, vc) in st["vboxes"]:
                        cv2.rectangle(view, (x, y), (x + bw, y + bh), (0, 200, 255), 2)
                        cv2.putText(view, vc.upper(), (x, max(15, y - 6)), FONT, .6, (0, 200, 255), 2)
                    for (x, y, bw, bh, d) in st["boxes"]:
                        cv2.rectangle(view, (x, y), (x + bw, y + bh), (0, 220, 0), 2)
                        if d:
                            cv2.putText(view, d, (x, max(15, y - 6)), FONT, .7, (0, 220, 0), 2)
                    if bus.alerts:
                        cv2.rectangle(view, (0, 0), (W, 60), (0, 0, 180), -1)
                        cv2.putText(view, f"ALERT: {bus.alerts[0]['msg']}  [C]onfirm [X]dismiss", (10, 38), FONT, .7, (255, 255, 255), 2)
                    if st["n"] % 2 == 0:
                        sm = cv2.resize(view, (640, int(640 * H / W)))
                        jpg_bytes = cv2.imencode(".jpg", sm, [cv2.IMWRITE_JPEG_QUALITY, 70])[1].tobytes()
                        bus.set_frame(jpg_bytes, cam=cam_name, status="online")
                    st["consec_errors"] = 0
                except Exception as frame_err:
                    st["consec_errors"] += 1
                    logger.error("Error processing frame #%d on camera %s (consec=%d): %s",
                                 st["n"], cam_name, st["consec_errors"], redact_url(frame_err), exc_info=True)

                STATUS["cameras"][cam_name] = {
                    "status": st["status"], "fps": st["fps"], "frames": st["n"],
                    "detections": st["det_runs"], "errors": st["consec_errors"], "fail_count": fail_cnt,
                    "reconnect_count": st.get("reconnect_count", 0)
                }

                k = 255
                if gui_enabled:
                    try:
                        cv2.imshow(f"MERSAD AI ({cam_name})", view)
                        k = cv2.waitKey(1) & 0xFF
                    except cv2.error as gui_err:
                        logger.warning("OpenCV GUI (imshow) unavailable in headless build; continuing in headless dashboard mode: %s", gui_err)
                        gui_enabled = False
                if k == ord("q"):
                    any_alive = False
                    break
                if k in (ord("c"), ord("x")) and bus.alerts:
                    decide(bus.alerts[0]["id"], "confirm" if k == ord("c") else "dismiss", "console")
                if k == ord("p") and st["last_plate"]:
                    R.save_vehicle({**(R.lookup_vehicle(st["last_plate"]) or {"plate": st["last_plate"]}), "status": "watch"}, "console")
                if k == ord("e"):
                    nm = input("Volunteer name: ").strip()
                    ref_in = input("Reference ID (optional, to distinguish homonymous names): ").strip()
                    if nm and input("Did this person give explicit consent? (y/n) ").lower() == "y":
                        w = input("Add to demo watchlist? (y/n) ").lower() == "y"
                        res_p = R.save_person({"name": nm, "ref": ref_in, "consent": True, "status": "watch" if w else "normal"}, "console")
                        req_enroll(nm, w, "console", ref=ref_in, person_id=res_p.get("id"))
            if not any_alive:
                break
            if not processed_any_frame:
                time.sleep(0.005)
    except KeyboardInterrupt:
        pass
    finally:
        stop_ev.set()
        try:
            _notify_mod.wait_listener_stopped(timeout=3.0)
        except Exception:
            pass
        # Release captures before joining so a backend blocked in read() gets a
        # chance to wake immediately. Network opens/reads are also bounded above.
        for st in cam_states.values():
            with st["lock"]:
                cap_to_rel = st["cap"]
                st["cap"] = None
            try:
                if cap_to_rel is not None:
                    cap_to_rel.release()
            except Exception:
                pass
        join_timeout = max(1.0, NETWORK_CAMERA_READ_TIMEOUT_MS / 1000.0 + 0.5)
        for rt in reader_threads:
            try:
                rt.join(timeout=join_timeout)
            except Exception:
                pass
        for cam_name, st in cam_states.items():
            if st.get("logged_session_start"):
                log("session end", cam_name)
        if gui_enabled:
            try: cv2.destroyAllWindows()
            except Exception: pass
        try: srv.shutdown()
        except Exception: pass


if __name__ == "__main__":
    import multiprocessing; multiprocessing.freeze_support()
    try:
        if "--verify-models" in sys.argv:
            model_ok, model_report = verify_runtime_model_assets()
            for item in model_report:
                state = "PASS" if item.get("ok") else "FAIL"
                print(f"[{state}] {item.get('model')}: {item.get('reason')}")
            if not model_ok:
                print("Bundled model verification failed. Restore/download verified weights and rebuild the complete MERSAD_AI distribution.", file=sys.stderr)
                raise SystemExit(2)
            print("All bundled AI models are present and valid.")
        elif "--verify" in sys.argv:
            print(verify())
        else:
            main()
    except Exception:
        import traceback; traceback.print_exc()
        if getattr(sys, "frozen", False):
            input("\nERROR - press Enter to close...")
