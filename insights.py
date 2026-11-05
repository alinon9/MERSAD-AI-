"""MERSAD AI learning, pattern/trend analytics & path tracking (CPU, trains in about a second).
1) Anomaly model: IsolationForest (with deterministic statistical StatForest MAD/z-score fallback when scikit-learn is absent)
   over sighting habits (hour, day type, camera, vehicle class, plate frequency, inter-sighting gap).
2) Traffic forecast & trend analysis: seasonal profile (day type x hour) with an empirical 80% dispersion band
   (mean +/- 1.28 * std per slot; requires >= 50 sightings).
3) Path & trajectory tracking: reconstructs multi-camera vehicle routes strictly per canonical plate identity
   (never merging plates with different known letters or substring digits), uses user-entered camera_links when calibrated
   or falls back to uncalibrated defaults ('افتراضي تجريبي غير معاير') with lower confidence, excludes demo data from live checks,
   deduplicates burst reads, and separates candidate trajectories when queried by digits alone.
Results are investigative leads requiring human review; they are NOT legal proof."""
import math, random, time
import numpy as np
import os as _os
try:
    if _os.environ.get("MERSAD_BLOCK_SKLEARN") == "1":
        raise ImportError("sklearn blocked by MERSAD_BLOCK_SKLEARN=1")
    from sklearn.ensemble import IsolationForest
except ImportError:
    IsolationForest = None


class _StatForest:
    """Deterministic statistical anomaly detector (Median + MAD / Z-score) used when scikit-learn is not installed."""
    def __init__(self, contamination=0.015, random_state=0):
        self.contamination = float(contamination)
        self.random_state = random_state
        self.median = None
        self.scale = None
        self.thresh = 0.0

    def fit(self, X):
        X = np.asarray(X, dtype=np.float64)
        if X.ndim != 2 or len(X) == 0:
            raise ValueError("Empty feature matrix")
        self.median = np.median(X, axis=0)
        mad = np.median(np.abs(X - self.median), axis=0)
        std = np.std(X, axis=0)
        self.scale = np.where(mad > 1e-5, mad * 1.4826, np.where(std > 1e-5, std, 1.0))
        scores = self._raw(X)
        self.thresh = float(np.quantile(scores, self.contamination))
        return self

    def _raw(self, X):
        X = np.asarray(X, dtype=np.float64)
        z = np.abs((X - self.median) / self.scale)
        return -np.mean(z ** 1.35, axis=1)

    def decision_function(self, X):
        return self._raw(X) - self.thresh


D = {}
M = {
    "model": None, "type": "none", "model_type": "none", "trained": 0, "n": 0, "n_demo": 0,
    "plate_n": {}, "last": {}, "last_cam": {}, "cams": {},
    "share": {}, "since": 0, "top": [], "corridors": [], "recent_paths": [],
    "topology": {}, "calibrated_cams": set()
}
VC = {"unknown": 0, "car": 1, "truck": 2, "bus": 3, "motorcycle": 4}
OFF = (4, 5)                                         # Friday, Saturday (time.struct_time.tm_wday)
HOURLY = [.2, .2, .2, .2, 1, 4, 10, 18, 16, 10, 8, 8, 9, 9, 8, 10, 14, 18, 15, 9, 6, 4, 2, 1]
DEFAULT_MIN_TRANSIT_SEC = 90.0                       # uncalibrated default minimum transit time between two distinct cameras
SIMULTANEOUS_SEC = 5.0                               # <=5s at two cameras => simultaneous appearance / clock skew suspicion
DEDUP_SAME_CAM_SEC = 15.0                            # duplicate reads at the same camera within 15s are merged in path steps
lt = time.localtime

# P0-A: Default topology and unverified hops are strictly EMPTY. 'via' comes ONLY from user configuration.
DEFAULT_TOPOLOGY = {}


def _tz_name():
    off = -time.timezone if (time.daylight == 0 or not time.localtime().tm_isdst) else -time.altzone
    sign = "+" if off >= 0 else "-"
    off = abs(int(off))
    return f"UTC{sign}{off // 3600:02d}:{(off % 3600) // 60:02d}"


def init(db, lock, topology=None):
    D.update(db=db, lock=lock)
    with lock:
        for ddl in (
            "ALTER TABLE sightings ADD COLUMN src TEXT DEFAULT 'live'",
            "ALTER TABLE sightings ADD COLUMN direction TEXT DEFAULT ''",
            "ALTER TABLE sightings ADD COLUMN raw_text TEXT DEFAULT ''",
            "ALTER TABLE sightings ADD COLUMN session_id TEXT DEFAULT ''",
            "CREATE TABLE IF NOT EXISTS camera_links(from_cam TEXT, to_cam TEXT, min_sec REAL DEFAULT 90, expected_sec REAL DEFAULT 300, source TEXT DEFAULT 'user_calibrated', PRIMARY KEY(from_cam, to_cam))"
        ):
            try: db.execute(ddl)
            except Exception: pass
        db.commit()
    configure_topology(topology)


