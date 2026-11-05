"""Privacy-conscious, read-only operational analytics for MERSAD AI.

This module deliberately reports aggregates only; it never exports plate values,
person names, embeddings, raw OCR text, or evidence paths.
"""
from __future__ import annotations

import csv
import io
import math
import sqlite3
import time
from datetime import datetime


def _tables(db):
    try:
        return {str(r[0]) for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    except Exception:
        return set()


def _cols(db, table):
    try:
        return {str(r[1]) for r in db.execute(f'PRAGMA table_info("{table}")')}
    except Exception:
        return set()


def _scalar(db, sql, params=(), default=0):
    try:
        row = db.execute(sql, params).fetchone()
        return default if not row or row[0] is None else row[0]
    except (sqlite3.Error, TypeError, ValueError):
        return default


def _safe_count(v):
    try:
        return max(0, int(v or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _label(ts):
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%H:%M")
    except (TypeError, ValueError, OSError, OverflowError):
        return "—"


def build_report(db, cameras=None, now=None):
    """Build a read-only 24-hour report safe for empty and legacy SQLite databases."""
    now = float(time.time() if now is None else now)
    start = now - 86400.0
    previous_start = now - 172800.0
    tables = _tables(db)
    sightings_cols = _cols(db, "sightings") if "sightings" in tables else set()
    alerts_cols = _cols(db, "alerts") if "alerts" in tables else set()
    live_clause = " AND COALESCE(src,'live')='live'" if "src" in sightings_cols else ""
    ts_col = "ts" if "ts" in sightings_cols else None

    current = previous = 0
    trend = [{"label": _label(start + i * 3600), "count": 0} for i in range(24)]
    classes = {}
    confidence = {"high": 0, "medium": 0, "low": 0, "unknown": 0}
    mean_conf = {}

    if ts_col:
        current = _safe_count(_scalar(db, f"SELECT COUNT(*) FROM sightings WHERE ts>=? AND ts<=?{live_clause}", (start, now)))
        previous = _safe_count(_scalar(db, f"SELECT COUNT(*) FROM sightings WHERE ts>=? AND ts<?{live_clause}", (previous_start, start)))
        try:
            class_expr = "COALESCE(NULLIF(vclass,''),'unknown')" if "vclass" in sightings_cols else "'unknown'"
            conf_expr = "conf" if "conf" in sightings_cols else "NULL"
            cam_expr = "COALESCE(cam,'unknown')" if "cam" in sightings_cols else "'unknown'"
            rows = db.execute(
                f"SELECT ts, {class_expr}, {conf_expr}, {cam_expr} "
                f"FROM sightings WHERE ts>=? AND ts<=?{live_clause} ORDER BY ts",
                (start, now),
            ).fetchall()
        except sqlite3.Error:
            rows = []
        cam_conf = {}
        for ts, vclass, conf, cam in rows:
            try:
                ix = int((float(ts) - start) // 3600)
                if 0 <= ix < 24:
                    trend[ix]["count"] += 1
            except (TypeError, ValueError, OverflowError):
                pass
            cls = str(vclass or "unknown")[:40]
            classes[cls] = classes.get(cls, 0) + 1
            try:
                c = float(conf)
                if not math.isfinite(c) or c < 0 or c > 1:
                    raise ValueError
                confidence["high" if c >= .85 else "medium" if c >= .65 else "low"] += 1
                cam_name = str(cam or "unknown")[:128]
                item = cam_conf.setdefault(cam_name, [0.0, 0])
                item[0] += c
                item[1] += 1
            except (TypeError, ValueError, OverflowError):
                confidence["unknown"] += 1
        mean_conf = {cam: round(total / n, 4) for cam, (total, n) in cam_conf.items() if n}

    cam_input = cameras if isinstance(cameras, dict) else {}
    camera_health = []
    for name, item in sorted(cam_input.items(), key=lambda kv: str(kv[0]).lower()):
        if not isinstance(item, dict):
            item = {}
        status = str(item.get("status") or "unknown")[:32]
        camera_health.append({
            "camera": str(name)[:128],
            "status": status,
            "fps": _rounded(item.get("fps"), 1),
            "frames": _safe_count(item.get("frames")),
            "detections": _safe_count(item.get("detections")),
            "errors": _safe_count(item.get("errors")),
            "reconnect_count": _safe_count(item.get("reconnect_count", item.get("fail_count", 0))),
            "mean_ocr_confidence": mean_conf.get(str(name), None),
        })

    alert_summary = {"last_24h": 0, "pending": 0, "confirmed": 0, "dismissed": 0, "dispatch_failed": 0, "dispatch_pending": 0}
    if "alerts" in tables:
        if "ts" in alerts_cols:
            alert_summary["last_24h"] = _safe_count(_scalar(db, "SELECT COUNT(*) FROM alerts WHERE ts>=? AND ts<=?", (start, now)))
        if "status" in alerts_cols:
            alert_summary["pending"] = _safe_count(_scalar(db, "SELECT COUNT(*) FROM alerts WHERE COALESCE(status,'pending')='pending'"))
            alert_summary["confirmed"] = _safe_count(_scalar(db, "SELECT COUNT(*) FROM alerts WHERE status='confirm'"))
            alert_summary["dismissed"] = _safe_count(_scalar(db, "SELECT COUNT(*) FROM alerts WHERE status='dismiss'"))
        if "dispatch_status" in alerts_cols:
            alert_summary["dispatch_failed"] = _safe_count(_scalar(db, "SELECT COUNT(*) FROM alerts WHERE COALESCE(dispatch_status,'') IN ('failed','uncertain') AND COALESCE(dispatched,0)=0"))
            alert_summary["dispatch_pending"] = _safe_count(_scalar(db, "SELECT COUNT(*) FROM alerts WHERE COALESCE(dispatch_status,'') IN ('pending','in_flight') AND COALESCE(dispatched,0)=0"))

    recommendations = []
    for cam in camera_health:
        if cam["status"] in ("offline", "disconnected"):
            recommendations.append({"level": "critical", "code": "CAMERA_OFFLINE", "camera": cam["camera"], "message": f"الكاميرا {cam['camera']} متوقفة؛ تحقّق من الطاقة والشبكة ومصدر البث."})
        elif cam["status"] in ("reconnecting", "connecting"):
            recommendations.append({"level": "warning", "code": "CAMERA_RECONNECTING", "camera": cam["camera"], "message": f"الكاميرا {cam['camera']} تحاول إعادة الاتصال؛ راجع استقرار الشبكة."})
        elif cam["status"] == "unknown":
            recommendations.append({"level": "info", "code": "CAMERA_STATUS_UNKNOWN", "camera": cam["camera"], "message": f"حالة الكاميرا {cam['camera']} غير معروفة؛ تأكد من وصول بيانات الصحة."})
        if cam["status"] == "online" and cam["fps"] is not None and 0 < cam["fps"] < 1:
            recommendations.append({"level": "warning", "code": "LOW_FPS", "camera": cam["camera"], "message": f"معدل الإطارات في {cam['camera']} منخفض؛ افحص الحمل وجودة الاتصال."})
        if cam["mean_ocr_confidence"] is not None and cam["mean_ocr_confidence"] < .65:
            recommendations.append({"level": "warning", "code": "LOW_OCR_CONFIDENCE", "camera": cam["camera"], "message": f"متوسط ثقة قراءة اللوحات في {cam['camera']} منخفض؛ راجع الإضاءة والزاوية وموضع الكاميرا."})
    if alert_summary["dispatch_failed"]:
        recommendations.append({"level": "critical", "code": "DISPATCH_FAILED", "camera": "", "message": f"يوجد {alert_summary['dispatch_failed']} توجيه/توجيهات لم يثبت إرسالها؛ راجع حالة الاتصال وسجل المحاولات."})
    if alert_summary["dispatch_pending"]:
        recommendations.append({"level": "warning", "code": "DISPATCH_PENDING", "camera": "", "message": f"يوجد {alert_summary['dispatch_pending']} توجيه/توجيهات بانتظار الإرسال أو اكتمال المحاولة."})
    if current < 10:
        recommendations.append({"level": "info", "code": "LOW_SAMPLE_SIZE", "camera": "", "message": "عدد الرصود الحية خلال 24 ساعة قليل؛ تعامل مع النسب والمقارنات بحذر."})
    if not camera_health:
        recommendations.append({"level": "info", "code": "NO_CAMERA_HEALTH", "camera": "", "message": "لا تتوفر بيانات صحة كاميرات حالية؛ تحقق من أن مصادر البث تعمل وأن الحالة تُحدّث."})

    delta = current - previous
    # A percentage comparison has no defensible baseline when the prior window is zero.
    pct = round((delta / previous) * 100.0, 1) if previous else None
    return {
        "ok": True, "generated_at": now, "window_seconds": 86400,
        "period": {"from": start, "to": now, "previous_from": previous_start, "previous_to": start},
        "sightings": {"current_24h": current, "previous_24h": previous, "delta": delta, "change_percent": pct},
        "trend": trend,
        "vehicle_classes": [{"class": k, "count": v} for k, v in sorted(classes.items(), key=lambda kv: (-kv[1], kv[0]))],
        "confidence": confidence,
        "camera_health": camera_health,
        "alerts": alert_summary,
        "recommendations": recommendations,
        "data_quality": {"live_only": True, "demo_rows_excluded": True, "privacy_export": "aggregates_only"},
    }


def _rounded(value, digits=2):
    try:
        f = float(value)
        return round(f, digits) if math.isfinite(f) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _csv_safe(value):
    value = "" if value is None else str(value)
    # Spreadsheet applications may evaluate values with leading whitespace before a formula marker.
    probe = value.lstrip(" \t\r\n\ufeff")
    if probe.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def export_csv(report):
    """Return UTF-8-with-BOM CSV containing aggregate data only."""
    out = io.StringIO(newline="")
    w = csv.writer(out, lineterminator="\r\n")
    w.writerow(["metric", "dimension", "value", "generated_at"])
    generated = _label(report.get("generated_at"))
    s = report.get("sightings", {})
    for key in ("current_24h", "previous_24h", "delta", "change_percent"):
        w.writerow(["sightings", key, _csv_safe(s.get(key)), generated])
    for key, value in (report.get("confidence") or {}).items():
        w.writerow(["confidence", _csv_safe(key), _csv_safe(value), generated])
    for item in report.get("vehicle_classes") or []:
        w.writerow(["vehicle_class", _csv_safe(item.get("class")), _csv_safe(item.get("count")), generated])
    for key, value in (report.get("alerts") or {}).items():
        w.writerow(["alerts", _csv_safe(key), _csv_safe(value), generated])
    for cam in report.get("camera_health") or []:
        # Camera identifiers are included as operational labels; no personal or evidence data is exported.
        for key in ("status", "fps", "frames", "detections", "errors", "reconnect_count", "mean_ocr_confidence"):
            w.writerow(["camera_health", _csv_safe(cam.get("camera")) + "." + key, _csv_safe(cam.get(key)), generated])
    return ("\ufeff" + out.getvalue()).encode("utf-8")
