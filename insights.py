"""MERSAD AI learning, pattern/trend analytics & path tracking (CPU, trains in about a second).
1) Anomaly model: IsolationForest (with deterministic statistical StatForest MAD/z-score fallback when scikit-learn is absent)
   over sighting habits (hour, day type, camera, vehicle class, plate frequency, inter-sighting gap).
2) Traffic forecast & trend analysis: seasonal profile (day type x hour) with an empirical 80% dispersion band
   (mean +/- 1.28 * std per slot; requires >= 50 sightings).
3) Path & trajectory tracking: reconstructs multi-camera vehicle routes strictly per canonical plate identity
   (never merging plates with different known letters or substring digits), uses user-entered camera_links when calibrated
   or falls back to uncalibrated defaults ('افتراضي تجريبي غير معاير') with lower confidence, strictly separates live vs demo data,
   deduplicates burst reads, and separates candidate trajectories when queried by digits alone.
Results are investigative leads requiring human review; they are NOT legal proof."""
import csv, io, json, math, random, threading, time
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


_STATE_LOCK = threading.RLock()
_TRAIN_LOCK = threading.Lock()
D = {}
M = {
    "model": None, "type": "none", "model_type": "none", "trained": 0, "n": 0, "n_demo": 0,
    "plate_n": {}, "last": {}, "last_cam": {}, "cams": {},
    "share": {}, "since": 0, "top": [], "corridors": [], "recent_paths": [],
    "topology": {}, "calibrated_cams": set()
}
M_DEMO = {
    "model": None, "type": "none", "model_type": "none", "trained": 0, "n": 0, "n_demo": 0,
    "cams": {}, "share": {}, "top": [], "corridors": [], "recent_paths": []
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


def _reset_state():
    with _STATE_LOCK:
        M.update(
            model=None, type="none", model_type="none", trained=0, n=0, n_demo=0,
            plate_n={}, last={}, last_cam={}, cams={}, share={}, since=0,
            top=[], corridors=[], recent_paths=[], topology={}, calibrated_cams=set()
        )
        M_DEMO.update(
            model=None, type="none", model_type="none", trained=0, n=0, n_demo=0,
            cams={}, share={}, top=[], corridors=[], recent_paths=[]
        )


def init(db, lock, db_path=None, topology=None):
    """Initialize insights module by delegating schema migrations to registry.migrate_db() (GAP-05)
    and loading calibrated camera topology deterministically."""
    if isinstance(db_path, dict) and topology is None:
        topology = db_path
        db_path = None
    import registry as R
    eff_path = db_path if db_path is not None else (R.D.get("db_path") if R.D.get("db") is db else None)
    if eff_path is None and R._is_in_memory_db(db, None):
        eff_path = ":memory:"
    prev_db = D.get("db")
    D.update(db=db, lock=lock, db_path=eff_path)
    if prev_db is not db:
        _reset_state()
    R.migrate_db(db, lock, db_path=eff_path)
    configure_topology(topology)


MEASUREMENT_SOURCES = {
    "manual": "يدوي (تقدير المشغّل)",
    "field_data": "مستمد من بيانات ميدانية",
    "computed_logs": "محسوب من سجلات فعلية",
    "user_calibrated": "معاير من المستخدم",
}
TRAFFIC_CONDITIONS = {
    "normal": "حركة مرور عادية",
    "peak": "ساعات الذروة",
    "off_peak": "خارج أوقات الذروة",
    "night": "فترة ليلية",
}


def _compute_calibration_completeness(min_sec, expected_sec, max_sec=0.0, distance_m=0.0, observations_count=0, calibration_date="", is_cal=True):
    """Determine whether a camera link calibration is complete or needs additional field metadata (Stage 11, AUDIT-007).
    Requires min_sec >= 1.0, expected_sec >= min_sec, at least one spatial/upper bound (max_sec >= expected_sec or distance_m > 0),
    and at least 3 field observations (or >= 1 observation when BOTH max_sec >= expected_sec and distance_m > 0 are provided)."""
    if not is_cal:
        return "uncalibrated", "غير معاير (افتراضي 90 ثانية)"
    has_max = bool(max_sec is not None and float(max_sec or 0) >= float(expected_sec or 0) and float(max_sec or 0) > 0)
    has_dist = bool(distance_m is not None and float(distance_m or 0) > 0)
    obs_cnt = int(observations_count or 0) if observations_count is not None else 0
    has_rich_meta = bool((has_max or has_dist) and (obs_cnt >= 3 or (obs_cnt >= 1 and has_max and has_dist)))
    if min_sec and expected_sec and float(min_sec) >= 1.0 and float(expected_sec) >= float(min_sec) and has_rich_meta:
        return "complete", "معايرة مكتملة"
    return "basic_needs_data", "معايرة أساسية — يوصى باستكمال (الحد الأعلى / المسافة / 3 قياسات على الأقل)"


def configure_topology(topology=None):
    """Load user-calibrated camera transition topology from camera_links table + optional user config dict (GAP-05, Stage 11).
    - Reads explicit 'via', 'max_sec', 'distance_m', 'observations_count', 'calibration_date', 'traffic_condition',
      'measurement_source', and 'notes' columns from camera_links.
    - Computes 2-hop inferred links strictly from a frozen snapshot of calibrated direct links (where not via),
      iterating over sorted camera names and selecting the path with minimum min_sec (tie-broken alphabetically by mid camera),
      without mutating the source dictionary during iteration.
    - Never treats DEFAULT_MIN_TRANSIT_SEC (90.0s) as a calibrated link unless explicitly stored as user_calibrated."""
    topo = {}
    if D.get("db") and D.get("lock"):
        with D["lock"]:
            try:
                cols = {r[1] for r in D["db"].execute("PRAGMA table_info(camera_links)").fetchall()}
                via_expr = "COALESCE(via, '')" if "via" in cols else "''"
                max_expr = "COALESCE(max_sec, 0)" if "max_sec" in cols else "0"
                dist_expr = "COALESCE(distance_m, 0)" if "distance_m" in cols else "0"
                obs_expr = "COALESCE(observations_count, 0)" if "observations_count" in cols else "0"
                cdate_expr = "COALESCE(calibration_date, '')" if "calibration_date" in cols else "''"
                traf_expr = "COALESCE(traffic_condition, 'normal')" if "traffic_condition" in cols else "'normal'"
                msrc_expr = "COALESCE(measurement_source, 'manual')" if "measurement_source" in cols else "'manual'"
                notes_expr = "COALESCE(notes, '')" if "notes" in cols else "''"
                rows = D["db"].execute(
                    f"SELECT from_cam, to_cam, min_sec, expected_sec, source, {via_expr}, "
                    f"{max_expr}, {dist_expr}, {obs_expr}, {cdate_expr}, {traf_expr}, {msrc_expr}, {notes_expr} "
                    "FROM camera_links ORDER BY from_cam ASC, to_cam ASC"
                ).fetchall()
                for c0, c1, mn, ex, src, via_val, mx_val, dist_val, obs_val, cdate_val, traf_val, msrc_val, notes_val in rows:
                    c0_s = str(c0 or "").strip()
                    c1_s = str(c1 or "").strip()
                    if not c0_s or not c1_s or c0_s == c1_s:
                        continue
                    src_s = str(src or "user_calibrated").strip() or "user_calibrated"
                    via_s = str(via_val or "").strip()
                    try:
                        mn_f = float(mn) if mn is not None else None
                    except (TypeError, ValueError):
                        mn_f = None
                    if mn_f is not None and (math.isnan(mn_f) or math.isinf(mn_f) or mn_f < 1.0):
                        mn_f = None
                    try:
                        ex_f = float(ex) if ex is not None else None
                    except (TypeError, ValueError):
                        ex_f = None
                    if ex_f is None or math.isnan(ex_f) or math.isinf(ex_f) or (mn_f is not None and ex_f < mn_f):
                        ex_f = max(mn_f or DEFAULT_MIN_TRANSIT_SEC, 300.0)
                    try:
                        mx_f = float(mx_val or 0.0)
                    except (TypeError, ValueError):
                        mx_f = 0.0
                    if math.isnan(mx_f) or math.isinf(mx_f) or mx_f < 0.0:
                        mx_f = 0.0
                    try:
                        dist_f = float(dist_val or 0.0)
                    except (TypeError, ValueError):
                        dist_f = 0.0
                    if math.isnan(dist_f) or math.isinf(dist_f) or dist_f < 0.0:
                        dist_f = 0.0
                    try:
                        obs_i = max(0, int(obs_val or 0))
                    except (TypeError, ValueError):
                        obs_i = 0
                    is_cal = (mn_f is not None) and (src_s not in ("uncalibrated_default", "demo", "default"))
                    eff_min = float(mn_f if mn_f is not None else DEFAULT_MIN_TRANSIT_SEC)
                    cal_st, cal_st_ar = _compute_calibration_completeness(
                        eff_min, ex_f, mx_f, dist_f, obs_i, str(cdate_val or ""), is_cal=is_cal
                    )
                    entry = {
                        "min_sec": eff_min,
                        "expected_sec": float(ex_f),
                        "max_sec": float(mx_f),
                        "distance_m": float(dist_f),
                        "observations_count": obs_i,
                        "calibration_date": str(cdate_val or ""),
                        "traffic_condition": str(traf_val or "normal"),
                        "measurement_source": str(msrc_val or "manual"),
                        "notes": str(notes_val or ""),
                        "source": src_s if is_cal else "uncalibrated_default",
                        "calibrated": bool(is_cal),
                        "calibration_status": cal_st,
                        "calibration_status_ar": cal_st_ar,
                    }
                    if via_s and via_s not in (c0_s, c1_s):
                        entry["via"] = via_s
                    topo[(c0_s, c1_s)] = entry
            except Exception:
                pass

    if isinstance(topology, dict):
        for k in sorted(topology.keys(), key=lambda x: str(x)):
            v = topology[k]
            if not isinstance(v, dict):
                continue
            if isinstance(k, tuple) and len(k) == 2:
                c0_s, c1_s = str(k[0] or "").strip(), str(k[1] or "").strip()
            elif "->" in str(k):
                a, b = str(k).split("->", 1)
                c0_s, c1_s = a.strip(), b.strip()
            else:
                continue
            if not c0_s or not c1_s or c0_s == c1_s:
                continue
            src_s = str(v.get("source", "user_calibrated")).strip() or "user_calibrated"
            raw_mn = v.get("min_sec")
            try:
                mn_f = float(raw_mn) if raw_mn is not None else None
            except (TypeError, ValueError):
                mn_f = None
            if mn_f is not None and (math.isnan(mn_f) or math.isinf(mn_f) or mn_f < 1.0):
                mn_f = None
            raw_ex = v.get("expected_sec")
            try:
                ex_f = float(raw_ex) if raw_ex is not None else None
            except (TypeError, ValueError):
                ex_f = None
            if ex_f is None or math.isnan(ex_f) or math.isinf(ex_f) or (mn_f is not None and ex_f < mn_f):
                ex_f = max(mn_f or DEFAULT_MIN_TRANSIT_SEC, 300.0)
            is_cal = bool(v.get("calibrated", (mn_f is not None) and (src_s not in ("uncalibrated_default", "demo", "default"))))
            if mn_f is None:
                is_cal = False
            via_s = str(v.get("via") or "").strip()
            mx_f = float(v.get("max_sec") or 0.0)
            dist_f = float(v.get("distance_m") or 0.0)
            obs_i = int(v.get("observations_count") or 0)
            cdate_s = str(v.get("calibration_date") or "")
            eff_min = float(mn_f if mn_f is not None else DEFAULT_MIN_TRANSIT_SEC)
            cal_st, cal_st_ar = _compute_calibration_completeness(eff_min, ex_f, mx_f, dist_f, obs_i, cdate_s, is_cal=is_cal)
            entry = {
                "min_sec": eff_min,
                "expected_sec": float(ex_f),
                "max_sec": mx_f,
                "distance_m": dist_f,
                "observations_count": obs_i,
                "calibration_date": cdate_s,
                "traffic_condition": str(v.get("traffic_condition") or "normal"),
                "measurement_source": str(v.get("measurement_source") or "manual"),
                "notes": str(v.get("notes") or ""),
                "source": src_s if is_cal else "uncalibrated_default",
                "calibrated": is_cal,
                "calibration_status": cal_st,
                "calibration_status_ar": cal_st_ar,
            }
            if via_s and via_s not in (c0_s, c1_s):
                entry["via"] = via_s
            topo[(c0_s, c1_s)] = entry

    # GAP-05: Deterministic 2-hop inference exclusively from frozen snapshot of calibrated direct links (not via)
    direct_links = {
        pair: dict(info)
        for pair, info in topo.items()
        if info.get("calibrated") and not info.get("via")
    }
    cams_sorted = sorted({c for pair in direct_links for c in pair})
    inferred_links = {}
    for c0 in cams_sorted:
        for c1 in cams_sorted:
            if c0 == c1 or (c0, c1) in topo:
                continue
            best_cand = None                         # (tot_min_sec, mid_cam, tot_expected_sec, tot_max_sec, tot_dist_m)
            for mid in cams_sorted:
                if mid not in (c0, c1) and (c0, mid) in direct_links and (mid, c1) in direct_links:
                    l1 = direct_links[(c0, mid)]
                    l2 = direct_links[(mid, c1)]
                    tot_min = float(l1["min_sec"] + l2["min_sec"])
                    tot_exp = float(l1["expected_sec"] + l2["expected_sec"])
                    tot_max = float((l1.get("max_sec") or 0.0) + (l2.get("max_sec") or 0.0)) if (l1.get("max_sec") and l2.get("max_sec")) else 0.0
                    tot_dist = float((l1.get("distance_m") or 0.0) + (l2.get("distance_m") or 0.0))
                    if best_cand is None or (tot_min, mid) < (best_cand[0], best_cand[1]):
                        best_cand = (tot_min, mid, tot_exp, tot_max, tot_dist)
            if best_cand is not None:
                tot_min, best_mid, tot_exp, tot_max, tot_dist = best_cand
                inferred_links[(c0, c1)] = {
                    "min_sec": tot_min,
                    "expected_sec": tot_exp,
                    "max_sec": tot_max,
                    "distance_m": tot_dist,
                    "observations_count": 0,
                    "calibration_date": "",
                    "traffic_condition": "normal",
                    "measurement_source": "inferred_2hop",
                    "notes": f"مستنتج تلقائياً عبر {best_mid}",
                    "source": "user_calibrated_inferred_2hop",
                    "calibrated": True,
                    "calibration_status": "inferred",
                    "calibration_status_ar": f"مستنتج (قفزتان عبر {best_mid})",
                    "via": best_mid,
                    "inferred": True,
                }

    topo.update(inferred_links)
    cal = {c for (a, b), info in topo.items() if info.get("calibrated") for c in (a, b)}
    with _STATE_LOCK:
        M["topology"] = topo
        M["calibrated_cams"] = cal
    return topo


def list_camera_links(q="", status_filter=""):
    """Return all user-configured camera_links rows and deterministic inferred 2-hop links with optional filtering (GAP-05, Stage 11)."""
    if not D.get("db") or not D.get("lock"):
        return {"ok": False, "error": "قاعدة البيانات غير متصلة", "links": [], "inferred_links": [], "calibrated_cameras": []}
    import registry as R
    R.migrate_db(D["db"], D["lock"], db_path=D.get("db_path"))
    configure_topology()
    explicit_links = []
    with D["lock"]:
        rows = D["db"].execute(
            "SELECT from_cam, to_cam, min_sec, expected_sec, COALESCE(source,'user_calibrated'), COALESCE(via,''), "
            "COALESCE(max_sec,0), COALESCE(distance_m,0), COALESCE(observations_count,0), COALESCE(calibration_date,''), "
            "COALESCE(traffic_condition,'normal'), COALESCE(measurement_source,'manual'), COALESCE(notes,''), "
            "COALESCE(updated_ts,0), COALESCE(updated_by,'') "
            "FROM camera_links ORDER BY from_cam ASC, to_cam ASC"
        ).fetchall()
    with _STATE_LOCK:
        topo_snap = dict(M.get("topology") or {})
        cal_snap = sorted(M.get("calibrated_cams") or ())

    q_norm = str(q or "").strip().lower()
    st_norm = str(status_filter or "").strip().lower()

    def _matches_filter(item):
        if q_norm:
            hay = f"{item.get('from_cam','')} {item.get('to_cam','')} {item.get('via','')} {item.get('notes','')}".lower()
            if q_norm not in hay:
                return False
        if st_norm and st_norm != "all":
            if st_norm == "complete" and item.get("calibration_status") != "complete":
                return False
            if st_norm == "needs_data" and item.get("calibration_status") != "basic_needs_data":
                return False
            if st_norm == "inferred" and not item.get("inferred"):
                return False
            if st_norm == "explicit" and item.get("inferred"):
                return False
        return True

    for c0, c1, mn, ex, src, via_val, mx_val, dist_val, obs_val, cdate_val, traf_val, msrc_val, notes_val, upd_ts, upd_by in rows:
        info = topo_snap.get((str(c0), str(c1)), {})
        is_cal = bool(info.get("calibrated", str(src or "user_calibrated") not in ("uncalibrated_default", "demo", "default")))
        mn_f = float(mn or DEFAULT_MIN_TRANSIT_SEC)
        ex_f = float(ex or 300.0)
        mx_f = float(mx_val or 0.0)
        dist_f = float(dist_val or 0.0)
        obs_i = int(obs_val or 0)
        cal_st, cal_st_ar = _compute_calibration_completeness(mn_f, ex_f, mx_f, dist_f, obs_i, str(cdate_val or ""), is_cal=is_cal)
        msrc_code = str(msrc_val or "manual")
        traf_code = str(traf_val or "normal")
        item = {
            "from_cam": str(c0),
            "to_cam": str(c1),
            "min_sec": mn_f,
            "expected_sec": ex_f,
            "max_sec": mx_f,
            "storage_unit": "seconds",
            "distance_m": dist_f,
            "observations_count": obs_i,
            "calibration_date": str(cdate_val or ""),
            "traffic_condition": traf_code,
            "traffic_condition_ar": TRAFFIC_CONDITIONS.get(traf_code, traf_code),
            "measurement_source": msrc_code,
            "measurement_source_ar": MEASUREMENT_SOURCES.get(msrc_code, msrc_code),
            "notes": str(notes_val or ""),
            "source": str(src or "user_calibrated"),
            "via": str(via_val or ""),
            "calibrated": is_cal,
            "calibration_status": cal_st,
            "calibration_status_ar": cal_st_ar,
            "updated_ts": float(upd_ts or 0.0),
            "updated_by": str(upd_by or ""),
            "inferred": False,
        }
        if _matches_filter(item):
            explicit_links.append(item)

    inferred_list = []
    for (c0, c1) in sorted(topo_snap.keys()):
        info = topo_snap[(c0, c1)]
        if info.get("inferred"):
            item = {
                "from_cam": c0,
                "to_cam": c1,
                "min_sec": float(info["min_sec"]),
                "expected_sec": float(info["expected_sec"]),
                "max_sec": float(info.get("max_sec") or 0.0),
                "storage_unit": "seconds",
                "distance_m": float(info.get("distance_m") or 0.0),
                "observations_count": 0,
                "calibration_date": "",
                "traffic_condition": "normal",
                "traffic_condition_ar": TRAFFIC_CONDITIONS["normal"],
                "measurement_source": "inferred_2hop",
                "measurement_source_ar": "مستنتج (قفزتان)",
                "notes": str(info.get("notes") or ""),
                "source": info["source"],
                "via": str(info.get("via") or ""),
                "calibrated": bool(info.get("calibrated", True)),
                "calibration_status": "inferred",
                "calibration_status_ar": str(info.get("calibration_status_ar") or "مستنتج (قفزتان)"),
                "inferred": True,
            }
            if _matches_filter(item):
                inferred_list.append(item)
    return {
        "ok": True,
        "storage_unit": "seconds",
        "links": explicit_links,
        "inferred_links": inferred_list,
        "calibrated_cameras": cal_snap,
        "total_explicit": len(explicit_links),
        "total_inferred": len(inferred_list),
    }


def save_camera_link(data, who="operator"):
    """Validate and persist a calibrated camera transition link in camera_links atomically (GAP-05, Stage 11).
    Supports unit conversion (seconds/minutes -> canonical seconds), min/expected/max validation, distance, observations count,
    calibration date, traffic condition, measurement source, duplicate rejection in create mode, and notes."""
    if not isinstance(data, dict):
        return {"ok": False, "error": "بيانات الرابط غير صالحة"}
    if not D.get("db") or not D.get("lock"):
        return {"ok": False, "error": "قاعدة البيانات غير متصلة"}
    from_cam = str(data.get("from_cam") or "").strip()
    to_cam = str(data.get("to_cam") or "").strip()
    via = str(data.get("via") or "").strip()
    source = str(data.get("source") or "user_calibrated").strip() or "user_calibrated"
    time_unit = str(data.get("time_unit") or "sec").strip().lower()
    unit_mult = 60.0 if time_unit in ("min", "mins", "minute", "minutes", "دقيقة", "دقائق") else 1.0

    if not from_cam or not to_cam:
        return {"ok": False, "error": "يرجى تحديد كاميرا المصدر (from_cam) وكاميرا الوجهة (to_cam)"}
    if from_cam == to_cam:
        return {"ok": False, "error": "لا يمكن ربط الكاميرا بنفسها؛ يجب أن تختلف الكاميرا المصدر عن الكاميرا الوجهة"}
    if via and via in (from_cam, to_cam):
        return {"ok": False, "error": "الكاميرا الوسيطة (via) لا يمكن أن تطابق كاميرا المصدر أو الوجهة"}

    raw_min = data.get("min_sec")
    raw_exp = data.get("expected_sec")
    try:
        min_val = float(raw_min)
    except (TypeError, ValueError):
        return {"ok": False, "error": "الحد الأدنى لزمن الانتقال (min_sec) يجب أن يكون رقماً صالحاً"}
    if math.isnan(min_val) or math.isinf(min_val) or min_val <= 0:
        return {"ok": False, "error": "الحد الأدنى لزمن الانتقال يجب أن يكون قيمة موجبة أكبر من الصفر"}
    min_sec = round(min_val * unit_mult, 2)
    if min_sec < 1.0:
        return {"ok": False, "error": "الحد الأدنى لزمن الانتقال (min_sec) يجب أن يكون 1.0 ثانية أو أكثر"}

    if raw_exp is None or str(raw_exp).strip() == "":
        expected_sec = max(min_sec, 300.0)
    else:
        try:
            exp_val = float(raw_exp)
        except (TypeError, ValueError):
            return {"ok": False, "error": "زمن الانتقال المعتاد/المتوقع (expected_sec) يجب أن يكون رقماً صالحاً"}
        if math.isnan(exp_val) or math.isinf(exp_val) or exp_val <= 0:
            return {"ok": False, "error": "زمن الانتقال المعتاد يجب أن يكون قيمة موجبة أكبر من الصفر"}
        expected_sec = round(exp_val * unit_mult, 2)
        if expected_sec < min_sec:
            return {"ok": False, "error": "الحد الأدنى لزمن الانتقال لا يجوز أن يتجاوز الزمن المعتاد (expected_sec >= min_sec)"}

    raw_max = data.get("max_sec")
    max_sec = 0.0
    if raw_max is not None and str(raw_max).strip() != "":
        try:
            max_val = float(raw_max)
        except (TypeError, ValueError):
            return {"ok": False, "error": "الحد الأعلى لزمن الانتقال (max_sec) يجب أن يكون رقماً صالحاً"}
        if math.isnan(max_val) or math.isinf(max_val) or max_val < 0:
            return {"ok": False, "error": "الحد الأعلى لزمن الانتقال لا يجوز أن يكون سالباً"}
        if max_val > 0:
            max_sec = round(max_val * unit_mult, 2)
            if max_sec < expected_sec:
                return {"ok": False, "error": "الحد الأعلى لزمن الانتقال لا يجوز أن يقل عن الزمن المعتاد (max_sec >= expected_sec)"}

    raw_dist = data.get("distance_m")
    distance_m = 0.0
    if raw_dist is not None and str(raw_dist).strip() != "":
        try:
            distance_m = float(raw_dist)
        except (TypeError, ValueError):
            return {"ok": False, "error": "المسافة التقريبية (distance_m) يجب أن تكون رقماً صالحاً"}
        if math.isnan(distance_m) or math.isinf(distance_m) or distance_m < 0:
            return {"ok": False, "error": "المسافة التقريبية لا يجوز أن تكون قيمة سالبة"}
        distance_m = round(distance_m, 2)
        if distance_m > 0:
            max_implied_kmh = (distance_m / min_sec) * 3.6
            exp_implied_kmh = (distance_m / expected_sec) * 3.6
            if max_implied_kmh > 260.0 or exp_implied_kmh < 0.5:
                return {
                    "ok": False,
                    "error": (
                        f"المسافة المدخلة ({distance_m}م) غير متسقة فيزيائياً مع زمن الانتقال "
                        f"(السرعة الضمنية القصوى {max_implied_kmh:.1f} كم/ساعة والمعتادة {exp_implied_kmh:.1f} كم/ساعة خارج النطاق المعقول 0.5–260 كم/ساعة)"
                    ),
                }

    raw_obs = data.get("observations_count")
    observations_count = 0
    if raw_obs is not None and str(raw_obs).strip() != "":
        try:
            obs_f = float(raw_obs)
            if math.isnan(obs_f) or math.isinf(obs_f) or obs_f < 0 or not obs_f.is_integer():
                return {"ok": False, "error": "عدد المشاهدات/القياسات يجب أن يكون عدداً صحيحاً غير سالب"}
            observations_count = int(obs_f)
        except (TypeError, ValueError):
            return {"ok": False, "error": "عدد المشاهدات/القياسات يجب أن يكون عدداً صحيحاً صالحاً"}

    calibration_date = str(data.get("calibration_date") or "").strip()[:32]
    if not calibration_date:
        calibration_date = time.strftime("%Y-%m-%d", time.localtime())
    traffic_condition = str(data.get("traffic_condition") or "normal").strip() or "normal"
    if traffic_condition not in TRAFFIC_CONDITIONS:
        traffic_condition = "normal"
    measurement_source = str(data.get("measurement_source") or "manual").strip() or "manual"
    if measurement_source not in MEASUREMENT_SOURCES:
        measurement_source = "manual"
    notes = str(data.get("notes") or "").strip()[:500]
    reject_duplicate = bool(data.get("reject_duplicate") or str(data.get("mode") or "").lower() == "create")

    import registry as R
    warnings = []
    now_ts = time.time()
    action_taken = ["added"]

    def _save_tx(conn):
        R.migrate_db(conn, D["lock"], db_path=D.get("db_path"))
        existing = conn.execute(
            "SELECT 1 FROM camera_links WHERE from_cam=? AND to_cam=?",
            (from_cam, to_cam)
        ).fetchone()
        if existing:
            if reject_duplicate:
                return "duplicate"
            action_taken[0] = "updated"
        rev = conn.execute(
            "SELECT min_sec, expected_sec, COALESCE(via,'') FROM camera_links WHERE from_cam=? AND to_cam=?",
            (to_cam, from_cam)
        ).fetchone()
        if rev and rev[0] is not None and float(rev[0]) > 0:
            rev_min = float(rev[0])
            ratio = max(min_sec, rev_min) / max(1.0, min(min_sec, rev_min))
            if ratio > 10.0:
                warnings.append(
                    f"تنبيه: يوجد تفاوت كبير بين زمن الانتقال ({from_cam}->{to_cam}: {min_sec:.0f}ث) "
                    f"والاتجاه المعاكس ({to_cam}->{from_cam}: {rev_min:.0f}ث)"
                )
        conn.execute(
            "INSERT INTO camera_links("
            "from_cam, to_cam, min_sec, expected_sec, source, via, "
            "max_sec, distance_m, observations_count, calibration_date, traffic_condition, measurement_source, notes, updated_ts, updated_by"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(from_cam, to_cam) DO UPDATE SET "
            "min_sec=excluded.min_sec, expected_sec=excluded.expected_sec, source=excluded.source, via=excluded.via, "
            "max_sec=excluded.max_sec, distance_m=excluded.distance_m, observations_count=excluded.observations_count, "
            "calibration_date=excluded.calibration_date, traffic_condition=excluded.traffic_condition, "
            "measurement_source=excluded.measurement_source, notes=excluded.notes, updated_ts=excluded.updated_ts, updated_by=excluded.updated_by",
            (from_cam, to_cam, min_sec, expected_sec, source, via,
             max_sec, distance_m, observations_count, calibration_date, traffic_condition, measurement_source, notes, now_ts, str(who))
        )
        return action_taken[0]

    tx_res = R.run_atomic_tx(D["db"], D["lock"], _save_tx, db_path=D.get("db_path"))
    if tx_res == "duplicate":
        return {"ok": False, "error": f"يوجد رابط معايرة محفوظ مسبقاً بين {from_cam} و {to_cam}؛ استخدم خيار التعديل لتحديثه"}

    log_fn = R.D.get("log")
    if callable(log_fn):
        try:
            log_fn("camera_link saved", f"{from_cam}->{to_cam} ({tx_res}) min={min_sec}s exp={expected_sec}s max={max_sec}s dist={distance_m}m obs={observations_count} src={measurement_source} via={via or '-'} by {who}")
        except Exception:
            pass
    configure_topology()
    is_cal = source not in ("uncalibrated_default", "demo", "default")
    cal_st, cal_st_ar = _compute_calibration_completeness(min_sec, expected_sec, max_sec, distance_m, observations_count, calibration_date, is_cal=is_cal)
    res = {
        "ok": True,
        "action": tx_res,
        "link": {
            "from_cam": from_cam,
            "to_cam": to_cam,
            "min_sec": min_sec,
            "expected_sec": expected_sec,
            "max_sec": max_sec,
            "storage_unit": "seconds",
            "distance_m": distance_m,
            "observations_count": observations_count,
            "calibration_date": calibration_date,
            "traffic_condition": traffic_condition,
            "traffic_condition_ar": TRAFFIC_CONDITIONS.get(traffic_condition, traffic_condition),
            "measurement_source": measurement_source,
            "measurement_source_ar": MEASUREMENT_SOURCES.get(measurement_source, measurement_source),
            "notes": notes,
            "source": source,
            "via": via,
            "calibrated": is_cal,
            "calibration_status": cal_st,
            "calibration_status_ar": cal_st_ar,
        },
        "warnings": warnings,
    }
    if warnings:
        res["warning"] = warnings[0]
    return res


def delete_camera_link(from_cam, to_cam=None, who="operator"):
    """Delete a calibrated camera transition link from camera_links atomically (GAP-05)."""
    if isinstance(from_cam, dict):
        d = from_cam
        if to_cam and who == "operator":
            who = str(to_cam)
        from_cam = d.get("from_cam", "")
        to_cam = d.get("to_cam", "")
    fc = str(from_cam or "").strip()
    tc = str(to_cam or "").strip()
    if not fc or not tc:
        return {"ok": False, "error": "يرجى تحديد كاميرا البداية وكاميرا النهاية للحذف"}
    if not D.get("db") or not D.get("lock"):
        return {"ok": False, "error": "قاعدة البيانات غير متصلة"}
    import registry as R

    def _del_tx(conn):
        cur = conn.execute("DELETE FROM camera_links WHERE from_cam=? AND to_cam=?", (fc, tc))
        return cur.rowcount > 0

    deleted = R.run_atomic_tx(D["db"], D["lock"], _del_tx, db_path=D.get("db_path"))
    log_fn = R.D.get("log")
    if deleted and callable(log_fn):
        try:
            log_fn("camera_link deleted", f"{fc}->{tc} by {who}")
        except Exception:
            pass
    configure_topology()
    return {"ok": True, "deleted": bool(deleted), "from_cam": fc, "to_cam": tc}


def _link_info(c0, c1):
    """Return transition metadata between c0 and c1.
    Unless explicitly configured by the user in camera_links / topology, calibrated is False,
    source is 'uncalibrated_default', and no 'via' hop is assumed."""
    with _STATE_LOCK:
        topo = M.get("topology") or {}
        raw_info = dict(topo[(c0, c1)]) if (c0, c1) in topo else None
    if raw_info is not None:
        raw_info.setdefault("calibrated", raw_info.get("source") not in ("uncalibrated_default", "demo", "default"))
        return raw_info
    return {
        "min_sec": DEFAULT_MIN_TRANSIT_SEC,
        "expected_sec": 300.0,
        "source": "uncalibrated_default",
        "source_label_ar": "افتراضي تجريبي غير معاير",
        "calibrated": False
    }


def feat(ts, cam, vc, n, gap, cams_map=None):
    t = lt(ts); h = t.tm_hour + t.tm_min / 60.0
    gap_norm = math.log1p(max(0.0, min(float(gap or 0.0), 30 * 86400)))
    cam_key = cam or "UNKNOWN"
    if cams_map is not None:
        cam_idx = float(cams_map.setdefault(cam_key, len(cams_map)))
    else:
        with _STATE_LOCK:
            cmap = M["cams"]
            cam_idx = float(cmap.get(cam_key, len(cmap)))
    return [
        math.sin(2 * math.pi * h / 24.0),
        math.cos(2 * math.pi * h / 24.0),
        float(t.tm_wday in OFF),
        cam_idx,
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
    dist_m = float(link.get("distance_m") or 0.0)
    implied_kmh = round((dist_m / dt) * 3.6, 1) if (dist_m > 0 and dt > 0) else None
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
        "distance_m": dist_m,
        "implied_speed_kmh": implied_kmh,
        "why": reason
    }


def _fetch_sightings(days=90, plate_filter=None, include_demo=False):
    """Fetch valid sightings from SQLite (GAP-04):
    - Defaults strictly to `include_demo=False` (`WHERE COALESCE(src, 'live') = 'live'`).
    - Never falls back to demo records unless `include_demo=True` is explicitly passed."""
    if isinstance(days, str):
        plate_filter = days
        days = 90
    elif isinstance(days, bool):
        include_demo = days
        days = 90
    if not D.get("db"):
        return []
    cutoff = time.time() - float(days) * 86400.0
    src_clause = "" if include_demo else " AND COALESCE(src, 'live') = 'live'"
    params = [cutoff]
    plate_clause = ""
    if plate_filter:
        c_pl = _canonical_plate(plate_filter)
        plate_clause = " AND plate = ?"
        params.append(c_pl)
    with D["lock"]:
        cols = {r[1] for r in D["db"].execute("PRAGMA table_info(sightings)").fetchall()}
        sess_expr = "COALESCE(session_id,'')" if "session_id" in cols else "''"
        raw = D["db"].execute(
            f"SELECT rowid, ts, cam, plate, vclass, conf, COALESCE(src,'live'), COALESCE(direction,''), {sess_expr} "
            f"FROM sightings WHERE ts IS NOT NULL AND ts > ?{src_clause}{plate_clause} ORDER BY ts ASC, rowid ASC",
            tuple(params)
        ).fetchall()
    return _valid_rows(raw)


def _analyze_paths(rows=None, include_demo=False):
    """Build multi-camera vehicle trajectories strictly by full canonical plate identity (P0-A, GAP-04).
    Excludes src='demo' sightings unless include_demo=True is explicitly requested."""
    if isinstance(rows, bool):
        include_demo = rows
        rows = None
    if rows is None:
        rows = _fetch_sightings(days=90, include_demo=include_demo)
    elif not include_demo:
        rows = [r for r in rows if (r[6] if len(r) > 6 else "live") != "demo"]

    by_plate = {}
    for row in rows:
        rid, ts, cam, plate, vc, conf, src, direction = row[:8]
        sess = row[8] if len(row) > 8 else ""
        key = _canonical_plate(plate)
        by_plate.setdefault(key, []).append((rid, ts, cam, vc, conf, src, direction, sess, key))
    transitions = {}
    conflicts = {}
    recent_paths = []
    with _STATE_LOCK:
        cal_cams = set(M.get("calibrated_cams") or ())

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
                path_srcs = {pt[5] for pt in dedup_pts}
                path_src = "demo" if "demo" in path_srcs else "live"
                recent_paths.append({
                    "plate": key,
                    "vclass": dedup_pts[-1][3],
                    "last_ts": dedup_pts[-1][1],
                    "sightings": len(dedup_pts),
                    "route": " ➔ ".join(dedup_cams[-5:]),
                    "direction": dedup_pts[-1][6] or f"{dedup_cams[-2]} ➔ {dedup_cams[-1]}",
                    "conflict": any(k[0] == key for k in conflicts),
                    "missing_hops": sorted(set(missing_hops)),
                    "calibrated": all_cal,
                    "src": path_src,
                })

    corridors = []
    for (c0, c1), dts in sorted(transitions.items(), key=lambda kv: (-len(kv[1]), kv[0])):
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
        if len(corridors) >= 10:
            break
    recent_paths.sort(key=lambda x: (-int(x["conflict"]), -x["last_ts"]))
    return corridors, recent_paths[:15], conflicts


def train(include_demo=False):
    """Train anomaly detector and path statistics (GAP-04, FINAL-OBS-02):
    - Protected by _TRAIN_LOCK to prevent concurrent overlapping training runs, and _STATE_LOCK when updating M/M_DEMO.
    - When `include_demo=False` (default): trains strictly on `src='live'` sightings and updates live state `M`.
    - When `include_demo=True`: trains on combined/demo sightings and updates `M_DEMO` without polluting live state `M`."""
    with _TRAIN_LOCK:
        inc_demo = bool(include_demo)
        target_state = M_DEMO if inc_demo else M
        data_source = "demo" if inc_demo else "live"
        rows = _fetch_sightings(days=90, include_demo=inc_demo)
        corridors, recent_paths, conflicts = _analyze_paths(rows, include_demo=inc_demo)
        if len(rows) < 50:
            with _STATE_LOCK:
                target_state.update(
                    model=None, type="none", model_type="none", trained=0, n=len(rows),
                    n_demo=sum(r[6] == "demo" for r in rows),
                    corridors=corridors, recent_paths=recent_paths, top=[]
                )
            return {
                "ok": False,
                "reason": "insufficient_data",
                "data_source": data_source,
                "includes_demo": inc_demo,
                "n": len(rows),
                "min_required": 50,
                "error": f"البيانات غير كافية للتدريب ({len(rows)} من أصل 50 رصداً مطلوباً). ولّد تاريخاً تجريبياً أو انتظر مزيداً من الرصد."
            }
        cams_map = {}
        for r in rows:
            cams_map.setdefault(r[2], len(cams_map))
        tot, last, last_cam, hrs, X = {}, {}, {}, {}, []
        for r in rows:
            k_id = _canonical_plate(r[3])
            tot[k_id] = tot.get(k_id, 0) + 1
        for rid, ts, cam, plate, vc, conf, src, _, sess in rows:
            k_id = _canonical_plate(plate)
            gap = ts - last[k_id] if k_id in last else 0.0
            X.append(feat(ts, cam, vc, tot[k_id], gap, cams_map=cams_map))
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

        with _STATE_LOCK:
            if inc_demo:
                M_DEMO.update(
                    model=model, type=short_type, model_type=mtype, trained=time.time(), n=len(rows),
                    n_demo=sum(r[6] == "demo" for r in rows),
                    cams=cams_map, share=share, top=top, corridors=corridors, recent_paths=recent_paths
                )
            else:
                M.update(
                    model=model, type=short_type, model_type=mtype, trained=time.time(), n=len(rows),
                    n_demo=0, plate_n=tot, last=last, last_cam=last_cam, cams=cams_map, share=share, since=0,
                    top=top, corridors=corridors, recent_paths=recent_paths
                )
        return {
            "ok": True,
            "n": len(rows),
            "type": short_type,
            "model_type": mtype,
            "data_source": data_source,
            "includes_demo": inc_demo,
        }


def check_route(plate, cam, ts=None, conf=0.9, cur_id=0, session_id="", identity_confirmed=True):
    """Track live camera-to-camera transition strictly for the exact canonical plate identity (P0-A).
    - Never uses LIKE '%digits' (so 112345 and 12345 never collide).
    - Never links two plates with different letters (e.g. 'صنعاء-77777' and 'عدن-77777').
    - Strictly excludes src='demo' sightings from live route checking."""
    if not identity_confirmed:
        return None, None
    ts = float(ts or time.time())
    k_id = _canonical_plate(plate)
    if not k_id:
        return None, None
    with _STATE_LOCK:
        prev = M["last_cam"].get(k_id)
    if D.get("db"):
        with D["lock"]:
            cols = {r[1] for r in D["db"].execute("PRAGMA table_info(sightings)").fetchall()}
            sess_col = "COALESCE(session_id,'')" if "session_id" in cols else "''"
            r = D["db"].execute(
                f"SELECT rowid, cam, ts, conf, {sess_col} FROM sightings "
                "WHERE plate=? AND COALESCE(src,'live')='live' AND ts IS NOT NULL AND ts > 0 AND ts <= ? AND rowid != ? "
                "ORDER BY ts DESC, rowid DESC LIMIT 1",
                (k_id, ts, int(cur_id or 0))
            ).fetchone()
            if r:
                prev = (int(r[0] or 0), str(r[1] or "UNKNOWN"), float(r[2]), float(r[3] or 0.8), str(r[4] or ""))
            elif prev:
                chk = D["db"].execute("SELECT plate, COALESCE(src,'live') FROM sightings WHERE rowid=?", (prev[0],)).fetchone()
                if not chk or _canonical_plate(chk[0]) != k_id or chk[1] != "live":
                    prev = None

    with _STATE_LOCK:
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
    """Update habit stats thread-safely under _STATE_LOCK; return reason string if this sighting looks anomalous, else None."""
    ts = float(ts or time.time())
    k_id = _canonical_plate(plate)
    if check_conflict and identity_confirmed:
        _, c_rec = check_route(k_id, cam, ts, conf=conf, cur_id=cur_id, session_id=session_id, identity_confirmed=identity_confirmed)
        if c_rec:
            return c_rec["why"]
    with _STATE_LOCK:
        model_ref = M.get("model")
        if not model_ref:
            return None
        n = M["plate_n"].get(k_id, 0) + 1
        gap = ts - M["last"][k_id] if k_id in M["last"] else 0.0
        M["plate_n"][k_id] = n
        M["last"][k_id] = ts
        M["since"] += 1
        fv = feat(ts, cam, vc, n, gap)
        share_val = M["share"].get((lt(ts).tm_wday in OFF, lt(ts).tm_hour), 0)
    if model_ref.decision_function(np.asarray([fv], dtype=np.float64))[0] >= 0:
        return None
    return why(vc, n, share_val)


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
    with _STATE_LOCK:
        cal_cams = set(M.get("calibrated_cams") or ())

    for i, (rid, ts, cam, pl, vc, conf, src, direction, _) in enumerate(dedup):
        prev = dedup[i - 1] if i > 0 else None
        dt_sec = round(ts - prev[1], 1) if prev else None
        dt_min = round(dt_sec / 60.0, 1) if dt_sec is not None else None
        prev_cam = prev[2] if prev else None
        c_rec = None
        missing_via = None
        cam_cal = (cam in cal_cams) if cal_cams else False

        step_exp_sec = None
        step_max_sec = None
        step_excessive_delay = False
        step_speed_kmh = None
        if prev_cam and prev_cam != cam:
            link = _link_info(prev_cam, cam)
            step_exp_sec = float(link.get("expected_sec") or 300.0)
            step_max_sec = float(link.get("max_sec") or 0.0)
            if step_max_sec > 0 and dt_sec is not None and dt_sec > step_max_sec:
                step_excessive_delay = True
            dist_m_step = float(link.get("distance_m") or 0.0)
            if dist_m_step > 0 and dt_sec and dt_sec > 0:
                step_speed_kmh = round((dist_m_step / dt_sec) * 3.6, 1)
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
            "expected_sec": step_exp_sec,
            "max_sec": step_max_sec if step_max_sec else None,
            "excessive_delay": step_excessive_delay,
            "implied_speed_kmh": step_speed_kmh,
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


def plate_path(plate, include_demo=False):
    """Return chronological trajectory for a plate (P0-A, GAP-04):
    - Defaults strictly to `include_demo=False` (live sightings only, `data_source='live'`).
    - Never falls back automatically to demo data when live sightings are empty; instead sets `has_demo_only=True`
      when matching records exist only in `src='demo'`.
    - When `include_demo=True` is explicitly passed, includes `src='demo'` records and tags response with `data_source='demo'`."""
    from registry import norm_plate, split_plate
    inc_demo = bool(include_demo)
    data_source = "demo" if inc_demo else "live"
    q_raw = str(plate or "").strip()
    if not q_raw:
        return {"ok": False, "error": "أدخل رقم اللوحة للبحث عن مسارها"}
    q_digits, q_letters = split_plate(q_raw)
    np_plate = norm_plate(q_raw)
    if not q_digits:
        return {"ok": False, "error": "صيغة رقم اللوحة غير صالحة"}
    if not D.get("db"):
        return {"ok": False, "error": "قاعدة البيانات غير متصلة"}

    src_filter = "" if inc_demo else " AND COALESCE(src,'live')='live'"
    has_demo_rows = False
    with D["lock"]:
        if q_letters:
            raw = D["db"].execute(
                "SELECT rowid, ts, cam, plate, vclass, conf, COALESCE(src,'live'), COALESCE(direction,'') "
                f"FROM sightings WHERE plate=?{src_filter} AND ts IS NOT NULL AND ts > 0 ORDER BY rowid ASC LIMIT 300",
                (np_plate,)
            ).fetchall()
            candidate_groups = {np_plate: raw} if raw else {}
            if not inc_demo and not candidate_groups:
                demo_chk = D["db"].execute(
                    "SELECT 1 FROM sightings WHERE plate=? AND COALESCE(src,'live')='demo' AND ts IS NOT NULL AND ts > 0 LIMIT 1",
                    (np_plate,)
                ).fetchone()
                has_demo_rows = bool(demo_chk)
        else:
            raw_all = D["db"].execute(
                "SELECT rowid, ts, cam, plate, vclass, conf, COALESCE(src,'live'), COALESCE(direction,'') "
                f"FROM sightings WHERE (plate=? OR plate LIKE ?){src_filter} AND ts IS NOT NULL AND ts > 0 ORDER BY rowid ASC LIMIT 600",
                (q_digits, f"%-{q_digits}")
            ).fetchall()
            candidate_groups = {}
            for r in raw_all:
                c_pl = _canonical_plate(r[3])
                if split_plate(c_pl)[0] == q_digits:
                    candidate_groups.setdefault(c_pl, []).append(r)
            if not inc_demo and not candidate_groups:
                demo_all = D["db"].execute(
                    "SELECT plate FROM sightings WHERE (plate=? OR plate LIKE ?) AND COALESCE(src,'live')='demo' AND ts IS NOT NULL AND ts > 0 LIMIT 50",
                    (q_digits, f"%-{q_digits}")
                ).fetchall()
                has_demo_rows = any(split_plate(_canonical_plate(r[0]))[0] == q_digits for r in demo_all)

    if not candidate_groups:
        return {
            "ok": True,
            "found": False,
            "data_source": data_source,
            "includes_demo": inc_demo,
            "has_demo_only": bool(has_demo_rows),
            "demo_hint_ar": (
                "هذه اللوحة موجودة في سجل المحاكاة التجريبي (Demo) فقط ولا توجد لها مشاهدات حية. "
                "فعّل «وضع استعراض بيانات المحاكاة التجريبية» لعرض مسارها التجريبي."
                if has_demo_rows else ""
            ),
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
            "data_source": data_source,
            "includes_demo": inc_demo,
            "has_demo_only": False,
            "ambiguous_query": False,
            "candidates": candidates,
            "candidate_paths": {only_pl: traj},
            **traj,
            "limitations": (
                "الربط بين الكاميرات يعتمد على تطابق الهوية الكاملة للوحة المقروءة آلياً وأوقات الرصد؛ "
                + ("تمت معايرة أزمنة الانتقال لجميع الكاميرات في المسار من قِبل المستخدم." if all_cal else "الكاميرات في المسار تستخدم قيماً افتراضية تجريبية غير معايرة (90 ثانية).")
            )
        }

    cand_paths = {c_pl: _build_single_trajectory(c_pl, candidate_groups[c_pl]) for c_pl in candidates}
    return {
        "ok": True,
        "found": True,
        "data_source": data_source,
        "includes_demo": inc_demo,
        "has_demo_only": False,
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


def forecast(include_demo=False):
    now = time.time()
    if not D.get("db"):
        return None
    inc_demo = bool(include_demo)
    src_clause = "" if inc_demo else " AND COALESCE(src, 'live') = 'live'"
    with D["lock"]:
        tss = [
            float(r[0]) for r in D["db"].execute(
                f"SELECT ts FROM sightings WHERE ts IS NOT NULL AND ts > ?{src_clause}", (now - 60 * 86400,)
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
        "data_source": "demo" if inc_demo else "live",
        "includes_demo": inc_demo,
        "band_method": "empirical_dispersion_mean_plus_minus_1.28_std",
        "band_description_ar": "نطاق التشتت التجريبي (المتوسط ± 1.28×الانحراف المعياري؛ يغطي نحو 80% تحت التوزيع الطبيعي)"
    }


def summary(include_demo=False):
    """Return insights summary (GAP-04):
    - Defaults strictly to `include_demo=False` (`data_source='live'`, live sightings only).
    - Never exposes demo sightings, demo anomalies, or demo paths unless `include_demo=True` is explicitly requested."""
    inc_demo = bool(include_demo)
    data_source = "demo" if inc_demo else "live"
    rows = _fetch_sightings(days=90, include_demo=inc_demo)
    demo_available = 0
    if D.get("db") and D.get("lock"):
        with D["lock"]:
            try:
                demo_available = int(D["db"].execute("SELECT COUNT(*) FROM sightings WHERE COALESCE(src,'live')='demo'").fetchone()[0] or 0)
            except Exception:
                demo_available = 0

    with _STATE_LOCK:
        need_demo_train = inc_demo and M_DEMO.get("model") is None and len(rows) >= 50
    if need_demo_train:
        train(include_demo=True)

    corridors, recent_paths, _ = _analyze_paths(rows, include_demo=inc_demo)
    n_demo_in_rows = sum(r[6] == "demo" for r in rows)
    default_short = "IsolationForest" if IsolationForest is not None else "StatForest"
    with _STATE_LOCK:
        state_snap = dict(M_DEMO if inc_demo else M)
        top_snap = list(state_snap.get("top") or [])
    is_ready = bool(state_snap.get("model")) and len(rows) >= 50
    short_type = state_snap.get("type", "none") if is_ready else default_short
    anomalies = top_snap if is_ready else []
    if not inc_demo:
        anomalies = [a for a in anomalies if a.get("src", "live") == "live"]

    return {
        "data_source": data_source,
        "includes_demo": inc_demo,
        "demo_available_count": demo_available,
        "model": {
            "ready": is_ready,
            "type": short_type,
            "model_type": state_snap.get("model_type", "none") if is_ready else "none",
            "trained": state_snap.get("trained", 0) if is_ready else 0,
            "n": len(rows),
            "demo": n_demo_in_rows,
            "live": len(rows) - n_demo_in_rows,
            "demo_available": demo_available,
            "data_source": data_source,
            "includes_demo": inc_demo,
            "min_required": 50,
            "timezone": _tz_name(),
            "reason": "ready" if is_ready else ("insufficient_data" if len(rows) < 50 else "not_trained")
        },
        "forecast": forecast(include_demo=inc_demo) if is_ready else None,
        "anomalies": anomalies,
        "corridors": corridors,
        "paths": recent_paths
    }


def seed_demo(days=30, cams=("CAM1", "CAM2", "CAM3"), seed=7):
    """Synthetic history so the models have something to learn from (including multi-camera paths). Marked src='demo'.
    GAP-04: Trains M_DEMO (include_demo=True) without polluting the live operational state M."""
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
    import registry as R

    def _seed_tx(conn):
        if conn.execute("SELECT COUNT(*) FROM sightings WHERE src='demo'").fetchone()[0]:
            return False
        conn.executemany("INSERT INTO sightings(ts, cam, plate, conf, vclass, src, direction) VALUES(?,?,?,?,?,?,?)", out)
        return True

    inserted = R.run_atomic_tx(D["db"], D["lock"], _seed_tx, db_path=D.get("db_path"))
    if not inserted:
        return {"ok": False, "error": "التاريخ التجريبي موجود مسبقاً"}
    r = train(include_demo=True)
    r["seeded"] = len(out)
    return r


def clear_demo():
    import registry as R

    def _clear_tx(conn):
        conn.execute("DELETE FROM sightings WHERE src='demo'")

    R.run_atomic_tx(D["db"], D["lock"], _clear_tx, db_path=D.get("db_path"))
    with _STATE_LOCK:
        M_DEMO.update(
            model=None, type="none", model_type="none", trained=0, n=0, n_demo=0,
            cams={}, share={}, top=[], corridors=[], recent_paths=[]
        )
    r = train(include_demo=False)
    return {**r, "ok": True, "cleared": True}


def _csv_safe_cell(val):
    s = "" if val is None else str(val)
    if s.lstrip(" \t\r\n\ufeff").startswith(("=", "+", "-", "@")):
        return "'" + s
    return s


def export_camera_links(fmt="json"):
    """Export explicit calibrated camera links as JSON or UTF-8-BOM CSV (Stage 11)."""
    res = list_camera_links()
    links = res.get("links") or []
    f_norm = str(fmt or "json").strip().lower()
    if f_norm == "csv":
        out = io.StringIO(newline="")
        w = csv.writer(out, lineterminator="\r\n")
        w.writerow([
            "from_cam", "to_cam", "min_sec", "expected_sec", "max_sec", "distance_m",
            "observations_count", "calibration_date", "traffic_condition", "measurement_source",
            "via", "notes", "calibration_status"
        ])
        for l in links:
            w.writerow([
                _csv_safe_cell(l.get("from_cam")),
                _csv_safe_cell(l.get("to_cam")),
                l.get("min_sec", 90),
                l.get("expected_sec", 300),
                l.get("max_sec", 0),
                l.get("distance_m", 0),
                l.get("observations_count", 0),
                _csv_safe_cell(l.get("calibration_date", "")),
                _csv_safe_cell(l.get("traffic_condition", "normal")),
                _csv_safe_cell(l.get("measurement_source", "manual")),
                _csv_safe_cell(l.get("via", "")),
                _csv_safe_cell(l.get("notes", "")),
                _csv_safe_cell(l.get("calibration_status", "")),
            ])
        return ("\ufeff" + out.getvalue()).encode("utf-8"), "mersad_camera_links.csv", "text/csv; charset=utf-8"
    payload = {
        "schema": "mersad_camera_links_v1",
        "storage_unit": "seconds",
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "links": links,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8"), "mersad_camera_links.json", "application/json; charset=utf-8"


def import_camera_links(raw_data, filename="", who="operator"):
    """Validate and import camera links from JSON or CSV without executing or trusting unvalidated fields (Stage 11)."""
    if not D.get("db") or not D.get("lock"):
        return {"ok": False, "error": "قاعدة البيانات غير متصلة"}
    if isinstance(raw_data, bytes):
        try:
            txt = raw_data.decode("utf-8-sig")
        except UnicodeDecodeError:
            txt = raw_data.decode("cp1256", "replace")
    else:
        txt = str(raw_data or "")
    txt = txt.strip()
    if not txt:
        return {"ok": False, "error": "ملف الاستيراد فارغ"}

    fn_low = str(filename or "").strip().lower()
    items = []
    if fn_low.endswith(".csv") or (not txt.startswith("{") and not txt.startswith("[")):
        reader = csv.DictReader(io.StringIO(txt))
        for r in reader:
            if not r:
                continue
            norm_r = {str(k or "").strip().lower(): str(v or "").strip().lstrip("'") for k, v in r.items() if k is not None}
            if any(norm_r.values()):
                items.append(norm_r)
    else:
        try:
            parsed = json.loads(txt)
        except json.JSONDecodeError:
            return {"ok": False, "error": "صيغة ملف JSON غير صالحة"}
        if isinstance(parsed, dict):
            items = parsed.get("links") or parsed.get("items") or []
        elif isinstance(parsed, list):
            items = parsed
        if not isinstance(items, list):
            return {"ok": False, "error": "بنية ملف JSON غير صالحة (يتوقع قائمة links)"}

    if not items:
        return {"ok": False, "error": "لا توجد سجلات صالحة للاستيراد في الملف"}

    added = updated = skipped = 0
    errors = []
    for idx, item in enumerate(items, 1):
        if not isinstance(item, dict):
            skipped += 1
            errors.append(f"السطر {idx}: سجل غير صالح")
            continue
        res = save_camera_link(item, who=who)
        if res.get("ok"):
            if res.get("action") == "updated":
                updated += 1
            else:
                added += 1
        else:
            skipped += 1
            errors.append(f"السطر {idx}: {res.get('error', 'بيانات غير صالحة')}")
    return {
        "ok": (added + updated) > 0,
        "added": added,
        "updated": updated,
        "skipped": skipped,
        "errors": errors[:15],
        "error": errors[0] if ((added + updated) == 0 and errors) else "",
    }


# ---------- Phase 4: Manual Field Calibration Registry (Strictly Separated from Automated AI Evaluation) ----------
def list_field_calibrations():
    """Return all manual field calibration records, clearly badged as manual_unverified and separated from automated AI runs."""
    if not D.get("db") or not D.get("lock"):
        return {"ok": False, "error": "قاعدة البيانات غير متصلة", "items": []}
    import registry as R
    R.migrate_db(D["db"], D["lock"], db_path=D.get("db_path"))
    with D["lock"]:
        rows = D["db"].execute(
            "SELECT id, entry_type, verification_status, from_cam, to_cam, transit_sec, "
            "measured_plate_accuracy, samples_count, correct_reads, incorrect_reads, "
            "source_description, measurement_date, model_used, operator_name, notes, created_ts, updated_ts "
            "FROM field_calibrations ORDER BY id DESC"
        ).fetchall()
        auto_eval_count = int(D["db"].execute("SELECT COUNT(*) FROM plate_eval_runs WHERE status='completed'").fetchone()[0] or 0)
    items = []
    for r in rows:
        items.append({
            "id": int(r[0]),
            "entry_type": str(r[1] or "manual_unverified"),
            "verification_status": "manual_unverified",
            "verification_label_ar": "مدخلة يدوياً — غير متحقق منها آلياً",
            "is_verified_ai_metric": False,
            "from_cam": str(r[3] or ""),
            "to_cam": str(r[4] or ""),
            "transit_sec": float(r[5] or 0.0),
            "measured_plate_accuracy": round(float(r[6]), 2) if r[6] is not None else None,
            "samples_count": int(r[7] or 0),
            "correct_reads": int(r[8] or 0),
            "incorrect_reads": int(r[9] or 0),
            "source_description": str(r[10] or ""),
            "measurement_date": str(r[11] or ""),
            "model_used": str(r[12] or ""),
            "operator_name": str(r[13] or ""),
            "notes": str(r[14] or ""),
            "created_ts": float(r[15] or 0.0),
            "updated_ts": float(r[16] or 0.0),
        })
    return {
        "ok": True,
        "items": items,
        "automated_eval_runs_count": auto_eval_count,
        "automated_eval_still_required": auto_eval_count == 0,
        "policy_notice_ar": (
            "جميع السجلات في هذا الجدول مصنفة كـ «مدخلة يدوياً — غير متحقق منها» ولا تُستخدم لرفع مؤشرات دقة نماذج الذكاء الاصطناعي الآلية."
            + (" لم يُنفّذ تقييم آلي بمجموعة بيانات ميدانية بعد؛ التقييم الميداني الآلي لا يزال مطلوباً." if auto_eval_count == 0 else "")
        ),
    }


def save_field_calibration(data, who="operator"):
    """Save or update a manual field calibration record in field_calibrations without affecting automated AI metrics."""
    if not isinstance(data, dict):
        return {"ok": False, "error": "بيانات المعايرة اليدوية غير صالحة"}
    if not D.get("db") or not D.get("lock"):
        return {"ok": False, "error": "قاعدة البيانات غير متصلة"}

    cal_id = None
    if data.get("id") not in (None, ""):
        try:
            cal_id = int(data["id"])
        except (TypeError, ValueError):
            return {"ok": False, "error": "معرّف السجل غير صالح"}

    from_cam = str(data.get("from_cam") or "").strip()[:64]
    to_cam = str(data.get("to_cam") or "").strip()[:64]
    if from_cam and to_cam and from_cam == to_cam:
        return {"ok": False, "error": "لا يمكن أن تطابق الكاميرا المصدر الكاميرا الوجهة في القياس اليدوي"}

    transit_sec = 0.0
    if data.get("transit_sec") not in (None, ""):
        try:
            transit_sec = float(data["transit_sec"])
        except (TypeError, ValueError):
            return {"ok": False, "error": "زمن الانتقال اليدوي يجب أن يكون رقماً صالحاً"}
        if math.isnan(transit_sec) or math.isinf(transit_sec) or transit_sec < 0:
            return {"ok": False, "error": "زمن الانتقال اليدوي لا يجوز أن يكون سالباً"}

    samples_count = 0
    if data.get("samples_count") not in (None, ""):
        try:
            sf = float(data["samples_count"])
            if math.isnan(sf) or math.isinf(sf) or sf < 0 or not sf.is_integer():
                return {"ok": False, "error": "عدد العينات يجب أن يكون عدداً صحيحاً غير سالب"}
            samples_count = int(sf)
        except (TypeError, ValueError):
            return {"ok": False, "error": "عدد العينات يجب أن يكون عدداً صحيحاً صالحاً"}

    correct_reads = 0
    if data.get("correct_reads") not in (None, ""):
        try:
            cf = float(data["correct_reads"])
            if math.isnan(cf) or math.isinf(cf) or cf < 0 or not cf.is_integer():
                return {"ok": False, "error": "عدد القراءات الصحيحة يجب أن يكون عدداً صحيحاً غير سالب"}
            correct_reads = int(cf)
        except (TypeError, ValueError):
            return {"ok": False, "error": "عدد القراءات الصحيحة يجب أن يكون عدداً صحيحاً صالحاً"}

    incorrect_reads = 0
    if data.get("incorrect_reads") not in (None, ""):
        try:
            icf = float(data["incorrect_reads"])
            if math.isnan(icf) or math.isinf(icf) or icf < 0 or not icf.is_integer():
                return {"ok": False, "error": "عدد القراءات الخاطئة يجب أن يكون عدداً صحيحاً غير سالب"}
            incorrect_reads = int(icf)
        except (TypeError, ValueError):
            return {"ok": False, "error": "عدد القراءات الخاطئة يجب أن يكون عدداً صحيحاً صالحاً"}

    if samples_count == 0 and (correct_reads + incorrect_reads) > 0:
        samples_count = correct_reads + incorrect_reads
    if samples_count > 0 and (correct_reads + incorrect_reads) > samples_count:
        return {"ok": False, "error": "مجموع القراءات الصحيحة والخاطئة لا يجوز أن يتجاوز إجمالي عدد العينات"}

    measured_acc = None
    if data.get("measured_plate_accuracy") not in (None, ""):
        try:
            measured_acc = float(data["measured_plate_accuracy"])
        except (TypeError, ValueError):
            return {"ok": False, "error": "نسبة الدقة المقاسة يجب أن تكون رقماً صالحاً بين 0 و 100"}
        if math.isnan(measured_acc) or math.isinf(measured_acc) or measured_acc < 0.0 or measured_acc > 100.0:
            return {"ok": False, "error": "نسبة الدقة المقاسة يجب أن تكون بين 0% و 100%"}
        measured_acc = round(measured_acc, 2)
    elif (correct_reads + incorrect_reads) > 0:
        measured_acc = round((correct_reads / float(correct_reads + incorrect_reads)) * 100.0, 2)
    elif samples_count > 0 and correct_reads > 0:
        measured_acc = round((correct_reads / float(samples_count)) * 100.0, 2)

    if transit_sec <= 0 and measured_acc is None and samples_count <= 0:
        return {"ok": False, "error": "يرجى إدخال زمن انتقال موجب أو نتيجة قياس دقة لوحات (عينات/قراءات) لحفظ المعايرة اليدوية"}

    source_description = str(data.get("source_description") or "").strip()[:300]
    if not source_description:
        return {"ok": False, "error": "يرجى إدخال وصف مصدر القياس الميداني"}
    measurement_date = str(data.get("measurement_date") or "").strip()[:32] or time.strftime("%Y-%m-%d", time.localtime())
    model_used = str(data.get("model_used") or "يدوي / مراقبة ميدانية").strip()[:120]
    operator_name = str(data.get("operator_name") or who or "operator").strip()[:80]
    notes = str(data.get("notes") or "").strip()[:500]
    now_ts = time.time()

    import registry as R

    def _tx(conn):
        R.migrate_db(conn, D["lock"], db_path=D.get("db_path"))
        if cal_id is not None and cal_id > 0:
            cur = conn.execute(
                "UPDATE field_calibrations SET "
                "entry_type='manual_unverified', verification_status='manual_unverified', "
                "from_cam=?, to_cam=?, transit_sec=?, measured_plate_accuracy=?, samples_count=?, "
                "correct_reads=?, incorrect_reads=?, source_description=?, measurement_date=?, "
                "model_used=?, operator_name=?, notes=?, updated_ts=? WHERE id=?",
                (from_cam, to_cam, transit_sec, measured_acc, samples_count,
                 correct_reads, incorrect_reads, source_description, measurement_date,
                 model_used, operator_name, notes, now_ts, cal_id)
            )
            if cur.rowcount == 0:
                return None, "not_found"
            return cal_id, "updated"
        else:
            cur = conn.execute(
                "INSERT INTO field_calibrations("
                "entry_type, verification_status, from_cam, to_cam, transit_sec, measured_plate_accuracy, "
                "samples_count, correct_reads, incorrect_reads, source_description, measurement_date, "
                "model_used, operator_name, notes, created_ts, updated_ts"
                ") VALUES('manual_unverified', 'manual_unverified', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (from_cam, to_cam, transit_sec, measured_acc, samples_count,
                 correct_reads, incorrect_reads, source_description, measurement_date,
                 model_used, operator_name, notes, now_ts, now_ts)
            )
            return int(cur.lastrowid), "added"

    row_id, act = R.run_atomic_tx(D["db"], D["lock"], _tx, db_path=D.get("db_path"))
    if act == "not_found":
        return {"ok": False, "error": "سجل المعايرة اليدوية المطلوب تعديله غير موجود"}

    log_fn = R.D.get("log")
    if callable(log_fn):
        try:
            log_fn("manual field calibration saved", f"id={row_id} ({act}) status=manual_unverified by {operator_name}")
        except Exception:
            pass
    return {
        "ok": True,
        "id": row_id,
        "action": act,
        "verification_status": "manual_unverified",
        "verification_label_ar": "مدخلة يدوياً — غير متحقق منها آلياً",
        "is_verified_ai_metric": False,
    }


def delete_field_calibration(cal_id, who="operator"):
    """Delete a manual field calibration entry by ID."""
    if isinstance(cal_id, dict):
        cal_id = cal_id.get("id")
    try:
        cid = int(cal_id)
    except (TypeError, ValueError):
        return {"ok": False, "error": "معرّف السجل غير صالح"}
    if not D.get("db") or not D.get("lock"):
        return {"ok": False, "error": "قاعدة البيانات غير متصلة"}
    import registry as R

    def _del_tx(conn):
        cur = conn.execute("DELETE FROM field_calibrations WHERE id=?", (cid,))
        return cur.rowcount > 0

    deleted = R.run_atomic_tx(D["db"], D["lock"], _del_tx, db_path=D.get("db_path"))
    log_fn = R.D.get("log")
    if deleted and callable(log_fn):
        try:
            log_fn("manual field calibration deleted", f"id={cid} by {who}")
        except Exception:
            pass
    return {"ok": True, "deleted": bool(deleted), "id": cid}


def export_field_calibrations(fmt="json"):
    """Export manual field calibration records as JSON or UTF-8-BOM CSV (always tagged manual_unverified)."""
    res = list_field_calibrations()
    items = res.get("items") or []
    f_norm = str(fmt or "json").strip().lower()
    if f_norm == "csv":
        out = io.StringIO(newline="")
        w = csv.writer(out, lineterminator="\r\n")
        w.writerow([
            "id", "verification_status", "from_cam", "to_cam", "transit_sec",
            "measured_plate_accuracy", "samples_count", "correct_reads", "incorrect_reads",
            "source_description", "measurement_date", "model_used", "operator_name", "notes"
        ])
        for it in items:
            w.writerow([
                it.get("id"),
                "manual_unverified",
                _csv_safe_cell(it.get("from_cam", "")),
                _csv_safe_cell(it.get("to_cam", "")),
                it.get("transit_sec", 0),
                "" if it.get("measured_plate_accuracy") is None else it.get("measured_plate_accuracy"),
                it.get("samples_count", 0),
                it.get("correct_reads", 0),
                it.get("incorrect_reads", 0),
                _csv_safe_cell(it.get("source_description", "")),
                _csv_safe_cell(it.get("measurement_date", "")),
                _csv_safe_cell(it.get("model_used", "")),
                _csv_safe_cell(it.get("operator_name", "")),
                _csv_safe_cell(it.get("notes", "")),
            ])
        return ("\ufeff" + out.getvalue()).encode("utf-8"), "mersad_manual_calibrations.csv", "text/csv; charset=utf-8"
    payload = {
        "schema": "mersad_manual_field_calibrations_v1",
        "verification_status": "manual_unverified",
        "disclaimer_ar": "مدخلة يدوياً — غير متحقق منها آلياً (لا تُحتسب ضمن دقة نماذج الذكاء الاصطناعي)",
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "items": items,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8"), "mersad_manual_calibrations.json", "application/json; charset=utf-8"


def import_field_calibrations(raw_data, filename="", who="operator"):
    """Import manual field calibration records from JSON or CSV, strictly preserving manual_unverified status."""
    if isinstance(raw_data, bytes):
        try:
            txt = raw_data.decode("utf-8-sig")
        except UnicodeDecodeError:
            txt = raw_data.decode("cp1256", "replace")
    else:
        txt = str(raw_data or "")
    txt = txt.strip()
    if not txt:
        return {"ok": False, "error": "ملف الاستيراد فارغ"}
    fn_low = str(filename or "").strip().lower()
    items = []
    if fn_low.endswith(".csv") or (not txt.startswith("{") and not txt.startswith("[")):
        reader = csv.DictReader(io.StringIO(txt))
        for r in reader:
            if not r:
                continue
            norm_r = {str(k or "").strip().lower(): str(v or "").strip().lstrip("'") for k, v in r.items() if k is not None}
            norm_r.pop("id", None)
            if any(norm_r.values()):
                items.append(norm_r)
    else:
        try:
            parsed = json.loads(txt)
        except json.JSONDecodeError:
            return {"ok": False, "error": "صيغة ملف JSON غير صالحة"}
        if isinstance(parsed, dict):
            items = parsed.get("items") or parsed.get("calibrations") or []
        elif isinstance(parsed, list):
            items = parsed
        if not isinstance(items, list):
            return {"ok": False, "error": "بنية ملف JSON غير صالحة"}
        for it in items:
            if isinstance(it, dict):
                it.pop("id", None)

    if not items:
        return {"ok": False, "error": "لا توجد سجلات صالحة للاستيراد"}
    added = skipped = 0
    errors = []
    for idx, it in enumerate(items, 1):
        res = save_field_calibration(it, who=who)
        if res.get("ok"):
            added += 1
        else:
            skipped += 1
            errors.append(f"السطر {idx}: {res.get('error', 'بيانات غير صالحة')}")
    return {
        "ok": added > 0,
        "added": added,
        "skipped": skipped,
        "errors": errors[:15],
        "error": errors[0] if (added == 0 and errors) else "",
    }


def suggest_camera_links_from_sightings(include_demo=False, min_observations=3, apply_directly=False, who="operator"):
    """Analyze recorded multi-camera vehicle transitions in sightings and statistically derive calibrated
    (min_sec, expected_sec, max_sec, observations_count) values for each observed camera pair (STAGE14-03).
    When apply_directly=True, atomically persists all derived links into camera_links with measurement_source='computed_logs'."""
    if not D.get("db") or not D.get("lock"):
        return {"ok": False, "error": "قاعدة البيانات غير متصلة", "suggestions": []}
    import registry as R
    R.migrate_db(D["db"], D["lock"], db_path=D.get("db_path"))
    inc_demo = bool(include_demo)
    min_obs = max(1, int(min_observations or 3))
    rows = _fetch_sightings(days=90, include_demo=inc_demo)

    by_plate = {}
    for row in rows:
        rid, ts, cam, plate, vc, conf, src, direction = row[:8]
        sess = row[8] if len(row) > 8 else ""
        key = _canonical_plate(plate)
        by_plate.setdefault(key, []).append((rid, ts, cam, vc, conf, src, direction, sess, key))

    pair_dts = {}
    for key, pts in by_plate.items():
        dedup_pts = []
        for pt in pts:
            if dedup_pts and dedup_pts[-1][2] == pt[2] and (pt[1] - dedup_pts[-1][1]) < DEDUP_SAME_CAM_SEC:
                continue
            dedup_pts.append(pt)
        if len(dedup_pts) < 2:
            continue
        for i in range(1, len(dedup_pts)):
            id0, t0, c0, _, conf0, src0, _, sess0, _ = dedup_pts[i - 1]
            id1, t1, c1, vc1, conf1, src1, dir1, sess1, pl1 = dedup_pts[i]
            dt = float(t1 - t0)
            if c1 != c0 and 1.0 <= dt <= 7200.0:
                if sess0 and sess1 and sess0 == sess1 and not sess0.startswith("multi:"):
                    continue
                pair_dts.setdefault((c0, c1), []).append(dt)

    existing_links = {}
    with D["lock"]:
        for r in D["db"].execute("SELECT from_cam, to_cam, COALESCE(distance_m,0), COALESCE(via,''), COALESCE(notes,'') FROM camera_links").fetchall():
            existing_links[(str(r[0]), str(r[1]))] = {
                "distance_m": float(r[2] or 0.0),
                "via": str(r[3] or ""),
                "notes": str(r[4] or ""),
            }

    today_str = time.strftime("%Y-%m-%d", time.localtime())
    suggestions = []
    applied_links = []
    for (c0, c1), dts in sorted(pair_dts.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        obs_n = len(dts)
        if obs_n < min_obs:
            continue
        arr = np.array(dts, dtype=np.float64)
        p05 = float(np.percentile(arr, 5))
        med = float(np.median(arr))
        p95 = float(np.percentile(arr, 95))
        calc_min = round(max(1.0, min(p05 * 0.85, med * 0.85)), 1)
        calc_exp = round(max(calc_min, med), 1)
        calc_max = round(max(calc_exp, p95 * 1.15), 1)
        ex_meta = existing_links.get((c0, c1), {})
        dist_m = float(ex_meta.get("distance_m") or 0.0)
        # Ensure existing distance_m does not violate physical bounds with new calc_min
        if dist_m > 0 and ((dist_m / calc_min) * 3.6 > 260.0 or (dist_m / calc_exp) * 3.6 < 0.5):
            dist_m = 0.0
        cal_st, cal_st_ar = _compute_calibration_completeness(
            calc_min, calc_exp, calc_max, dist_m, obs_n, today_str, is_cal=True
        )
        sug = {
            "from_cam": c0,
            "to_cam": c1,
            "min_sec": calc_min,
            "expected_sec": calc_exp,
            "max_sec": calc_max,
            "distance_m": dist_m,
            "observations_count": obs_n,
            "calibration_date": today_str,
            "traffic_condition": "normal",
            "measurement_source": "computed_logs",
            "measurement_source_ar": MEASUREMENT_SOURCES["computed_logs"],
            "via": ex_meta.get("via", ""),
            "notes": ex_meta.get("notes") or f"معايرة محسوبة تلقائياً من {obs_n} انتقال مرصود",
            "calibration_status": cal_st,
            "calibration_status_ar": cal_st_ar,
        }
        suggestions.append(sug)
        if apply_directly:
            sv_res = save_camera_link({**sug, "mode": "upsert"}, who=who)
            if sv_res.get("ok"):
                applied_links.append(sv_res["link"])

    return {
        "ok": True,
        "includes_demo": inc_demo,
        "min_observations": min_obs,
        "suggestions_count": len(suggestions),
        "applied_count": len(applied_links),
        "suggestions": suggestions,
        "applied_links": applied_links,
    }