def configure_topology(topology=None):
    """Load user-calibrated camera transition topology from camera_links table + optional user config dict.
    Never invents calibrated links or unconfigured 'via' hops; 'via' comes ONLY from user-configured topology."""
    topo = {}
    if D.get("db") and D.get("lock"):
        with D["lock"]:
            try:
                for c0, c1, mn, ex, src in D["db"].execute("SELECT from_cam, to_cam, min_sec, expected_sec, source FROM camera_links"):
                    if c0 and c1:
                        src_s = str(src or "user_calibrated")
                        is_cal = src_s not in ("uncalibrated_default", "demo", "default")
                        topo[(str(c0), str(c1))] = {
                            "min_sec": float(mn or DEFAULT_MIN_TRANSIT_SEC),
                            "expected_sec": float(ex or 300.0),
                            "source": src_s,
                            "calibrated": is_cal
                        }
            except Exception:
                pass
    if isinstance(topology, dict):
        for k, v in topology.items():
            if isinstance(k, tuple) and len(k) == 2:
                pair = (str(k[0]), str(k[1]))
            elif "->" in str(k):
                a, b = str(k).split("->", 1)
                pair = (a.strip(), b.strip())
            else:
                continue
            src_s = str(v.get("source", "user_calibrated"))
            is_cal = bool(v.get("calibrated", src_s not in ("uncalibrated_default", "demo", "default")))
            topo[pair] = {
                "min_sec": float(v.get("min_sec", DEFAULT_MIN_TRANSIT_SEC)),
                "expected_sec": float(v.get("expected_sec", 300.0)),
                "source": src_s,
                "calibrated": is_cal,
                **({"via": v["via"]} if "via" in v else {})
            }
    # Infer intermediate 'via' hops ONLY from user-configured 2-hop chains c0 -> mid -> c1 in topo
    cams_in_topo = {c for pair in topo for c in pair}
    for c0 in cams_in_topo:
        for c1 in cams_in_topo:
            if c0 != c1 and (c0, c1) not in topo:
                for mid in cams_in_topo:
                    if mid not in (c0, c1) and (c0, mid) in topo and (mid, c1) in topo:
                        l1, l2 = topo[(c0, mid)], topo[(mid, c1)]
                        both_cal = bool(l1.get("calibrated") and l2.get("calibrated"))
                        topo[(c0, c1)] = {
                            "min_sec": float(l1["min_sec"] + l2["min_sec"]),
                            "expected_sec": float(l1["expected_sec"] + l2["expected_sec"]),
                            "source": "user_calibrated" if both_cal else "uncalibrated_default",
                            "calibrated": both_cal,
                            "via": mid
                        }
                        break

    cal = {c for (a, b), info in topo.items() if info.get("calibrated") for c in (a, b)}
    M["topology"] = topo
    M["calibrated_cams"] = cal


def _link_info(c0, c1):
    """Return transition metadata between c0 and c1.
    Unless explicitly configured by the user in camera_links / topology, calibrated is False,
    source is 'uncalibrated_default', and no 'via' hop is assumed."""
    topo = M.get("topology") or {}
    if (c0, c1) in topo:
        info = dict(topo[(c0, c1)])
        info.setdefault("calibrated", info.get("source") not in ("uncalibrated_default", "demo", "default"))
        return info
    return {
        "min_sec": DEFAULT_MIN_TRANSIT_SEC,
        "expected_sec": 300.0,
        "source": "uncalibrated_default",
        "source_label_ar": "افتراضي تجريبي غير معاير",
        "calibrated": False
    }


def feat(ts, cam, vc, n, gap):
    t = lt(ts); h = t.tm_hour + t.tm_min / 60.0
    gap_norm = math.log1p(max(0.0, min(float(gap or 0.0), 30 * 86400)))
    return [
        math.sin(2 * math.pi * h / 24.0),
        math.cos(2 * math.pi * h / 24.0),
        float(t.tm_wday in OFF),
        float(M["cams"].setdefault(cam or "UNKNOWN", len(M["cams"]))),
        float(vc == "truck"),
        math.log1p(max(0, int(n))),
        gap_norm
    ]


def why(vc, n, share, route_conflict=None):
    r = []
    if route_conflict:
        r.append(route_conflict if isinstance(route_conflict, str) else route_conflict.get("why", ""))
    if share < 0.012:
        r.append(f"وقت نادر ({share * 100:.1f}% فقط من الحركة)")
    if n <= 2:
        r.append("لوحة نادرة الظهور")
    if vc == "truck" and share < 0.03:
        r.append("شاحنة في وقت غير معتاد")
    return "، ".join(x for x in r if x) or "تركيبة غير معتادة من (الوقت، الكاميرا، نوع المركبة)"


