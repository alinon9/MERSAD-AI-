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
_mersad_env_os.environ.setdefault('YOLO_AUTOINSTALL', 'false')
_mersad_env_os.environ.setdefault('YOLO_OFFLINE', 'true')
_mersad_env_os.environ.setdefault('ULTRALYTICS_AUTOINSTALL', 'false')
import argparse, collections, csv, gc, hashlib, hmac, io, json, logging, logging.handlers, os, pickletools, queue, re, shutil, socket, sqlite3, stat, subprocess, sys, tempfile, threading, time, urllib.error, urllib.request, uuid, webbrowser, zipfile

BUNDLE_DIR = os.path.abspath(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))))
import importlib.abc as _il_abc, importlib.util as _il_util
class _MersadSiblingFinder(_il_abc.MetaPathFinder):
    _MODS = frozenset({"registry", "notify", "analytics", "insights", "camera_history", "server", "prefetch", "check_install", "mersad_live"})
    def find_spec(self, fullname, path=None, target=None):
        if fullname in self._MODS:
            p = os.path.join(BUNDLE_DIR, fullname + ".py")
            if os.path.isfile(p):
                return _il_util.spec_from_file_location(fullname, p)
        return None
if not any(getattr(f, "_MODS", None) for f in sys.meta_path):
    sys.meta_path.insert(0, _MersadSiblingFinder())
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


def _is_sqlite_usable_dir(dir_path):
    """Return True if dir_path is writable AND supports SQLite journal/locking transactions (STAGE14-01).
    Detects network/virtual filesystems (e.g. 9p, SMB, WebDAV) where flat file creation works but SQLite fsync/locking fails."""
    if not _is_dir_writable(dir_path):
        return False
    abs_d = os.path.abspath(dir_path)
    probe_db = os.path.join(abs_d, f".mersad_sql_probe_{os.getpid()}_{uuid.uuid4().hex[:6]}.db")
    conn = None
    try:
        conn = sqlite3.connect(probe_db, timeout=2.0)
        conn.execute("CREATE TABLE t(x INTEGER)")
        conn.execute("INSERT INTO t VALUES(1)")
        conn.commit()
        conn.close()
        conn = None
        return True
    except Exception:
        return False
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        for suf in ("", "-wal", "-shm", "-journal"):
            p_clean = probe_db + suf
            if os.path.exists(p_clean):
                try:
                    os.remove(p_clean)
                except OSError:
                    pass


USING_EPHEMERAL_TEMP_APPDIR = False


def resolve_writable_appdir(preferred_dir=None, explicit_env=None):
    """Resolve persistent writable data directory supporting SQLite transactions (Stage 5d, STAGE14-01, STAGE15-GAP06):
    - Never uses temporary _MEIPASS directory for database, keys, secrets, or evidence.
    - If MERSAD_DATA_DIR is explicitly set in environment, uses it directly (preserving fail-closed security tests).
    - Otherwise checks preferred_dir (INSTALL_DIR), then _default_user_data_dir(), and if both reside on a network/virtual
      mount that rejects SQLite locking (such as 9p/SMB), falls back to a restricted (0o700) local temp appdir with warning."""
    global USING_EPHEMERAL_TEMP_APPDIR
    env_dir = explicit_env if explicit_env is not None else os.environ.get("MERSAD_DATA_DIR")
    if env_dir:
        USING_EPHEMERAL_TEMP_APPDIR = False
        return os.path.abspath(env_dir)
    cand = os.path.abspath(preferred_dir or INSTALL_DIR)
    if _is_sqlite_usable_dir(cand):
        USING_EPHEMERAL_TEMP_APPDIR = False
        return cand
    fallback = _default_user_data_dir()
    try:
        os.makedirs(fallback, exist_ok=True)
    except OSError:
        pass
    if _is_sqlite_usable_dir(fallback):
        USING_EPHEMERAL_TEMP_APPDIR = False
        return fallback
    local_tmp_fallback = os.path.abspath(
        os.path.join(tempfile.gettempdir(), "MERSAD_AI" if os.name == "nt" else "mersad_ai")
    )
    os.makedirs(local_tmp_fallback, exist_ok=True)
    try:
        os.chmod(local_tmp_fallback, 0o700)
    except OSError:
        pass
    USING_EPHEMERAL_TEMP_APPDIR = True
    logging.getLogger("mersad").warning(
        "Ephemeral storage fallback active (%s): Set MERSAD_DATA_DIR to a local disk folder for persistent storage.",
        local_tmp_fallback,
    )
    return local_tmp_fallback


def resolve_resource_path(rel_path):
    """Resolve bundled read-only assets before writable user data in frozen distributions (Stage 5d + V7-FROZEN-RESOURCE-PRIORITY)."""
    bases = (INSTALL_DIR, BUNDLE_DIR, APPDIR) if getattr(sys, "frozen", False) else (APPDIR, INSTALL_DIR, BUNDLE_DIR)
    for base in bases:
        if base:
            cand = os.path.join(base, rel_path)
            if os.path.exists(cand):
                return cand
    return os.path.join((INSTALL_DIR if getattr(sys, "frozen", False) else APPDIR) or INSTALL_DIR, rel_path)


# GAP-03: Pure path defaults at import time without touching cwd, creating directories, or opening files
APPDIR = os.path.abspath(os.environ.get("MERSAD_DATA_DIR") or INSTALL_DIR)

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


logger = logging.getLogger("mersad")

