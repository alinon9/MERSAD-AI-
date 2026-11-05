"""Persistent camera status history and uptime estimates for MERSAD AI.

Uptime is based only on observed camera state intervals within an application
session; intervals across process restarts are intentionally not inferred.
"""
from __future__ import annotations

import atexit
import csv
import io
import sqlite3
import threading
import time
import uuid

import registry as R

ALLOWED_STATUSES = {"online", "reconnecting", "offline", "unknown"}
REASONS = {
    "startup", "camera_reconnected", "frame_received", "read_failed",
    "stream_stalled", "offline_timeout", "application_stop", "status_unknown",
}
SESSION_ID = uuid.uuid4().hex
_DB = None
_LOCK = threading.RLock()
_DB_PATH = None
_CURRENT = {}


def init(db, lock, db_path=None):
    global _DB, _LOCK, _DB_PATH
    eff_lock = lock or threading.RLock()
    with eff_lock:
        if _DB is not db or _DB_PATH != db_path:
            _CURRENT.clear()
        _DB, _LOCK, _DB_PATH = db, eff_lock, db_path

    def _ensure_schema(conn):
        # Schema creation must be serialized across application processes too.
        conn.execute("""CREATE TABLE IF NOT EXISTS camera_status_history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            cam TEXT NOT NULL,
            prev_status TEXT,
            status TEXT NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            session_id TEXT NOT NULL,
            duration_sec REAL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_camera_history_cam_ts ON camera_status_history(cam, ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_camera_history_session_ts ON camera_status_history(session_id, ts)")
        return True

    return bool(R.run_atomic_tx(db, _LOCK, _ensure_schema, db_path=db_path))


def record_status(cam, status, reason="status_unknown", ts=None, force=False):
    """Record a camera state transition once; repeated polls do not create noise."""
    if _DB is None:
        return False
    cam = str(cam or "").strip()[:128]
    status = str(status or "unknown").lower()
    if not cam or status not in ALLOWED_STATUSES:
        return False
    reason = reason if reason in REASONS else "status_unknown"
    ts = float(time.time() if ts is None else ts)
    if ts < 0:
        return False
    state_key = (id(_DB), _DB_PATH or "", SESSION_ID, cam)
    with _LOCK:
        if not force and _CURRENT.get(state_key) == status:
            return False

    def tx(conn):
        row = conn.execute(
            "SELECT status, ts FROM camera_status_history WHERE cam=? AND session_id=? ORDER BY ts DESC, id DESC LIMIT 1",
            (cam, SESSION_ID),
        ).fetchone()
        previous = row[0] if row else None
        prev_ts = float(row[1]) if row else None
        if previous == status and not force:
            return False
        # Do not attribute transitions across process restarts: the intervening
        # interval is unobserved, so the first event of a new session has no prior state.
        duration = max(0.0, ts - prev_ts) if prev_ts is not None and ts >= prev_ts else None
        conn.execute(
            "INSERT INTO camera_status_history(ts,cam,prev_status,status,reason,session_id,duration_sec) VALUES(?,?,?,?,?,?,?)",
            (ts, cam, previous, status, reason, SESSION_ID, duration),
        )
        return True

    try:
        changed = R.run_atomic_tx(_DB, _LOCK, tx, db_path=_DB_PATH)
        with _LOCK:
            _CURRENT[state_key] = status
            _CURRENT[cam] = status
        return bool(changed)
    except (sqlite3.Error, OSError, RuntimeError):
        return False


def close_session():
    """Best-effort close markers so last observed intervals are not extended past a clean shutdown."""
    with _LOCK:
        items_snap = list(_CURRENT.items())
    for cam, status in items_snap:
        if isinstance(cam, str) and status != "unknown":
            record_status(cam, "unknown", "application_stop", force=True)


atexit.register(close_session)


def prune_history(retention_days=90, now=None, db=None, lock=None, db_path=None):
    """Atomically delete camera_status_history rows older than max(30.0, float(retention_days)) days (POST-GAP-05)."""
    eff_days = max(30.0, float(retention_days if retention_days is not None else 90.0))
    eff_db = db if db is not None else _DB
    eff_lock = lock if lock is not None else _LOCK
    eff_path = db_path if db_path is not None else _DB_PATH
    if eff_db is None:
        return {"ok": False, "deleted": 0, "retention_days": eff_days}
    now_ts = float(time.time() if now is None else now)
    cutoff = now_ts - eff_days * 86400.0

    def _tx(conn):
        cur = conn.execute("DELETE FROM camera_status_history WHERE ts < ?", (cutoff,))
        return int(cur.rowcount or 0)

    try:
        deleted = int(R.run_atomic_tx(eff_db, eff_lock, _tx, db_path=eff_path) or 0)
        return {"ok": True, "deleted": deleted, "retention_days": eff_days}
    except (sqlite3.Error, OSError, RuntimeError) as e:
        return {"ok": False, "deleted": 0, "retention_days": eff_days, "error": str(e)}


def _window_seconds(period):
    return {"24h": 86400, "7d": 7 * 86400, "30d": 30 * 86400}.get(str(period or "24h").lower(), 86400)


def build_report(db=None, current_cameras=None, period="24h", now=None):
    """Compute observed uptime and outage summaries for 24 hours, 7 days, or 30 days."""
    db = db or _DB
    now = float(time.time() if now is None else now)
    span = _window_seconds(period)
    start = now - span
    current_cameras = current_cameras if isinstance(current_cameras, dict) else {}
    if db is None:
        return {"ok": True, "period": period, "from": start, "to": now, "cameras": [], "events": [], "note": "لا تتوفر قاعدة بيانات لسجل الكاميرات."}

    eff_lock = _LOCK or threading.RLock()
    try:
        with eff_lock:
            rows = db.execute(
                "SELECT ts, cam, prev_status, status, reason, session_id FROM camera_status_history WHERE ts<=? ORDER BY cam, ts, id",
                (now,),
            ).fetchall()
    except sqlite3.Error:
        rows = []

    per_cam = {}
    for ts, cam, prev, status, reason, session in rows:
        per_cam.setdefault(str(cam), []).append({
            "ts": float(ts), "prev_status": prev, "status": str(status or "unknown"),
            "reason": str(reason or ""), "session_id": str(session or ""),
        })

    names = set(per_cam) | {str(k) for k in current_cameras}
    summaries = []
    now_session = SESSION_ID
    for cam in sorted(names, key=str.lower):
        evs = per_cam.get(cam, [])
        online_sec = 0.0
        downtime_sec = 0.0
        unknown_sec = 0.0
        observed_sec = 0.0
        outages = recoveries = 0
        # Each session forms its own observation segments. Do not fill gaps between runs.
        sessions = {}
        for event in evs:
            sessions.setdefault(event["session_id"], []).append(event)
        for sess, seq in sessions.items():
            seq.sort(key=lambda x: x["ts"])
            for i, event in enumerate(seq):
                a = event["ts"]
                if i + 1 < len(seq):
                    b = seq[i + 1]["ts"]
                elif sess == now_session:
                    b = now
                else:
                    # No shutdown marker means we do not infer how long an old state lasted.
                    continue
                left, right = max(start, a), min(now, b)
                if right <= left:
                    continue
                seconds = right - left
                status = event["status"]
                if status == "online":
                    online_sec += seconds
                    observed_sec += seconds
                elif status in ("offline", "reconnecting"):
                    downtime_sec += seconds
                    observed_sec += seconds
                else:
                    unknown_sec += seconds

            in_window = [e for e in seq if start <= e["ts"] <= now]
            for event in in_window:
                if event["status"] in ("offline", "reconnecting") and event.get("prev_status") == "online":
                    outages += 1
                if event["status"] == "online" and event.get("prev_status") in ("offline", "reconnecting"):
                    recoveries += 1

        live = current_cameras.get(cam) if isinstance(current_cameras.get(cam), dict) else {}
        live_status = str(live.get("status") or "unknown")
        # The app's current status is authoritative for the present, history is authoritative for past intervals.
        last = evs[-1] if evs else None
        pct = round((online_sec / observed_sec) * 100, 2) if observed_sec else None
        summaries.append({
            "camera": cam,
            "status": live_status if cam in current_cameras else (last["status"] if last else "unknown"),
            "uptime_percent": pct,
            "online_seconds": round(online_sec, 1),
            "downtime_seconds": round(downtime_sec, 1),
            "observed_seconds": round(observed_sec, 1),
            "unknown_seconds": round(unknown_sec, 1),
            "outages": outages,
            "recoveries": recoveries,
            "last_change": last["ts"] if last else None,
            "coverage_percent": round(min(100.0, (observed_sec / span) * 100), 2),
            "coverage_note": "محسوب من فترات الحالة المرصودة فقط؛ لا تُقدّر الفجوات بين جلسات تشغيل البرنامج.",
        })

    recent_events = []
    for cam, evs in per_cam.items():
        recent_events.extend({"ts": e["ts"], "camera": cam, "previous_status": e["prev_status"], "status": e["status"], "reason": e["reason"]}
                             for e in evs if start <= e["ts"] <= now)
    recent_events.sort(key=lambda x: x["ts"], reverse=True)
    return {
        "ok": True, "period": period if period in ("24h", "7d", "30d") else "24h",
        "from": start, "to": now, "generated_at": now,
        "cameras": summaries, "events": recent_events[:300],
        "note": "النسب تقديرية مبنية على فترات الحالة المرصودة، ولا تُحتسب فجوات توقف التطبيق ضمن زمن التشغيل أو الانقطاع.",
    }


def _csv_safe(value):
    value = "" if value is None else str(value)
    if value.lstrip(" \t\r\n\ufeff").startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def export_csv(report):
    out = io.StringIO(newline="")
    w = csv.writer(out, lineterminator="\r\n")
    w.writerow(["record_type", "camera", "timestamp", "status", "previous_status", "uptime_percent", "online_seconds", "downtime_seconds", "observed_seconds", "coverage_percent", "outages", "recoveries", "reason"])
    for cam in report.get("cameras", []):
        w.writerow(["summary", _csv_safe(cam.get("camera")), "", _csv_safe(cam.get("status")), "",
                    _csv_safe(cam.get("uptime_percent")), _csv_safe(cam.get("online_seconds")),
                    _csv_safe(cam.get("downtime_seconds")), _csv_safe(cam.get("observed_seconds")),
                    _csv_safe(cam.get("coverage_percent")), _csv_safe(cam.get("outages")),
                    _csv_safe(cam.get("recoveries")), ""])
    for event in report.get("events", []):
        w.writerow(["event", _csv_safe(event.get("camera")), _csv_safe(event.get("ts")),
                    _csv_safe(event.get("status")), _csv_safe(event.get("previous_status")), "", "", "", "", "", "", "",
                    _csv_safe(event.get("reason"))])
    return ("\ufeff" + out.getvalue()).encode("utf-8")