def _canonical_plate(plate_str):
    """Return canonical plate identity ('letters-digits' or 'digits').
    Never merges two plates with different letters or different digit lengths (P0-A)."""
    from registry import norm_plate
    return norm_plate(plate_str) or str(plate_str or "").strip()


def _valid_rows(raw_rows):
    """Filter out NULL or corrupted timestamps/plates and sort chronologically."""
    cleaned = []
    for row in raw_rows:
        rid, ts, cam, plate, vc, conf, src, direction = row[:8]
        sess = row[8] if len(row) > 8 else ""
        if ts is None or not isinstance(ts, (int, float)) or math.isnan(ts) or ts <= 0:
            continue
        plate_s = _canonical_plate(plate)
        if not plate_s:
            continue
        cam_s = str(cam or "UNKNOWN").strip() or "UNKNOWN"
        vc_s = str(vc or "unknown").strip() or "unknown"
        conf_f = float(conf) if isinstance(conf, (int, float)) and not math.isnan(conf) else 0.0
        cleaned.append((int(rid or 0), float(ts), cam_s, plate_s, vc_s, conf_f, str(src or "live"), str(direction or ""), str(sess or "")))
    cleaned.sort(key=lambda x: (x[1], x[0]))
    return cleaned


def _build_conflict_record(id0, t0, c0, conf0, id1, t1, c1, conf1):
    """Create a structured, reviewable route suspicion record with honest calibration provenance."""
    dt = max(0.0, t1 - t0)
    link = _link_info(c0, c1)
    min_sec = link["min_sec"]
    if dt >= min_sec:
        return None
    is_cal = bool(link.get("calibrated"))
    base_conf = min(conf0 or 0.8, conf1 or 0.8)
    if not is_cal:
        base_conf *= 0.65
    kind = "simultaneous_sighting" if dt <= SIMULTANEOUS_SEC else "impossible_transit"
    src_ar = "مخطط مواقع الكاميرات المعاير من المستخدم" if is_cal else f"حد افتراضي تجريبي غير معاير ({int(min_sec)} ثانية)"
    prio_label = "تنبيه مسار معاير" if is_cal else "ملاحظة للعلم (غير معايرة)"
    reason = (
        f"اشتباه تعارض مكاني-زماني قابل للمراجعة [{prio_label} — {'ظهور متزامن' if kind == 'simultaneous_sighting' else 'زمن انتقال أقل من الحد'}]: "
        f"رُصدت في {c0} (#{id0}) ثم {c1} (#{id1}) بفارق {int(round(dt))} ثانية "
        f"(الحد الأدنى المفترض {int(min_sec)} ثانية حسب {src_ar}). "
        f"قد ينتج عن خطأ قراءة OCR أو فرق توقيت الساعات أو عدم معايرة المسافة أو لوحة مكررة — يتطلب مراجعة بشرية."
    )
    return {
        "type": kind,
        "from_id": id0,
        "to_id": id1,
        "from_cam": c0,
        "to_cam": c1,
        "from_ts": round(t0, 3),
        "to_ts": round(t1, 3),
        "dt_sec": round(dt, 2),
        "min_expected_sec": min_sec,
        "config_source": link["source"],
        "source_label_ar": src_ar,
        "calibrated": is_cal,
        "priority": "high" if is_cal else "info",
        "confidence": round(float(base_conf), 2),
        "why": reason
    }