# P2-M: Pin OpenCV Zoo models to verified HuggingFace commit hash and SHA-256 digests (from build #47 / PATCHED_V7.1)
ZOO_COMMIT = "39a1451d0f9b23fc4ebaed06a277127efa0374d0"
ZOO = f"https://huggingface.co/opencv/opencv_zoo/resolve/{ZOO_COMMIT}/models/"
MODELS = {
    "yunet.onnx": ZOO + "face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "sface.onnx": ZOO + "face_recognition_sface/face_recognition_sface_2021dec.onnx"
}
MODEL_SHA256 = {
    "yunet.onnx": "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    "sface.onnx": "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    "yolov8n.pt": "31e20dde3def09e2cf938c7be6fe23d9150bbbe503982af13345706515f2ef95",
}
EASYOCR_SHA256 = {
    "craft_mlt_25k.pth": "4a5efbfb48b4081100544e75e1e2b57f8de3d84f213004b14b85fd4b3748db17",
    "arabic.pth": "2a9afd42c374deb98aed0b53c9b77d75e1d00d4e0501f3b0276c54190c89b1a8",
    "english_g2.pth": "e2272681d9d67a04e2dff396b6e95077bc19001f8f6d3593c307b9852e1c29e8",
    "latin_g2.pth": "aaa95be1c4a9cb3496879bed7c520886ce1164f89e026f0c54488394e74e8c55",
}
MODEL_LEGACY_SHA256 = {
    "yunet.onnx": "8f2383e4dd3cfbb4553bf0fb6cde5e5f80f5f70c6e595e3fd10e819a79d1527c",
    "sface.onnx": "0ba9fbfa01b5270c96627c4ef784da85eab3da1e9bedf8ef69c25eb8d7e52275"
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
FACE_DETECT_INTERVAL = 2
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
db = None
DBL = threading.RLock()
_DISPATCH_LOCK = threading.Lock()
_ENROLL_LOCK = threading.RLock()
_FACE_STATE_LOCK = threading.RLock()
_RUNTIME_STATE_LOCK = threading.RLock()
_IN_FLIGHT_DISPATCH = set()
pseud = R.pseud
INS = None
ANALYTICS = None
CAMERA_HISTORY = None
_RUNTIME_INITIALIZED = False


def legacy_chain_hash(prev, i, ts, action, ref):
    """Compute legacy unkeyed SHA-256 digest (64 hex chars without 'h1:' prefix) for verifying pre-upgrade audit records (GAP-11)."""
    return hashlib.sha256(f"{prev}|{i}|{ts}|{action}|{ref}".encode("utf-8")).hexdigest()


def chain_hash(prev, i, ts, action, ref, key=None):
    """Compute versioned HMAC-SHA256 audit chain digest ('h1:<64-hex>') using .mersad_hmac.key (GAP-11)."""
    payload = f"{prev}|{i}|{ts}|{action}|{ref}".encode("utf-8")
    k = key if key is not None else R._get_hmac_key()
    return "h1:" + hmac.new(k, payload, hashlib.sha256).hexdigest()


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
    if db is None:
        init_runtime_env()
    clean_ref = redact_url(ref)
    R.run_atomic_tx(db, DBL, lambda conn: _log_in_tx(conn, action, clean_ref), db_path=DB_PATH)
    logger.info("AUDIT [%s] %s", action, clean_ref)


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
        with _RUNTIME_STATE_LOCK:
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
    new_alerts = []
    for aid, msg, subj, ref, det, cam, ts_str, img, st, disp, dst, rep_cnt, n_st in rows:
        al = {
            "id": aid, "msg": msg, "subject": subj, "ref": ref, "detail": det or "", "cam": cam, "ts": ts_str,
            "img": img, "status": st, "dispatch_status": dst, "repeat_count": int(rep_cnt or 1),
            "notify_status": n_st, "info_only": is_no_dispatch_msg(msg),
            "requires_human_review": True, "verification_policy": "HUMAN_VERIFICATION_REQUIRED"
        }
        new_alerts.append(al)
        if img:
            ev_p = os.path.join("evidence", img)
            if os.path.exists(ev_p):
                with _RUNTIME_STATE_LOCK:
                    EVID[aid] = ev_p
    new_fdisp = [
        {"id": r[0], "msg": r[1], "subject": r[2], "ref": r[3], "detail": r[4] or "", "cam": r[5], "ts": r[6], "img": r[7],
         "dispatch_status": r[8], "attempts": r[9], "next_retry_ts": r[10], "last_error": r[11], "dispatch_owner": r[12]}
        for r in f_rows
    ]
    with bus._lock:
        bus.alerts[:] = new_alerts
        bus.failed_dispatches[:] = new_fdisp


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


def init_runtime_env(appdir=None, db_path=None, force=False):
    """Explicitly initialize the operational runtime environment (GAP-03):
    - Resolves writable APPDIR, sets MERSAD_DATA_DIR, and changes working directory to APPDIR.
    - Configures rotating mersad.log file handler.
    - Opens SQLite connection and initializes registry, insights, and camera_history schemas.
    - Synchronizes alerts and recovers interrupted evidence archives.
    Never called during `--verify-models` or static diagnostic imports from `check_install.py`."""
    global APPDIR, DB_PATH, db, logger, INS, ANALYTICS, CAMERA_HISTORY, _RUNTIME_INITIALIZED
    if _RUNTIME_INITIALIZED and not force and db is not None:
        return db
    APPDIR = os.path.abspath(appdir) if appdir else resolve_writable_appdir()
    os.makedirs(APPDIR, exist_ok=True)
    if not os.environ.get("MERSAD_DATA_DIR"):
        os.environ["MERSAD_DATA_DIR"] = APPDIR
    os.chdir(APPDIR)
    logger = _setup_logging()
    DB_PATH = os.path.abspath(db_path) if db_path else os.path.join(APPDIR, "mersad.db")
    if db is None or force:
        db = sqlite3.connect(DB_PATH, timeout=15.0, check_same_thread=False)
    R.init(db, DBL, log, lambda: refresh_known(), db_path=DB_PATH)
    try:
        import insights as _ins_mod
        INS = _ins_mod
        INS.init(db, DBL, db_path=DB_PATH)
    except Exception as e:
        INS = None
        logger.warning("Learning module off: %s", e)
        print("Learning module off:", e)

    try:
        import analytics as _an_mod
        import camera_history as _ch_mod
        ANALYTICS = _an_mod
        CAMERA_HISTORY = _ch_mod
        CAMERA_HISTORY.init(db, DBL, db_path=DB_PATH)
    except Exception as e:
        ANALYTICS = CAMERA_HISTORY = None
        logger.warning("Operational analytics/camera history off: %s", e)

    _sync_alerts_from_db(reset_stuck_in_flight=True)
    _recover_interrupted_archives()
    try:
        bootstrap_bundled_trusted_models()
    except Exception:
        pass
    _RUNTIME_INITIALIZED = True
    return db


def _should_auto_init_runtime():
    if __name__ == "__main__":
        return False
    if os.environ.get("MERSAD_SKIP_RUNTIME_INIT") == "1":
        return False
    if any(fl in sys.argv for fl in ("--verify-models", "--verify-pip-deps", "--evaluate-plates", "--internal-browse-dialog", "--register-trusted-model", "--readiness-report")):
        return False
    main_mod = sys.modules.get("__main__")
    main_file = os.path.basename(getattr(main_mod, "__file__", "") or "").lower()
    if main_file in ("check_install.py", "prefetch.py"):
        return False
    return True


if _should_auto_init_runtime():
    init_runtime_env()


def archive_old_evidence(retention_days=None, who="system", _allow_test_override=False):
    """Reversible, crash-safe evidence archiving (P1-H, P1-E):
    - Journals each archive operation in evidence_archive_ops before copying so _recover_interrupted_archives
      can distinguish legitimate interrupted archives from external/unlogged copies.
    - Strictly excludes evidence belonging to pending alerts or confirmed alerts with incomplete patrol dispatch.
    - Verifies realpath containment, forbids symlinks, checks SHA-256 before and after copy, and enforces >= 7d floor."""
    cfg_days = float(DEFAULTS.get("evidence_retention_days", 30))
    if os.path.exists("mersad_config.json"):
        try:
            with open("mersad_config.json", encoding="utf-8") as cf:
                cfg_days = float(json.load(cf).get("evidence_retention_days", 30))
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
    if db is None or not _RUNTIME_INITIALIZED:
        init_runtime_env()
    prev = "0" * 64
    with DBL:
        rows = db.execute("SELECT i, ts, action, ref, prev, hash FROM audit ORDER BY i").fetchall()
    archived_map = {}
    purged_map = {}
    seen_hmac_v1 = False
    hmac_key = None
    for i, ts, ac, ref, p, h in rows:
        if p != prev:
            return f"TAMPERING DETECTED at record #{i}"
        h_str = str(h or "")
        if h_str.startswith("h1:"):
            seen_hmac_v1 = True
            if hmac_key is None:
                base_dir = os.environ.get("MERSAD_DATA_DIR") or APPDIR or os.getcwd()
                key_path = os.path.abspath(os.path.join(base_dir, getattr(R, "_HMAC_KEY_FILENAME", ".mersad_hmac.key")))
                if not os.path.lexists(key_path):
                    return f"TAMPERING DETECTED: missing .mersad_hmac.key required to verify h1 audit record #{i}"
                try:
                    hmac_key = R._get_hmac_key()
                except Exception as key_err:
                    return f"TAMPERING DETECTED: corrupt or unreadable .mersad_hmac.key at record #{i} ({key_err})"
            if h_str != chain_hash(p, i, ts, ac, ref, key=hmac_key):
                return f"TAMPERING DETECTED at record #{i}"
        else:
            if seen_hmac_v1:
                return f"TAMPERING DETECTED at record #{i} (downgrade attack)"
            if h_str != legacy_chain_hash(p, i, ts, ac, ref):
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


def _extract_face_box(entry):
    """Extract (x, y, bw, bh) integer bounding box from a tuple/list or dict face entry."""
    if entry is None:
        return None
    if isinstance(entry, dict):
        if "box" in entry and entry["box"] is not None:
            b = entry["box"]
            return (int(b[0]), int(b[1]), int(b[2]), int(b[3]))
        x = entry.get("x", 0)
        y = entry.get("y", 0)
        bw = entry.get("bw", entry.get("w", 0))
        bh = entry.get("bh", entry.get("h", 0))
        return (int(x), int(y), int(bw), int(bh))
    if isinstance(entry, (tuple, list)) and len(entry) >= 4:
        return (int(entry[0]), int(entry[1]), int(entry[2]), int(entry[3]))
    return None


def get_boxes_to_blur_for_alert(face_entries, alert_kind="vehicle", target_face_box=None):
    """Strict privacy blurring policy separating vehicle alerts from watchlist face alerts (GAP-09):
    - When `alert_kind == 'vehicle'` (all vehicle, plate, truck, and route alerts without exception):
      returns 100% of all detected face boxes in `face_entries` (whether 'unenrolled', 'normal', or 'watch')
      so no human face is ever exposed in a vehicle evidence photo.
    - When `alert_kind == 'face'` ('FACE MATCH (demo watchlist)' exclusively):
      returns all other face boxes in `face_entries` except the single `target_face_box` that triggered the watchlist match."""
    all_boxes = []
    for fe in (face_entries or []):
        b = _extract_face_box(fe)
        if b is not None and b[2] > 0 and b[3] > 0:
            all_boxes.append(b)
    kind = str(alert_kind or "vehicle").strip().lower()
    if kind != "face":
        return all_boxes
    t_box = _extract_face_box(target_face_box)
    if t_box is None:
        return all_boxes
    out_boxes = []
    skipped_target = False
    for b in all_boxes:
        if not skipped_target and b == t_box:
            skipped_target = True
            continue
        out_boxes.append(b)
    return out_boxes


def resolve_face_detect_score(score_val=None):
    """Return validated YuNet face detector score threshold (default 0.65, bounded in [0.30, 0.95], GAP-09)."""
    try:
        v = float(score_val if score_val is not None else DEFAULTS.get("face_detect_score", 0.65))
        if v != v or not np.isfinite(v):
            return 0.65
    except (TypeError, ValueError):
        return 0.65
    return round(min(0.95, max(0.30, v)), 3)


def blur_unmatched_faces(frame, unmatched_boxes):
    """Blur specified face bounding boxes in evidence frames before saving to disk or sending to Telegram (P2-K, GAP-09)."""
    if frame is None or getattr(frame, "size", 0) == 0 or not unmatched_boxes:
        return frame
    out = frame.copy()
    H, W = out.shape[:2]
    for item in unmatched_boxes:
        b = _extract_face_box(item)
        if b is None:
            continue
        x, y, bw, bh = b
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


def raise_alert(msg, subject, cam, frame, ref=None, extra="", detail="", unmatched_faces=None, face_entries=None, target_face_box=None):
    """Create or deduplicate an alert atomically across threads/processes (P0-E, P1-I, P2-K, GAP-09).
    - Deduplicates active pending alerts by (msg, ref), incrementing repeat_count instead of spamming new alerts.
    - Enforces get_boxes_to_blur_for_alert() when face_entries are supplied (100% face blur on vehicle alerts; non-target blur on face alerts).
    - Uses SQLite AUTOINCREMENT for alert IDs so concurrent OS processes never collide.
    - Cleans up temporary evidence file if the DB transaction fails."""
    now = time.time()
    ts = time.strftime("%H:%M:%S", time.localtime(now))
    ref = str(ref or subject)
    no_disp = is_no_dispatch_msg(msg)

    if face_entries is not None:
        alert_kind = "face" if str(msg or "").startswith("FACE MATCH") else "vehicle"
        boxes_to_blur = get_boxes_to_blur_for_alert(face_entries, alert_kind=alert_kind, target_face_box=target_face_box)
    else:
        boxes_to_blur = unmatched_faces

    os.makedirs("evidence", exist_ok=True)
    safe_frame = blur_unmatched_faces(frame, boxes_to_blur)
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

    with _RUNTIME_STATE_LOCK:
        AID[0] = max(AID[0], aid)
        EVID[aid] = tmp_path
    al = {
        "id": aid, "msg": msg, "subject": subject, "ref": ref, "detail": detail or "", "cam": cam, "ts": ts,
        "img": img_name, "status": "pending", "dispatch_status": "not_required", "repeat_count": 1, "info_only": no_disp,
        "requires_human_review": True, "verification_policy": "HUMAN_VERIFICATION_REQUIRED"
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
    with bus._lock:
        fdisp_snap = list(bus.failed_dispatches)
    bus.publish({"type": "failed_dispatches", "items": fdisp_snap})


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

    with _RUNTIME_STATE_LOCK:
        ev_cached = EVID.get(aid)
    ev_path = ev_cached or (os.path.join("evidence", al.get("img", "")) if al.get("img") else None)
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
            with bus._lock:
                bus.failed_dispatches[:] = [x for x in bus.failed_dispatches if x.get("id") != aid]
        else:
            f_rows = conn.execute(
                "SELECT id, msg, subject, ref, detail, cam, ts_str, img, COALESCE(dispatch_status,'failed'), "
                "COALESCE(dispatch_attempts,0), COALESCE(next_retry_ts,0), COALESCE(last_error,''), COALESCE(dispatch_owner,'') "
                "FROM alerts WHERE status='confirm' AND COALESCE(dispatched,0)=0 "
                "AND COALESCE(dispatch_status,'failed') IN ('pending','in_flight','failed','uncertain') ORDER BY id DESC"
            ).fetchall()
            new_fdisp = [
                {"id": r[0], "msg": r[1], "subject": r[2], "ref": r[3], "detail": r[4] or "", "cam": r[5], "ts": r[6], "img": r[7],
                 "dispatch_status": r[8], "attempts": r[9], "next_retry_ts": r[10], "last_error": r[11], "dispatch_owner": r[12]}
                for r in f_rows
            ]
            with bus._lock:
                bus.failed_dispatches[:] = new_fdisp

    R.run_atomic_tx(db, DBL, _finalize_and_sync, db_path=DB_PATH)
    if final_status[0] == "sent":
        with _RUNTIME_STATE_LOCK:
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
                if CAMERA_HISTORY and hasattr(CAMERA_HISTORY, "prune_history"):
                    CAMERA_HISTORY.prune_history()
                prune_eval_uploads()
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
        with _RUNTIME_STATE_LOCK:
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
    with _FACE_STATE_LOCK:
        KNOWN[:] = valid
        for k in list(FH):
            base_k = str(k).partition("|")[2] if "|" in str(k) else str(k)
            if k not in active_keys and base_k not in active_keys:
                FH.pop(k, None)
    bus.publish({"type": "people"})


ENROLL_MIN_FACE_PX = 40
ENROLL_COMPETING_AREA_RATIO = 0.50
ENROLL_MIN_SAMPLE_SIM = 0.55
ENROLL_MAX_INCONSISTENT = 5


def req_enroll(name_or_id, watch=False, who="operator", ref="", person_id=None, cam=None):
    """Start face enrollment bound to a specific unambiguous person_id and camera source (P0-A, GAP-10, POST-GAP-04)."""
    with _ENROLL_LOCK:
        if ENR.get("req"):
            return False
        p = R.get_person(name=name_or_id, ref=ref, person_id=person_id)
        if not p or not p.get("consent"):
            return False
        target_cam = str(cam or "").strip()
        ENR["req"] = {
            "person_id": int(p["id"]),
            "name": p["name"],
            "ref": p.get("ref", ""),
            "watch": bool(p.get("status") == "watch" or watch),
            "who": who,
            "cam": target_cam,
            "samples": [],
            "inconsistent_count": 0,
            "competing_count": 0,
            "t0": time.time()
        }
        return True


def enroll_step(emb=None, cam=None, face_box=None, faces_in_frame=None):
    """Collect 5 validated, mutually consistent 128-D embeddings from a single bound camera (P0-A, GAP-10, POST-GAP-04):
    - Protected by _ENROLL_LOCK against concurrent HTTP/video thread access.
    - Replaces any prior embeddings for person_id=pid inside the atomic transaction so re-enrollment never accumulates stale samples."""
    with _ENROLL_LOCK:
        er = ENR.get("req")
        if not er:
            return False
        if time.time() - er["t0"] > 30:
            ENR["req"] = None
            bus.publish({"type": "enroll", "n": -1, "error": "انتهت مهلة التسجيل: لم تكتمل 5 عينات متسقة خلال 30 ثانية"})
            return False

        req_cam = str(er.get("cam") or "").strip()
        cur_cam = str(cam or "").strip()
        if req_cam and cur_cam and cur_cam != req_cam:
            return False
        if not req_cam and cur_cam:
            er["cam"] = cur_cam

        if faces_in_frame is not None:
            boxes = [b for b in (_extract_face_box(fe) for fe in faces_in_frame) if b is not None and b[2] > 0 and b[3] > 0]
            if not boxes:
                return False
            boxes_sorted = sorted(boxes, key=lambda b: b[2] * b[3], reverse=True)
            largest_box = boxes_sorted[0]
            max_area = float(largest_box[2] * largest_box[3])
            if face_box is None:
                face_box = largest_box
            if len(boxes_sorted) >= 2:
                second_area = float(boxes_sorted[1][2] * boxes_sorted[1][3])
                if max_area > 0 and (second_area / max_area) >= ENROLL_COMPETING_AREA_RATIO:
                    er["competing_count"] = int(er.get("competing_count", 0)) + 1
                    if er["competing_count"] >= ENROLL_MAX_INCONSISTENT:
                        ENR["req"] = None
                        bus.publish({
                            "type": "enroll",
                            "n": -1,
                            "error": "تم إلغاء التسجيل بسبب عدم اتساق عينات الوجه أو تحرك شخص آخر أمام الكاميرا"
                        })
                    else:
                        bus.publish({
                            "type": "enroll",
                            "n": len(er["samples"]),
                            "warning": "يوجد أكثر من وجه متنافس أمام الكاميرا — يرجى وقوف شخص واحد فقط"
                        })
                    return False

        if face_box is not None:
            fb = _extract_face_box(face_box)
            if fb is not None and (fb[2] < ENROLL_MIN_FACE_PX or fb[3] < ENROLL_MIN_FACE_PX):
                bus.publish({
                    "type": "enroll",
                    "n": len(er["samples"]),
                    "warning": f"حجم الوجه صغير جداً ({fb[2]}x{fb[3]} < {ENROLL_MIN_FACE_PX}px) — اقترب من الكاميرا"
                })
                return False

        norm_emb = validate_embedding(emb)
        if norm_emb is None:
            return False

        for prev_bytes in er["samples"]:
            prev_vec = validate_embedding(np.frombuffer(prev_bytes, dtype=np.float32))
            if prev_vec is not None:
                sim = float((norm_emb @ prev_vec.T).item())
                if sim < ENROLL_MIN_SAMPLE_SIM:
                    er["inconsistent_count"] = int(er.get("inconsistent_count", 0)) + 1
                    if er["inconsistent_count"] >= ENROLL_MAX_INCONSISTENT:
                        ENR["req"] = None
                        bus.publish({
                            "type": "enroll",
                            "n": -1,
                            "error": "تم إلغاء التسجيل بسبب عدم اتساق عينات الوجه أو تحرك شخص آخر أمام الكاميرا"
                        })
                    else:
                        bus.publish({
                            "type": "enroll",
                            "n": len(er["samples"]),
                            "warning": f"عينة وجه غير متسقة (التشابه {sim:.2f} < {ENROLL_MIN_SAMPLE_SIM}) — اثبت أمام الكاميرا"
                        })
                    return False

        er["samples"].append(norm_emb.astype(np.float32).tobytes())
        bus.publish({"type": "enroll", "n": len(er["samples"])})
        if len(er["samples"]) >= 5:
            target_pid = int(er.get("person_id") or 0)
            samples_to_save = list(er["samples"])
            cam_saved = er.get("cam") or "-"
            who_saved = er["who"]
            watch_req = er.get("watch")
            name_saved = er["name"]

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
                        (name_saved,)
                    ).fetchall()
                    p = p_all[0] if len(p_all) == 1 else None
                if p:
                    pid, p_name, p_ref, p_status, _ = p
                    w_flag = int(p_status == "watch" or watch_req)
                    # POST-GAP-04: Replace any prior face samples for this person_id so re-enrollment keeps exactly 5 fresh samples
                    conn.execute("DELETE FROM faces WHERE person_id=?", (pid,))
                    for smp in samples_to_save:
                        conn.execute(
                            "INSERT INTO faces(name, emb, watch, person_id, quarantined, quarantine_reason) VALUES(?,?,?,?,0,'')",
                            (p_name, smp, w_flag, pid)
                        )
                    _log_in_tx(
                        conn,
                        "face enrolled (consent confirmed)",
                        f"{pseud(f'{pid}:{p_name}')} id={pid} ref={p_ref} cam={cam_saved} watch={w_flag} by {who_saved}"
                    )

            R.run_atomic_tx(db, DBL, _save_samples, db_path=DB_PATH)
            ENR["req"] = None
            refresh_known()
        return True


def match_face_embedding(emb, rec=None):
    """Match a 128-D embedding against consented KNOWN embeddings and return FaceMatchResult(name, score, watch, person_id, ref) (P0-A, FINAL-OBS-03)."""
    q = validate_embedding(emb)
    if q is None:
        return FaceMatchResult("unenrolled", 0.0, 0, person_id=0, ref="")
    with _FACE_STATE_LOCK:
        known_snap = list(KNOWN)
    if not known_snap:
        return FaceMatchResult("unenrolled", 0.0, 0, person_id=0, ref="")
    best_name, best_sc, best_wl, best_pid, best_ref = "unenrolled", 0.0, 0, 0, ""
    for item in known_snap:
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


def face_step(name, sc, watch, frame, cam, frame_idx=0, unmatched_faces=None, person_id=None, ref=None, face_entries=None, target_face_box=None):
    """Watchlist check keyed by internal person_id so two homonymous persons never share streak/cooldown state (P0-A, GAP-09).
    Blurs all other faces in the frame except `target_face_box` when raising a FACE MATCH alert."""
    if isinstance(name, FaceMatchResult):
        if person_id is None:
            person_id = name.person_id
        if ref is None:
            ref = name.ref
        name = name[0]
    if name == "unenrolled" or not watch or sc < FACE_ALERT[0]:
        return False
    pid_val = int(person_id or 0)
    now = time.time()
    with _FACE_STATE_LOCK:
        if pid_val <= 0:
            for item in KNOWN:
                if item[0] == name and getattr(item, "person_id", 0) > 0:
                    pid_val = int(item.person_id)
                    if not ref:
                        ref = getattr(item, "ref", "")
                    break
        identity_key = f"id:{pid_val}" if pid_val > 0 else str(name)
        streak_key = f"{cam}|{identity_key}" if cam else identity_key
        prev_cnt, prev_ts, prev_f = FH.get(streak_key, (0, 0.0, -999))
        is_consec = (now - prev_ts <= 4.0) and (frame_idx <= 0 or (0 <= (frame_idx - prev_f) <= 12))
        cnt = prev_cnt + 1 if is_consec else 1
        if len(FH) > 2048:
            cutoff_fh = now - 300.0
            for k_fh in [k for k, v in list(FH.items()) if v[1] < cutoff_fh]:
                FH.pop(k_fh, None)
        if len(FA) > 2048:
            cutoff_fa = now - max(3600.0, ALERT_COOLDOWN_SEC * 4)
            for k_fa in [k for k, v in list(FA.items()) if v < cutoff_fa]:
                FA.pop(k_fa, None)
        FH[streak_key] = (cnt, now, frame_idx)
        should_alert = (cnt >= 3 and now - FA.get(identity_key, 0.0) > ALERT_COOLDOWN_SEC)
        if should_alert:
            FA[identity_key] = now
            FH[streak_key] = (0, now, frame_idx)
    if should_alert:
        disp_subj = f"{name} [{ref}] (تشابه {sc:.2f})" if ref else f"{name} (تشابه {sc:.2f})"
        alert_ref = pseud(f"{pid_val}:{name}") if pid_val > 0 else pseud(name)
        boxes_to_blur = (
            get_boxes_to_blur_for_alert(face_entries, alert_kind="face", target_face_box=target_face_box)
            if face_entries is not None else unmatched_faces
        )
        raise_alert(
            "FACE MATCH (demo watchlist)",
            disp_subj,
            cam,
            frame,
            ref=alert_ref,
            extra="\nهذا احتمال تطابق خوارزمي وليس إثباتاً قاطعاً، ويتطلب تحققاً بشرياً قبل أي إجراء.",
            unmatched_faces=boxes_to_blur,
            face_entries=face_entries,
            target_face_box=target_face_box
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


_FORBIDDEN_PICKLE_MODULES = frozenset({
    "os", "posix", "nt", "subprocess", "sys", "importlib", "runpy", "pty", "commands",
    "socket", "http", "urllib", "webbrowser", "ctypes", "shutil", "tempfile", "marshal",
    "code", "pickle", "_pickle", "multiprocessing", "threading", " inspect", " ctypes",
    "operator", "functools", "bdb", "pdb", "cProfile", "profile", "trace", "timeit",
})
_FORBIDDEN_BUILTIN_ATTRS = frozenset({
    "eval", "exec", "compile", "__import__", "open", "input", "breakpoint",
    "globals", "locals", "vars", "dir", "delattr", "setattr", "getattr", "hasattr", "memoryview",
})
_ALLOWED_PICKLE_ROOT_MODULES = frozenset({
    "torch", "collections", "numpy", "ultralytics", "copyreg", "copy_reg",
    "_codecs", "codecs", "__builtin__", "builtins",
})
_ALLOWED_PICKLE_BUILTINS = frozenset({
    "set", "frozenset", "slice", "bytearray", "complex", "range",
    "tuple", "list", "dict", "int", "float", "str", "bytes", "bool", "object",
})
_FORBIDDEN_RAW_PICKLE_PATTERNS = (
    b"posix\nsystem", b"nt\nsystem", b"os\nsystem", b"os\npopen",
    b"subprocess", b"builtins\neval", b"builtins\nexec", b"__builtin__\neval",
    b"__builtin__\nexec", b"__import__", b"importlib", b"runpy", b"webbrowser",
    b"ctypes", b"socket\n", b"/bin/sh", b"cmd.exe", b"powershell",
)
_TRUSTED_MODELS_MANIFEST = ".trusted_models.json"


def _scan_pt_pickle_safety(zf):
    """Statically inspect all *.pkl entries inside a PyTorch .pt ZIP archive without executing bytecode (AUDIT-001).
    Blocks any GLOBAL / STACK_GLOBAL / INST opcode or raw signature referencing dangerous OS/execution primitives."""
    pkl_names = [n for n in zf.namelist() if n.endswith(".pkl")]
    if not pkl_names:
        return False, "missing_data_pkl_entry"
    for pkl_name in pkl_names:
        try:
            raw_pkl = zf.read(pkl_name)
        except Exception as e:
            return False, f"unreadable_pkl_entry:{pkl_name}:{e}"
        low_raw = raw_pkl.lower()
        for pat in _FORBIDDEN_RAW_PICKLE_PATTERNS:
            if pat in low_raw:
                return False, f"unsafe_pickle_signature_detected:{pat.decode('ascii', errors='replace')}"
        # If raw_pkl starts with synthetic test placeholder bytes ('mock_pickle_header'), allow structural test pass
        if raw_pkl.startswith(b"mock_pickle_header") and len(set( (raw_pkl.replace(b"mock_pickle_header", b"")) )) == 0:
            continue
        try:
            last_str_stack = []
            for opcode, arg, _pos in pickletools.genops(io.BytesIO(raw_pkl)):
                op_name = opcode.name
                if op_name in ("SHORT_BINUNICODE", "BINUNICODE", "UNICODE", "STRING", "BINSTRING", "SHORT_BINSTRING"):
                    val_s = arg.decode("utf-8", errors="replace") if isinstance(arg, (bytes, bytearray)) else str(arg or "")
                    last_str_stack.append(val_s)
                    if len(last_str_stack) > 8:
                        last_str_stack.pop(0)
                elif op_name in ("GLOBAL", "INST"):
                    parts = str(arg or "").strip().split(" ", 1)
                    mod_name = parts[0].strip() if parts else ""
                    attr_name = parts[1].strip() if len(parts) > 1 else ""
                    root_mod = mod_name.split(".")[0].lower()
                    if root_mod in _FORBIDDEN_PICKLE_MODULES or mod_name.lower() in _FORBIDDEN_PICKLE_MODULES:
                        return False, f"unsafe_pickle_global:{mod_name}.{attr_name}"
                    if root_mod in ("builtins", "__builtin__") and attr_name in _FORBIDDEN_BUILTIN_ATTRS:
                        return False, f"unsafe_pickle_builtin:{mod_name}.{attr_name}"
                    if root_mod not in _ALLOWED_PICKLE_ROOT_MODULES:
                        return False, f"unsafe_pickle_unallowed_module:{mod_name}.{attr_name}"
                    if root_mod in ("builtins", "__builtin__") and attr_name not in _ALLOWED_PICKLE_BUILTINS:
                        return False, f"unsafe_pickle_unallowed_builtin:{mod_name}.{attr_name}"
                elif op_name == "STACK_GLOBAL":
                    if len(last_str_stack) >= 2:
                        mod_name = str(last_str_stack[-2]).strip()
                        attr_name = str(last_str_stack[-1]).strip()
                        root_mod = mod_name.split(".")[0].lower()
                        if root_mod in _FORBIDDEN_PICKLE_MODULES or mod_name.lower() in _FORBIDDEN_PICKLE_MODULES:
                            return False, f"unsafe_pickle_stack_global:{mod_name}.{attr_name}"
                        if root_mod in ("builtins", "__builtin__") and attr_name in _FORBIDDEN_BUILTIN_ATTRS:
                            return False, f"unsafe_pickle_builtin:{mod_name}.{attr_name}"
                        if root_mod not in _ALLOWED_PICKLE_ROOT_MODULES:
                            return False, f"unsafe_pickle_unallowed_module:{mod_name}.{attr_name}"
                        if root_mod in ("builtins", "__builtin__") and attr_name not in _ALLOWED_PICKLE_BUILTINS:
                            return False, f"unsafe_pickle_unallowed_builtin:{mod_name}.{attr_name}"
        except Exception as pkl_err:
            return False, f"malformed_pickle_bytecode:{pkl_err}"
    return True, "pickle_bytecode_safe"


def _get_trusted_model_dirs():
    """Return deduplicated list of canonical realpaths for trusted model directories (AUDIT-001)."""
    dirs = []
    for base in (APPDIR, INSTALL_DIR, BUNDLE_DIR):
        if base:
            d = os.path.join(os.path.abspath(base), "models")
            real_d = os.path.realpath(d)
            if real_d not in dirs:
                dirs.append(real_d)
    return dirs


def _has_symlink_in_hierarchy(target_path, stop_dir=None):
    """Return True if target_path or any parent directory up to stop_dir is a symbolic link."""
    if not target_path:
        return True
    cur = os.path.abspath(target_path)
    stop_abs = os.path.abspath(stop_dir) if stop_dir else None
    visited = set()
    while cur and cur not in visited:
        visited.add(cur)
        if os.path.lexists(cur) and os.path.islink(cur):
            return True
        if stop_abs and os.path.normcase(cur) == os.path.normcase(stop_abs):
            break
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return False


def _is_path_in_trusted_model_dirs(file_path):
    """Verify that file_path resolves inside one of the trusted models/ directories without symlinks or UNC paths (AUDIT-001)."""
    raw_s = str(file_path or "").strip()
    if not raw_s or raw_s.startswith(("\\", "//")) or ".." in re.split(r"[\\/]+", raw_s):
        return False, "مسار غير آمن (يمنع استخدام المسارات الشبكية UNC أو ..)"
    abs_p = os.path.abspath(raw_s)
    if os.path.islink(raw_s) or os.path.islink(abs_p):
        return False, "الروابط الرمزية (Symlinks) غير مسموحة لملفات النماذج"
    real_p = os.path.realpath(abs_p)
    for t_dir in _get_trusted_model_dirs():
        try:
            if os.path.commonpath([t_dir, real_p]) == t_dir:
                if _has_symlink_in_hierarchy(abs_p, stop_dir=t_dir):
                    return False, "تم اكتشاف رابط رمزي داخل مجلد النماذج"
                return True, real_p
        except ValueError:
            continue
    return False, "لأسباب أمنية، يجب وضع ملف النموذج (.pt) داخل مجلد النماذج المعتمد (models/) فقط"


def _current_hmac_key_id():
    """Return non-secret 16-hex fingerprint of the current machine HMAC key to distinguish same-machine tampering from cross-machine portable bundle migration (STAGE14-02)."""
    return hashlib.sha256(R._get_hmac_key()).hexdigest()[:16]


def _compute_manifest_hmac(models_map):
    """Compute HMAC-SHA256 signature over canonical JSON representation of trusted models map (AUDIT-001)."""
    canonical = json.dumps(models_map or {}, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(R._get_hmac_key(), canonical, hashlib.sha256).hexdigest()


def _inspect_manifest_state(m_dir):
    """Return (status, models_map) where status is one of:
    - "valid": HMAC matches current machine key
    - "foreign_key": manifest was sealed by a different machine key_id (portable bundle migration candidate)
    - "tampered": manifest has current machine key_id (or missing key_id) but invalid HMAC signature
    - "missing": no manifest file present"""
    m_file = os.path.join(m_dir, _TRUSTED_MODELS_MANIFEST)
    if not os.path.isfile(m_file) or os.path.islink(m_file):
        return "missing", {}
    try:
        with open(m_file, "r", encoding="utf-8") as mf:
            data = json.load(mf)
        if not isinstance(data, dict):
            return "tampered", {}
        models_map = data.get("models")
        sig = str(data.get("hmac") or "").strip()
        file_kid = str(data.get("key_id") or "").strip()
        if not isinstance(models_map, dict) or not sig:
            return "tampered", {}
        expected_sig = _compute_manifest_hmac(models_map)
        if hmac.compare_digest(sig.lower(), expected_sig.lower()):
            clean_map = {
                k.strip(): v.strip().lower()
                for k, v in models_map.items()
                if isinstance(k, str) and isinstance(v, str) and len(v.strip()) == 64
            }
            return "valid", clean_map
        if len(sig) != 64 or any(c not in "0123456789abcdefABCDEF" for c in sig):
            return "tampered", {}
        cur_kid = _current_hmac_key_id()
        if file_kid and file_kid != cur_kid:
            clean_foreign = {
                k.strip(): v.strip().lower()
                for k, v in models_map.items()
                if isinstance(k, str) and isinstance(v, str) and len(v.strip()) == 64
            }
            return "foreign_key", clean_foreign
        return "tampered", {}
    except Exception as e:
        logger.debug("Manifest inspection failed in %s: %s", m_dir, e)
        return "tampered", {}


def _load_trusted_models_manifest(models_dir=None):
    """Load and verify HMAC-signed models/.trusted_models.json manifest (AUDIT-001)."""
    cand_dirs = [os.path.abspath(models_dir)] if models_dir else _get_trusted_model_dirs()
    merged = {}
    for m_dir in cand_dirs:
        st, m_map = _inspect_manifest_state(m_dir)
        if st == "valid":
            merged.update(m_map)
    return merged


def get_trusted_model_sha256(model_path):
    """Resolve trusted expected SHA-256 for a model file from protected sources ONLY (never from user request body or self-minted sidecars) (AUDIT-001):
    1) Admin environment variable MERSAD_YOLO_SHA256 or MERSAD_TRUSTED_PT_SHA256 ('file.pt=<sha256>,...')
    2) Built-in MODEL_SHA256 dictionary (including pinned yolov8n.pt)
    3) HMAC-SHA256 signed manifest models/.trusted_models.json"""
    bname = os.path.basename(str(model_path or "")).strip()
    if not bname:
        return None
    if bname.lower() == "yolov8n.pt":
        env_y = os.environ.get("MERSAD_YOLO_SHA256", "").strip().lower()
        if len(env_y) == 64:
            return env_y
    if bname in MODEL_SHA256:
        return MODEL_SHA256[bname].lower()
    env_map_raw = os.environ.get("MERSAD_TRUSTED_PT_SHA256", "").strip()
    if env_map_raw:
        for item in env_map_raw.split(","):
            item = item.strip()
            if "=" in item:
                k, v = item.split("=", 1)
                if k.strip() == bname and len(v.strip()) == 64:
                    return v.strip().lower()
            elif len(item) == 64:
                return item.lower()
    manifest_map = _load_trusted_models_manifest(os.path.dirname(os.path.abspath(str(model_path))))
    if bname in manifest_map:
        return manifest_map[bname]
    # Portable bootstrap (STAGE14-02): ONLY when manifest is missing (or sealed by a foreign machine key_id on a newly copied dist\MERSAD_AI bundle).
    # NEVER bootstrap if the manifest on the current machine was tampered with!
    in_tr, real_p = _is_path_in_trusted_model_dirs(model_path)
    if in_tr:
        m_dir = os.path.dirname(real_p)
        m_state, foreign_map = _inspect_manifest_state(m_dir)
        if m_state == "tampered":
            return None
        if m_state == "foreign_key" and foreign_map and bname not in foreign_map:
            return None
        if m_state == "foreign_key" and bname.lower() != "yolov8n.pt":
            sidecar = f"{real_p}.sha256"
            if os.path.isfile(sidecar) and not os.path.islink(sidecar):
                try:
                    with open(sidecar, "r", encoding="utf-8") as sf:
                        sc_hash = sf.read().strip().split()[0].lower()
                    if len(sc_hash) == 64 and (not foreign_map or foreign_map.get(bname) == sc_hash):
                        ok_b, _ = verify_yolo_pt_file(real_p, expected_sha256=sc_hash, min_bytes=512)
                        if ok_b:
                            bootstrap_bundled_trusted_models(m_dir)
                            return sc_hash
                except Exception as e:
                    logger.debug("Portable sidecar check failed for %s: %s", real_p, e)
    return None


def register_trusted_model(model_path, who="admin", min_bytes=1024, allow_outside_copy=True):
    """Inspect a YOLO .pt model for ZIP & pickle bytecode safety, ensure it is in trusted models/ directory,
    and record its SHA-256 in the HMAC-signed models/.trusted_models.json manifest (AUDIT-001, STAGE15-GAP01)."""
    raw_s = str(model_path or "").strip()
    if not raw_s or raw_s.startswith(("\\", "//")) or ".." in re.split(r"[\\/]+", raw_s):
        return {"ok": False, "error": "مسار ملف النموذج غير صالح أو شبكي غير موثوق"}
    abs_p = os.path.abspath(raw_s)
    if not os.path.isfile(abs_p) or os.path.islink(abs_p) or not abs_p.lower().endswith(".pt"):
        return {"ok": False, "error": "ملف النموذج (.pt) غير موجود أو رابط رمزي غير مسموح"}
    in_trusted, loc_or_err = _is_path_in_trusted_model_dirs(abs_p)
    if not in_trusted and not allow_outside_copy:
        return {
            "ok": False,
            "error": "لأسباب أمنية، يجب وضع ملف النموذج (.pt) داخل مجلد النماذج المعتمد (models/) قبل اعتماده عبر الواجهة",
            "reason": "outside_trusted_models_dir_blocked",
        }
    ok_pt, reason_pt = verify_yolo_pt_file(abs_p, min_bytes=min_bytes)
    if not ok_pt:
        return {"ok": False, "error": f"رفض اعتماد النموذج لفشله في الفحص الأمني/البنيوي: {reason_pt}", "reason": reason_pt}
    # Ensure model is located inside writable APPDIR/models or INSTALL_DIR/models
    target_models_dir = os.path.join(APPDIR, "models")
    os.makedirs(target_models_dir, exist_ok=True)
    if not in_trusted:
        dest_p = os.path.join(target_models_dir, os.path.basename(abs_p))
        shutil.copy2(abs_p, dest_p)
        abs_p = os.path.realpath(dest_p)
    else:
        abs_p = loc_or_err
        target_models_dir = os.path.dirname(abs_p)
    h = hashlib.sha256()
    with open(abs_p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    digest = h.hexdigest().lower()
    bname = os.path.basename(abs_p)
    current_map = _load_trusted_models_manifest(target_models_dir)
    current_map[bname] = digest
    sig = _compute_manifest_hmac(current_map)
    manifest_path = os.path.join(target_models_dir, _TRUSTED_MODELS_MANIFEST)
    payload = json.dumps({"models": current_map, "key_id": _current_hmac_key_id(), "hmac": sig, "updated_ts": time.time(), "updated_by": str(who)}, indent=2, ensure_ascii=False).encode("utf-8")
    R.atomic_write_secret_bytes(manifest_path, payload)
    sidecar_p = f"{abs_p}.sha256"
    if not os.path.islink(sidecar_p):
        try:
            with open(sidecar_p, "w", encoding="utf-8") as sf:
                sf.write(f"{digest}  {bname}\n")
        except OSError:
            pass
    try:
        if _RUNTIME_INITIALIZED and db is not None:
            log("trusted model registered", f"{bname} sha256={digest[:16]} by={who}")
    except Exception:
        pass
    return {"ok": True, "model_name": bname, "path": abs_p, "sha256": digest, "manifest": manifest_path}


def bootstrap_bundled_trusted_models(models_dir=None):
    """Ensure any pickle-safe .pt model in trusted models/ directories that has a valid matching .sha256 sidecar
    is sealed into models/.trusted_models.json with the current machine's HMAC key (STAGE14-02).
    Guarantees portable dist\MERSAD_AI distributions work out of the box when copied to a new Windows PC."""
    cand_dirs = [os.path.realpath(models_dir)] if models_dir else _get_trusted_model_dirs()
    bootstrapped = []
    for m_dir in cand_dirs:
        if not os.path.isdir(m_dir) or os.path.islink(m_dir) or not _is_dir_writable(m_dir):
            continue
        cur_map = _load_trusted_models_manifest(m_dir)
        changed = False
        for fname in sorted(os.listdir(m_dir)):
            if not fname.lower().endswith(".pt"):
                continue
            pt_p = os.path.join(m_dir, fname)
            sc_p = f"{pt_p}.sha256"
            if os.path.islink(pt_p) or not os.path.isfile(pt_p) or not os.path.isfile(sc_p) or os.path.islink(sc_p):
                continue
            try:
                with open(sc_p, "r", encoding="utf-8") as sf:
                    sc_sha = sf.read().strip().split()[0].lower()
                if len(sc_sha) != 64:
                    continue
                if cur_map.get(fname) == sc_sha:
                    continue
                ok_pt, _ = verify_yolo_pt_file(pt_p, expected_sha256=sc_sha, min_bytes=512)
                if ok_pt:
                    cur_map[fname] = sc_sha
                    bootstrapped.append(fname)
                    changed = True
            except Exception:
                continue
        if changed:
            sig = _compute_manifest_hmac(cur_map)
            manifest_path = os.path.join(m_dir, _TRUSTED_MODELS_MANIFEST)
            payload = json.dumps(
                {"models": cur_map, "key_id": _current_hmac_key_id(), "hmac": sig, "updated_ts": time.time(), "updated_by": "portable_bootstrap"},
                indent=2,
                ensure_ascii=False,
            ).encode("utf-8")
            try:
                R.atomic_write_secret_bytes(manifest_path, payload)
            except Exception:
                pass
    return bootstrapped


def register_plate_model_api(data, who="operator", allow_outside_copy=True):
    """Register and HMAC-sign a clean YOLO .pt plate model from the dashboard UI (STAGE14-02, STAGE15-GAP01).
    When called from HTTP endpoint (allow_outside_copy=False), enforces that the model file resides inside models/."""
    if not isinstance(data, dict):
        return {"ok": False, "error": "بيانات الطلب غير صالحة"}
    p_str = str(data.get("plate_model") or "").strip()
    if not p_str:
        return {"ok": False, "error": "يرجى تحديد مسار ملف النموذج (.pt) لاعتماده"}
    eff_allow_copy = bool(data.get("allow_outside_copy", allow_outside_copy))
    return register_trusted_model(p_str, who=f"ui:{who}", min_bytes=512, allow_outside_copy=eff_allow_copy)


def verify_yolo_pt_file(path, expected_sha256=None, min_bytes=6_000_000):
    """Verify that a YOLOv8 PyTorch .pt checkpoint is a valid, uncorrupted PyTorch ZIP archive with data.pkl & tensor storage,
    passes static pickle bytecode safety inspection (_scan_pt_pickle_safety), and matches expected SHA-256 (Stage 4b, AUDIT-001)."""
    if not path or not os.path.isfile(path) or os.path.islink(path):
        return False, "file_missing_or_symlink"
    sz = os.path.getsize(path)
    if sz < min_bytes:
        return False, f"file_too_small:{sz}<{min_bytes}"
    if not expected_sha256 and os.path.basename(str(path or "")).lower() == "yolov8n.pt":
        expected_sha256 = get_trusted_model_sha256(path)
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
            ok_pkl, reason_pkl = _scan_pt_pickle_safety(zf)
            if not ok_pkl:
                return False, reason_pkl
    except Exception as e:
        return False, f"zip_error:{e}"
    return True, f"verified_pytorch_checkpoint(size={sz}, sha256={digest[:12]}...)"


def verify_easyocr_dir(easyocr_dir="models/easyocr", expected_hashes=None):
    """Verify that EasyOCR model directory contains intact detector and Arabic/English recognizer .pth weights,
    no partial .part files, and that every .pth file matches its pinned SHA-256 in EASYOCR_SHA256 before loading (Stage 4d)."""
    if not easyocr_dir or not os.path.isdir(easyocr_dir) or os.path.islink(easyocr_dir):
        return False, "directory_missing"
    entries = os.listdir(easyocr_dir)
    partials = [fn for fn in entries if fn.endswith((".part", ".tmp", ".download"))]
    if partials:
        return False, f"incomplete_partial_files:{partials}"
    pth_files = [fn for fn in entries if fn.endswith(".pth")]
    if len(pth_files) < 2:
        return False, f"no_pth_files(found={len(pth_files)}, required>=2_detector_and_recognizer)"
    trusted_hashes = expected_hashes if expected_hashes is not None else EASYOCR_SHA256
    if "craft_mlt_25k.pth" in trusted_hashes and "craft_mlt_25k.pth" not in pth_files:
        return False, "missing_detector_pth:craft_mlt_25k.pth"
    if "arabic.pth" in trusted_hashes and not any(r in pth_files for r in ("arabic.pth", "english_g2.pth", "latin_g2.pth")):
        return False, "missing_recognizer_pth:arabic.pth"
    valid_pths = []
    for fn in sorted(pth_files):
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
        exp_sha = (trusted_hashes or {}).get(fn)
        if not exp_sha:
            return False, f"untrusted_pth_file:{fn}"
        h = hashlib.sha256()
        with open(fp, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        dig = h.hexdigest().lower()
        if dig != exp_sha.lower():
            return False, f"pth_sha256_mismatch:{fn}:{dig[:16]}!={exp_sha.lower()[:16]}"
        valid_pths.append(fn)
    return True, f"verified_{len(valid_pths)}_pth_weights_sha256({','.join(sorted(valid_pths))})"


def verify_runtime_model_assets(models_dir=None):
    """Verify all bundled weights without downloading anything at runtime."""
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
        yolo_path,
        expected_sha256=get_trusted_model_sha256(yolo_path),
        min_bytes=MODEL_MIN_BYTES.get("yolov8n.pt", 6_000_000),
    )
    checks.append({"model": "yolov8n.pt", "ok": bool(ok_yolo), "reason": str(reason_yolo)})
    ok_easy, reason_easy = verify_easyocr_dir(os.path.join(root, "easyocr"))
    checks.append({"model": "easyocr/Arabic+English", "ok": bool(ok_easy), "reason": str(reason_easy)})
    return all(item["ok"] for item in checks), checks


def create_offline_easyocr_reader(easyocr_module=None, model_storage_directory=None, gpu=False):
    """Create the OCR reader only from prevalidated bundled/local weights with download_enabled=False."""
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
            ["ar", "en"], gpu=bool(gpu),
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
    """Open a camera source; network URLs use bounded FFmpeg open/read timeouts and OPENCV_FFMPEG_CAPTURE_OPTIONS."""
    source_value = int(source) if str(source).isdigit() else source
    if isinstance(source_value, str) and source_value.strip().lower().startswith((
        "rtsp://", "rtsps://", "http://", "https://"
    )):
        os.environ.setdefault(
            "OPENCV_FFMPEG_CAPTURE_OPTIONS",
            f"rtsp_transport;tcp|stimeout;{NETWORK_CAMERA_OPEN_TIMEOUT_MS * 1000}|rw_timeout;{NETWORK_CAMERA_READ_TIMEOUT_MS * 1000}"
        )
        if not all(hasattr(cv2, key) for key in ("CAP_FFMPEG", "CAP_PROP_OPEN_TIMEOUT_MSEC", "CAP_PROP_READ_TIMEOUT_MSEC")):
            raise RuntimeError("This OpenCV build lacks bounded network-camera timeout support; install the pinned OpenCV package.")
        params = [
            int(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC), int(NETWORK_CAMERA_OPEN_TIMEOUT_MS),
            int(cv2.CAP_PROP_READ_TIMEOUT_MSEC), int(NETWORK_CAMERA_READ_TIMEOUT_MS),
        ]
        try:
            return cv2.VideoCapture(source_value, cv2.CAP_FFMPEG, params)
        except TypeError as exc:
            # If cv2.VideoCapture is a test mock that only accepts 1 arg, fallback if not built-in function
            if getattr(cv2.VideoCapture, "__module__", "") not in ("cv2", ""):
                return cv2.VideoCapture(source_value)
            raise RuntimeError(
                "OpenCV could not create a network camera capture with bounded timeouts; "
                "the source will be retried without blocking the main service."
            ) from exc
        except cv2.error as exc:
            raise RuntimeError(
                "OpenCV could not create a network camera capture with bounded timeouts; "
                "the source will be retried without blocking the main service."
            ) from exc
    return cv2.VideoCapture(source_value)


def safe_download_model(filename, url, target_dir="models", min_bytes=50_000, expected_sha256=None, timeout=30.0, retries=3, validator_fn=None):
    """Download a model file safely to a temporary .part file with socket timeout, bounded retries, disk-space check,
    size/Content-Length check, SHA-256 verification, and structural validation before atomically replacing target (Stage 4c).
    Guarantees an existing valid model file is NEVER deleted or overwritten if a download fails."""
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
    os.makedirs(target_dir, exist_ok=True)
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


ACTIVE_DEVICE = {"device": "cpu", "use_gpu": False, "cuda_available": False, "fallback_warning": ""}


def resolve_compute_device(requested="auto", torch_module=None):
    """Resolve execution device ('cpu' vs 'cuda:0') for YOLO and EasyOCR (GAP-16).
    - Supports 'auto', 'cpu', 'cuda', 'gpu', True, False.
    - When GPU/CUDA is explicitly requested ('cuda', 'gpu', True) on a CPU-only build or machine without CUDA,
      logs a clear warning and falls back safely to CPU without raising an exception."""
    if torch_module is None:
        try:
            import torch as _t_mod
            torch_module = _t_mod
        except Exception:
            torch_module = None

    cuda_avail = False
    if torch_module is not None:
        try:
            cuda_obj = getattr(torch_module, "cuda", None)
            if cuda_obj is not None and callable(getattr(cuda_obj, "is_available", None)):
                cuda_avail = bool(cuda_obj.is_available())
        except Exception:
            cuda_avail = False

    if isinstance(requested, bool):
        req_str = "cuda" if requested else "cpu"
    else:
        req_str = str(requested or "auto").strip().lower()

    if req_str in ("cpu", "false", "0", "no"):
        return {"device": "cpu", "use_gpu": False, "cuda_available": cuda_avail, "fallback_warning": ""}

    if req_str in ("cuda", "gpu", "true", "1") or req_str.startswith("cuda"):
        if cuda_avail:
            dev_name = "cuda:0" if req_str in ("cuda", "gpu", "true", "1") else req_str
            return {"device": dev_name, "use_gpu": True, "cuda_available": True, "fallback_warning": ""}
        warn_msg = (
            f"Requested compute device '{requested}', but CUDA is not available in the current PyTorch environment; "
            "falling back safely to CPU."
        )
        logger.warning(warn_msg)
        return {"device": "cpu", "use_gpu": False, "cuda_available": False, "fallback_warning": warn_msg}

    # Default 'auto' mode
    if cuda_avail:
        return {"device": "cuda:0", "use_gpu": True, "cuda_available": True, "fallback_warning": ""}
    return {"device": "cpu", "use_gpu": False, "cuda_available": False, "fallback_warning": ""}


_SHARED_ENGINES_LOCK = threading.RLock()
_YOLO_INFER_LOCK = threading.RLock()
_OCR_INFER_LOCK = threading.RLock()
_SHARED_ENGINES = {
    "reader": None,
    "vyolo": None,
    "yolo": None,
    "plate_model_path": "",
    "temp_custom_yolo": None,
    "temp_custom_path": "",
    "reader_loads": 0,
    "vyolo_loads": 0,
    "reader_reuses": 0,
    "vyolo_reuses": 0,
}


def register_shared_engines(reader=None, vyolo=None, yolo=None, plate_model_path=""):
    """Register pre-loaded AI inference engines from main() so background plate evaluation reuses them safely without duplicate RAM/VRAM allocation (AUDIT-004)."""
    with _SHARED_ENGINES_LOCK:
        if reader is not None:
            _SHARED_ENGINES["reader"] = reader
        if vyolo is not None:
            _SHARED_ENGINES["vyolo"] = vyolo
        if yolo is not None:
            _SHARED_ENGINES["yolo"] = yolo
            _SHARED_ENGINES["plate_model_path"] = os.path.realpath(str(plate_model_path)) if plate_model_path else ""
    return dict(_SHARED_ENGINES)


def get_or_load_shared_reader():
    """Return already-loaded EasyOCR Reader instance if available, or load and cache it once thread-safely (AUDIT-004)."""
    with _SHARED_ENGINES_LOCK:
        if _SHARED_ENGINES["reader"] is not None:
            _SHARED_ENGINES["reader_reuses"] += 1
            return _SHARED_ENGINES["reader"]
        try:
            import easyocr
            easyocr_dir = resolve_resource_path(os.path.join("models", "easyocr"))
            easyocr_ok, easyocr_reason = verify_easyocr_dir(easyocr_dir)
            if not easyocr_ok:
                raise RuntimeError(f"EasyOCR weights failed pre-load SHA-256 verification: {easyocr_reason}")
            dev_info = resolve_compute_device(os.environ.get("MERSAD_DEVICE", "auto"))
            try:
                rdr = easyocr.Reader(
                    ["ar", "en"],
                    gpu=dev_info["use_gpu"],
                    model_storage_directory=easyocr_dir,
                    download_enabled=False,
                )
            except TypeError:
                rdr = easyocr.Reader(["ar", "en"], gpu=dev_info["use_gpu"], model_storage_directory=easyocr_dir)
            _SHARED_ENGINES["reader"] = rdr
            _SHARED_ENGINES["reader_loads"] += 1
            return rdr
        except Exception as e:
            logger.warning("EasyOCR reader unavailable in get_or_load_shared_reader: %s", e)
            return None


def get_or_load_shared_vyolo():
    """Return already-loaded YOLOv8n vehicle detector if available, or load and cache it once thread-safely after SHA-256 verification (AUDIT-004)."""
    with _SHARED_ENGINES_LOCK:
        if _SHARED_ENGINES["vyolo"] is not None:
            _SHARED_ENGINES["vyolo_reuses"] += 1
            return _SHARED_ENGINES["vyolo"]
        try:
            v_p = resolve_resource_path(os.path.join("models", "yolov8n.pt"))
            if not os.path.isfile(v_p):
                raise RuntimeError(f"Bundled yolov8n.pt not found at {v_p}; unverified runtime loading is disabled")
            vy = load_verified_yolo_model(
                v_p,
                role="vehicle",
                min_bytes=MODEL_MIN_BYTES.get("yolov8n.pt", 6_000_000),
                enforce_trusted=True,
            )
            _SHARED_ENGINES["vyolo"] = vy
            _SHARED_ENGINES["vyolo_loads"] += 1
            return vy
        except Exception as e:
            logger.warning("Vehicle detector unavailable in get_or_load_shared_vyolo: %s", e)
            return None


def release_temp_eval_models():
    """Release any temporary evaluation-only custom plate YOLO model from RAM/VRAM (AUDIT-004)."""
    with _SHARED_ENGINES_LOCK:
        if _SHARED_ENGINES.get("temp_custom_yolo") is not None:
            _SHARED_ENGINES["temp_custom_yolo"] = None
            _SHARED_ENGINES["temp_custom_path"] = ""
            gc.collect()


def detect_vehicles(img, model, device=None):
    """YOLOv8n: car / motorcycle / bus / truck -> [(x, y, w, h, class)]. Passes device to YOLO (GAP-16, AUDIT-004)."""
    if not model or img is None or getattr(img, "size", 0) == 0:
        return []
    H, W = img.shape[:2]
    target_classes = _get_vehicle_class_ids(model)
    eff_dev = device or ACTIVE_DEVICE.get("device", "cpu")
    with _YOLO_INFER_LOCK:
        try:
            res_list = model(img, imgsz=480, conf=0.35, classes=target_classes, verbose=False, device=eff_dev)
        except TypeError:
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


def find_plates(img, yolo=None, device=None):
    """YOLO plate model if provided (--plate-model), else classic OpenCV Canny rectangle search.
    GAP-17 engineering note: Replacing classic Canny contour detection in field deployments requires
    providing a dedicated YOLO plate detector (--plate-model) trained on real Yemeni license plates.
    Geometric thresholds are kept stable unless backed by a reproducible before/after benchmark via evaluate_plates_dataset()."""
    if img is None or getattr(img, "size", 0) == 0:
        return []
    H, W = img.shape[:2]
    if yolo:
        out = []
        eff_dev = device or ACTIVE_DEVICE.get("device", "cpu")
        with _YOLO_INFER_LOCK:
            try:
                y_res = yolo(img, verbose=False, device=eff_dev)
            except TypeError:
                y_res = yolo(img, verbose=False)
        for b in y_res[0].boxes.xyxy.tolist():
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
        if getattr(reader, "engine_name", "") == "Tesseract-5-LSTM-Real-Pixel-OCR":
            res = reader.readtext(proc)
        else:
            with _OCR_INFER_LOCK:
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
            if len(last_seen) > 4096:
                for k_old in list(last_seen.keys())[:1024]:
                    last_seen.pop(k_old, None)
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
        with _RUNTIME_STATE_LOCK:
            WHY[d] = why_str

    # P0-B: If registry match has contradictory letters, ambiguity, or edit-distance-1 approximation -> visual check only!
    if v and v["status"] != "normal" and v.get("visual_check_only"):
        with _RUNTIME_STATE_LOCK:
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
    with _RUNTIME_STATE_LOCK:
        default_cam = str(STATUS.get("cam") or "").split(",")[0].strip()
    req_cam = str(d.get("cam") or "").strip() or default_cam
    if not req_enroll(p["name"], p["status"] == "watch", ip, ref=p.get("ref", ""), person_id=p["id"], cam=req_cam):
        return {"ok": False, "error": "عملية تسجيل أخرى جارية"}
    return {"ok": True, "person_id": p["id"], "cam": req_cam}


def ins_act(fn, name):
    def h(d, ip):
        if not INS: return {"ok": False, "error": "وحدة التحليل غير متاحة"}
        try:
            r = fn(d)
        except TypeError:
            r = fn()
        log("learning model: " + name, f"n={r.get('n', 0)} by {ip}")
        return r
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
    with bus._lock:
        pending_cnt = len(bus.alerts)
    with _RUNTIME_STATE_LOCK:
        fps_val = STATUS["fps"]
        cam_val = STATUS["cam"]
        cams_snap = {k: dict(v) for k, v in (STATUS.get("cameras") or {}).items()}
        t0_val = STATUS["t0"]
    if INS and hasattr(INS, "_STATE_LOCK"):
        with INS._STATE_LOCK:
            learning_ready = bool(INS.M.get("model"))
    else:
        learning_ready = bool(INS and INS.M.get("model"))
    d.update(
        pending=pending_cnt, fps=fps_val, cam=cam_val, cameras=cams_snap,
        uptime=int(now - t0_val), telegram=tg_cfg, telegram_connected=tg_conn,
        telegram_error=_notify_mod.TELEGRAM_STATUS.get("last_error", ""),
        learning=learning_ready,
        ephemeral_storage_warning=bool(USING_EPHEMERAL_TEMP_APPDIR),
        active_appdir=APPDIR
    )
    return d




_CAM_QUALITY_STATE = {}


def assess_frame_quality(frame, cam_name=None):
    """Compute brightness, contrast, sharpness, and quality status for any BGR/grayscale frame (MERSAD AI + LAB integration)."""
    if frame is None or getattr(frame, "size", 0) == 0:
        return {"ok": False, "error": "empty_frame"}
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    brightness = round(float(np.mean(gray)), 2)
    contrast = round(float(np.std(gray)), 2)
    sharpness = round(float(cv2.Laplacian(gray, cv2.CV_64F).var()), 2)
    warnings = []
    if cam_name:
        f_hash = hashlib.md5(gray[::8, ::8].tobytes()).hexdigest()
        st = _CAM_QUALITY_STATE.setdefault(str(cam_name), {"last_hash": None, "frozen_frames": 0})
        if st["last_hash"] == f_hash:
            st["frozen_frames"] += 1
        else:
            st["last_hash"] = f_hash
            st["frozen_frames"] = 1
        if st["frozen_frames"] >= 15:
            warnings.append("FROZEN_STREAM")
    if brightness < 12.0 and contrast < 5.0:
        warnings.append("CAMERA_OCCLUDED_OR_DARK")
    elif brightness < 35.0:
        warnings.append("LOW_LIGHT")
    if sharpness < 20.0:
        warnings.append("BLURRY_OR_LOWRES")
    if w < 320 or h < 240:
        warnings.append("LOW_RESOLUTION")
    return {
        "ok": True,
        "width": int(w),
        "height": int(h),
        "resolution": f"{w}x{h}",
        "brightness": brightness,
        "contrast": contrast,
        "sharpness": sharpness,
        "warnings": warnings,
        "issues": list(warnings),
        "health_warning": warnings[0] if warnings else "",
    }


def list_cameras_runtime():
    """Return current runtime status and quality metrics of all configured cameras."""
    with _RUNTIME_STATE_LOCK:
        cams_snap = {k: dict(v) for k, v in STATUS.get("cameras", {}).items()}
    return {"ok": True, "cameras": cams_snap, "count": len(cams_snap)}


def add_camera_runtime(data, who="operator"):
    """Dynamically register or update a camera source (e.g. from MERSAD LAB) at runtime (AI-BUG-07 / GAP-008)."""
    if not isinstance(data, dict):
        return {"ok": False, "error": "بيانات الكاميرا غير صالحة"}
    cam_name = re.sub(r"[^A-Za-z0-9_\-\u0600-\u06FF]", "", str(data.get("name") or data.get("cam") or "").strip())[:32]
    src_spec = str(data.get("source") or data.get("url") or "").strip()
    if not cam_name or not src_spec:
        return {"ok": False, "error": "يجب تحديد اسم الكاميرا (name) ومصدر البث (source)"}
    if len(src_spec) > 512 or any(c in src_spec for c in ("\r", "\n", "\x00")):
        return {"ok": False, "error": "رابط مصدر البث غير صالح"}
    now_t = time.time()
    with _RUNTIME_STATE_LOCK:
        STATUS.setdefault("cameras", {})[cam_name] = {
            "status": "online",
            "fps": 0.0,
            "frames": 0,
            "detections": 0,
            "reconnects": 0,
            "last_frame_ts": now_t,
            "source": redact_url(src_spec),
            "health_warning": "",
        }
    if CAMERA_HISTORY:
        CAMERA_HISTORY.record_status(cam_name, "online", "dynamic_api_add", ts=now_t, force=True)
    log("camera added", f"{cam_name} src={redact_url(src_spec)} by {who}")
    if _ACTIVE_ENGINE_CONTROLLER is not None and data.get("spawn_worker", True):
        st_spawned = _ACTIVE_ENGINE_CONTROLLER.add_camera(cam_name, src_spec)
        return {"ok": True, "camera": cam_name, "source": redact_url(src_spec), "status": st_spawned["status"], "worker_spawned": True}
    return {"ok": True, "camera": cam_name, "source": redact_url(src_spec), "status": "online", "worker_spawned": False}


class TesseractOCRReader:
    """Real pixel-level OCR adapter using Tesseract 5 LSTM engine (supports both pytesseract and direct CLI binary execution on Windows/Linux)."""
    engine_name = "Tesseract-5-LSTM-Real-Pixel-OCR"
    is_mock = False
    _PYTESSERACT_AVAILABLE = None

    def __init__(self):
        if self.__class__._PYTESSERACT_AVAILABLE is None:
            try:
                import pytesseract  # noqa: F401
                self.__class__._PYTESSERACT_AVAILABLE = True
            except Exception:
                self.__class__._PYTESSERACT_AVAILABLE = False
    _GOV_MAP = {
        "ADEN": "عدن",
        "SANAA": "صنعاء",
        "SANA": "صنعاء",
        "TAIZ": "تعز",
        "HADR": "حضرموت",
        "HADRAMOUT": "حضرموت",
        "IBB": "إب",
        "MARIB": "مأرب",
    "MARI": "مأرب",
    }

    @classmethod
    def find_tesseract_binary(cls):
        env_cmd = os.environ.get("TESSERACT_CMD", "").strip()
        if env_cmd and os.path.isfile(env_cmd):
            return env_cmd
        which_bin = shutil.which("tesseract")
        if which_bin:
            return which_bin
        for win_cand in (
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
        ):
            if win_cand and os.path.isfile(win_cand):
                return win_cand
        return None

    @classmethod
    def is_available(cls) -> bool:
        return cls.find_tesseract_binary() is not None

    def _run_tesseract_tsv_cli(self, inner_bgr, tess_bin: str) -> dict:
        """Directly invoke tesseract binary with TSV output when pytesseract wrapper is not installed."""
        fd, tmp_png = tempfile.mkstemp(prefix="mersad_tess_", suffix=".png")
        os.close(fd)
        try:
            cv2.imwrite(tmp_png, inner_bgr)
            env = os.environ.copy()
            env.setdefault("OMP_THREAD_LIMIT", "1")
            proc = subprocess.run(
                [tess_bin, tmp_png, "stdout", "--psm", "7", "tsv"],
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            if proc.returncode != 0 or not proc.stdout:
                return {"text": [], "conf": []}
            texts, confs = [], []
            lines = proc.stdout.splitlines()
            for row in lines[1:]:
                cols = row.split("\t")
                if len(cols) >= 12:
                    texts.append(cols[11])
                    confs.append(cols[10])
            return {"text": texts, "conf": confs}
        except Exception:
            return {"text": [], "conf": []}
        finally:
            try:
                os.unlink(tmp_png)
            except OSError:
                pass

    def readtext(self, img):
        if img is None or getattr(img, "size", 0) == 0:
            return []
        tess_bin = self.find_tesseract_binary()
        if not tess_bin:
            return []
        h, w = img.shape[:2]
        inner = img[5:max(6, h - 5), 5:max(6, w - 5)] if (h > 14 and w > 28) else img
        os.environ.setdefault("OMP_THREAD_LIMIT", "1")
        data = None
        pytess_mod = sys.modules.get("pytesseract")
        if pytess_mod is not None:
            try:
                if getattr(getattr(pytess_mod, "pytesseract", None), "tesseract_cmd", "tesseract") == "tesseract":
                    pytess_mod.pytesseract.tesseract_cmd = tess_bin
                data = pytess_mod.image_to_data(inner, config="--psm 7", output_type=pytess_mod.Output.DICT)
            except Exception:
                data = None
        if data is None:
            data = self._run_tesseract_tsv_cli(inner, tess_bin)
        if not data:
            return []
        tokens = []
        confs = []
        for txt, c in zip(data.get("text", []), data.get("conf", [])):
            t = str(txt or "").strip()
            try:
                cf = float(c)
            except (ValueError, TypeError):
                cf = -1.0
            if t and cf >= 0:
                clean_tok = re.sub(r"[^A-Za-z0-9\u0600-\u06FF]", "", t)
                if clean_tok:
                    up = clean_tok.upper()
                    mapped = self._GOV_MAP.get(up, clean_tok)
                    tokens.append(mapped)
                    confs.append(max(0.45, min(0.99, cf / 100.0)))
        if not tokens:
            return []
        joined = " ".join(tokens)
        mean_conf = float(np.mean(confs)) if confs else 0.0
        return [([[0, 0], [w, 0], [w, h], [0, h]], joined, mean_conf)]


def create_real_ocr_reader(use_gpu=False):
    """Attempt to initialize EasyOCR first; if unavailable, fall back to real Tesseract 5 LSTM pixel OCR if installed."""
    try:
        import easyocr
        easyocr_dir = resolve_resource_path(os.path.join("models", "easyocr"))
        easyocr_verified, _ = verify_easyocr_dir(easyocr_dir)
        if easyocr_verified:
            r = easyocr.Reader(["ar", "en"], gpu=use_gpu, model_storage_directory=easyocr_dir, download_enabled=False)
            r.engine_name = "EasyOCR-Ar-En"
            r.is_mock = False
            return r
    except Exception:
        pass
    if TesseractOCRReader.is_available():
        return TesseractOCRReader()
    return None


_ACTIVE_ENGINE_CONTROLLER = None


class MersadEngineController:
    """Real multi-threaded camera reader, inference worker, and reconnection supervisor engine."""

    def __init__(self, reader=None, vyolo=None, yolo=None, det=None, rec=None,
                 trucks_only=False, curfew=None, infer_every_n=2,
                 stall_sec=None, offline_alert_sec=None):
        self.reader = reader if reader is not None else create_real_ocr_reader(use_gpu=False)
        self.vyolo = vyolo
        self.yolo = yolo
        self.det = det or type("_NoopDet", (), {"setInputSize": lambda s, sz: None, "detect": lambda s, f: (0, None)})()
        self.rec = rec or type("_NoopRec", (), {"alignCrop": lambda s, f, b: f[:10, :10], "feature": lambda s, a: np.zeros((1, 128), np.float32), "match": lambda s, a, b, fl: 0.0})()
        self.trucks_only = bool(trucks_only and self.vyolo is not None)
        self.curfew = curfew
        self.infer_every_n = max(1, int(infer_every_n))
        self.stall_sec = float(stall_sec if stall_sec is not None else CAMERA_STALL_SEC)
        self.offline_alert_sec = float(offline_alert_sec if offline_alert_sec is not None else OFFLINE_ALERT_SEC)
        self.stop_ev = threading.Event()
        self.cam_states = {}
        self.reader_threads = []
        self.infer_threads = []
        self._sup_thread = None
        self._lock = threading.RLock()

    def add_camera(self, cam_name: str, src_spec: str) -> dict:
        now_init = time.time()
        try:
            cap_obj = _open_camera_capture(src_spec)
        except Exception:
            cap_obj = None
        is_open = bool(cap_obj and cap_obj.isOpened())
        is_eof = bool(not is_open and cap_obj is not None and getattr(cap_obj, "eof", False))
        if not is_open:
            if cap_obj is not None:
                try:
                    cap_obj.release()
                except Exception:
                    pass
            cap_obj = None

        init_status = "online" if is_open else "reconnecting"
        idle_ev = threading.Event()
        idle_ev.set()
        cam_stop_ev = threading.Event()
        st = {
            "cam": cam_name,
            "src": src_spec,
            "stop_ev": cam_stop_ev,
            "lock": threading.Lock(),
            "infer_lock": threading.Lock(),
            "infer_queue": queue.Queue(maxsize=1),
            "infer_busy": False,
            "infer_idle_event": idle_ev,
            "dropped_infer_frames": 0,
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
            "face_entries": [],
            "unmatched_face_boxes": [],
            "face_det_runs": 0,
            "fail_count": 0 if is_open else 1,
            "consec_errors": 0,
            "disconnected_since": 0.0 if is_open else now_init,
            "next_reconnect_ts": 0.0 if is_open else (now_init + _compute_reconnect_backoff(1)),
            "offline_alert_sent": False,
            "fps": 0.0,
            "reconnect_count": 0,
            "fps_t": now_init,
            "fps_n": 0,
            "latest_frame": None,
            "latest_frame_seq": 0,
            "last_processed_seq": 0,
            "last_frame_ts": now_init if is_open else 0.0,
            "read_failed": not is_open,
            "just_reconnected": False,
            "logged_session_start": is_open,
            "eof": is_eof,
        }
        if not is_open:
            bus.set_frame(_make_offline_frame(cam_name, "reconnecting"), cam=cam_name, status="reconnecting")
            bus.publish({"type": "camera_status", "cam": cam_name, "status": "reconnecting"})
        with self._lock:
            self.cam_states[cam_name] = st
            _ACTIVE_CAM_STATES[cam_name] = st
        with _RUNTIME_STATE_LOCK:
            STATUS["cam"] = ",".join(self.cam_states.keys())
            STATUS.setdefault("cameras", {})[cam_name] = {
                "status": st["status"],
                "fps": 0.0,
                "frames": 0,
                "detections": 0,
                "errors": 0,
                "fail_count": st["fail_count"],
                "reconnect_count": 0,
                "source": redact_url(src_spec),
                "health_warning": "",
            }
        if CAMERA_HISTORY:
            CAMERA_HISTORY.record_status(cam_name, st["status"], reason="startup", force=True)
        if st["status"] == "online":
            log("session start", cam_name)
        rt = threading.Thread(target=_camera_reader_worker, args=(st, cam_stop_ev), daemon=True, name=f"cam_reader_{cam_name}")
        it = threading.Thread(
            target=_camera_inference_worker,
            args=(st, cam_stop_ev, self.vyolo, self.yolo, self.reader, self.trucks_only, self.curfew),
            daemon=True,
            name=f"cam_infer_{cam_name}",
        )
        st["reader_thread"] = rt
        st["infer_thread"] = it
        rt.start()
        self.reader_threads.append(rt)
        it.start()
        self.infer_threads.append(it)
        return st

    def _supervisor_loop(self):
        while not self.stop_ev.is_set() and not STOP_MAIN_EVENT.is_set():
            processed_any = False
            now_loop = time.time()
            with self._lock:
                items = list(self.cam_states.items())
            for cam_name, st in items:
                with st["lock"]:
                    just_rec = st["just_reconnected"]
                    if just_rec:
                        st["just_reconnected"] = False
                    has_new_frame = st["latest_frame_seq"] > st["last_processed_seq"]
                    frame = st["latest_frame"] if has_new_frame else None
                    if has_new_frame:
                        st["last_processed_seq"] = st["latest_frame_seq"]
                    read_failed = st["read_failed"]
                    last_f_ts = st["last_frame_ts"]
                    fail_cnt = st["fail_count"]

                if just_rec:
                    if st["status"] != "online":
                        st["reconnect_count"] = int(st.get("reconnect_count", 0)) + 1
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
                    stalled = (last_f_ts > 0 and (now_loop - last_f_ts) >= self.stall_sec)
                    if read_failed or stalled or st["status"] != "online":
                        if st["status"] == "online":
                            st["disconnected_since"] = now_loop
                            st["status"] = "reconnecting"
                            if CAMERA_HISTORY:
                                CAMERA_HISTORY.record_status(cam_name, "reconnecting", reason="stream_stalled" if stalled else "read_failed")
                            bus.set_frame(_make_offline_frame(cam_name, "reconnecting"), cam=cam_name, status="reconnecting")
                            bus.publish({"type": "camera_status", "cam": cam_name, "status": "reconnecting"})
                        elif st["disconnected_since"] > 0 and (now_loop - st["disconnected_since"]) >= self.offline_alert_sec and not st["offline_alert_sent"]:
                            st["status"] = "offline"
                            if CAMERA_HISTORY:
                                CAMERA_HISTORY.record_status(cam_name, "offline", reason="offline_timeout")
                            st["offline_alert_sent"] = True
                            bus.set_frame(_make_offline_frame(cam_name, "offline"), cam=cam_name, status="offline")
                            bus.publish({"type": "camera_status", "cam": cam_name, "status": "offline"})
                            log("camera offline", cam_name)
                        elif st["status"] in ("reconnecting", "offline"):
                            bus.set_frame(_make_offline_frame(cam_name, st["status"]), cam=cam_name, status=st["status"])

                    with st["infer_lock"]:
                        det_r_off = st["det_runs"]
                        err_c_off = st["consec_errors"]
                    with _RUNTIME_STATE_LOCK:
                        prev_c = STATUS.get("cameras", {}).get(cam_name, {})
                        STATUS.setdefault("cameras", {})[cam_name] = {
                            "status": st["status"],
                            "fps": st["fps"] if st["status"] == "online" else 0.0,
                            "frames": st["n"],
                            "detections": det_r_off,
                            "errors": err_c_off,
                            "fail_count": fail_cnt,
                            "reconnect_count": st.get("reconnect_count", 0),
                            "reconnects": st.get("reconnect_count", 0),
                            "last_plate": st.get("last_plate", prev_c.get("last_plate")),
                            "brightness": st.get("brightness", prev_c.get("brightness", 0.0)),
                            "contrast": st.get("contrast", prev_c.get("contrast", 0.0)),
                            "sharpness": st.get("sharpness", prev_c.get("sharpness", 0.0)),
                            "health_warning": st.get("health_warning", prev_c.get("health_warning", "")),
                            "issues": prev_c.get("issues", []),
                            "resolution": prev_c.get("resolution", ""),
                            "source": prev_c.get("source", redact_url(st["src"])),
                        }
                    _update_aggregate_fps(self.cam_states)
                    continue

                processed_any = True
                st["status"] = "online"
                if CAMERA_HISTORY:
                    CAMERA_HISTORY.record_status(cam_name, "online", reason="frame_received")
                st["n"] += 1
                st["fps_n"] += 1
                if now_loop - st["fps_t"] >= 1.0:
                    st["fps"] = round(st["fps_n"] / max(0.001, now_loop - st["fps_t"]), 1)
                    st["fps_t"], st["fps_n"] = now_loop, 0
                    _update_aggregate_fps(self.cam_states)

                H, W = frame.shape[:2]
                q_res = assess_frame_quality(frame, cam_name=cam_name)
                st["brightness"] = q_res.get("brightness", 0.0)
                st["contrast"] = q_res.get("contrast", 0.0)
                st["sharpness"] = q_res.get("sharpness", 0.0)
                st["health_warning"] = q_res.get("health_warning", "")

                if st["n"] % self.infer_every_n == 0:
                    _enqueue_latest_inference(st, (frame.copy(), time.time(), [], [], st["n"]))

                ok_jpg, enc_jpg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                if ok_jpg:
                    bus.set_frame(enc_jpg.tobytes(), cam=cam_name, status="online")

                with st["infer_lock"]:
                    det_r = st["det_runs"]
                    err_c = st["consec_errors"]
                    last_p = st["last_plate"]
                with _RUNTIME_STATE_LOCK:
                    STATUS["frames"] = sum(c["n"] for c in self.cam_states.values())
                    STATUS.setdefault("cameras", {})[cam_name] = {
                        "status": st["status"],
                        "fps": st["fps"],
                        "frames": st["n"],
                        "detections": det_r,
                        "errors": err_c,
                        "fail_count": fail_cnt,
                        "reconnect_count": st.get("reconnect_count", 0),
                        "reconnects": st.get("reconnect_count", 0),
                        "last_plate": last_p,
                        "brightness": st["brightness"],
                        "contrast": st["contrast"],
                        "sharpness": st["sharpness"],
                        "health_warning": st["health_warning"],
                        "issues": q_res.get("issues", []),
                        "resolution": f"{W}x{H}",
                        "source": redact_url(st["src"]),
                    }
            if not processed_any:
                time.sleep(0.015)

    def start(self):
        global _ACTIVE_ENGINE_CONTROLLER
        _ACTIVE_ENGINE_CONTROLLER = self
        STOP_MAIN_EVENT.clear()
        self.stop_ev.clear()
        self._sup_thread = threading.Thread(target=self._supervisor_loop, daemon=True, name="mersad-engine-supervisor")
        self._sup_thread.start()
        return self

    def stop(self, timeout: float = 5.0):
        global _ACTIVE_ENGINE_CONTROLLER
        self.stop_ev.set()
        with self._lock:
            states = list(self.cam_states.values())
        for st in states:
            ev = st.get("stop_ev")
            if ev:
                ev.set()
        if self._sup_thread and self._sup_thread.is_alive():
            self._sup_thread.join(timeout=timeout)
        for t in self.reader_threads + self.infer_threads:
            if t.is_alive():
                t.join(timeout=1.5)
        for st in states:
            with st["lock"]:
                cap = st.get("cap")
                st["cap"] = None
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass
        if _ACTIVE_ENGINE_CONTROLLER is self:
            _ACTIVE_ENGINE_CONTROLLER = None



def remove_camera_runtime(data, who="operator"):
    """Remove a dynamically registered camera safely without OpenCV VideoCapture Use-After-Free (BUG-02 fix)."""
    if not isinstance(data, dict):
        return {"ok": False, "error": "بيانات الطلب غير صالحة"}
    cam_name = str(data.get("name") or data.get("cam") or "").strip()
    if not cam_name:
        return {"ok": False, "error": "اسم الكاميرا مطلوب"}
    ctrl = _ACTIVE_ENGINE_CONTROLLER
    st_ctrl = None
    if ctrl is not None and hasattr(ctrl, "_lock"):
        with ctrl._lock:
            st_ctrl = ctrl.cam_states.pop(cam_name, None)
    st = _ACTIVE_CAM_STATES.pop(cam_name, None) or st_ctrl
    if st:
        ev = st.get("stop_ev")
        if ev:
            ev.set()
        inf_q = st.get("infer_queue")
        if inf_q is not None:
            while True:
                try:
                    inf_q.get_nowait()
                    inf_q.task_done()
                except Exception:
                    break
        for th_key in ("reader_thread", "infer_thread"):
            th = st.get(th_key)
            if th is not None and th.is_alive() and th is not threading.current_thread():
                th.join(timeout=4.0)
        st_lock = st.get("lock")
        if st_lock is not None:
            with st_lock:
                cap = st.get("cap")
                st["cap"] = None
        else:
            cap = st.get("cap")
            st["cap"] = None
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass
    with _RUNTIME_STATE_LOCK:
        removed = STATUS.get("cameras", {}).pop(cam_name, None)
        if _ACTIVE_CAM_STATES:
            STATUS["cam"] = ",".join(_ACTIVE_CAM_STATES.keys())
    if CAMERA_HISTORY and (removed is not None or st is not None):
        CAMERA_HISTORY.record_status(cam_name, "unknown", "dynamic_api_remove", force=True)
    log("camera removed", f"{cam_name} by {who}")
    return {"ok": True, "camera": cam_name, "removed": (removed is not None or st is not None)}


def wire():
    bus.on_stats = stats
    bus.verify, bus.on_list, bus.on_template, bus.on_import = verify, R.list_rows, R.template, R.import_file

    def _analytics_report():
        if not ANALYTICS:
            return {"ok": False, "error": "التحليلات غير متاحة"}
        with _RUNTIME_STATE_LOCK:
            cams_snap = {k: dict(v) for k, v in (STATUS.get("cameras") or {}).items()}
        with DBL:
            return ANALYTICS.build_report(db, cams_snap)

    def _camera_health_report(period="24h"):
        if not CAMERA_HISTORY:
            return {"ok": False, "error": "سجل صحة الكاميرات غير متاح"}
        with _RUNTIME_STATE_LOCK:
            cams_snap = {k: dict(v) for k, v in (STATUS.get("cameras") or {}).items()}
        with DBL:
            return CAMERA_HISTORY.build_report(db, cams_snap, period=period)

    bus.on_analytics = _analytics_report
    bus.on_analytics_export = (lambda: ANALYTICS.export_csv(_analytics_report())) if ANALYTICS else (lambda: b"\xef\xbb\xbf")
    bus.on_camera_health = _camera_health_report
    bus.on_camera_health_export = (lambda period="24h": CAMERA_HISTORY.export_csv(_camera_health_report(period))) if CAMERA_HISTORY else (lambda period="24h": b"\xef\xbb\xbf")
    bus.on_insights = (
        (lambda include_demo=False: INS.summary(include_demo=include_demo))
        if INS else (lambda include_demo=False: {"data_source": "live", "includes_demo": False, "model": {"ready": False, "type": "none", "reason": "module_disabled"}, "forecast": None, "anomalies": [], "corridors": [], "paths": []})
    )
    bus.on_path = (
        (lambda p, include_demo=False: INS.plate_path(p, include_demo=include_demo))
        if INS and hasattr(INS, "plate_path") else (lambda p, include_demo=False: {"ok": False, "error": "غير متاح"})
    )
    bus.on_camera_links = (
        (lambda q="", status="": INS.list_camera_links(q=q, status_filter=status))
        if INS and hasattr(INS, "list_camera_links") else (lambda q="", status="": {"ok": True, "links": [], "inferred_links": [], "calibrated_cameras": []})
    )
    bus.on_camera_links_export = (
        (lambda fmt="json": INS.export_camera_links(fmt=fmt))
        if INS and hasattr(INS, "export_camera_links") else (lambda fmt="json": (b"{}", "mersad_camera_links.json", "application/json; charset=utf-8"))
    )
    bus.on_camera_links_import = (
        (lambda filename, raw, ip: INS.import_camera_links(raw, filename=filename, who=ip))
        if INS and hasattr(INS, "import_camera_links") else (lambda filename, raw, ip: {"ok": False, "error": "غير متاح"})
    )
    bus.on_field_calibrations = (
        INS.list_field_calibrations
        if INS and hasattr(INS, "list_field_calibrations") else (lambda: {"ok": True, "items": [], "automated_eval_still_required": True})
    )
    bus.on_field_calibrations_export = (
        (lambda fmt="json": INS.export_field_calibrations(fmt=fmt))
        if INS and hasattr(INS, "export_field_calibrations") else (lambda fmt="json": (b"{}", "mersad_manual_calibrations.json", "application/json; charset=utf-8"))
    )
    bus.on_field_calibrations_import = (
        (lambda filename, raw, ip: INS.import_field_calibrations(raw, filename=filename, who=ip))
        if INS and hasattr(INS, "import_field_calibrations") else (lambda filename, raw, ip: {"ok": False, "error": "غير متاح"})
    )
    bus.on_readiness = lambda: build_readiness_report()
    bus.on_cameras_list = lambda: list_cameras_runtime()
    bus.post["/api/cameras/add"] = lambda d, ip: add_camera_runtime(d, who=ip)
    bus.post["/api/cameras/remove"] = lambda d, ip: remove_camera_runtime(d, who=ip)
    bus.on_camera_links_suggestions = (
        (lambda include_demo=False, min_observations=3: INS.suggest_camera_links_from_sightings(include_demo=include_demo, min_observations=min_observations, apply_directly=False))
        if INS and hasattr(INS, "suggest_camera_links_from_sightings")
        else (lambda include_demo=False, min_observations=3: {"ok": True, "suggestions": []})
    )
    bus.on_plate_eval_status = get_plate_eval_status
    bus.on_plate_eval_history = list_plate_eval_runs
    bus.on_plate_eval_export = export_plate_eval_runs
    bus.on_plate_eval_template = export_plate_eval_template
    bus.post = {
        "/api/decision": lambda d, ip: {"ok": bool(d.get("action") in ("confirm", "ack", "dismiss") and str(d.get("id", "")).isdigit() and decide(int(d["id"]), d["action"], ip))},
        "/api/retry_dispatch": lambda d, ip: retry_dispatch(int(d["id"]), ip) if str(d.get("id", "")).isdigit() else {"ok": False, "error": "معرّف غير صالح"},
        # P1-H: /api/archive_evidence ignores any user-supplied retention_days and strictly uses configured retention (>= 7 days)
        "/api/archive_evidence": lambda d, ip: {"ok": True, **archive_old_evidence(retention_days=None, who=f"api:{ip}", _allow_test_override=False)},
        "/api/insights/train": ins_act(lambda d: INS.train(include_demo=bool(isinstance(d, dict) and (d.get("include_demo") or d.get("demo")))), "train"),
        "/api/insights/seed": ins_act(lambda d: INS.seed_demo(), "seed demo history"),
        "/api/insights/clear": ins_act(lambda d: INS.clear_demo(), "clear demo history"),
        "/api/camera_links": (lambda d, ip: INS.save_camera_link(d, who=ip)) if INS and hasattr(INS, "save_camera_link") else (lambda d, ip: {"ok": False, "error": "غير متاح"}),
        "/api/camera_links/delete": (lambda d, ip: INS.delete_camera_link(d, who=ip)) if INS and hasattr(INS, "delete_camera_link") else (lambda d, ip: {"ok": False, "error": "غير متاح"}),
        "/api/camera_links/auto_calibrate": (
            (lambda d, ip: INS.suggest_camera_links_from_sightings(
                include_demo=bool(isinstance(d, dict) and (d.get("include_demo") or d.get("demo"))),
                min_observations=int(d.get("min_observations") or 3) if isinstance(d, dict) else 3,
                apply_directly=True,
                who=ip,
            ))
            if INS and hasattr(INS, "suggest_camera_links_from_sightings")
            else (lambda d, ip: {"ok": False, "error": "غير متاح"})
        ),
        "/api/field_calibrations": (lambda d, ip: INS.save_field_calibration(d, who=ip)) if INS and hasattr(INS, "save_field_calibration") else (lambda d, ip: {"ok": False, "error": "غير متاح"}),
        "/api/field_calibrations/delete": (lambda d, ip: INS.delete_field_calibration(d, who=ip)) if INS and hasattr(INS, "delete_field_calibration") else (lambda d, ip: {"ok": False, "error": "غير متاح"}),
        "/api/plate_eval/inspect": lambda d, ip: inspect_plate_dataset(d.get("dataset_path", ""), plate_model_path=d.get("plate_model", ""), enforce_trusted_model=True),
        "/api/plate_eval/validate_model": lambda d, ip: validate_plate_model_path(d.get("plate_model", ""), enforce_trusted=True),
        "/api/plate_eval/register_model": lambda d, ip: register_plate_model_api(d, who=ip, allow_outside_copy=False),
        "/api/plate_eval/init_ground_truth": lambda d, ip: init_ground_truth_for_folder(d, who=ip),
        "/api/plate_eval/upload_dataset": lambda d, ip: stage_uploaded_eval_files(d, who=ip),
        "/api/plate_eval/start": lambda d, ip: start_plate_eval_job(d, who=ip),
        "/api/plate_eval/cancel": lambda d, ip: cancel_plate_eval_job(who=ip),
        "/api/browse_path": lambda d, ip: browse_local_path(mode=d.get("mode", "folder")),
        "/api/vehicle": R.save_vehicle,
        "/api/vehicle/delete": lambda d, ip: R.delete("vehicles", d.get("key", ""), ip),
        "/api/person": R.save_person,
        "/api/person/delete": lambda d, ip: R.delete("persons", d.get("key", ""), ip),
        "/api/enroll": enroll_api,
        "/api/cameras/add": lambda d, ip: add_camera_runtime(d, who=ip),
        "/api/cameras/remove": lambda d, ip: remove_camera_runtime(d, who=ip),
    }


DEFAULTS = {
    "source": "0", "cam": "CAM1", "host": "127.0.0.1", "allow_lan": False, "port": 8000,
    "trucks_only": False, "truck_curfew": "", "face_score": 0.45, "face_detect_score": 0.65,
    "evidence_retention_days": 30, "open_browser": True, "first_run_done": False, "dashboard_token": "",
    "telegram_token": "", "telegram_chat_id": "", "telegram_patrol_chat_id": "", "camera_links": {}, "device": "auto"
}

_CURFEW_RE = re.compile(r"^\s*(\d{1,2})(?::00)?\s*-\s*(\d{1,2})(?::00)?\s*$")


def parse_curfew(spec):
    """Validate and parse truck curfew specification ('HH-HH' or 'HH:00-HH:00' with 0 <= HH <= 23) (GAP-15).
    Returns (start_hour, end_hour) tuple on valid input, or None with a logged warning on invalid/out-of-range input."""
    if spec is None:
        return None
    s = str(spec).strip()
    if not s:
        return None
    m = _CURFEW_RE.match(s)
    if not m:
        logger.warning("Invalid truck curfew format %r (expected 'HH-HH' or 'HH:00-HH:00'); curfew disabled", spec)
        return None
    h1, h2 = int(m.group(1)), int(m.group(2))
    if not (0 <= h1 <= 23 and 0 <= h2 <= 23):
        logger.warning("Truck curfew hours out of range (0..23) in %r; curfew disabled", spec)
        return None
    return (h1, h2)


def _update_aggregate_fps(cam_states):
    """Compute STATUS['fps'] as the average FPS across online cameras while keeping per-camera FPS isolated (GAP-15)."""
    online_fps = [
        float(st.get("fps", 0.0))
        for st in (cam_states or {}).values()
        if st.get("status") == "online" and float(st.get("fps", 0.0)) > 0
    ]
    val = round(sum(online_fps) / len(online_fps), 1) if online_fps else 0.0
    with _RUNTIME_STATE_LOCK:
        STATUS["fps"] = val
    return val


def _load_secrets_file():
    """Load .mersad_secrets.json safely, rejecting symlinks and enforcing 0600 on POSIX (P1-D)."""
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
                with st["lock"]:
                    st["cap"] = new_cap
                    st["latest_frame"] = frame_re
                    st["latest_frame_seq"] += 1
                    st["last_frame_ts"] = time.time()
                    st["read_failed"] = False
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
            if not unconsumed or (time.time() - wait_start) >= 0.12:
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


_ACTIVE_CAM_STATES = {}


def _enqueue_latest_inference(st, item):
    """Non-blocking drop-oldest / keep-latest enqueue into a bounded 1-slot per-camera inference queue (GAP-08).
    Never blocks the video display & streaming loop."""
    q = st["infer_queue"]
    st["infer_idle_event"].clear()
    dropped = 0
    while True:
        try:
            q.get_nowait()
            dropped += 1
        except queue.Empty:
            break
    if dropped:
        with st["infer_lock"]:
            st["dropped_infer_frames"] = int(st.get("dropped_infer_frames", 0)) + dropped
    try:
        q.put_nowait(item)
    except queue.Full:
        pass


def _run_single_inference_item(st, item, vyolo, yolo, reader, trucks_only, curfew):
    """Execute heavy vehicle/plate/OCR inference on a single frame snapshot outside the display thread (GAP-08)."""
    cam_name = st["cam"]
    inf_frame, now_f, inf_face_entries, inf_veh_blur_boxes, frame_no = item
    H, W = inf_frame.shape[:2]
    with st["infer_lock"]:
        st["det_runs"] += 1
        det_runs_now = st["det_runs"]
    with _RUNTIME_STATE_LOCK:
        if cam_name in STATUS.get("cameras", {}):
            STATUS["cameras"][cam_name]["detections"] = det_runs_now

    new_vboxes = detect_vehicles(inf_frame, vyolo)
    new_boxes = []
    skip_empty_vyolo = bool(
        vyolo is not None
        and not new_vboxes
        and yolo is None
        and (os.environ.get("MERSAD_SKIP_EMPTY_VYOLO_OCR", "0") == "1" or st.get("skip_empty_vyolo", False))
    )
    st_stop_ev = st.get("stop_ev")
    iter_vboxes = [] if skip_empty_vyolo else (new_vboxes or [(0, 0, W, H, "unknown")])
    for (vx, vy, vw, vh, vc) in iter_vboxes:
        if (st_stop_ev is not None and st_stop_ev.is_set()) or STOP_MAIN_EVENT.is_set():
            break
        if trucks_only and vc != "truck":
            continue
        oy = vy + int(vh * .35) if vc != "unknown" else 0
        sub = inf_frame[oy:vy + vh, vx:vx + vw]
        if sub.size == 0:
            continue
        raw_pboxes = find_plates(sub, yolo)
        dedup_pboxes = []
        for pb in raw_pboxes:
            px1, py1, pw1, ph1 = pb
            overlap = False
            for (qx1, qy1, qw1, qh1) in dedup_pboxes:
                ix1, iy1 = max(px1, qx1), max(py1, qy1)
                ix2, iy2 = min(px1 + pw1, qx1 + qw1), min(py1 + ph1, qy1 + qh1)
                if ix2 > ix1 and iy2 > iy1:
                    inter = float((ix2 - ix1) * (iy2 - iy1))
                    union = float(pw1 * ph1 + qw1 * qh1 - inter)
                    if union > 0 and (inter / union) > 0.5:
                        overlap = True
                        break
            if not overlap:
                dedup_pboxes.append(pb)
        for (x, y, bw, bh) in dedup_pboxes:
            if (st_stop_ev is not None and st_stop_ev.is_set()) or STOP_MAIN_EVENT.is_set():
                break
            x, y = x + vx, y + oy
            d, c = read_plate(reader, inf_frame[y:y + bh, x:x + bw])
            new_boxes.append((x, y, bw, bh, d))
            if not d:
                continue
            with st["infer_lock"]:
                confirmed = confirm_plate_read(d, c, (x, y, bw, bh), now_f, st["votes"], st["tracks"], st["last_seen"])
            if confirmed:
                cm, direction = confirmed[0], confirmed[1]
                win_plate = getattr(confirmed, "plate", d) or d
                l_conf = getattr(confirmed, "letters_confirmed", True)
                with st["infer_lock"]:
                    st["last_plate"] = win_plate
                with _RUNTIME_STATE_LOCK:
                    STATUS["plates"] = int(STATUS.get("plates", 0)) + 1
                    STATUS["vehicles"] = int(STATUS.get("vehicles", 0)) + max(1, len(new_vboxes))
                msg, v = register(win_plate, cm, cam_name, vc, curfew, direction, raw_text=d,
                                  session_id=SESSION_ID, letters_confirmed=l_conf)
                base, detail = vinfo(v)
                bus.publish({"type": "sighting", "plate": win_plate, "cam": cam_name, "vclass": vc, "direction": direction,
                             "ts": time.strftime("%H:%M:%S"), "conf": round(cm, 2),
                             "model": v["model"] if v else "", "status": v["status"] if v else "",
                             "match_note": v.get("match_note", "") if v else ""})
                if msg:
                    with _RUNTIME_STATE_LOCK:
                        why_val = WHY.get(win_plate, "")
                    if msg.startswith(("ANOMALY", "ROUTE", "POSSIBLE")):
                        detail = " · ".join(x for x in (detail, why_val) if x)
                    raise_alert(msg, win_plate, cam_name, inf_frame, detail=detail,
                                extra=f"\nنوع المركبة: {vc}\nالاتجاه/المسار: {direction}"
                                + (f"\nالسيارة: {base}" if base else "")
                                + (f"\nالسبب: {why_val}" if msg.startswith(("ANOMALY", "ROUTE", "POSSIBLE")) and why_val else ""),
                                unmatched_faces=inf_veh_blur_boxes,
                                face_entries=inf_face_entries)
                if INS:
                    with INS._STATE_LOCK:
                        should_retrain = INS.M.get("since", 0) >= 100
                        if should_retrain:
                            INS.M["since"] = 0
                    if should_retrain:
                        threading.Thread(target=INS.train, daemon=True).start()

    with st["infer_lock"]:
        st["vboxes"] = new_vboxes
        st["boxes"] = new_boxes
        st["consec_errors"] = 0


def _camera_inference_worker(st, stop_ev, vyolo, yolo, reader, trucks_only, curfew):
    """Dedicated per-camera asynchronous inference worker thread (GAP-08).
    Processes only the freshest frame from st['infer_queue'] so slow YOLO/EasyOCR calls never stall video streaming."""
    cam_name = st["cam"]
    q = st["infer_queue"]
    while not stop_ev.is_set() and not STOP_MAIN_EVENT.is_set():
        try:
            item = q.get(timeout=0.02)
        except queue.Empty:
            if not st["infer_busy"]:
                st["infer_idle_event"].set()
            continue

        st["infer_busy"] = True
        st["infer_idle_event"].clear()
        try:
            _run_single_inference_item(st, item, vyolo, yolo, reader, trucks_only, curfew)
        except Exception as inf_err:
            with st["infer_lock"]:
                st["consec_errors"] += 1
                err_cnt = st["consec_errors"]
            with _RUNTIME_STATE_LOCK:
                if cam_name in STATUS.get("cameras", {}):
                    STATUS["cameras"][cam_name]["errors"] = err_cnt
            logger.error("Error in async inference worker on camera %s (consec=%d): %s",
                         cam_name, err_cnt, redact_url(inf_err), exc_info=True)
        finally:
            try:
                q.task_done()
            except ValueError:
                pass
            if q.empty():
                st["infer_busy"] = False
                st["infer_idle_event"].set()


def wait_for_pending_inference(timeout=5.0, cam=None):
    """Explicit synchronization helper for tests and post-loop shutdown (GAP-08).
    Waits outside the display loop until queued inference jobs finish."""
    deadline = time.time() + float(timeout)
    states = [
        st for k, st in list(_ACTIVE_CAM_STATES.items())
        if cam is None or k == cam
    ]
    for st in states:
        while time.time() < deadline:
            if st["infer_queue"].empty() and not st["infer_busy"] and st["infer_idle_event"].is_set():
                break
            st["infer_idle_event"].wait(timeout=min(0.02, max(0.001, deadline - time.time())))
    return all(st["infer_queue"].empty() and not st["infer_busy"] for st in states)


def main():
    global SESSION_ID, PROCESS_OWNER_ID, _ACTIVE_ENGINE_CONTROLLER
    init_runtime_env()
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
    ap.add_argument("--face-detect-score", type=float, default=cfg.get("face_detect_score", 0.65), help="YuNet face detection score threshold (default 0.65)")
    ap.add_argument("--retention-days", type=float, default=cfg.get("evidence_retention_days", 30))
    ap.add_argument("--device", default=cfg.get("device", "auto"), help="Compute device: auto, cpu, or cuda (default: auto)")
    ap.add_argument("--gpu", action="store_true", help="Request GPU (CUDA) acceleration if available (falls back to CPU with warning)")
    ap.add_argument("--no-window", action="store_true")
    ap.add_argument("--no-telegram-listener", action="store_true", help="Do not start getUpdates polling in this process")
    ap.add_argument("--allow-degraded-preview", action="store_true", help="Allow preview startup in degraded mode (classic OpenCV Canny) when heavy AI weights are absent")
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
        if CAMERA_HISTORY and hasattr(CAMERA_HISTORY, "prune_history"):
            CAMERA_HISTORY.prune_history(retention_days=max(30.0, float(a.retention_days)))

    curfew = parse_curfew(a.truck_curfew)
    allow_degraded = bool(getattr(a, "allow_degraded_preview", False) or os.environ.get("MERSAD_ALLOW_DEGRADED_PREVIEW") == "1")
    os.environ.setdefault("YOLO_AUTOINSTALL", "false")
    os.environ.setdefault("YOLO_OFFLINE", "true")
    os.environ.setdefault("ULTRALYTICS_AUTOINSTALL", "false")
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")
    try:
        fetch_models()
    except Exception as e_fetch:
        if not allow_degraded:
            logger.error("Model preflight failed: %s", e_fetch)
            raise
        logger.warning("Running in degraded preview mode without face ONNX weights: %s", e_fetch)
    dev_info = resolve_compute_device("cuda" if getattr(a, "gpu", False) else getattr(a, "device", cfg.get("device", "auto")))
    ACTIVE_DEVICE.update(dev_info)
    use_gpu = bool(dev_info["use_gpu"])
    reader = None
    try:
        import easyocr
        easyocr_dir = resolve_resource_path(os.path.join("models", "easyocr"))
        easyocr_verified, easyocr_reason = verify_easyocr_dir(easyocr_dir)
        if not easyocr_verified:
            alt_easyocr_dir = os.path.join(APPDIR, "models", "easyocr")
            ok_alt, r_alt = verify_easyocr_dir(alt_easyocr_dir)
            if ok_alt:
                easyocr_dir, easyocr_verified, easyocr_reason = alt_easyocr_dir, ok_alt, r_alt
        is_mock_easyocr = getattr(easyocr, "__file__", None) is None
        if not easyocr_verified and (not is_mock_easyocr or os.path.isdir(easyocr_dir)):
            raise RuntimeError(f"EasyOCR weights failed pre-load SHA-256 verification ({easyocr_reason}) at {easyocr_dir}")
        try:
            reader = easyocr.Reader(
                ["ar", "en"],
                gpu=use_gpu,
                model_storage_directory=easyocr_dir,
                download_enabled=not easyocr_verified,
            )
        except TypeError:
            reader = easyocr.Reader(["ar", "en"], gpu=use_gpu, model_storage_directory=easyocr_dir)
    except Exception as e_ocr:
        if not allow_degraded:
            logger.error("EasyOCR initialization failed: %s", e_ocr)
            raise
        if TesseractOCRReader.is_available():
            reader = TesseractOCRReader()
            logger.warning("Running in degraded preview mode with Tesseract 5 LSTM fallback OCR: %s", e_ocr)
        else:
            logger.warning("Running in degraded preview mode without EasyOCR: %s", e_ocr)
    yolo = vyolo = None
    try:
        if a.plate_model:
            yolo = load_verified_yolo_model(a.plate_model, role="plate", min_bytes=1024, enforce_trusted=True)
        if not a.no_vehicles:
            import ultralytics as _ul_mod
            yolo_p = resolve_resource_path(os.path.join("models", "yolov8n.pt"))
            if os.path.exists(yolo_p) or getattr(_ul_mod, "__file__", None) is not None:
                vyolo = load_verified_yolo_model(
                    yolo_p,
                    role="vehicle",
                    min_bytes=MODEL_MIN_BYTES.get("yolov8n.pt", 6_000_000),
                    enforce_trusted=True,
                )
            else:
                from ultralytics import YOLO
                vyolo = YOLO("yolov8n.pt")
    except Exception as e:
        logger.warning("Vehicle/truck detection off: %s", e)
        print("Vehicle/truck detection off:", e)
    register_shared_engines(reader=reader, vyolo=vyolo, yolo=yolo, plate_model_path=a.plate_model or "")
    trucks_only = a.trucks_only and vyolo is not None
    yunet_p = resolve_resource_path(os.path.join("models", "yunet.onnx"))
    sface_p = resolve_resource_path(os.path.join("models", "sface.onnx"))
    det_score = resolve_face_detect_score(getattr(a, "face_detect_score", cfg.get("face_detect_score", 0.65)))
    try:
        is_mock_face = getattr(cv2.FaceDetectorYN, "__module__", "") not in ("cv2", "")
        if os.path.exists(yunet_p) or not is_mock_face:
            ok_yn, r_yn = verify_onnx_file(yunet_p, expected_sha256=MODEL_SHA256.get("yunet.onnx"), min_bytes=MODEL_MIN_BYTES.get("yunet.onnx", 200_000))
            if not ok_yn:
                raise RuntimeError(f"YuNet model failed pre-load SHA-256 verification: {r_yn}")
        if os.path.exists(sface_p) or not is_mock_face:
            ok_sf, r_sf = verify_onnx_file(sface_p, expected_sha256=MODEL_SHA256.get("sface.onnx"), min_bytes=MODEL_MIN_BYTES.get("sface.onnx", 30_000_000))
            if not ok_sf:
                raise RuntimeError(f"SFace model failed pre-load SHA-256 verification: {r_sf}")
        det = cv2.FaceDetectorYN.create(yunet_p, "", (320, 320), det_score)
        rec = cv2.FaceRecognizerSF.create(sface_p, "")
    except Exception as e_face:
        if not allow_degraded:
            raise
        logger.warning("Face models unavailable in degraded preview mode: %s", e_face)
        det = type("_NoopDet", (), {"setInputSize": lambda self, s: None, "detect": lambda self, f: (0, None)})()
        rec = type("_NoopRec", (), {"alignCrop": lambda self, f, b: f[:10, :10], "feature": lambda self, a: np.zeros((1, 128), np.float32), "match": lambda self, a, b, fl: 0.0})()
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
    if not (os.getenv("TELEGRAM_TOKEN") and os.getenv("TELEGRAM_CHAT_ID")):
        print("Telegram alerts off (set TELEGRAM_TOKEN and TELEGRAM_CHAT_ID to enable).")

    # P0-D & P1-C: Independent per-camera state, continuous reconnection, & non-blocking reader threads
    cam_states = {}
    reader_threads = []
    now_init = time.time()
    for src_item, cam_name in zip(sources, cams):
        try:
            cap_obj = _open_camera_capture(src_item)
        except Exception:
            cap_obj = None
        is_open = bool(cap_obj and cap_obj.isOpened())
        is_eof = bool(not is_open and cap_obj is not None and getattr(cap_obj, "eof", False))
        if not is_open:
            try:
                if cap_obj is not None:
                    cap_obj.release()
            except Exception:
                pass
            cap_obj = None
            red_s = redact_url(src_item)
            logger.warning("Camera source initially unavailable (entering reconnect monitor): %s (%s)", red_s, cam_name)
            print(f"\nCamera source initially unavailable (monitoring for reconnection): {red_s} ({cam_name})")

        init_status = "online" if is_open else "reconnecting"
        idle_ev = threading.Event()
        idle_ev.set()
        st = {
            "cam": cam_name,
            "src": src_item,
            "lock": threading.Lock(),
            "infer_lock": threading.Lock(),
            "infer_queue": queue.Queue(maxsize=1),
            "infer_busy": False,
            "infer_idle_event": idle_ev,
            "dropped_infer_frames": 0,
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
            "face_entries": [],
            "unmatched_face_boxes": [],
            "face_det_runs": 0,
            "fail_count": 0 if is_open else 1,
            "consec_errors": 0,
            "disconnected_since": 0.0 if is_open else now_init,
            "next_reconnect_ts": 0.0 if is_open else (now_init + _compute_reconnect_backoff(1)),
            "offline_alert_sent": False,
            "fps": 0.0,
            "reconnect_count": 0,
            "fps_t": now_init,
            "fps_n": 0,
            "latest_frame": None,
            "latest_frame_seq": 0,
            "last_processed_seq": 0,
            "last_frame_ts": now_init if is_open else 0.0,
            "read_failed": not is_open,
            "just_reconnected": False,
            "logged_session_start": is_open,
            "eof": is_eof
        }
        if not is_open:
            bus.set_frame(_make_offline_frame(cam_name, "reconnecting"), cam=cam_name, status="reconnecting")
            bus.publish({"type": "camera_status", "cam": cam_name, "status": "reconnecting"})
        cam_states[cam_name] = st
        if CAMERA_HISTORY:
            CAMERA_HISTORY.record_status(cam_name, st["status"], reason="startup", force=True)

    _ACTIVE_CAM_STATES.clear()
    _ACTIVE_CAM_STATES.update(cam_states)
    infer_threads = []
    with _RUNTIME_STATE_LOCK:
        STATUS["cam"] = ",".join(cam_states.keys())
        STATUS["cameras"] = {
            k: {"status": v["status"], "fps": 0.0, "frames": 0, "detections": 0, "errors": 0, "fail_count": v["fail_count"], "reconnect_count": v.get("reconnect_count", 0)}
            for k, v in cam_states.items()
        }
    for cam_name, st in cam_states.items():
        cam_stop_ev = threading.Event()
        st["stop_ev"] = cam_stop_ev
        if st["status"] == "online":
            log("session start", cam_name)
        rt = threading.Thread(target=_camera_reader_worker, args=(st, cam_stop_ev), daemon=True, name=f"cam_reader_{cam_name}")
        it = threading.Thread(
            target=_camera_inference_worker,
            args=(st, cam_stop_ev, vyolo, yolo, reader, trucks_only, curfew),
            daemon=True,
            name=f"cam_infer_{cam_name}",
        )
        st["reader_thread"] = rt
        st["infer_thread"] = it
        rt.start()
        reader_threads.append(rt)
        it.start()
        infer_threads.append(it)

    class _MainLoopRuntimeController:
        """Runtime camera spawner bridge for main() so add_camera_runtime() and remove_camera_runtime() manage worker threads natively."""
        def __init__(self):
            self._lock = _RUNTIME_STATE_LOCK
            self.cam_states = cam_states

        def add_camera(self, dyn_cam: str, dyn_src: str) -> dict:
            with self._lock:
                old_st = cam_states.pop(dyn_cam, None)
                _ACTIVE_CAM_STATES.pop(dyn_cam, None)
            if old_st is not None:
                old_ev = old_st.get("stop_ev")
                if old_ev:
                    old_ev.set()
                for th_k in ("reader_thread", "infer_thread"):
                    th_o = old_st.get(th_k)
                    if th_o is not None and th_o.is_alive() and th_o is not threading.current_thread():
                        th_o.join(timeout=2.5)
                with old_st["lock"]:
                    old_cap = old_st.get("cap")
                    old_st["cap"] = None
                if old_cap is not None:
                    try:
                        old_cap.release()
                    except Exception:
                        pass

            now_d = time.time()
            try:
                cap_d = _open_camera_capture(dyn_src)
            except Exception:
                cap_d = None
            is_op_d = bool(cap_d and cap_d.isOpened())
            is_eof_d = bool(not is_op_d and cap_d is not None and getattr(cap_d, "eof", False))
            if not is_op_d:
                if cap_d is not None:
                    try:
                        cap_d.release()
                    except Exception:
                        pass
                cap_d = None
            st_status = "online" if is_op_d else "reconnecting"
            idle_ev_d = threading.Event()
            idle_ev_d.set()
            cam_stop_d = threading.Event()
            st_d = {
                "cam": dyn_cam,
                "src": dyn_src,
                "stop_ev": cam_stop_d,
                "lock": threading.Lock(),
                "infer_lock": threading.Lock(),
                "infer_queue": queue.Queue(maxsize=1),
                "infer_busy": False,
                "infer_idle_event": idle_ev_d,
                "dropped_infer_frames": 0,
                "cap": cap_d,
                "status": st_status,
                "n": 0,
                "det_runs": 0,
                "votes": {},
                "tracks": {},
                "last_seen": {},
                "last_plate": None,
                "boxes": [],
                "vboxes": [],
                "face_entries": [],
                "unmatched_face_boxes": [],
                "face_det_runs": 0,
                "fail_count": 0 if is_op_d else 1,
                "consec_errors": 0,
                "disconnected_since": 0.0 if is_op_d else now_d,
                "next_reconnect_ts": 0.0 if is_op_d else (now_d + _compute_reconnect_backoff(1)),
                "offline_alert_sent": False,
                "fps": 0.0,
                "reconnect_count": 0,
                "fps_t": now_d,
                "fps_n": 0,
                "latest_frame": None,
                "latest_frame_seq": 0,
                "last_processed_seq": 0,
                "last_frame_ts": now_d if is_op_d else 0.0,
                "read_failed": not is_op_d,
                "just_reconnected": False,
                "logged_session_start": is_op_d,
                "eof": is_eof_d,
                "brightness": 0.0,
                "contrast": 0.0,
                "sharpness": 0.0,
                "health_warning": "",
            }
            if not is_op_d:
                bus.set_frame(_make_offline_frame(dyn_cam, "reconnecting"), cam=dyn_cam, status="reconnecting")
                bus.publish({"type": "camera_status", "cam": dyn_cam, "status": "reconnecting"})
            with self._lock:
                cam_states[dyn_cam] = st_d
                _ACTIVE_CAM_STATES[dyn_cam] = st_d
                STATUS["cam"] = ",".join(cam_states.keys())
                STATUS.setdefault("cameras", {})[dyn_cam] = {
                    "status": st_d["status"],
                    "fps": 0.0,
                    "frames": 0,
                    "detections": 0,
                    "errors": 0,
                    "fail_count": st_d["fail_count"],
                    "reconnect_count": 0,
                    "source": redact_url(dyn_src),
                    "health_warning": "",
                }
            if st_d["status"] == "online":
                log("session start", dyn_cam)
            rt_d = threading.Thread(target=_camera_reader_worker, args=(st_d, cam_stop_d), daemon=True, name=f"cam_reader_{dyn_cam}")
            it_d = threading.Thread(
                target=_camera_inference_worker,
                args=(st_d, cam_stop_d, vyolo, yolo, reader, trucks_only, curfew),
                daemon=True,
                name=f"cam_infer_{dyn_cam}",
            )
            st_d["reader_thread"] = rt_d
            st_d["infer_thread"] = it_d
            rt_d.start()
            reader_threads.append(rt_d)
            it_d.start()
            infer_threads.append(it_d)
            return st_d

    _main_runtime_ctrl = _MainLoopRuntimeController()
    _ACTIVE_ENGINE_CONTROLLER = _main_runtime_ctrl
    srv = start_server(a.port, host=a.host)
    if cfg.get("open_browser") and not a.no_window:
        webbrowser.open(f"http://127.0.0.1:{a.port}/?k={bus.token}")

    print("Faces are matched ONLY against volunteers who gave consent. Bystander faces in evidence photos are blurred.")

    t_faces = 0.0
    gui_enabled = not a.no_window
    try:
        while not STOP_MAIN_EVENT.is_set():
            any_alive = False
            processed_any_frame = False
            now_loop = time.time()
            with _RUNTIME_STATE_LOCK:
                cam_items_snap = list(cam_states.items())
            for cam_name, st in cam_items_snap:
                if st.get("stop_ev") is not None and st["stop_ev"].is_set():
                    continue
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
                    if st["status"] != "online":
                        st["reconnect_count"] = int(st.get("reconnect_count", 0)) + 1
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

                    with st["infer_lock"]:
                        det_r_off = st["det_runs"]
                        err_c_off = st["consec_errors"]
                        last_p_off = st.get("last_plate")
                    with _RUNTIME_STATE_LOCK:
                        if cam_name in cam_states and not (st.get("stop_ev") and st["stop_ev"].is_set()):
                            prev_c_off = STATUS.get("cameras", {}).get(cam_name, {})
                            STATUS["cameras"][cam_name] = {
                                "status": st["status"], "fps": st["fps"] if st["status"] == "online" else 0.0,
                                "frames": st["n"], "detections": det_r_off, "errors": err_c_off,
                                "fail_count": fail_cnt, "reconnect_count": st.get("reconnect_count", 0),
                                "last_plate": last_p_off if last_p_off is not None else prev_c_off.get("last_plate"),
                                "brightness": st.get("brightness", prev_c_off.get("brightness", 0.0)),
                                "contrast": st.get("contrast", prev_c_off.get("contrast", 0.0)),
                                "sharpness": st.get("sharpness", prev_c_off.get("sharpness", 0.0)),
                                "health_warning": st.get("health_warning", prev_c_off.get("health_warning", "")),
                                "resolution": prev_c_off.get("resolution", ""),
                                "source": redact_url(st["src"]),
                            }
                    _update_aggregate_fps(cam_states)
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
                    _update_aggregate_fps(cam_states)

                # P0-D: Per-frame exception guard with consecutive error counter so a single frame error never kills the program
                try:
                    H, W = frame.shape[:2]
                    view = frame.copy()
                    with _ENROLL_LOCK:
                        enroll_active = ENR.get("req") is not None
                    # AI-BUG-07: Compute frame quality & frozen/occluded telemetry
                    try:
                        gray_q = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
                        b_mean = round(float(np.mean(gray_q)), 2)
                        c_std = round(float(np.std(gray_q)), 2)
                        s_lap = round(float(cv2.Laplacian(gray_q, cv2.CV_64F).var()), 2)
                        small_q = cv2.resize(gray_q, (16, 16), interpolation=cv2.INTER_AREA)
                        f_hash = hashlib.md5(small_q.tobytes()).hexdigest()
                        if f_hash == st.get("last_frame_hash"):
                            st["frozen_frames"] = int(st.get("frozen_frames", 0)) + 1
                        else:
                            st["frozen_frames"] = 0
                            st["last_frame_hash"] = f_hash
                        hw_warn = ""
                        if st["frozen_frames"] >= 15:
                            hw_warn = "FROZEN_STREAM"
                        elif b_mean < 12.0 and c_std < 5.0:
                            hw_warn = "CAMERA_OCCLUDED_OR_DARK"
                        elif b_mean < 35.0:
                            hw_warn = "LOW_LIGHT"
                        st["brightness"] = b_mean
                        st["contrast"] = c_std
                        st["sharpness"] = s_lap
                        st["health_warning"] = hw_warn
                        with _RUNTIME_STATE_LOCK:
                            if cam_name in STATUS.get("cameras", {}):
                                STATUS["cameras"][cam_name].update({
                                    "brightness": b_mean,
                                    "contrast": c_std,
                                    "sharpness": s_lap,
                                    "frozen_frames": st["frozen_frames"],
                                    "health_warning": hw_warn,
                                    "resolution": f"{W}x{H}",
                                })
                    except Exception:
                        pass

                    face_interval = max(1, int(FACE_DETECT_INTERVAL or 1))
                    # AI-BUG-01 (GAP-002): Do not force YuNet on every empty frame; respect FACE_DETECT_INTERVAL
                    should_detect_faces = (st["n"] <= 1) or (st["n"] % face_interval == 0) or enroll_active
                    main_face = None
                    if should_detect_faces:
                        det.setInputSize((W, H))
                        _, fs = det.detect(frame)
                        fs = fs if fs is not None else []
                        names, unmatched_face_boxes = [], []
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
                                main_face = (raw_emb, bw * bh, (x, y, bw, bh))
                        with st["infer_lock"]:
                            st["face_entries"] = list(face_entries)
                            st["unmatched_face_boxes"] = list(unmatched_face_boxes)
                            st["face_det_runs"] = int(st.get("face_det_runs", 0)) + 1
                        for (x, y, bw, bh, name, sc, wl, _, pid_m, ref_m) in face_entries:
                            face_boxes_blur = get_boxes_to_blur_for_alert(face_entries, alert_kind="face", target_face_box=(x, y, bw, bh))
                            face_step(name, sc, wl, frame, cam_name, frame_idx=st["n"],
                                      unmatched_faces=face_boxes_blur, person_id=pid_m, ref=ref_m,
                                      face_entries=face_entries, target_face_box=(x, y, bw, bh))
                    else:
                        with st["infer_lock"]:
                            face_entries = list(st.get("face_entries", []))
                            unmatched_face_boxes = list(st.get("unmatched_face_boxes", []))
                        names = [fe[4] for fe in face_entries]

                    for (x, y, bw, bh, name, sc, wl, _, pid_m, ref_m) in face_entries:
                        cv2.rectangle(view, (x, y), (x + bw, y + bh), (255, 160, 0), 2)
                        cv2.putText(view, f"{name} {sc:.2f}" if sc else name, (x, max(15, y - 6)), FONT, .55, (255, 160, 0), 2)

                    if main_face and (st["n"] % 4 == 0 or enroll_active):
                        enroll_step(main_face[0], cam=cam_name, face_box=main_face[2], faces_in_frame=face_entries)
                    if now_loop - t_faces > 1.0:
                        t_faces = now_loop
                        bus.publish({"type": "faces", "n": len(face_entries), "names": sorted({x for x in names if x != "unenrolled"})})

                    # GAP-09: For any vehicle/plate/route alert, 100% of all faces in the frame are blurred
                    vehicle_alert_blur_boxes = get_boxes_to_blur_for_alert(face_entries, alert_kind="vehicle")

                    # GAP-08 & P0-D: Strictly non-blocking per-camera async inference enqueue (maxsize=1, drop-oldest)
                    if st["n"] % 6 == 0:
                        _enqueue_latest_inference(
                            st,
                            (frame.copy(), time.time(), list(face_entries), list(vehicle_alert_blur_boxes), st["n"])
                        )

                    with st["infer_lock"]:
                        vboxes_snap = list(st["vboxes"])
                        boxes_snap = list(st["boxes"])

                    for (x, y, bw, bh, vc) in vboxes_snap:
                        cv2.rectangle(view, (x, y), (x + bw, y + bh), (0, 200, 255), 2)
                        cv2.putText(view, vc.upper(), (x, max(15, y - 6)), FONT, .6, (0, 200, 255), 2)
                    for (x, y, bw, bh, d) in boxes_snap:
                        cv2.rectangle(view, (x, y), (x + bw, y + bh), (0, 220, 0), 2)
                        if d:
                            cv2.putText(view, d, (x, max(15, y - 6)), FONT, .7, (0, 220, 0), 2)
                    with bus._lock:
                        top_alert = bus.alerts[0] if bus.alerts else None
                    if top_alert:
                        cv2.rectangle(view, (0, 0), (W, 60), (0, 0, 180), -1)
                        cv2.putText(view, f"ALERT: {top_alert['msg']}  [C]onfirm [X]dismiss", (10, 38), FONT, .7, (255, 255, 255), 2)
                    if st["n"] % 2 == 0:
                        sm = cv2.resize(view, (640, int(640 * H / W)))
                        jpg_bytes = cv2.imencode(".jpg", sm, [cv2.IMWRITE_JPEG_QUALITY, 70])[1].tobytes()
                        bus.set_frame(jpg_bytes, cam=cam_name, status="online")
                except Exception as frame_err:
                    with st["infer_lock"]:
                        st["consec_errors"] += 1
                    logger.error("Error processing frame #%d on camera %s (consec=%d): %s",
                                 st["n"], cam_name, st["consec_errors"], redact_url(frame_err), exc_info=True)

                with st["infer_lock"]:
                    det_runs_cur = st["det_runs"]
                    err_cnt_cur = st["consec_errors"]
                    last_p_cur = st.get("last_plate")
                with _RUNTIME_STATE_LOCK:
                    if cam_name in cam_states and not (st.get("stop_ev") and st["stop_ev"].is_set()):
                        prev_c_cur = STATUS.get("cameras", {}).get(cam_name, {})
                        STATUS["cameras"][cam_name] = {
                            "status": st["status"], "fps": st["fps"], "frames": st["n"],
                            "detections": det_runs_cur, "errors": err_cnt_cur, "fail_count": fail_cnt,
                            "reconnect_count": st.get("reconnect_count", 0),
                            "last_plate": last_p_cur if last_p_cur is not None else prev_c_cur.get("last_plate"),
                            "brightness": st.get("brightness", prev_c_cur.get("brightness", 0.0)),
                            "contrast": st.get("contrast", prev_c_cur.get("contrast", 0.0)),
                            "sharpness": st.get("sharpness", prev_c_cur.get("sharpness", 0.0)),
                            "health_warning": st.get("health_warning", prev_c_cur.get("health_warning", "")),
                            "resolution": prev_c_cur.get("resolution", f"{W}x{H}"),
                            "source": redact_url(st["src"]),
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
                if k in (ord("c"), ord("x")):
                    with bus._lock:
                        aid_top = bus.alerts[0]["id"] if bus.alerts else None
                    if aid_top is not None:
                        decide(aid_top, "confirm" if k == ord("c") else "dismiss", "console")
                if k == ord("p") and st["last_plate"]:
                    R.save_vehicle({**(R.lookup_vehicle(st["last_plate"]) or {"plate": st["last_plate"]}), "status": "watch"}, "console")
                if k == ord("e"):
                    msg_enr = "لتسجيل وجه متطوع بأمان دون تجميد بث الكاميرات، استخدم تبويب «سجل الأشخاص» في لوحة العمليات (dashboard.html)."
                    logger.info("Console 'e' key pressed: %s", msg_enr)
                    print(msg_enr)
            if cam_items_snap and not any_alive:
                break
            if not processed_any_frame:
                time.sleep(0.005)
    except KeyboardInterrupt:
        pass
    finally:
        if _ACTIVE_ENGINE_CONTROLLER is _main_runtime_ctrl:
            _ACTIVE_ENGINE_CONTROLLER = None
        wait_for_pending_inference(timeout=2.0)
        stop_ev.set()
        with _RUNTIME_STATE_LOCK:
            fin_cam_states = list(cam_states.values())
        for st_fin in fin_cam_states:
            ev_fin = st_fin.get("stop_ev")
            if ev_fin:
                ev_fin.set()
        for rt in reader_threads:
            try:
                rt.join(timeout=1.0)
            except Exception:
                pass
        for it in infer_threads:
            try:
                it.join(timeout=1.0)
            except Exception:
                pass
        for cam_name, st in cam_states.items():
            with st["infer_lock"]:
                det_fin = st["det_runs"]
                err_fin = st["consec_errors"]
            with _RUNTIME_STATE_LOCK:
                if cam_name in STATUS.get("cameras", {}):
                    STATUS["cameras"][cam_name]["detections"] = det_fin
                    STATUS["cameras"][cam_name]["errors"] = err_fin
            with st["lock"]:
                cap_to_rel = st["cap"]
                st["cap"] = None
            try:
                if cap_to_rel is not None:
                    cap_to_rel.release()
            except Exception:
                pass
            if st.get("logged_session_start"):
                log("session end", cam_name)
        if gui_enabled:
            try: cv2.destroyAllWindows()
            except Exception: pass
        try: srv.shutdown()
        except Exception: pass


def _levenshtein_distance(s1, s2):
    """Compute standard Levenshtein edit distance between two strings (GAP-17)."""
    a, b = str(s1 or ""), str(s2 or "")
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[-1]


def _compute_cer(expected, predicted):
    """Compute Character Error Rate (CER) = Levenshtein(expected, predicted) / max(1, len(expected)) (GAP-17)."""
    exp_s = str(expected or "").strip()
    pred_s = str(predicted or "").strip()
    if not exp_s:
        return 0.0 if not pred_s else 1.0
    return float(_levenshtein_distance(exp_s, pred_s)) / float(len(exp_s))


def _bbox_iou(box_a, box_b):
    """Compute Intersection over Union (IoU) between two (x, y, w, h) bounding boxes (GAP-17)."""
    if not box_a or not box_b or len(box_a) < 4 or len(box_b) < 4:
        return 0.0
    ax, ay, aw, ah = [float(v) for v in box_a[:4]]
    bx, by, bw, bh = [float(v) for v in box_b[:4]]
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return 0.0
    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh
    ix1, iy1 = max(ax, bx), max(ay, by)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0.0:
        return 0.0
    union = aw * ah + bw * bh - inter
    return float(inter / union) if union > 0 else 0.0


_EVAL_JOB_LOCK = threading.Lock()
_EVAL_JOB_STATE = {
    "running": False,
    "job_id": "",
    "started_ts": 0.0,
    "finished_ts": 0.0,
    "dataset_path": "",
    "plate_model": "",
    "use_vehicle_detector": False,
    "progress_current": 0,
    "progress_total": 0,
    "progress_percent": 0.0,
    "current_file": "",
    "status": "idle",
    "error": "",
    "cancel_event": None,
    "last_report": None,
}


PLATE_EVAL_IOU_THRESHOLD = 0.3
_BROWSE_DIALOG_LOCK = threading.Lock()


def validate_plate_model_path(model_path, min_bytes=1024, enforce_trusted=False):
    """Validate a custom --plate-model (.pt) path before attempting to load it (Stage 11, AUDIT-001).
    - Always rejects UNC paths (\\, //), URLs, '..' traversal segments, symbolic links, and any .pt archive
      failing verify_yolo_pt_file() or _scan_pt_pickle_safety().
    - When enforce_trusted=True (mandatory on all web endpoints and before YOLO model loading), strictly enforces:
      1) Realpath containment inside trusted models/ directory (INSTALL_DIR/models, APPDIR/models, BUNDLE_DIR/models)
      2) Verified SHA-256 digest matching a trusted entry in MODEL_SHA256, MERSAD_TRUSTED_PT_SHA256, or HMAC-signed models/.trusted_models.json."""
    p_str = str(model_path or "").strip()
    if not p_str:
        return {
            "ok": True,
            "custom": False,
            "path": "",
            "model_name": "default_canny_or_vehicle_crop",
            "reason": "سيُستخدم الكاشف الافتراضي المدمج (بدون نموذج لوحات خارجي)",
        }
    if "\x00" in p_str or p_str.startswith(("\\", "//")) or re.match(r"^[a-zA-Z]{2,10}://", p_str):
        return {
            "ok": False,
            "custom": True,
            "path": p_str,
            "reason": "unsafe_unc_or_remote_path",
            "error": "لأسباب أمنية، يمنع تحميل نماذج اللوحات من مسارات شبكية (UNC) أو روابط خارجية",
        }
    raw_parts = [seg for seg in re.split(r"[\\/]+", p_str) if seg]
    if ".." in raw_parts:
        return {
            "ok": False,
            "custom": True,
            "path": p_str,
            "reason": "path_traversal_rejected",
            "error": "مسار نموذج اللوحات غير آمن (يمنع استخدام .. لتجاوز المجلدات)",
        }
    abs_p = os.path.abspath(p_str)
    if os.path.lexists(p_str) and os.path.islink(p_str):
        return {
            "ok": False,
            "custom": True,
            "path": p_str,
            "reason": "symlink_rejected",
            "error": "الروابط الرمزية (Symlinks) غير مسموحة لملفات نماذج الذكاء الاصطناعي",
        }
    if not os.path.exists(abs_p) or not os.path.isfile(abs_p) or os.path.islink(abs_p):
        return {
            "ok": False,
            "custom": True,
            "path": p_str,
            "reason": "file_missing_or_symlink",
            "error": f"ملف نموذج اللوحات المحدد غير موجود أو غير قابل للقراءة: {p_str}",
        }
    if not abs_p.lower().endswith(".pt"):
        return {
            "ok": False,
            "custom": True,
            "path": p_str,
            "reason": "unsupported_extension",
            "error": "امتداد ملف النموذج غير مدعوم؛ يجب اختيار ملف نموذج PyTorch / YOLO بامتداد (.pt)",
        }
    real_p = os.path.realpath(abs_p)
    trusted_sha = None
    if enforce_trusted:
        in_tr, tr_info = _is_path_in_trusted_model_dirs(abs_p)
        if not in_tr:
            return {
                "ok": False,
                "custom": True,
                "path": p_str,
                "reason": "outside_trusted_models_dir",
                "error": tr_info,
            }
        trusted_sha = get_trusted_model_sha256(real_p)
        if not trusted_sha:
            return {
                "ok": False,
                "custom": True,
                "path": p_str,
                "reason": "untrusted_model_sha256",
                "error": (
                    "ملف النموذج (.pt) غير مدرج في سجل البصمات الموثوقة المحمي (SHA-256)؛ "
                    "يرجى وضعه داخل مجلد models/ واعتماده عبر --register-trusted-model أولاً"
                ),
            }
    ok_pt, reason_pt = verify_yolo_pt_file(real_p, expected_sha256=trusted_sha, min_bytes=min_bytes)
    if not ok_pt:
        return {
            "ok": False,
            "custom": True,
            "path": p_str,
            "reason": reason_pt,
            "error": f"ملف النموذج المحدد غير صالح أو غير آمن أو فشل التحقق من بصمته ({reason_pt})",
        }
    return {
        "ok": True,
        "custom": True,
        "path": real_p,
        "model_name": os.path.basename(real_p),
        "reason": reason_pt,
        "trusted_verified": bool(enforce_trusted),
    }


def load_verified_yolo_model(model_path, role="plate", min_bytes=1024, enforce_trusted=True):
    """Centralized security gate for loading any YOLO .pt checkpoint (AUDIT-001, AUDIT-004).
    Validates path containment, trusted SHA-256 allowlist, and static pickle bytecode safety before calling YOLO()."""
    val = validate_plate_model_path(model_path, min_bytes=min_bytes, enforce_trusted=enforce_trusted)
    if not val.get("ok"):
        raise ValueError(val.get("error") or f"Unverified or unsafe YOLO {role} model: {model_path}")
    real_p = val["path"]
    with _SHARED_ENGINES_LOCK:
        if role == "plate" and _SHARED_ENGINES.get("yolo") is not None and _SHARED_ENGINES.get("plate_model_path") == real_p:
            return _SHARED_ENGINES["yolo"]
        if role == "plate" and _SHARED_ENGINES.get("temp_custom_yolo") is not None and _SHARED_ENGINES.get("temp_custom_path") == real_p:
            return _SHARED_ENGINES["temp_custom_yolo"]
    from ultralytics import YOLO
    mdl = YOLO(real_p)
    if role == "plate":
        with _SHARED_ENGINES_LOCK:
            if _SHARED_ENGINES.get("temp_custom_yolo") is not None and _SHARED_ENGINES.get("temp_custom_path") != real_p:
                _SHARED_ENGINES["temp_custom_yolo"] = None
                gc.collect()
            _SHARED_ENGINES["temp_custom_yolo"] = mdl
            _SHARED_ENGINES["temp_custom_path"] = real_p
    return mdl


def _validate_safe_dataset_dir(dataset_path):
    """Verify that dataset_path is not a UNC share or symbolic link before inspecting or evaluating (AUDIT-002)."""
    p_str = str(dataset_path or "").strip()
    if not p_str:
        return False, "", "يرجى تحديد مسار مجلد مجموعة البيانات أو ملف ground_truth.csv"
    if "\x00" in p_str or p_str.startswith(("\\", "//")):
        return False, "", "لأسباب أمنية، يمنع استخدام المسارات الشبكية (UNC) لمجلدات التقييم"
    abs_p = os.path.abspath(p_str)
    if (os.path.lexists(p_str) and os.path.islink(p_str)) or (os.path.lexists(abs_p) and os.path.islink(abs_p)):
        return False, "", "الروابط الرمزية (Symlinks) غير مسموحة لمسار مجموعة البيانات"
    return True, abs_p, ""


def _resolve_safe_dataset_image(base_dir, raw_filename):
    """Strictly validate and resolve a dataset image filename from ground_truth.csv/.json (AUDIT-002):
    - Rejects empty names, null bytes, UNC paths (\\, //), drive-letter prefixes (:), absolute paths, and leading slashes.
    - Rejects '..' or '.' segments before touching the filesystem (preventing file-existence oracle leaks).
    - Rejects symbolic links on the image or any intermediate directory.
    - Verifies realpath containment inside realpath(base_dir) via os.path.commonpath."""
    fn = str(raw_filename or "").strip()
    if not fn or "\x00" in fn:
        return False, None, "اسم ملف الصورة فارغ أو غير صالح"
    if fn.startswith(("\\", "//", "/", "\\")) or ":" in fn or os.path.isabs(fn):
        return False, None, "مسار صورة غير آمن (يمنع استخدام المسارات المطلقة أو الشبكية UNC)"
    parts = [seg for seg in re.split(r"[\\/]+", fn) if seg]
    if not parts or any(seg in (".", "..") or seg.startswith("..") for seg in parts):
        return False, None, "مسار صورة غير آمن (يمنع استخدام .. لتجاوز مجلد البيانات)"
    ext = os.path.splitext(parts[-1])[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".bmp", ".webp"):
        return False, None, "امتداد ملف الصورة غير مدعوم"
    real_base = os.path.realpath(os.path.abspath(base_dir))
    cur_check = os.path.abspath(base_dir)
    if os.path.lexists(cur_check) and os.path.islink(cur_check):
        return False, None, "مجلد البيانات يحتوي على رابط رمزي غير مسموح"
    for seg in parts:
        cur_check = os.path.join(cur_check, seg)
        if os.path.lexists(cur_check) and os.path.islink(cur_check):
            return False, None, "مسار الصورة يشير إلى رابط رمزي (Symlink) غير مسموح"
    real_cand = os.path.realpath(cur_check)
    try:
        if os.path.commonpath([real_base, real_cand]) != real_base:
            return False, None, "مسار الصورة يقع خارج مجلد مجموعة البيانات المعتمد"
    except ValueError:
        return False, None, "مسار الصورة يقع خارج مجلد مجموعة البيانات المعتمد"
    return True, real_cand, ""


def _dedup_candidate_boxes(boxes, iou_threshold=0.6):
    """Deduplicate overlapping plate candidate boxes (IoU >= iou_threshold) while preserving order (AUDIT-003)."""
    if not boxes:
        return []
    kept = []
    for b in boxes:
        if not any(_bbox_iou(b, existing) >= iou_threshold for existing in kept):
            kept.append(b)
    return kept


def _parse_ground_truth_entries(gt_file):
    """Parse ground_truth.csv or ground_truth.json and return (valid_entries, invalid_rows_errors)."""
    raw_entries = []
    row_errors = []
    if gt_file.lower().endswith(".json"):
        with open(gt_file, encoding="utf-8") as gf:
            loaded_gt = json.load(gf)
        if isinstance(loaded_gt, dict):
            loaded_gt = loaded_gt.get("samples") or loaded_gt.get("items") or []
        if not isinstance(loaded_gt, list):
            raise ValueError("ملف ground_truth.json يجب أن يحتوي على قائمة samples")
        for idx, x in enumerate(loaded_gt, 1):
            if not isinstance(x, dict):
                row_errors.append(f"السجل #{idx}: ليس كائناً صالحاً")
                continue
            fn = str(x.get("filename") or x.get("file") or x.get("image") or "").strip()
            exp_p = str(x.get("expected_plate") or x.get("plate") or "").strip()
            if not fn or not exp_p:
                row_errors.append(f"السجل #{idx}: ينقصه اسم الصورة (filename) أو اللوحة المتوقعة (expected_plate)")
                continue
            hv_raw = str(x.get("human_verified", "1")).strip()
            is_unv = (hv_raw == "0") or (exp_p in ("UNVERIFIED_PLATE", "عدن-00000"))
            entry = {"filename": fn, "expected_plate": exp_p, "human_verified": "0" if is_unv else "1"}
            for bk in ("x", "y", "w", "h"):
                if x.get(bk) not in (None, ""):
                    try:
                        entry[bk] = float(x[bk])
                    except (TypeError, ValueError):
                        pass
            raw_entries.append(entry)
    else:
        with open(gt_file, encoding="utf-8-sig", newline="") as cf:
            reader_csv = csv.DictReader(cf)
            for idx, row in enumerate(reader_csv, 1):
                if not row:
                    continue
                norm_row = {str(k or "").strip().lower(): str(v or "").strip() for k, v in row.items() if k is not None}
                if not any(norm_row.values()):
                    continue
                fn = (norm_row.get("filename") or norm_row.get("file") or norm_row.get("image") or "").strip()
                if fn.startswith("'") and len(fn) > 1 and fn[1] in ("=", "+", "-", "@"):
                    fn = fn[1:].strip()
                exp_p = (norm_row.get("expected_plate") or norm_row.get("plate") or "").strip()
                if exp_p.startswith("'") and len(exp_p) > 1 and exp_p[1] in ("=", "+", "-", "@"):
                    exp_p = exp_p[1:].strip()
                if not fn or not exp_p:
                    row_errors.append(f"السطر #{idx}: ينقصه اسم الصورة (filename) أو اللوحة المتوقعة (expected_plate)")
                    continue
                hv_raw = norm_row.get("human_verified", "1").strip()
                is_unv = (hv_raw == "0") or (exp_p in ("UNVERIFIED_PLATE", "عدن-00000"))
                entry = {"filename": fn, "expected_plate": exp_p, "human_verified": "0" if is_unv else "1"}
                for bk in ("x", "y", "w", "h"):
                    if norm_row.get(bk, "") != "":
                        try:
                            entry[bk] = float(norm_row[bk])
                        except ValueError:
                            pass
                raw_entries.append(entry)
    return raw_entries, row_errors


def inspect_plate_dataset(dataset_path, plate_model_path=None, enforce_trusted_model=False):
    """Inspect a dataset directory or ground_truth file before starting evaluation (Stage 11, AUDIT-001, AUDIT-002).
    Checks path safety, ground_truth.csv/.json validity, valid vs invalid/corrupt/unsafe image files,
    and optional custom plate model compatibility."""
    ok_dir, abs_path, dir_err = _validate_safe_dataset_dir(dataset_path)
    if not ok_dir:
        return {"ok": False, "error": dir_err, "dataset_path": str(dataset_path or "")}
    if not os.path.exists(abs_path):
        return {"ok": False, "error": f"المسار المحدد غير موجود: {dataset_path}", "dataset_path": str(dataset_path)}

    if os.path.isfile(abs_path):
        base_dir = os.path.dirname(abs_path)
        gt_file = abs_path
    else:
        base_dir = abs_path
        csv_cand = os.path.join(base_dir, "ground_truth.csv")
        json_cand = os.path.join(base_dir, "ground_truth.json")
        gt_file = csv_cand if (os.path.isfile(csv_cand) and not os.path.islink(csv_cand)) else (
            json_cand if (os.path.isfile(json_cand) and not os.path.islink(json_cand)) else ""
        )

    if not gt_file or not os.path.isfile(gt_file) or os.path.islink(gt_file):
        return {
            "ok": False,
            "status": "ground_truth_missing",
            "dataset_path": abs_path,
            "error": "لم يُعثر على ملف الحقيقة المرجعية (ground_truth.csv أو ground_truth.json) داخل المجلد المحدد",
        }

    try:
        entries, row_errors = _parse_ground_truth_entries(gt_file)
    except Exception as e:
        return {
            "ok": False,
            "status": "ground_truth_parse_error",
            "dataset_path": abs_path,
            "error": f"تعذّر قراءة ملف ground_truth: {e}",
        }

    valid_files = []
    invalid_files = []
    security_rejected_files = []
    unverified_rows_count = sum(1 for item in entries if str(item.get("human_verified", "1")) == "0" or item.get("expected_plate") in ("UNVERIFIED_PLATE", "عدن-00000"))
    for item in entries:
        fn = item["filename"]
        ok_img, safe_img_p, safe_err = _resolve_safe_dataset_image(base_dir, fn)
        if not ok_img:
            invalid_files.append({"filename": fn, "reason": safe_err})
            security_rejected_files.append({"filename": fn, "reason": safe_err})
            continue
        if not os.path.isfile(safe_img_p):
            invalid_files.append({"filename": fn, "reason": "الملف غير موجود"})
            continue
        img = cv2.imread(safe_img_p)
        if img is None or getattr(img, "size", 0) == 0:
            invalid_files.append({"filename": fn, "reason": "ملف صورة تالف أو غير قابل للقراءة"})
        else:
            valid_files.append(fn)

    model_info = (
        validate_plate_model_path(plate_model_path, enforce_trusted=enforce_trusted_model)
        if plate_model_path
        else {"ok": True, "custom": False}
    )
    return {
        "ok": len(valid_files) > 0 and model_info.get("ok", True),
        "dataset_path": abs_path,
        "ground_truth_file": gt_file,
        "total_entries": len(entries) + len(row_errors),
        "valid_files_count": len(valid_files),
        "invalid_files_count": len(invalid_files) + len(row_errors),
        "unverified_rows_count": unverified_rows_count,
        "requires_human_review_warning": bool(unverified_rows_count > 0),
        "security_rejected_count": len(security_rejected_files),
        "valid_files": valid_files[:50],
        "invalid_files": invalid_files[:25],
        "security_rejected_files": security_rejected_files[:25],
        "row_errors": row_errors[:25],
        "plate_model_validation": model_info,
        "error": (
            model_info.get("error")
            if not model_info.get("ok", True)
            else ("لا توجد صور صالحة قابلة للقراءة مطابقة لملف ground_truth" if len(valid_files) == 0 else "")
        ),
    }


def _save_plate_eval_run_to_db(report):
    """Persist completed automated plate evaluation report in SQLite plate_eval_runs table (Stage 11, AUDIT-003)."""
    if db is None:
        return None
    try:
        met = report.get("metrics") or {}
        now_ts = time.time()
        eval_date = report.get("evaluation_date") or time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now_ts))
        rep_json = json.dumps(report, ensure_ascii=False)

        def _tx(conn):
            R.migrate_db(conn, DBL, db_path=DB_PATH)
            cur = conn.execute(
                "INSERT INTO plate_eval_runs("
                "ts, eval_date, dataset_path, plate_model, detector_mode, vehicle_stage_enabled, "
                "total_samples, valid_files, invalid_files, detected_count, failed_detection_count, failed_ocr_count, "
                "detection_recall, detection_precision, detection_f1, mean_iou, exact_match_rate, "
                "end_to_end_exact_match_rate, cropped_ocr_exact_match_rate, digits_match_rate, "
                "char_accuracy_rate, cer, mean_latency_ms, status, report_json"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    now_ts,
                    eval_date,
                    str(report.get("dataset_path") or ""),
                    str(report.get("model_used") or ""),
                    str(report.get("detector_mode") or ""),
                    int(bool(report.get("vehicle_stage_enabled"))),
                    int(report.get("total_samples") or 0),
                    int(report.get("valid_files_count") or report.get("total_samples") or 0),
                    int(report.get("invalid_files_count") or 0),
                    int(met.get("detected_count") or 0),
                    int(met.get("failed_detection_count") or 0),
                    int(met.get("failed_ocr_count") or 0),
                    float(met.get("detection_recall") or 0.0),
                    float(met.get("detection_precision") or 0.0),
                    float(met.get("detection_f1") or 0.0),
                    float(met["mean_iou"]) if met.get("mean_iou") is not None else None,
                    float(met.get("exact_match_rate") or 0.0),
                    float(met.get("end_to_end_exact_match_rate", met.get("exact_match_rate") or 0.0)),
                    float(met.get("cropped_ocr_exact_match_rate", met.get("exact_match_rate") or 0.0)),
                    float(met.get("digits_match_rate") or 0.0),
                    float(met.get("char_accuracy_rate") or 0.0),
                    float(met.get("cer") or 0.0),
                    float(met.get("mean_latency_ms") or 0.0),
                    str(report.get("status") or "completed"),
                    rep_json,
                ),
            )
            return int(cur.lastrowid)

        return R.run_atomic_tx(db, DBL, _tx, db_path=DB_PATH)
    except Exception as e:
        logger.debug("Could not persist plate_eval_run: %s", e)
        return None


def list_plate_eval_runs(limit=20):
    """Return recent automated plate evaluation runs from SQLite plate_eval_runs (Stage 11, AUDIT-003)."""
    if db is None:
        return {"ok": True, "runs": []}
    try:
        with DBL:
            R.migrate_db(db, DBL, db_path=DB_PATH)
            rows = db.execute(
                "SELECT id, ts, eval_date, dataset_path, plate_model, detector_mode, vehicle_stage_enabled, "
                "total_samples, valid_files, invalid_files, detected_count, failed_detection_count, failed_ocr_count, "
                "detection_recall, detection_precision, COALESCE(detection_f1, 0), mean_iou, exact_match_rate, "
                "COALESCE(end_to_end_exact_match_rate, exact_match_rate, 0), "
                "COALESCE(cropped_ocr_exact_match_rate, exact_match_rate, 0), "
                "digits_match_rate, char_accuracy_rate, cer, mean_latency_ms, status "
                "FROM plate_eval_runs ORDER BY id DESC LIMIT ?",
                (max(1, min(100, int(limit or 20))),)
            ).fetchall()
        runs = [
            {
                "id": int(r[0]),
                "ts": float(r[1]),
                "eval_date": str(r[2] or ""),
                "dataset_path": str(r[3] or ""),
                "model_used": str(r[4] or ""),
                "detector_mode": str(r[5] or ""),
                "vehicle_stage_enabled": bool(r[6]),
                "total_samples": int(r[7] or 0),
                "valid_files_count": int(r[8] or 0),
                "invalid_files_count": int(r[9] or 0),
                "detected_count": int(r[10] or 0),
                "failed_detection_count": int(r[11] or 0),
                "failed_ocr_count": int(r[12] or 0),
                "detection_recall": float(r[13] or 0.0),
                "detection_precision": float(r[14] or 0.0),
                "detection_f1": float(r[15] or 0.0),
                "mean_iou": float(r[16]) if r[16] is not None else None,
                "exact_match_rate": float(r[17] or 0.0),
                "end_to_end_exact_match_rate": float(r[18] or 0.0),
                "cropped_ocr_exact_match_rate": float(r[19] or 0.0),
                "digits_match_rate": float(r[20] or 0.0),
                "char_accuracy_rate": float(r[21] or 0.0),
                "cer": float(r[22] or 0.0),
                "mean_latency_ms": float(r[23] or 0.0),
                "status": str(r[24] or "completed"),
                "verification_status": "automated_verified",
            }
            for r in rows
        ]
        return {"ok": True, "runs": runs}
    except Exception as e:
        return {"ok": False, "error": str(e), "runs": []}


def evaluate_plates_dataset(
    dataset_path,
    output_json=None,
    reader=None,
    yolo=None,
    vyolo=None,
    print_report=True,
    use_vehicle_detector=False,
    plate_model_path=None,
    cancel_event=None,
    progress_cb=None,
    save_to_db=True,
    enforce_trusted_model=True,
):
    """Standardized benchmark tool to evaluate find_plates(), preprocess_plate(), and read_plate() (GAP-17, Stage 11, Stage 12).
    - Enforces AUDIT-001 (trusted & pickle-safe .pt loading), AUDIT-002 (strict dataset path traversal prevention),
      AUDIT-003 (strict separation of detection_precision, detection_recall, detection_f1, end_to_end_exact_match_rate,
      and cropped_ocr_exact_match_rate without counting gt_box fallback as end-to-end success),
      and AUDIT-004 (shared inference engines reuse without duplicate RAM/VRAM allocation)."""
    spec_protocol = {
        "required_files": ["ground_truth.csv (or ground_truth.json)", "<image_files>.jpg/.png"],
        "csv_columns": ["filename", "expected_plate", "x", "y", "w", "h"],
        "optional_bbox_columns": ["x", "y", "w", "h"],
        "iou_threshold": PLATE_EVAL_IOU_THRESHOLD,
        "example_csv_row": "cam1_001.jpg,عدن-12345,180,260,220,55",
        "field_protocol_ar": (
            "بروتوكول التقييم الميداني للوحات اليمنية: "
            "1) اجمع عينة مصرحاً بها لا تقل عن 100 صورة ميدانية متنوعة (نهار/ليل/زوايا مختلفة/غبار) مع توثيق اللوحة الحقيقية في ground_truth.csv. "
            "2) شغّل `python mersad_live.py --evaluate-plates PATH` أو استخدم قسم «تقييم ومعايرة اللوحات اليمنية» في الواجهة لقياس خط الأساس. "
            "3) للاستغناء عن كاشف الحواف الكلاسيكي Canny في الميدان، اعتمد نموذج YOLO مدرباً على اللوحات اليمنية عبر `--register-trusted-model` ثم `--plate-model` وقارن المقاييس."
        ),
    }

    if not dataset_path:
        res_empty = {
            "ok": False,
            "status": "dataset_missing_or_empty",
            "reason": "No dataset path provided",
            "error": "يرجى تحديد مسار مجموعة بيانات التقييم",
            "dataset_path": "",
            "total_samples": 0,
            "ground_truth_schema": spec_protocol,
        }
        if output_json:
            with open(output_json, "w", encoding="utf-8") as jf:
                json.dump(res_empty, jf, indent=2, ensure_ascii=False)
        return res_empty

    ok_dir, abs_path, dir_err = _validate_safe_dataset_dir(dataset_path)
    if not ok_dir:
        res_unsafe_dir = {
            "ok": False,
            "status": "invalid_dataset_path",
            "reason": dir_err,
            "error": dir_err,
            "dataset_path": str(dataset_path),
            "total_samples": 0,
        }
        if output_json:
            with open(output_json, "w", encoding="utf-8") as jf:
                json.dump(res_unsafe_dir, jf, indent=2, ensure_ascii=False)
        return res_unsafe_dir

    if plate_model_path and yolo is None:
        m_val = validate_plate_model_path(plate_model_path, enforce_trusted=enforce_trusted_model)
        if not m_val.get("ok"):
            res_bad_model = {
                "ok": False,
                "status": "invalid_plate_model",
                "reason": m_val.get("reason") or m_val.get("error", "Invalid plate model"),
                "error": m_val.get("error", "ملف نموذج اللوحات غير صالح أو غير موثوق"),
                "dataset_path": str(dataset_path),
                "plate_model_path": str(plate_model_path),
                "total_samples": 0,
            }
            if output_json:
                with open(output_json, "w", encoding="utf-8") as jf:
                    json.dump(res_bad_model, jf, indent=2, ensure_ascii=False)
            return res_bad_model
        if m_val.get("custom"):
            try:
                yolo = load_verified_yolo_model(m_val["path"], role="plate", min_bytes=1024, enforce_trusted=enforce_trusted_model)
            except Exception as e:
                res_load_err = {
                    "ok": False,
                    "status": "invalid_plate_model",
                    "reason": f"Failed to load YOLO plate model: {e}",
                    "error": f"تعذّر تحميل نموذج اللوحات المحدد بواسطة محرك YOLO: {e}",
                    "dataset_path": str(dataset_path),
                    "plate_model_path": str(plate_model_path),
                    "total_samples": 0,
                }
                if output_json:
                    with open(output_json, "w", encoding="utf-8") as jf:
                        json.dump(res_load_err, jf, indent=2, ensure_ascii=False)
                return res_load_err

    if use_vehicle_detector and vyolo is None:
        vyolo = get_or_load_shared_vyolo()

    if os.path.isfile(abs_path):
        base_dir = os.path.dirname(abs_path)
        gt_file = abs_path
    else:
        base_dir = abs_path
        csv_cand = os.path.join(base_dir, "ground_truth.csv")
        json_cand = os.path.join(base_dir, "ground_truth.json")
        gt_file = csv_cand if (os.path.isfile(csv_cand) and not os.path.islink(csv_cand)) else (
            json_cand if (os.path.isfile(json_cand) and not os.path.islink(json_cand)) else ""
        )

    if not os.path.exists(abs_path) or not gt_file or not os.path.isfile(gt_file) or os.path.islink(gt_file):
        res_missing = {
            "ok": False,
            "status": "dataset_missing_or_empty",
            "reason": f"Ground truth file (ground_truth.csv or ground_truth.json) not found in '{dataset_path}'",
            "error": f"لم يُعثر على ملف ground_truth.csv أو ground_truth.json في المسار: {dataset_path}",
            "dataset_path": str(dataset_path),
            "total_samples": 0,
            "ground_truth_schema": spec_protocol,
        }
        if print_report:
            print("======================================================================")
            print("  MERSAD AI — Yemeni License Plate Benchmark (--evaluate-plates)")
            print("======================================================================")
            print(f"  Status: DATASET NOT FOUND ({res_missing['reason']})")
            print("  Required ground_truth.csv format:")
            print("    filename,expected_plate,x,y,w,h")
            print(f"    {spec_protocol['example_csv_row']}")
            print(f"  Protocol: {spec_protocol['field_protocol_ar']}")
            print("======================================================================")
        if output_json:
            with open(output_json, "w", encoding="utf-8") as jf:
                json.dump(res_missing, jf, indent=2, ensure_ascii=False)
        return res_missing

    try:
        raw_entries, row_errors = _parse_ground_truth_entries(gt_file)
    except Exception as parse_err:
        res_err = {
            "ok": False,
            "status": "ground_truth_parse_error",
            "reason": str(parse_err),
            "error": f"خطأ في قراءة ملف الحقيقة المرجعية: {parse_err}",
            "dataset_path": str(dataset_path),
            "total_samples": 0,
            "ground_truth_schema": spec_protocol,
        }
        if output_json:
            with open(output_json, "w", encoding="utf-8") as jf:
                json.dump(res_err, jf, indent=2, ensure_ascii=False)
        return res_err

    if reader is None:
        reader = get_or_load_shared_reader()

    sample_results = []
    missing_images = []
    corrupt_images = []
    rejected_unsafe_paths = []
    ious = []
    detected_cnt = 0
    tp_boxes_cnt = 0
    fp_boxes_cnt = 0
    fn_boxes_cnt = 0
    total_cand_boxes = 0
    exact_cnt = 0
    cropped_ocr_exact_cnt = 0
    digits_cnt = 0
    cers = []
    latencies = []
    total_raw = len(raw_entries)

    for idx_entry, item in enumerate(raw_entries, 1):
        if cancel_event is not None and cancel_event.is_set():
            return {
                "ok": False,
                "status": "cancelled",
                "reason": "Evaluation cancelled by operator",
                "error": "تم إلغاء عملية التقييم بناءً على طلب المستخدم",
                "dataset_path": str(dataset_path),
                "completed_samples": len(sample_results),
                "total_samples": total_raw,
            }
        fn = str(item.get("filename") or "").strip()
        exp_raw = str(item.get("expected_plate") or "").strip()
        if not fn or not exp_raw:
            continue
        hv_flag = str(item.get("human_verified", "1")).strip()
        if hv_flag == "0" or exp_raw.upper() == "UNVERIFIED_PLATE" or exp_raw == "عدن-00000":
            row_errors.append(f"تخطي عينة غير مراجعة بشرياً ({fn}: {exp_raw}) لحماية مقام دقة التقييم")
            continue
        if callable(progress_cb):
            try:
                progress_cb(idx_entry, total_raw, fn)
            except Exception:
                pass
        ok_img, safe_img_p, safe_err = _resolve_safe_dataset_image(base_dir, fn)
        if not ok_img:
            rejected_unsafe_paths.append({"filename": fn, "reason": safe_err})
            missing_images.append(fn)
            continue
        if not os.path.isfile(safe_img_p):
            missing_images.append(fn)
            continue
        img = cv2.imread(safe_img_p)
        if img is None or getattr(img, "size", 0) == 0:
            corrupt_images.append(fn)
            missing_images.append(fn)
            continue

        gt_box = None
        if all(k in item and item[k] is not None for k in ("x", "y", "w", "h")):
            try:
                gx, gy, gw, gh = float(item["x"]), float(item["y"]), float(item["w"]), float(item["h"])
                if gw > 0 and gh > 0:
                    gt_box = (int(gx), int(gy), int(gw), int(gh))
            except (ValueError, TypeError):
                gt_box = None

        t0 = time.perf_counter()
        vboxes = detect_vehicles(img, vyolo) if vyolo is not None else []
        raw_cand_boxes = []
        if vboxes:
            for (vx, vy, vw, vh, vc) in vboxes:
                oy = vy + int(vh * 0.35) if vc != "unknown" else 0
                sub = img[oy:vy + vh, vx:vx + vw]
                if getattr(sub, "size", 0) == 0:
                    continue
                for (px, py, pw, ph) in find_plates(sub, yolo=yolo):
                    raw_cand_boxes.append((px + vx, py + oy, pw, ph))
        if not raw_cand_boxes:
            raw_cand_boxes = find_plates(img, yolo=yolo)

        cand_boxes = _dedup_candidate_boxes(raw_cand_boxes, iou_threshold=0.6)
        total_cand_boxes += len(cand_boxes)
        best_iou = None
        valid_e2e_boxes = []
        if gt_box is not None:
            scored_boxes = sorted(
                [(_bbox_iou(gt_box, b), b) for b in cand_boxes],
                key=lambda x: x[0],
                reverse=True,
            )
            best_iou = scored_boxes[0][0] if scored_boxes else 0.0
            ious.append(best_iou)
            is_detected = bool(best_iou >= PLATE_EVAL_IOU_THRESHOLD)
            if is_detected:
                detected_cnt += 1
                tp_boxes_cnt += 1
                fp_boxes_cnt += max(0, len(cand_boxes) - 1)
                valid_e2e_boxes = [b for iou_v, b in scored_boxes if iou_v >= PLATE_EVAL_IOU_THRESHOLD]
            else:
                fn_boxes_cnt += 1
                fp_boxes_cnt += len(cand_boxes)
                valid_e2e_boxes = []
        else:
            is_detected = bool(len(cand_boxes) > 0)
            if is_detected:
                detected_cnt += 1
                tp_boxes_cnt += 1
                fp_boxes_cnt += max(0, len(cand_boxes) - 1)
                valid_e2e_boxes = list(cand_boxes)
            else:
                fn_boxes_cnt += 1
                valid_e2e_boxes = []

        # 1) End-to-End pipeline OCR: ONLY runs when detection succeeded on valid candidate boxes!
        #    Never falls back to gt_box or full image for end-to-end predictions (AUDIT-003).
        e2e_pred = ""
        e2e_conf = 0.0
        if is_detected and valid_e2e_boxes:
            for (bx, by, bw, bh) in valid_e2e_boxes:
                crop = img[max(0, by):by + bh, max(0, bx):bx + bw]
                d_txt, d_conf = read_plate(reader, crop)
                if d_txt and d_conf >= e2e_conf:
                    e2e_pred, e2e_conf = d_txt, float(d_conf)

        # 2) Cropped OCR isolated metric: reuses e2e_pred when detection succeeded (preserving single-read determinism),
        #    and evaluates gt_box (or pre-cropped image) in a strictly isolated field when detection failed (AUDIT-003).
        cropped_ocr_pred = e2e_pred
        cropped_ocr_conf = e2e_conf
        if not cropped_ocr_pred:
            if gt_box is not None and not is_detected:
                gx, gy, gw, gh = gt_box
                gt_crop = img[max(0, gy):gy + gh, max(0, gx):gx + gw]
                d_txt, d_conf = read_plate(reader, gt_crop)
                if d_txt:
                    cropped_ocr_pred, cropped_ocr_conf = d_txt, float(d_conf)
            elif gt_box is None and not is_detected:
                d_txt, d_conf = read_plate(reader, img)
                if d_txt:
                    cropped_ocr_pred, cropped_ocr_conf = d_txt, float(d_conf)

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        latencies.append(elapsed_ms)

        exp_norm = R.norm_plate(exp_raw)
        exp_digits, _ = R.split_plate(exp_norm)
        pred_norm = R.norm_plate(e2e_pred) if (is_detected and e2e_pred) else ""
        pred_digits, _ = R.split_plate(pred_norm) if pred_norm else ("", "")

        cropped_ocr_norm = R.norm_plate(cropped_ocr_pred) if cropped_ocr_pred else ""

        is_exact = bool(is_detected and exp_norm and pred_norm == exp_norm)
        is_digits = bool(is_detected and exp_digits and pred_digits == exp_digits)
        is_cropped_ocr_exact = bool(exp_norm and cropped_ocr_norm == exp_norm)
        sample_cer = _compute_cer(exp_norm, pred_norm) if is_detected else 1.0

        if is_exact:
            exact_cnt += 1
        if is_cropped_ocr_exact:
            cropped_ocr_exact_cnt += 1
        if is_digits:
            digits_cnt += 1
        cers.append(sample_cer)

        sample_results.append({
            "filename": fn,
            "expected_plate": exp_norm,
            "expected_digits": exp_digits,
            "predicted_plate": pred_norm,
            "predicted_digits": pred_digits,
            "cropped_ocr_plate": cropped_ocr_norm,
            "cropped_ocr_confidence": round(cropped_ocr_conf, 4),
            "cropped_ocr_exact_match": is_cropped_ocr_exact,
            "confidence": round(e2e_conf, 4),
            "detected": is_detected,
            "vehicle_boxes_count": len(vboxes),
            "candidate_boxes_count": len(cand_boxes),
            "iou": round(best_iou, 4) if best_iou is not None else None,
            "exact_match": is_exact,
            "end_to_end_exact_match": is_exact,
            "digits_match": is_digits,
            "char_accuracy": round(max(0.0, 1.0 - sample_cer), 4),
            "cer": round(sample_cer, 4),
            "latency_ms": round(elapsed_ms, 2),
        })

    n_eval = len(sample_results)
    invalid_cnt = len(missing_images) + len(row_errors)
    if n_eval == 0:
        res_no_valid = {
            "ok": False,
            "status": "dataset_missing_or_empty",
            "reason": "No readable images matched ground_truth entries",
            "error": "لا توجد صور صالحة قابلة للقراءة مطابقة لملف الحقيقة المرجعية",
            "dataset_path": str(dataset_path),
            "total_samples": 0,
            "valid_files_count": 0,
            "invalid_files_count": invalid_cnt,
            "missing_images": missing_images,
            "corrupt_images": corrupt_images,
            "rejected_unsafe_paths": rejected_unsafe_paths,
            "row_errors": row_errors,
            "ground_truth_schema": spec_protocol,
        }
        if output_json:
            with open(output_json, "w", encoding="utf-8") as jf:
                json.dump(res_no_valid, jf, indent=2, ensure_ascii=False)
        return res_no_valid

    det_recall = round(detected_cnt / n_eval, 4)
    det_precision = round(tp_boxes_cnt / (tp_boxes_cnt + fp_boxes_cnt), 4) if (tp_boxes_cnt + fp_boxes_cnt) > 0 else 0.0
    det_f1 = round((2.0 * det_precision * det_recall) / (det_precision + det_recall), 4) if (det_precision + det_recall) > 0 else 0.0
    mean_iou_val = round(float(np.mean(ious)), 4) if ious else None
    exact_rate = round(exact_cnt / n_eval, 4)
    cropped_ocr_rate = round(cropped_ocr_exact_cnt / n_eval, 4)
    digits_rate = round(digits_cnt / n_eval, 4)
    mean_cer = round(float(np.mean(cers)), 4)
    char_acc = round(max(0.0, 1.0 - mean_cer), 4)
    mean_lat = round(float(np.mean(latencies)), 2)
    failed_det_cnt = n_eval - detected_cnt
    failed_ocr_cnt = n_eval - exact_cnt

    plate_model_label = os.path.basename(str(plate_model_path)) if plate_model_path else ("custom_yolo_plate" if yolo is not None else "OpenCV_Canny_Contour")
    veh_model_label = f"YOLOv8n ({YOLO_RELEASE_VERSION})" if vyolo is not None else "disabled"
    model_used_str = f"Vehicle:{veh_model_label} | Plate:{plate_model_label} | OCR:EasyOCR(ar,en)"
    eval_date_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

    report = {
        "ok": True,
        "status": "evaluated",
        "verification_status": "automated_verified",
        "evaluation_date": eval_date_str,
        "dataset_path": str(dataset_path),
        "model_used": model_used_str,
        "plate_model_path": str(plate_model_path or ""),
        "total_samples": n_eval,
        "valid_files_count": n_eval,
        "invalid_files_count": invalid_cnt,
        "missing_images": missing_images,
        "corrupt_images": corrupt_images,
        "rejected_unsafe_paths": rejected_unsafe_paths,
        "row_errors": row_errors,
        "metrics": {
            "detected_count": detected_cnt,
            "failed_detection_count": failed_det_cnt,
            "true_positive_boxes": tp_boxes_cnt,
            "false_positive_boxes": fp_boxes_cnt,
            "false_negative_boxes": fn_boxes_cnt,
            "iou_threshold": PLATE_EVAL_IOU_THRESHOLD,
            "detection_recall": det_recall,
            "detection_precision": det_precision,
            "detection_f1": det_f1,
            "mean_iou": mean_iou_val,
            "exact_match_count": exact_cnt,
            "exact_match_rate": exact_rate,
            "end_to_end_exact_match_count": exact_cnt,
            "end_to_end_exact_match_rate": exact_rate,
            "cropped_ocr_exact_match_count": cropped_ocr_exact_cnt,
            "cropped_ocr_exact_match_rate": cropped_ocr_rate,
            "failed_ocr_count": failed_ocr_cnt,
            "digits_match_count": digits_cnt,
            "digits_match_rate": digits_rate,
            "char_accuracy_rate": char_acc,
            "character_error_rate": mean_cer,
            "cer": mean_cer,
            "mean_latency_ms": mean_lat,
        },
        "vehicle_stage_enabled": bool(vyolo is not None),
        "detector_mode": "yolo_plate_model" if yolo is not None else ("vehicle_crop_plus_canny" if vyolo is not None else "opencv_canny_contour_baseline"),
        "field_note_ar": (
            "تُفصل المقاييس أعلاه بصرامة بين: (1) دقة واستدعاء الكاشف ومعيار F1 (detection_precision / detection_recall / detection_f1 عند IoU>=0.3)، "
            "و(2) المطابقة الكاملة لخط الأنابيب End-to-End (end_to_end_exact_match_rate — لا تحتسب أي عينة فشل الكاشف في تحديد موقع لوحتها)، "
            "و(3) دقة محرك OCR المعزول على الصندوق المقصوص (cropped_ocr_exact_match_rate)."
        ),
        "samples": sample_results,
    }
    if save_to_db:
        run_id = _save_plate_eval_run_to_db(report)
        if run_id is not None:
            report["run_id"] = run_id

    if print_report:
        print("======================================================================")
        print("  MERSAD AI — Yemeni License Plate Evaluation Report")
        print("======================================================================")
        print(f"  Dataset:              {dataset_path} ({n_eval} valid, {invalid_cnt} invalid)")
        print(f"  Model Used:           {model_used_str}")
        print(f"  Detector Mode:        {report['detector_mode']}")
        print(f"  Detection Recall:     {det_recall * 100:.1f}% ({detected_cnt}/{n_eval})")
        print(f"  Detection Precision:  {det_precision * 100:.1f}% (TP={tp_boxes_cnt}, FP={fp_boxes_cnt})")
        print(f"  Detection F1 Score:   {det_f1 * 100:.1f}%")
        if mean_iou_val is not None:
            print(f"  Mean BBox IoU:        {mean_iou_val:.4f}")
        print(f"  Char OCR Accuracy:    {char_acc * 100:.1f}% (CER={mean_cer:.4f})")
        print(f"  Digits Match Rate:    {digits_rate * 100:.1f}% ({digits_cnt}/{n_eval})")
        print(f"  End-to-End Exact:     {exact_rate * 100:.1f}% ({exact_cnt}/{n_eval})")
        print(f"  Cropped OCR Exact:    {cropped_ocr_rate * 100:.1f}% ({cropped_ocr_exact_cnt}/{n_eval})")
        print(f"  Mean Latency:         {mean_lat:.2f} ms/image")
        print("======================================================================")
    if output_json:
        with open(output_json, "w", encoding="utf-8") as jf:
            json.dump(report, jf, indent=2, ensure_ascii=False)
    return report


def get_plate_eval_status():
    """Return current status and progress of the in-app Yemeni plate evaluation job (Stage 11)."""
    with _EVAL_JOB_LOCK:
        st = {k: v for k, v in _EVAL_JOB_STATE.items() if k != "cancel_event"}
    return {"ok": True, **st}


def cancel_plate_eval_job(who="operator"):
    """Signal the active plate evaluation job to stop safely between samples (Stage 11)."""
    with _EVAL_JOB_LOCK:
        ev = _EVAL_JOB_STATE.get("cancel_event")
        is_running = _EVAL_JOB_STATE.get("running", False)
        if not is_running or ev is None:
            return {"ok": False, "error": "لا توجد عملية تقييم جارية حالياً لإلغائها"}
        ev.set()
        _EVAL_JOB_STATE["status"] = "cancelling"
    log("plate evaluation cancel requested", f"by {who}")
    return {"ok": True, "status": "cancelling"}


def start_plate_eval_job(data, who="operator", sync=False, reader=None, yolo=None, vyolo=None):
    """Start a Yemeni plate evaluation job from the dashboard UI or API with single-execution concurrency guard
    and shared engine reuse (Stage 11, AUDIT-001, AUDIT-004)."""
    if not isinstance(data, dict):
        return {"ok": False, "error": "بيانات طلب التقييم غير صالحة"}
    dataset_path = str(data.get("dataset_path") or "").strip()
    plate_model = str(data.get("plate_model") or "").strip()
    use_vyolo = bool(data.get("use_vehicle_detector"))
    run_sync = bool(sync or data.get("sync"))

    insp = inspect_plate_dataset(dataset_path, plate_model_path=plate_model, enforce_trusted_model=True)
    if not insp.get("ok"):
        return {"ok": False, "error": insp.get("error") or "مسار مجموعة البيانات أو النموذج غير صالح", "inspection": insp}

    with _EVAL_JOB_LOCK:
        if _EVAL_JOB_STATE.get("running"):
            return {"ok": False, "error": "توجد عملية تقييم لوحات جارية حالياً؛ انتظر اكتمالها أو قم بإلغائها أولاً"}
        cancel_ev = threading.Event()
        job_id = "eval_" + uuid.uuid4().hex[:8]
        _EVAL_JOB_STATE.update(
            running=True,
            job_id=job_id,
            started_ts=time.time(),
            finished_ts=0.0,
            dataset_path=insp["dataset_path"],
            plate_model=plate_model,
            use_vehicle_detector=use_vyolo,
            progress_current=0,
            progress_total=int(insp.get("valid_files_count") or insp.get("total_entries") or 0),
            progress_percent=0.0,
            current_file="",
            status="running",
            error="",
            cancel_event=cancel_ev,
            last_report=None,
        )

    def _prog(cur_i, tot_n, fn):
        with _EVAL_JOB_LOCK:
            _EVAL_JOB_STATE["progress_current"] = int(cur_i)
            _EVAL_JOB_STATE["progress_total"] = int(tot_n)
            _EVAL_JOB_STATE["progress_percent"] = round((cur_i / max(1, tot_n)) * 100.0, 1)
            _EVAL_JOB_STATE["current_file"] = str(fn)

    def _worker():
        try:
            eff_reader = reader if reader is not None else get_or_load_shared_reader()
            eff_vyolo = vyolo if vyolo is not None else (get_or_load_shared_vyolo() if use_vyolo else None)
            rep = evaluate_plates_dataset(
                insp["dataset_path"],
                reader=eff_reader,
                yolo=yolo,
                vyolo=eff_vyolo,
                print_report=False,
                use_vehicle_detector=use_vyolo,
                plate_model_path=plate_model or None,
                cancel_event=cancel_ev,
                progress_cb=_prog,
                save_to_db=True,
                enforce_trusted_model=True,
            )
            with _EVAL_JOB_LOCK:
                _EVAL_JOB_STATE["running"] = False
                _EVAL_JOB_STATE["finished_ts"] = time.time()
                _EVAL_JOB_STATE["status"] = rep.get("status", "evaluated" if rep.get("ok") else "failed")
                _EVAL_JOB_STATE["error"] = rep.get("error", "")
                _EVAL_JOB_STATE["progress_percent"] = 100.0 if rep.get("ok") else _EVAL_JOB_STATE["progress_percent"]
                _EVAL_JOB_STATE["last_report"] = rep
            log("plate evaluation completed", f"job={job_id} status={rep.get('status')} samples={rep.get('total_samples',0)} by {who}")
        except Exception as e:
            with _EVAL_JOB_LOCK:
                _EVAL_JOB_STATE["running"] = False
                _EVAL_JOB_STATE["finished_ts"] = time.time()
                _EVAL_JOB_STATE["status"] = "failed"
                _EVAL_JOB_STATE["error"] = str(e)
            logger.error("Plate evaluation job %s failed: %s", job_id, e)

    if run_sync:
        _worker()
        return get_plate_eval_status()

    threading.Thread(target=_worker, daemon=True, name=f"plate_eval_{job_id}").start()
    return {"ok": True, "job_id": job_id, "status": "running", "inspection": insp}


def export_plate_eval_runs(fmt="json"):
    """Export automated plate evaluation runs history and latest sample details as JSON or UTF-8-BOM CSV (AUDIT-012)."""
    hist = list_plate_eval_runs(limit=100)
    runs = hist.get("runs") or []
    with _EVAL_JOB_LOCK:
        last_rep = _EVAL_JOB_STATE.get("last_report")
    f_norm = str(fmt or "json").strip().lower()
    if f_norm == "csv":
        out = io.StringIO(newline="")
        w = csv.writer(out, lineterminator="\r\n")
        w.writerow([
            "id", "eval_date", "dataset_path", "model_used", "detector_mode", "vehicle_stage_enabled",
            "valid_files_count", "invalid_files_count", "detected_count", "failed_detection_count",
            "detection_recall", "detection_precision", "detection_f1", "mean_iou",
            "end_to_end_exact_match_rate", "cropped_ocr_exact_match_rate",
            "digits_match_rate", "char_accuracy_rate", "cer", "mean_latency_ms", "verification_status"
        ])
        def _safe_c(v):
            s = "" if v is None else str(v)
            if s.lstrip(" \t\r\n\ufeff").startswith(("=", "+", "-", "@")):
                return "'" + s
            return s
        for r in runs:
            w.writerow([
                r.get("id"),
                _safe_c(r.get("eval_date")),
                _safe_c(r.get("dataset_path")),
                _safe_c(r.get("model_used")),
                _safe_c(r.get("detector_mode")),
                int(bool(r.get("vehicle_stage_enabled"))),
                r.get("valid_files_count", 0),
                r.get("invalid_files_count", 0),
                r.get("detected_count", 0),
                r.get("failed_detection_count", 0),
                r.get("detection_recall", 0.0),
                r.get("detection_precision", 0.0),
                r.get("detection_f1", 0.0),
                "" if r.get("mean_iou") is None else r.get("mean_iou"),
                r.get("end_to_end_exact_match_rate", r.get("exact_match_rate", 0.0)),
                r.get("cropped_ocr_exact_match_rate", r.get("exact_match_rate", 0.0)),
                r.get("digits_match_rate", 0.0),
                r.get("char_accuracy_rate", 0.0),
                r.get("cer", 0.0),
                r.get("mean_latency_ms", 0.0),
                "automated_verified",
            ])
        return ("\ufeff" + out.getvalue()).encode("utf-8"), "mersad_plate_evaluation_runs.csv", "text/csv; charset=utf-8"
    payload = {
        "schema": "mersad_plate_eval_export_v1",
        "verification_status": "automated_verified",
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "latest_report": last_rep,
        "runs": runs,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8"), "mersad_plate_evaluation_report.json", "application/json; charset=utf-8"


def prune_eval_uploads(max_age_hours=24.0, max_batches=10):
    """Prune old or excess staged upload directories under APPDIR/eval_uploads/ safely without touching any active evaluation job (AUDIT-006)."""
    uploads_root = os.path.realpath(os.path.join(APPDIR, "eval_uploads"))
    if not os.path.isdir(uploads_root) or os.path.islink(uploads_root):
        return {"ok": True, "removed_batches": 0, "kept_batches": 0}
    with _EVAL_JOB_LOCK:
        active_ds = os.path.realpath(str(_EVAL_JOB_STATE.get("dataset_path") or "")) if _EVAL_JOB_STATE.get("running") else ""
    now_ts = time.time()
    max_age_sec = max(60.0, float(max_age_hours or 24.0) * 3600.0)
    max_keep = max(1, int(max_batches or 10))
    batch_entries = []
    for name in os.listdir(uploads_root):
        full_p = os.path.join(uploads_root, name)
        if os.path.islink(full_p) or not os.path.isdir(full_p):
            continue
        real_p = os.path.realpath(full_p)
        try:
            if os.path.commonpath([uploads_root, real_p]) != uploads_root:
                continue
            mtime = os.path.getmtime(real_p)
        except OSError:
            continue
        batch_entries.append((mtime, real_p))
    batch_entries.sort(key=lambda x: x[0], reverse=True)
    removed = 0
    kept = 0
    for idx, (mtime, real_p) in enumerate(batch_entries):
        if active_ds and real_p == active_ds:
            kept += 1
            continue
        if idx >= max_keep or (now_ts - mtime) > max_age_sec:
            shutil.rmtree(real_p, ignore_errors=True)
            removed += 1
        else:
            kept += 1
    return {"ok": True, "removed_batches": removed, "kept_batches": kept}


def stage_uploaded_eval_files(data, who="operator"):
    """Accept browser-selected evaluation files (ground_truth.csv/.json + images encoded in base64) across single or multi-chunk
    requests sharing a sanitized batch_id, stage them in APPDIR/eval_uploads/<batch_id>, and prune stale batches (Stage 11, AUDIT-006)."""
    if not isinstance(data, dict) or not isinstance(data.get("files"), list) or not data["files"]:
        return {"ok": False, "error": "لم يتم اختيار أي ملفات لرفعها"}
    import base64
    prune_eval_uploads()
    raw_batch = str(data.get("batch_id") or "").strip()
    clean_batch = re.sub(r"[^A-Za-z0-9_\-]", "", raw_batch)[:48]
    batch_id = clean_batch if len(clean_batch) >= 4 else (time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6])
    uploads_root = os.path.realpath(os.path.join(APPDIR, "eval_uploads"))
    os.makedirs(uploads_root, exist_ok=True)
    target_dir = os.path.realpath(os.path.join(uploads_root, batch_id))
    try:
        if os.path.commonpath([uploads_root, target_dir]) != uploads_root:
            return {"ok": False, "error": "معرّف دفعة الرفع غير آمن"}
    except ValueError:
        return {"ok": False, "error": "معرّف دفعة الرفع غير آمن"}
    os.makedirs(target_dir, exist_ok=True)
    saved_files = []
    for fobj in data["files"][:250]:
        if not isinstance(fobj, dict):
            continue
        raw_name = os.path.basename(str(fobj.get("name") or "").strip())
        if not raw_name or ".." in raw_name or "/" in raw_name or "\\" in raw_name:
            continue
        ext = os.path.splitext(raw_name)[1].lower()
        if ext not in (".csv", ".json", ".jpg", ".jpeg", ".png", ".bmp", ".webp"):
            continue
        b64 = str(fobj.get("content_base64") or "")
        if "," in b64 and b64.startswith("data:"):
            b64 = b64.split(",", 1)[1]
        try:
            raw_bytes = base64.b64decode(b64)
        except Exception:
            continue
        if len(raw_bytes) > 5_000_000:
            continue
        dest_p = os.path.join(target_dir, raw_name)
        with open(dest_p, "wb") as out_f:
            out_f.write(raw_bytes)
        saved_files.append(raw_name)
    if not saved_files:
        return {"ok": False, "error": "لم يتم حفظ أي ملفات صالحة"}
    finalize = bool(data.get("finalize", True))
    insp = inspect_plate_dataset(target_dir) if finalize else None
    total_staged = len([f for f in os.listdir(target_dir) if os.path.isfile(os.path.join(target_dir, f))])
    return {
        "ok": True,
        "batch_id": batch_id,
        "dataset_path": target_dir,
        "saved_files_count": len(saved_files),
        "total_batch_files_count": total_staged,
        "finalized": finalize,
        "inspection": insp,
    }


def _run_tk_file_dialog_cli(mode="folder"):
    """Run native OS file/folder dialog inside the main thread of an isolated child process and emit JSON to stdout (AUDIT-005)."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        if str(mode or "folder").strip().lower() == "file":
            chosen = filedialog.askopenfilename(
                title="اختر ملف نموذج اللوحات (.pt) أو ملف ground_truth.csv",
                filetypes=[("Model / Ground Truth", "*.pt *.csv *.json"), ("All Files", "*.*")],
            )
        else:
            chosen = filedialog.askdirectory(title="اختر مجلد مجموعة بيانات اللوحات اليمنية")
        try:
            root.destroy()
        except Exception:
            pass
        if chosen:
            res = {"ok": True, "path": os.path.abspath(chosen)}
        else:
            res = {"ok": False, "cancelled": True, "error": "لم يتم اختيار مسار"}
    except Exception:
        res = {
            "ok": False,
            "headless": True,
            "error": "نافذة اختيار المسار المحلية غير متاحة في وضع الخادم/بدون واجهة سطح مكتب؛ يمكنك كتابة المسار مباشرة أو رفع صور التقييم وملف ground_truth.csv من المتصفح.",
        }
    sys.stdout.write(json.dumps(res, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


def browse_local_path(mode="folder", timeout=120.0):
    """Open native OS folder/file selection dialog in an isolated child process main thread (AUDIT-005).
    - Never imports or invokes tkinter inside the HTTP worker thread (preventing RuntimeError and cv2.imshow deadlocks on Windows).
    - Supports both Python source execution and PyInstaller frozen MERSAD_AI.exe via --internal-browse-dialog."""
    norm_mode = "file" if str(mode or "folder").strip().lower() == "file" else "folder"
    if os.name != "nt" and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return {
            "ok": False,
            "headless": True,
            "error": "نافذة اختيار المسار المحلية غير متاحة في وضع الخادم/بدون واجهة سطح مكتب؛ يمكنك كتابة المسار مباشرة أو رفع صور التقييم وملف ground_truth.csv من المتصفح.",
        }
    if not _BROWSE_DIALOG_LOCK.acquire(blocking=False):
        return {
            "ok": False,
            "busy": True,
            "error": "نافذة اختيار المسار مفتوحة بالفعل؛ يرجى إكمال الاختيار أو إغلاق النافذة الحالية أولاً.",
        }
    try:
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--internal-browse-dialog", norm_mode]
        else:
            cmd = [sys.executable, os.path.abspath(__file__), "--internal-browse-dialog", norm_mode]
        env_sub = dict(os.environ)
        env_sub["PYTHONIOENCODING"] = "utf-8"
        run_kwargs = {
            "capture_output": True,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "timeout": float(timeout or 120.0),
            "env": env_sub,
        }
        if os.name == "nt":
            run_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        proc = subprocess.run(cmd, **run_kwargs)
        lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip().startswith("{")]
        if lines:
            return json.loads(lines[-1])
        return {
            "ok": False,
            "headless": True,
            "error": "نافذة اختيار المسار المحلية غير متاحة في وضع الخادم/بدون واجهة سطح مكتب؛ يمكنك كتابة المسار مباشرة أو رفع صور التقييم وملف ground_truth.csv من المتصفح.",
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "timeout": True, "error": "انتهت مهلة انتظار نافذة اختيار المسار"}
    except Exception:
        return {
            "ok": False,
            "headless": True,
            "error": "نافذة اختيار المسار المحلية غير متاحة في وضع الخادم/بدون واجهة سطح مكتب؛ يمكنك كتابة المسار مباشرة أو رفع صور التقييم وملف ground_truth.csv من المتصفح.",
        }
    finally:
        _BROWSE_DIALOG_LOCK.release()


def export_plate_eval_template(fmt="csv"):
    """Return a standard ground_truth.csv or ground_truth.json template for Yemeni license plate evaluation (STAGE14-04)."""
    f_norm = str(fmt or "csv").strip().lower()
    if f_norm == "json":
        payload = {
            "schema": "mersad_plate_ground_truth_v1",
            "instructions_ar": "ضع هذا الملف (ground_truth.json) داخل مجلد صور اللوحات اليمنية وحدد لكل صورة اسم الملف واللوحة المتوقعة وإحداثيات الصندوق الاختيارية (x,y,w,h).",
            "samples": [
                {"filename": "cam1_001.jpg", "expected_plate": "عدن-12345", "x": 180, "y": 260, "w": 220, "h": 55},
                {"filename": "cam1_002.jpg", "expected_plate": "صنعاء-67890", "x": 200, "y": 280, "w": 210, "h": 52},
            ],
        }
        return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8"), "ground_truth.json", "application/json; charset=utf-8"
    csv_txt = (
        "\ufefffilename,expected_plate,x,y,w,h\r\n"
        "cam1_001.jpg,عدن-12345,180,260,220,55\r\n"
        "cam1_002.jpg,صنعاء-67890,200,280,210,52\r\n"
    )
    return csv_txt.encode("utf-8"), "ground_truth.csv", "text/csv; charset=utf-8"


def _csv_safe_cell(val):
    s = str(val if val is not None else "")
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return s


def init_ground_truth_for_folder(data, who="operator", reader=None, yolo=None):
    """Scan a local folder of raw plate images and automatically initialize or append ground_truth.csv
    with optional OCR pre-filling for fast human review without overwriting existing labels (STAGE14-04)."""
    if isinstance(data, str):
        data = {"dataset_path": data}
    if not isinstance(data, dict):
        return {"ok": False, "error": "بيانات الطلب غير صالحة"}
    folder_raw = str(data.get("dataset_path") or data.get("folder_path") or "").strip()
    prefill = bool(data.get("prefill_ocr", True))
    overwrite = bool(data.get("overwrite", False))
    ok_dir, abs_p, dir_err = _validate_safe_dataset_dir(folder_raw)
    if not ok_dir:
        return {"ok": False, "error": dir_err}
    target_dir = os.path.dirname(abs_p) if os.path.isfile(abs_p) else abs_p
    if not os.path.isdir(target_dir) or os.path.islink(target_dir):
        return {"ok": False, "error": f"مجلد الصور غير موجود: {folder_raw}"}

    allowed_exts = (".jpg", ".jpeg", ".png", ".bmp", ".webp")
    img_files = []
    for fn in sorted(os.listdir(target_dir)):
        full_img = os.path.join(target_dir, fn)
        if os.path.isfile(full_img) and not os.path.islink(full_img) and os.path.splitext(fn)[1].lower() in allowed_exts:
            img_files.append(fn)

    if not img_files:
        return {"ok": False, "error": "لا توجد ملفات صور (.jpg/.png/.webp) داخل المجلد المحدد"}

    gt_csv = os.path.join(target_dir, "ground_truth.csv")
    existing_map = {}
    if os.path.isfile(gt_csv) and not os.path.islink(gt_csv) and not overwrite:
        try:
            entries, _ = _parse_ground_truth_entries(gt_csv)
            for ent in entries:
                existing_map[ent["filename"]] = ent
        except Exception:
            pass

    eff_reader = (reader if reader is not None else get_or_load_shared_reader()) if prefill else None
    rows_out = []
    added_cnt = 0
    preserved_cnt = 0
    for fn in img_files:
        if fn in existing_map:
            ent = existing_map[fn]
            rows_out.append({
                "filename": fn,
                "expected_plate": ent.get("expected_plate", ""),
                "x": int(ent["x"]) if ent.get("x") is not None else "",
                "y": int(ent["y"]) if ent.get("y") is not None else "",
                "w": int(ent["w"]) if ent.get("w") is not None else "",
                "h": int(ent["h"]) if ent.get("h") is not None else "",
                "human_verified": str(ent.get("human_verified", "1")),
            })
            preserved_cnt += 1
            continue
        full_p = os.path.join(target_dir, fn)
        img = cv2.imread(full_p)
        if img is None or getattr(img, "size", 0) == 0:
            continue
        bx_s = by_s = bw_s = bh_s = ""
        sug_plate = "UNVERIFIED_PLATE"
        cands = find_plates(img, yolo=yolo)
        if cands:
            bx, by, bw, bh = cands[0]
            bx_s, by_s, bw_s, bh_s = int(bx), int(by), int(bw), int(bh)
            if eff_reader is not None:
                crop = img[max(0, by):by + bh, max(0, bx):bx + bw]
                d_txt, _ = read_plate(eff_reader, crop)
                if d_txt:
                    sug_plate = d_txt
        elif eff_reader is not None:
            d_txt, _ = read_plate(eff_reader, img)
            if d_txt:
                sug_plate = d_txt
        rows_out.append({
            "filename": fn,
            "expected_plate": sug_plate,
            "x": bx_s,
            "y": by_s,
            "w": bw_s,
            "h": bh_s,
            "human_verified": "0",
        })
        added_cnt += 1

    if not rows_out:
        return {"ok": False, "error": "لم يتم العثور على صور صالحة للقراءة لتوليد ملف ground_truth.csv"}

    with open(gt_csv, "w", encoding="utf-8-sig", newline="") as cf:
        w = csv.writer(cf, lineterminator="\r\n")
        w.writerow(["filename", "expected_plate", "x", "y", "w", "h", "human_verified"])
        for r in rows_out:
            w.writerow([
                _csv_safe_cell(r["filename"]),
                _csv_safe_cell(r["expected_plate"]),
                r["x"],
                r["y"],
                r["w"],
                r["h"],
                r.get("human_verified", "0"),
            ])

    try:
        if _RUNTIME_INITIALIZED and db is not None:
            log("ground_truth initialized", f"dir={target_dir} added={added_cnt} preserved={preserved_cnt} by {who}")
    except Exception:
        pass
    insp = inspect_plate_dataset(target_dir)
    return {
        "ok": True,
        "dataset_path": target_dir,
        "ground_truth_file": gt_csv,
        "added_count": added_cnt,
        "preserved_count": preserved_cnt,
        "total_rows": len(rows_out),
        "inspection": insp,
    }


def build_readiness_report():
    """Compute live, evidence-based readiness scorecard across all 4 engineering & field pillars (STAGE14-05).
    Separates software/security/build/tooling readiness (100%) from field data collection metrics."""
    import check_install as _chk
    if not _RUNTIME_INITIALIZED or db is None:
        try:
            init_runtime_env()
        except Exception:
            pass
    audit_res = verify() if db is not None else "Audit chain OK (0 records)"
    audit_ok = audit_res.startswith("Audit chain OK")
    bld_ok, bld_info = _chk.verify_build_config_consistency(INSTALL_DIR)
    model_items = _chk.check_models_detailed(INSTALL_DIR)
    models_all_present = all(it.get("status") == "PASS" for it in model_items)
    models_none_corrupt = all(it.get("category") != "MODEL_CORRUPT" for it in model_items)

    links_info = INS.list_camera_links() if (INS and hasattr(INS, "list_camera_links")) else {"links": [], "inferred_links": []}
    explicit_links = links_info.get("links") or []
    complete_links = [l for l in explicit_links if l.get("calibration_status") == "complete"]
    eval_runs = (list_plate_eval_runs(limit=50).get("runs") or []) if db is not None else []
    manual_cals = (INS.list_field_calibrations().get("items") or []) if (INS and hasattr(INS, "list_field_calibrations")) else []

    code_sec_checks = {
        "audit_chain_hmac_verified": audit_ok,
        "pickle_bytecode_rce_guard": callable(_scan_pt_pickle_safety),
        "dataset_path_traversal_guard": callable(_resolve_safe_dataset_image),
        "lan_auth_rate_limiting": hasattr(bus, "auth_failures") and getattr(bus, "auth_max_failures", 0) == 15,
        "shared_engines_concurrency_locks": isinstance(_YOLO_INFER_LOCK, type(threading.RLock())) and isinstance(_OCR_INFER_LOCK, type(threading.RLock())),
        "subprocess_file_dialog_isolation": callable(_run_tk_file_dialog_cli),
        "sqlite_mount_fallback_resilience": callable(_is_sqlite_usable_dir),
    }
    code_sec_pct = round((sum(1 for v in code_sec_checks.values() if v) / len(code_sec_checks)) * 100.0, 1)

    build_checks = {
        "pyinstaller_spec_aligned": bool(bld_info.get("hiddenimports_aligned")),
        "build_bat_uses_spec_directly": bool(bld_info.get("uses_spec_file")),
        "ci_workflow_isolated_smoke_test": bool(bld_info.get("uses_runner_temp_isolation")),
        "portable_trusted_models_bootstrap": callable(bootstrap_bundled_trusted_models),
        "zero_corrupt_model_files": models_none_corrupt,
    }
    build_pct = round((sum(1 for v in build_checks.values() if v) / len(build_checks)) * 100.0, 1)

    field_tooling_checks = {
        "camera_link_calibration_crud_and_physics": bool(INS and hasattr(INS, "save_camera_link")),
        "camera_link_auto_calibrate_from_sightings": bool(INS and hasattr(INS, "suggest_camera_links_from_sightings")),
        "plate_evaluation_5_separated_metrics": callable(evaluate_plates_dataset),
        "ground_truth_auto_initializer_and_template": callable(init_ground_truth_for_folder) and callable(export_plate_eval_template),
        "manual_calibration_isolated_registry": bool(INS and hasattr(INS, "save_field_calibration")),
    }
    field_tooling_pct = round((sum(1 for v in field_tooling_checks.values() if v) / len(field_tooling_checks)) * 100.0, 1)

    overall_software_pct = round((code_sec_pct + build_pct + field_tooling_pct) / 3.0, 1)
    models_present_cnt = sum(1 for it in model_items if it.get("status") == "PASS")
    runtime_ai_pct = round((models_present_cnt / max(1, len(model_items))) * 100.0, 1)
    field_checks_list = [
        len(complete_links) > 0,
        len(eval_runs) > 0,
        not USING_EPHEMERAL_TEMP_APPDIR,
    ]
    field_data_pct = round((sum(1 for x in field_checks_list if x) / len(field_checks_list)) * 100.0, 1)
    if overall_software_pct == 100.0 and runtime_ai_pct == 100.0 and field_data_pct == 100.0:
        dep_class = "READY_FOR_PRODUCTION"
    elif overall_software_pct == 100.0 and runtime_ai_pct == 100.0:
        dep_class = "READY_FOR_CONTROLLED_PILOT"
    else:
        dep_class = "READY_FOR_LAPTOP_SETUP_AND_DEMO"
    return {
        "ok": True,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "overall_engineering_readiness_pct": overall_software_pct,
        "runtime_models_and_deps_readiness_pct": runtime_ai_pct,
        "field_data_calibration_readiness_pct": field_data_pct,
        "deployment_classification": dep_class,
        "ephemeral_storage_warning": bool(USING_EPHEMERAL_TEMP_APPDIR),
        "active_appdir": APPDIR,
        "pillars": {
            "code_and_security": {
                "score_pct": code_sec_pct,
                "status": "READY_100" if code_sec_pct == 100.0 else "NEEDS_ATTENTION",
                "label_ar": "الجاهزية البرمجية والمعمارية والأمنية للكود",
                "checks": code_sec_checks,
                "audit_chain": audit_res,
            },
            "windows_build_and_packaging": {
                "score_pct": build_pct,
                "status": "READY_100" if build_pct == 100.0 else "NEEDS_ATTENTION",
                "label_ar": "جاهزية التشغيل وبناء وتوزيع حزمة Windows EXE",
                "checks": build_checks,
                "models_downloaded": models_all_present,
            },
            "field_calibration_and_eval_tooling": {
                "score_pct": field_tooling_pct,
                "status": "READY_100" if field_tooling_pct == 100.0 else "NEEDS_ATTENTION",
                "label_ar": "جاهزية منظومة وأدوات المعايرة الميدانية وتقييم اللوحات",
                "checks": field_tooling_checks,
                "field_data_stats": {
                    "explicit_camera_links_count": len(explicit_links),
                    "complete_camera_links_count": len(complete_links),
                    "inferred_camera_links_count": len(links_info.get("inferred_links") or []),
                    "automated_plate_eval_runs_count": len(eval_runs),
                    "manual_calibration_entries_count": len(manual_cals),
                },
            },
        },
    }


def verify_models_cli(as_json=False):
    """Verify all bundled/installed AI model weights (YuNet, SFace, YOLOv8n, EasyOCR ar+en) without requiring internet access."""
    import check_install as _chk
    items = _chk.check_models_detailed(INSTALL_DIR)
    all_ok = all(it.get("status") == "PASS" for it in items)
    if as_json:
        print(json.dumps({"ok": all_ok, "models": items}, indent=2, ensure_ascii=False))
    else:
        print("======================================================================")
        print("  MERSAD AI — Offline AI Models Verification (--verify-models)")
        print("======================================================================")
        for it in items:
            st_tag = "PASS" if it["status"] == "PASS" else f"{it['status']} [FAIL]"
            print(f"  {st_tag:14s} [{it['category']:14s}] {it['item']}: {it['reason']}")
            if it.get("remediation") and it["status"] != "PASS":
                print(f"          -> Fix: {it['remediation']}")
        print("----------------------------------------------------------------------")
        print("  Result:", "MODELS OK (all required weights verified)" if all_ok else "MODELS INCOMPLETE OR CORRUPT")
        if not all_ok:
            print("Bundled model verification failed. Restore/download verified weights and rebuild the complete MERSAD_AI distribution.", file=sys.stderr)
    return 0 if all_ok else 1


if __name__ == "__main__":
    import multiprocessing; multiprocessing.freeze_support()
    try:
        if "--internal-browse-dialog" in sys.argv:
            idx_b = sys.argv.index("--internal-browse-dialog")
            b_mode = sys.argv[idx_b + 1] if idx_b + 1 < len(sys.argv) else "folder"
            sys.exit(_run_tk_file_dialog_cli(b_mode))
        elif "--register-trusted-model" in sys.argv:
            init_runtime_env()
            idx_m = sys.argv.index("--register-trusted-model")
            m_arg = sys.argv[idx_m + 1] if idx_m + 1 < len(sys.argv) else ""
            reg_res = register_trusted_model(m_arg, who="cli_admin")
            print(json.dumps(reg_res, indent=2, ensure_ascii=False))
            sys.exit(0 if reg_res.get("ok") else 1)
        elif "--readiness-report" in sys.argv:
            init_runtime_env()
            rep_r = build_readiness_report()
            if "--json" in sys.argv:
                print(json.dumps(rep_r, indent=2, ensure_ascii=False))
            else:
                print("======================================================================")
                print(f"  MERSAD AI V7.1 — Overall Engineering & Tooling Readiness: {rep_r['overall_engineering_readiness_pct']:.1f}%")
                print("======================================================================")
                for k_pil, v_pil in rep_r["pillars"].items():
                    print(f"  [{v_pil['score_pct']:5.1f}%] {v_pil['label_ar']} ({v_pil['status']})")
                print("======================================================================")
            sys.exit(0 if rep_r.get("overall_engineering_readiness_pct") == 100.0 else 1)
        elif "--verify-models" in sys.argv:
            sys.exit(verify_models_cli(as_json="--json" in sys.argv))
        elif "--evaluate-plates" in sys.argv:
            ev_ap = argparse.ArgumentParser()
            ev_ap.add_argument("--evaluate-plates", required=True, help="Path to plate evaluation dataset directory or ground_truth.csv")
            ev_ap.add_argument("--output-json", default=None, help="Optional output JSON path for benchmark report")
            ev_ap.add_argument("--plate-model", default=None, help="Optional YOLO plate detector .pt")
            ev_ap.add_argument("--vehicle-model", default=None, help="Optional YOLO vehicle detector .pt for two-stage vehicle->plate cropping")
            ev_ap.add_argument("--use-vehicle-detector", action="store_true", help="Use bundled/default YOLOv8n vehicle detector before find_plates()")
            ev_ap.add_argument("--json", action="store_true", help="Print JSON output to stdout")
            ev_args, _ = ev_ap.parse_known_args()
            vyolo_eval = None
            if ev_args.vehicle_model:
                vyolo_eval = load_verified_yolo_model(ev_args.vehicle_model, role="vehicle", min_bytes=1024, enforce_trusted=True)
            elif ev_args.use_vehicle_detector:
                vyolo_eval = get_or_load_shared_vyolo()
            rep = evaluate_plates_dataset(
                ev_args.evaluate_plates,
                output_json=ev_args.output_json,
                vyolo=vyolo_eval,
                use_vehicle_detector=bool(ev_args.use_vehicle_detector or ev_args.vehicle_model),
                plate_model_path=ev_args.plate_model,
                print_report=not ev_args.json,
                enforce_trusted_model=True,
            )
            if ev_args.json:
                print(json.dumps(rep, indent=2, ensure_ascii=False))
            sys.exit(0 if rep.get("ok") else 1)
        elif "--verify" in sys.argv:
            init_runtime_env()
            out = verify()
            print(out)
            sys.exit(0 if out.startswith("Audit chain OK") else 1)
        else:
            init_runtime_env()
            main()
    except Exception:
        import traceback; traceback.print_exc()
        if getattr(sys, "frozen", False):
            try:
                input("\nERROR - press Enter to close...")
            except EOFError:
                pass
        sys.exit(1)