def _analyze_paths(rows):
    """Build multi-camera vehicle trajectories strictly by full canonical plate identity (P0-A).
    Never merges two plates that have different known letters (e.g. 'اب-4444' vs 'جد-4444')."""
    by_plate = {}
    for row in rows:
        rid, ts, cam, plate, vc, conf, src, direction = row[:8]
        sess = row[8] if len(row) > 8 else ""
        key = _canonical_plate(plate)
        by_plate.setdefault(key, []).append((rid, ts, cam, vc, conf, src, direction, sess, key))
    transitions = {}
    conflicts = {}
    recent_paths = []
    cal_cams = M.get("calibrated_cams") or set()

    for key, pts in by_plate.items():
        dedup_pts = []
        for pt in pts:
            if dedup_pts and dedup_pts[-1][2] == pt[2] and (pt[1] - dedup_pts[-1][1]) < DEDUP_SAME_CAM_SEC:
                continue
            dedup_pts.append(pt)
        if len(dedup_pts) < 2:
            continue
        cams_seq = [dedup_pts[0][2]]
        missing_hops = []
        for i in range(1, len(dedup_pts)):
            id0, t0, c0, _, conf0, src0, _, sess0, _ = dedup_pts[i - 1]
            id1, t1, c1, vc1, conf1, src1, dir1, sess1, pl1 = dedup_pts[i]
            dt = max(0.0, t1 - t0)
            if c1 != c0:
                if sess0 and sess1 and sess0 == sess1 and not sess0.startswith("multi:"):
                    continue
                cams_seq.append(c1)
                link = _link_info(c0, c1)
                if link.get("via") and link["via"] not in (c0, c1):
                    missing_hops.append(link["via"])
                if dt <= 7200:
                    transitions.setdefault((c0, c1), []).append(dt)
                c_rec = _build_conflict_record(id0, t0, c0, conf0, id1, t1, c1, conf1)
                if c_rec:
                    conflicts[(key, t1)] = c_rec
        if len(cams_seq) >= 2:
            dedup_cams = [cams_seq[0]]
            for c in cams_seq[1:]:
                if c != dedup_cams[-1]:
                    dedup_cams.append(c)
            if len(dedup_cams) >= 2:
                all_cal = bool(cal_cams) and all(c in cal_cams for c in dedup_cams)
                recent_paths.append({
                    "plate": key,
                    "vclass": dedup_pts[-1][3],
                    "last_ts": dedup_pts[-1][1],
                    "sightings": len(dedup_pts),
                    "route": " ➔ ".join(dedup_cams[-5:]),
                    "direction": dedup_pts[-1][6] or f"{dedup_cams[-2]} ➔ {dedup_cams[-1]}",
                    "conflict": any(k[0] == key for k in conflicts),
                    "missing_hops": sorted(set(missing_hops)),
                    "calibrated": all_cal
                })

    corridors = []
    for (c0, c1), dts in sorted(transitions.items(), key=lambda kv: -len(kv[1]))[:10]:
        link = _link_info(c0, c1)
        corridors.append({
            "from": c0,
            "to": c1,
            "route": f"{c0} ➔ {c1}",
            "count": len(dts),
            "avg_min": round(float(np.mean(dts)) / 60.0, 1),
            "expected_min": round(link["expected_sec"] / 60.0, 1),
            "calibrated": link["calibrated"],
            "source_label_ar": "معاير" if link["calibrated"] else "افتراضي تجريبي غير معاير"
        })
    recent_paths.sort(key=lambda x: (-int(x["conflict"]), -x["last_ts"]))
    return corridors, recent_paths[:15], conflicts


def _fetch_sightings(days=90):
    if not D.get("db"):
        return []
    cutoff = time.time() - days * 86400
    with D["lock"]:
        cols = {r[1] for r in D["db"].execute("PRAGMA table_info(sightings)").fetchall()}
        sess_expr = "COALESCE(session_id,'')" if "session_id" in cols else "''"
        raw = D["db"].execute(
            f"SELECT rowid, ts, cam, plate, vclass, conf, COALESCE(src,'live'), COALESCE(direction,''), {sess_expr} "
            "FROM sightings WHERE ts IS NOT NULL AND ts > ? ORDER BY ts ASC, rowid ASC",
            (cutoff,)
        ).fetchall()
    return _valid_rows(raw)


def train():
    rows = _fetch_sightings(90)
    corridors, recent_paths, conflicts = _analyze_paths(rows)
    if len(rows) < 50:
        M.update(
            model=None, type="none", model_type="none", trained=0, n=len(rows),
            n_demo=sum(r[6] == "demo" for r in rows),
            corridors=corridors, recent_paths=recent_paths, top=[]
        )
        return {
            "ok": False,
            "reason": "insufficient_data",
            "n": len(rows),
            "min_required": 50,
            "error": f"البيانات غير كافية للتدريب ({len(rows)} من أصل 50 رصداً مطلوباً). ولّد تاريخاً تجريبياً أو انتظر مزيداً من الرصد."
        }
    M["cams"] = {}
    for r in rows:
        M["cams"].setdefault(r[2], len(M["cams"]))
    tot, last, last_cam, hrs, X = {}, {}, {}, {}, []
    for r in rows:
        k_id = _canonical_plate(r[3])
        tot[k_id] = tot.get(k_id, 0) + 1
    for rid, ts, cam, plate, vc, conf, src, _, sess in rows:
        k_id = _canonical_plate(plate)
        gap = ts - last[k_id] if k_id in last else 0.0
        X.append(feat(ts, cam, vc, tot[k_id], gap))
        last[k_id] = ts
        if src == "live":
            last_cam[k_id] = (rid, cam, ts, conf, sess)
        k = (lt(ts).tm_wday in OFF, lt(ts).tm_hour)
        hrs[k] = hrs.get(k, 0) + 1

    daytot = {w: sum(v for (ww, _), v in hrs.items() if ww == w) or 1 for w in (False, True)}
    share = {k: v / daytot[k[0]] for k, v in hrs.items()}
    arr = np.asarray(X, dtype=np.float64)
    if IsolationForest is not None:
        model = IsolationForest(n_estimators=120, contamination=0.015, random_state=0).fit(arr)
        short_type = "IsolationForest"
        mtype = "IsolationForest(n_estimators=120, contamination=0.015, random_state=0)"
    else:
        model = _StatForest(contamination=0.015, random_state=0).fit(arr)
        short_type = "StatForest"
        mtype = "StatForest(contamination=0.015)"

    sc = np.asarray(model.decision_function(arr), dtype=np.float64).copy()
    for idx, (rid, ts, cam, plate, vc, conf, src, _, _) in enumerate(rows):
        k_id = _canonical_plate(plate)
        if (k_id, ts) in conflicts:
            sc[idx] -= 0.5
    top = []
    for i in np.argsort(sc)[:15]:
        rid, ts, cam, plate, vc, conf, src, _, _ = rows[i]
        k_id = _canonical_plate(plate)
        c_rec = conflicts.get((k_id, ts))
        top.append({
            "id": rid,
            "ts": ts,
            "plate": plate,
            "cam": cam,
            "vclass": vc,
            "src": src,
            "score": round(float(sc[i]), 3),
            "conflict": c_rec,
            "why": why(vc, tot[k_id], share.get((lt(ts).tm_wday in OFF, lt(ts).tm_hour), 0), c_rec)
        })
    M.update(
        model=model, type=short_type, model_type=mtype, trained=time.time(), n=len(rows),
        n_demo=sum(r[6] == "demo" for r in rows),
        plate_n=tot, last=last, last_cam=last_cam, share=share, since=0,
        top=top, corridors=corridors, recent_paths=recent_paths
    )
    return {"ok": True, "n": len(rows), "type": short_type, "model_type": mtype}


def check_route(plate, cam, ts=None, conf=0.9, cur_id=0, session_id="", identity_confirmed=True):
    """Track live camera-to-camera transition strictly for the exact canonical plate identity (P0-A).
    - Never uses LIKE '%digits' (so 112345 and 12345 never collide).
    - Never links two plates with different letters (e.g. 'صنعاء-77777' and 'عدن-77777').
    - If identity_confirmed is False (ambiguous/unconfirmed letters), does not create a confirmed route or conflict."""
    if not identity_confirmed:
        return None, None
    ts = float(ts or time.time())
    k_id = _canonical_plate(plate)
    if not k_id:
        return None, None
    prev = M["last_cam"].get(k_id)
    if D.get("db"):
        with D["lock"]:
            cols = {r[1] for r in D["db"].execute("PRAGMA table_info(sightings)").fetchall()}
            sess_col = "COALESCE(session_id,'')" if "session_id" in cols else "''"
            r = D["db"].execute(
                f"SELECT rowid, cam, ts, conf, {sess_col} FROM sightings "
                "WHERE plate=? AND COALESCE(src,'live')='live' AND ts<? AND rowid!=? "
                "ORDER BY ts DESC, rowid DESC LIMIT 1",
                (k_id, ts, int(cur_id or 0))
            ).fetchone()
            if r:
                prev = (int(r[0] or 0), str(r[1] or "UNKNOWN"), float(r[2]), float(r[3] or 0.8), str(r[4] or ""))
            elif prev:
                chk = D["db"].execute("SELECT plate, COALESCE(src,'live') FROM sightings WHERE rowid=?", (prev[0],)).fetchone()
                if not chk or _canonical_plate(chk[0]) != k_id or chk[1] != "live":
                    prev = None

    M["last_cam"][k_id] = (int(cur_id or 0), str(cam or "UNKNOWN"), ts, float(conf or 0.8), str(session_id or ""))
    if not prev:
        return None, None
    prev_id, prev_cam, prev_ts, prev_conf = prev[0], prev[1], prev[2], prev[3]
    prev_sess = prev[4] if len(prev) > 4 else ""
    if prev_cam != cam:
        if session_id and prev_sess and session_id == prev_sess and not str(session_id).startswith("multi:"):
            return None, None
        if D.get("db"):
            with D["lock"]:
                ended = D["db"].execute(
                    "SELECT 1 FROM audit WHERE action='session end' AND ref=? AND ts>=? AND ts<=? LIMIT 1",
                    (prev_cam, prev_ts, ts)
                ).fetchone()
                if ended and session_id and prev_sess and session_id != prev_sess:
                    return None, None
        route_str = f"{prev_cam} ➔ {cam}"
        c_rec = _build_conflict_record(prev_id, prev_ts, prev_cam, prev_conf, int(cur_id or 0), ts, str(cam), float(conf or 0.8))
        return route_str, c_rec
    return None, None


def score_live(plate, cam, vc, ts=None, conf=0.9, cur_id=0, check_conflict=True, session_id="", identity_confirmed=True):
    """Update habit stats; return reason string if this sighting looks anomalous, else None."""
    ts = float(ts or time.time())
    k_id = _canonical_plate(plate)
    if check_conflict and identity_confirmed:
        _, c_rec = check_route(k_id, cam, ts, conf=conf, cur_id=cur_id, session_id=session_id, identity_confirmed=identity_confirmed)
        if c_rec:
            return c_rec["why"]
    if not M["model"]:
        return None
    n = M["plate_n"].get(k_id, 0) + 1
    gap = ts - M["last"][k_id] if k_id in M["last"] else 0.0
    M["plate_n"][k_id] = n
    M["last"][k_id] = ts
    M["since"] += 1
    if M["model"].decision_function(np.asarray([feat(ts, cam, vc, n, gap)], dtype=np.float64))[0] >= 0:
        return None
    return why(vc, n, M["share"].get((lt(ts).tm_wday in OFF, lt(ts).tm_hour), 0))


def _build_single_trajectory(np_plate, raw_rows):
    """Build trajectory dictionary for a single canonical plate from its raw sighting rows."""
    raw_ts = [float(r[1]) for r in raw_rows if r[1] is not None and r[1] > 0]
    clock_skew = any(raw_ts[i] < raw_ts[i - 1] - 1.0 for i in range(1, len(raw_ts)))
    rows = _valid_rows(raw_rows)

    dedup = []
    duplicates_merged = 0
    for r in rows:
        if dedup and dedup[-1][2] == r[2] and (r[1] - dedup[-1][1]) < DEDUP_SAME_CAM_SEC:
            duplicates_merged += 1
            continue
        dedup.append(r)

    steps = []
    cams = []
    conflicts = []
    missing_hops = []
    cal_cams = M.get("calibrated_cams") or set()

    for i, (rid, ts, cam, pl, vc, conf, src, direction, _) in enumerate(dedup):
        prev = dedup[i - 1] if i > 0 else None
        dt_sec = round(ts - prev[1], 1) if prev else None
        dt_min = round(dt_sec / 60.0, 1) if dt_sec is not None else None
        prev_cam = prev[2] if prev else None
        c_rec = None
        missing_via = None
        cam_cal = (cam in cal_cams) if cal_cams else False

        if prev_cam and prev_cam != cam:
            link = _link_info(prev_cam, cam)
            if link.get("via") and link["via"] not in (prev_cam, cam):
                missing_via = link["via"]
                missing_hops.append(missing_via)
            c_rec = _build_conflict_record(prev[0], prev[1], prev_cam, prev[5], rid, ts, cam, conf)
            if c_rec:
                conflicts.append(c_rec)

        if not cams or cams[-1] != cam:
            cams.append(cam)

        steps.append({
            "id": rid,
            "ts": ts,
            "cam": cam,
            "calibrated": cam_cal,
            "vclass": vc,
            "conf": round(conf, 2),
            "src": src,
            "direction": direction or (f"{prev_cam} ➔ {cam}" if prev_cam and prev_cam != cam else "عبور نسبي في الإطار"),
            "dt_sec": dt_sec,
            "dt_min": dt_min,
            "missing_via": missing_via,
            "conflict": bool(c_rec),
            "conflict_detail": c_rec
        })

    all_cal = bool(steps) and all(s["calibrated"] for s in steps)
    return {
        "plate": np_plate,
        "total": len(steps),
        "duplicates_merged": duplicates_merged,
        "clock_skew_detected": clock_skew,
        "calibrated": all_cal,
        "route": " ➔ ".join(cams),
        "missing_hops": sorted(set(missing_hops)),
        "conflicts": conflicts,
        "steps": steps[-30:]
    }


def plate_path(plate):
    """Return chronological trajectory for a plate (P0-A).
    - Full plate search (with letters, e.g. 'أب-4444'): preserves exact identity and returns only that plate's trajectory.
    - Digits-only search (e.g. '4444'): finds all candidate plates with exact core digits == '4444' (never substring LIKE '%4444').
      If multiple distinct lettered plates share those digits, returns them as separate candidates in 'candidate_paths'
      without mixing their steps or routes!"""
    from registry import norm_plate, split_plate
    q_raw = str(plate or "").strip()
    if not q_raw:
        return {"ok": False, "error": "أدخل رقم اللوحة للبحث عن مسارها"}
    q_digits, q_letters = split_plate(q_raw)
    np_plate = norm_plate(q_raw)
    if not q_digits:
        return {"ok": False, "error": "صيغة رقم اللوحة غير صالحة"}
    if not D.get("db"):
        return {"ok": False, "error": "قاعدة البيانات غير متصلة"}

    with D["lock"]:
        if q_letters:
            # Exact full plate identity requested
            raw = D["db"].execute(
                "SELECT rowid, ts, cam, plate, vclass, conf, COALESCE(src,'live'), COALESCE(direction,'') "
                "FROM sightings WHERE plate=? AND ts IS NOT NULL AND ts > 0 ORDER BY rowid ASC LIMIT 300",
                (np_plate,)
            ).fetchall()
            candidate_groups = {np_plate: raw} if raw else {}
        else:
            # Digits-only search: match exact core digits (plate == q_digits OR plate LIKE '%-' || q_digits)
            raw_all = D["db"].execute(
                "SELECT rowid, ts, cam, plate, vclass, conf, COALESCE(src,'live'), COALESCE(direction,'') "
                "FROM sightings WHERE (plate=? OR plate LIKE ?) AND ts IS NOT NULL AND ts > 0 ORDER BY rowid ASC LIMIT 600",
                (q_digits, f"%-{q_digits}")
            ).fetchall()
            candidate_groups = {}
            for r in raw_all:
                c_pl = _canonical_plate(r[3])
                if split_plate(c_pl)[0] == q_digits:
                    candidate_groups.setdefault(c_pl, []).append(r)

    if not candidate_groups:
        return {
            "ok": True,
            "found": False,
            "plate": np_plate,
            "candidates": [],
            "ambiguous_query": False,
            "total": 0,
            "route": "",
            "steps": [],
            "conflicts": [],
            "missing_hops": [],
            "clock_skew_detected": False,
            "calibrated": False
        }

    candidates = sorted(candidate_groups.keys())
    if len(candidates) == 1:
        only_pl = candidates[0]
        traj = _build_single_trajectory(only_pl, candidate_groups[only_pl])
        all_cal = traj["calibrated"]
        return {
            "ok": True,
            "found": True,
            "ambiguous_query": False,
            "candidates": candidates,
            "candidate_paths": {only_pl: traj},
            **traj,
            "limitations": (
                "الربط بين الكاميرات يعتمد على تطابق الهوية الكاملة للوحة المقروءة آلياً وأوقات الرصد؛ "
                + ("تمت معايرة أزمنة الانتقال لجميع الكاميرات في المسار من قِبل المستخدم." if all_cal else "الكاميرات في المسار تستخدم قيماً افتراضية تجريبية غير معايرة (90 ثانية).")
            )
        }

    # Multiple distinct plates share the queried digits (e.g. 'اب-4444' and 'جد-4444') -> do NOT mix their paths!
    cand_paths = {c_pl: _build_single_trajectory(c_pl, candidate_groups[c_pl]) for c_pl in candidates}
    return {
        "ok": True,
        "found": True,
        "ambiguous_query": True,
        "plate": q_digits,
        "candidates": candidates,
        "candidate_paths": cand_paths,
        "total": sum(cp["total"] for cp in cand_paths.values()),
        "route": "",
        "steps": [],
        "conflicts": [],
        "missing_hops": [],
        "clock_skew_detected": any(cp["clock_skew_detected"] for cp in cand_paths.values()),
        "calibrated": all(cp["calibrated"] for cp in cand_paths.values()),
        "limitations": (
            f"البحث بالأرقام فقط ({q_digits}) طابق {len(candidates)} لوحات مختلفة بالأحرف ({' ، '.join(candidates)}). "
            "فُصلت مسارات كل مرشح على حدة لمنع خلط مسارات مركبتين مختلفتين — اختر اللوحة الكاملة لعرض مسارها المستقل."
        )
    }


def forecast():
    now = time.time()
    if not D.get("db"):
        return None
    with D["lock"]:
        tss = [
            float(r[0]) for r in D["db"].execute(
                "SELECT ts FROM sightings WHERE ts IS NOT NULL AND ts > ?", (now - 60 * 86400,)
            )
            if r[0] is not None and isinstance(r[0], (int, float)) and not math.isnan(r[0]) and r[0] > 0
        ]
    if len(tss) < 50:
        return None
    cnt = {}
    for t in tss:
        k = time.strftime("%Y%m%d%H", lt(t))
        cnt[k] = cnt.get(k, 0) + 1
    slots = {}
    span_days = max(1, int((now - min(tss)) // 86400) + 1)
    for d in range(span_days):
        day = now - d * 86400
        w = lt(day).tm_wday in OFF
        for h in range(24):
            if d == 0 and h >= lt(now).tm_hour:
                continue
            slots.setdefault((w, h), []).append(cnt.get(time.strftime("%Y%m%d", lt(day)) + f"{h:02d}", 0))
    stat = {k: (float(np.mean(v)), float(np.std(v))) for k, v in slots.items() if v}
    exp = act = 0.0
    for k in range(1, 7):
        t = now - k * 3600
        key = (lt(t).tm_wday in OFF, lt(t).tm_hour)
        exp += stat.get(key, (0.0, 0.0))[0]
        act += cnt.get(time.strftime("%Y%m%d%H", lt(t)), 0)
    f = min(2.0, max(0.5, act / exp)) if exp > 5 else 1.0
    out = []
    for k in range(1, 25):
        t = now + k * 3600
        m, s = stat.get((lt(t).tm_wday in OFF, lt(t).tm_hour), (0.0, 0.0))
        out.append({
            "label": f"{lt(t).tm_hour:02d}:00",
            "mean": round(m * f, 1),
            "lo": round(max(0.0, m - 1.28 * s) * f, 1),
            "hi": round((m + 1.28 * s) * f, 1)
        })
    return {
        "hours": out,
        "peaks": [x["label"] for x in sorted(out, key=lambda x: -x["mean"])[:3]],
        "level": round(f, 2),
        "timezone": _tz_name(),
        "band_method": "empirical_dispersion_mean_plus_minus_1.28_std",
        "band_description_ar": "نطاق التشتت التجريبي (المتوسط ± 1.28×الانحراف المعياري؛ يغطي نحو 80% تحت التوزيع الطبيعي)"
    }


def summary():
    rows = _fetch_sightings(90)
    corridors, recent_paths, _ = _analyze_paths(rows)
    n_demo = sum(r[6] == "demo" for r in rows)
    short_type = M.get("type", "none") if M.get("model") else ("IsolationForest" if IsolationForest is not None else "StatForest")
    return {
        "model": {
            "ready": bool(M["model"]),
            "type": M.get("type", "none") if M.get("model") else short_type,
            "model_type": M.get("model_type", "none"),
            "trained": M["trained"],
            "n": len(rows),
            "demo": n_demo,
            "live": len(rows) - n_demo,
            "min_required": 50,
            "timezone": _tz_name(),
            "reason": "ready" if M["model"] else ("insufficient_data" if len(rows) < 50 else "not_trained")
        },
        "forecast": forecast() if M["model"] else None,
        "anomalies": M["top"],
        "corridors": corridors,
        "paths": recent_paths
    }


def seed_demo(days=30, cams=("CAM1", "CAM2", "CAM3"), seed=7):
    """Synthetic history so the models have something to learn from (including multi-camera paths). Marked src='demo'."""
    with D["lock"]:
        if D["db"].execute("SELECT COUNT(*) FROM sightings WHERE src='demo'").fetchone()[0]:
            return {"ok": False, "error": "التاريخ التجريبي موجود مسبقاً"}
    rnd = random.Random(seed); now = time.time(); out = []
    plate = lambda: str(rnd.randint(10000, 99999))
    pool, trucks = [plate() for _ in range(250)], [plate() for _ in range(25)]
    commuters = [(plate(), rnd.choice((7, 8)), rnd.choice((16, 17, 18)), cams[0], cams[1]) for _ in range(40)]
    for d in range(days, 0, -1):
        day = now - d * 86400; t = lt(day); mid = day - t.tm_hour * 3600 - t.tm_min * 60 - t.tm_sec
        off = t.tm_wday in OFF; f = (0.6 if off else 1.0) * rnd.uniform(.85, 1.15)
        for h in range(24):
            c = HOURLY[h] * f * rnd.uniform(.8, 1.2)
            for _ in range(int(c) + (rnd.random() < c - int(c))):
                out.append((mid + h * 3600 + rnd.uniform(0, 3599), rnd.choice(cams), rnd.choice(pool), .9,
                            rnd.choices(("car", "bus", "motorcycle"), (88, 6, 6))[0], "demo", "اقتراب نسبي في الإطار"))
        if not off:
            for p, m, e, c1, c2 in commuters:
                if rnd.random() < .85:
                    t_m = mid + m * 3600 + rnd.uniform(0, 2400)
                    out.append((t_m, c1, p, .92, "car", "demo", "اقتراب نسبي في الإطار"))
                    out.append((t_m + rnd.uniform(420, 900), c2, p, .91, "car", "demo", f"{c1} ➔ {c2}"))
                if rnd.random() < .85:
                    t_e = mid + e * 3600 + rnd.uniform(0, 2400)
                    out.append((t_e, c2, p, .92, "car", "demo", "ابتعاد نسبي في الإطار"))
                    out.append((t_e + rnd.uniform(420, 900), c1, p, .91, "car", "demo", f"{c2} ➔ {c1}"))
            for p in rnd.sample(trucks, 12):
                t_tr = mid + rnd.randint(8, 15) * 3600 + rnd.uniform(0, 2400)
                out.append((t_tr, cams[0], p, .9, "truck", "demo", "اقتراب نسبي في الإطار"))
                out.append((t_tr + rnd.uniform(600, 1500), cams[2], p, .9, "truck", "demo", f"{cams[0]} ➔ {cams[2]}"))
        if rnd.random() < .25:
            out.append((mid + rnd.randint(1, 4) * 3600 + rnd.uniform(0, 3000), rnd.choice(cams),
                        rnd.choice(trucks) if rnd.random() < .5 else plate(), .9, "truck" if rnd.random() < .6 else "car", "demo", "عبور ليلي"))
    t_conf = now - 3600
    out.append((t_conf, "CAM1", "99991", .95, "car", "demo", "اقتراب نسبي في الإطار"))
    out.append((t_conf + 25, "CAM3", "99991", .94, "car", "demo", "CAM1 ➔ CAM3"))
    with D["lock"]:
        D["db"].executemany("INSERT INTO sightings(ts, cam, plate, conf, vclass, src, direction) VALUES(?,?,?,?,?,?,?)", out)
        D["db"].commit()
    r = train(); r["seeded"] = len(out); return r


def clear_demo():
    with D["lock"]:
        D["db"].execute("DELETE FROM sightings WHERE src='demo'"); D["db"].commit()
    r = train(); return {**r, "ok": True, "cleared": True}
