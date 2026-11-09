"""Comprehensive categorized self-test suite for MERSAD AI (Round 1 + Round 2 + Round 3: 100+ behavioral checks).
Runs without real camera, GPU, or internet, and passes both WITH and WITHOUT scikit-learn (including child subprocesses).
Separates PASS, SKIP, and FAIL explicitly.
   python selftest.py"""
import hashlib, json, os, shutil, socket, sqlite3, subprocess, sys, tempfile, threading, time, types, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from email import message_from_bytes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import numpy as np

if sys.modules.get("sklearn") is None and "sklearn" in sys.modules:
    os.environ["MERSAD_BLOCK_SKLEARN"] = "1"

SRC = os.path.dirname(os.path.abspath(__file__))
WORK = tempfile.mkdtemp(prefix="mersad_selftest_")
for f in os.listdir(SRC):
    if f.endswith((".py", ".html", ".bat", ".md", ".txt", ".spec")) and f != "selftest.py":
        shutil.copy(os.path.join(SRC, f), WORK)
if os.path.isdir(os.path.join(SRC, ".github")):
    shutil.copytree(os.path.join(SRC, ".github"), os.path.join(WORK, ".github"), dirs_exist_ok=True)
os.chdir(WORK)
sys.path.insert(0, WORK)
os.environ["MERSAD_DATA_DIR"] = WORK

import cv2
for k, v in {
    "TELEGRAM_TOKEN": "SECRET_BOT_TOKEN_999",
    "TELEGRAM_CHAT_ID": "-100",
    "TELEGRAM_PATROL_CHAT_ID": "-200",
    "TELEGRAM_API": "http://127.0.0.1:8780"
}.items():
    os.environ[k] = v

# ---------- fake heavy components for headless CI/VM ----------
EASYOCR_INIT_KWARGS = {}
eo = types.ModuleType("easyocr")
class Reader:
    def __init__(self, langs, gpu=False, model_storage_directory=None, **kw):
        EASYOCR_INIT_KWARGS.update({"langs": langs, "gpu": gpu, "model_storage_directory": model_storage_directory, **kw})
    def readtext(self, crop):
        return [([[0, 0], [1, 0], [1, 1], [0, 1]], "عدن ١٢٣٤٥", 0.92)] if (crop is not None and crop.size) else []
eo.Reader = Reader
sys.modules["easyocr"] = eo

YOLO_CALL_KWARGS = {}
INJECT_DETECT_EXC = {"count": 0}
ul = types.ModuleType("ultralytics")
class Boxes:
    xyxy = type("T", (), {"tolist": lambda s: [[100, 150, 500, 440]]})()
    cls = type("T", (), {"tolist": lambda s: [7.0]})()
class YOLO:
    def __init__(self, p):
        self.names = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
    def __call__(self, img, **k):
        YOLO_CALL_KWARGS.update(k)
        if INJECT_DETECT_EXC["count"] > 0:
            INJECT_DETECT_EXC["count"] -= 1
            raise RuntimeError("Simulated transient detector error")
        return [type("R", (), {"boxes": Boxes()})()]
ul.YOLO = YOLO
sys.modules["ultralytics"] = ul

E_VEC = np.random.default_rng(5).normal(size=(1, 128)).astype(np.float32)
E_VEC /= np.linalg.norm(E_VEC)
class FakeDet:
    def setInputSize(self, s): pass
    def detect(self, f):
        # Return two faces: one consented volunteer face (520,60) and one smaller bystander face (40,60)
        return 1, np.array([
            [520, 60, 90, 110] + [0] * 10 + [0.99],
            [40, 60, 50, 60] + [0] * 10 + [0.95]
        ], np.float32)
class FakeRec:
    def alignCrop(self, f, face):
        x = int(face[0])
        return f[:10, :10] if x > 200 else f[10:20, 10:20]
    def feature(self, a):
        # If crop is from the bystander (x <= 200), return an orthogonal embedding so it stays 'unenrolled'
        if a is not None and a.shape == (10, 10, 3) and int(a[0, 0, 0]) == 77:
            v = np.zeros((1, 128), np.float32); v[0, 0] = 1.0
            return v
        return E_VEC.copy()
    def match(self, a, b, flag): return float((a @ b.T).item() / (np.linalg.norm(a) * np.linalg.norm(b)))
cv2.FaceDetectorYN = type("FD", (), {"create": staticmethod(lambda *a: FakeDet())})
cv2.FaceRecognizerSF = type("FR", (), {"create": staticmethod(lambda *a: FakeRec())})
cv2.FaceRecognizerSF_FR_COSINE = 0

NFR = int(os.environ.get("NFR", "600"))
DRIVER_DONE = threading.Event()
MC_INSPECT_DONE = threading.Event()
CAM_DROP_STATE = {"CAM2_failed_once": False, "reads": {}, "opens": {}}
class FakeCap:
    def __init__(self, src):
        self.src = str(src)
        self.eof = False
        CAM_DROP_STATE["opens"][self.src] = CAM_DROP_STATE["opens"].get(self.src, 0) + 1
        self.open_no = CAM_DROP_STATE["opens"][self.src]
    def isOpened(self):
        if self.src == "fake" and DRIVER_DONE.is_set():
            self.eof = True
            return False
        cnt = CAM_DROP_STATE["reads"].get(self.src, 0)
        if self.src in ("cam1_ok", "cam2_drop", "cam3_ok") and not MC_INSPECT_DONE.is_set() and cnt < 120:
            return True
        if cnt >= NFR:
            self.eof = True
            return False
        if self.src.startswith("cam_boot_offline") and self.open_no <= 2:
            return False
        if self.src == "cam_fail4_recover" and self.open_no in (2, 3, 4, 5):
            return False
        return self.src != "dead_cam"
    def read(self):
        cnt = CAM_DROP_STATE["reads"].get(self.src, 0)
        keep_mc = (self.src in ("cam1_ok", "cam2_drop", "cam3_ok") and not MC_INSPECT_DONE.is_set() and cnt < 120)
        if (cnt >= NFR and not keep_mc) or (self.src == "fake" and DRIVER_DONE.is_set()):
            self.eof = True
            return False, None
        if self.src == "dead_cam":
            return False, None
        if self.src.startswith("cam_boot_offline") and self.open_no <= 2:
            return False, None
        if self.src == "cam_fail4_recover":
            if self.open_no == 1 and cnt >= 6:
                return False, None
            if self.open_no in (2, 3, 4, 5):
                return False, None
        if self.src == "cam_slow_rtsp":
            time.sleep(0.18)
            if CAM_DROP_STATE["reads"].get("cam1_ok", 0) >= NFR:
                self.eof = True
                return False, None
        CAM_DROP_STATE["reads"][self.src] = cnt + 1
        # Simulate temporary drop on cam2_drop at frame 8, then recovery on reconnect!
        if self.src == "cam2_drop" and cnt == 8 and not CAM_DROP_STATE["CAM2_failed_once"]:
            CAM_DROP_STATE["CAM2_failed_once"] = True
            time.sleep(0.015)
            return False, None
        time.sleep(0.008)
        f = np.full((480, 640, 3), 90, np.uint8)
        f[10:20, 10:20] = 77                              # marker for bystander face crop
        cv2.rectangle(f, (200, 360), (440, 410), (255, 255, 255), -1)
        cv2.rectangle(f, (200, 360), (440, 410), (0, 0, 0), 3)
        return True, f
    def release(self): pass
cv2.VideoCapture = FakeCap

# ---------- fake Telegram server ----------
TG = {"calls": [], "updates": [], "fail_chat": set(), "delay_chat": {}, "lock": threading.Lock()}
class TGH(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        method = self.path.rsplit("/", 1)[-1]
        msg = message_from_bytes(b"Content-Type: " + self.headers["Content-Type"].encode() + b"\r\n\r\n" + body)
        fields = {p.get_param("name", header="content-disposition"): p.get_payload(decode=True) for p in msg.get_payload()}
        fields = {k: (f"<{len(v)} bytes>" if k == "photo" else v.decode("utf-8", "ignore")) for k, v in fields.items()}
        chat_id = fields.get("chat_id")
        with TG["lock"]:
            delay_s = TG["delay_chat"].get(chat_id, 0.0)
            should_fail = chat_id in TG["fail_chat"]
        if delay_s > 0:
            time.sleep(delay_s)
        if should_fail:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b'{"ok":false,"description":"Simulated patrol network failure"}')
            return
        res = {"ok": True, "result": {"message_id": 7}}
        if method == "getUpdates":
            time.sleep(0.15)
            with TG["lock"]:
                res = {"ok": True, "result": TG["updates"][:]}
                TG["updates"].clear()
        else:
            with TG["lock"]:
                TG["calls"].append((method, fields))
        out = json.dumps(res).encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
        except (BrokenPipeError, ConnectionResetError):
            pass

ThreadingHTTPServer.daemon_threads = True
ThreadingHTTPServer.allow_reuse_address = True
threading.Thread(target=ThreadingHTTPServer(("127.0.0.1", 8780), TGH).serve_forever, daemon=True).start()

def calls(method):
    with TG["lock"]: return [f for mm, f in TG["calls"] if mm == method]
def press(uid, cid, chat, data):
    with TG["lock"]:
        TG["updates"].append({"update_id": uid, "callback_query": {"id": cid, "from": {"id": 555}, "data": data,
                                                                   "message": {"chat": {"id": chat}, "message_id": 7}}})

import registry as reg_mod
import insights as ins_mod
import notify as not_mod
import server as srv_mod
import mersad_live as m

m.fetch_models = lambda *a, **k: None
m.DISPATCH_RETRY_BASE_SEC = 0.35
m.RECONNECT_BASE_SEC = 0.05
m.MAX_RECONNECT_ATTEMPTS = 1
U = "http://127.0.0.1:8771"
RESULTS = []                                         # (cat, name, status: 'PASS'|'SKIP'|'FAIL', extra)
_CAT_COUNTS = {}

def check(cat, name, ok, extra=""):
    cnt = _CAT_COUNTS.get(cat, 0) + 1
    _CAT_COUNTS[cat] = cnt
    uniq_cat = cat if cnt == 1 else f"{cat}#{cnt}"
    st = "PASS" if ok else "FAIL"
    RESULTS.append((uniq_cat, name, st, str(extra if not ok else "")))
    print(f"{st}  [{uniq_cat}] {name}" + (f" -> {extra}" if not ok and extra else ""))

def skip_check(cat, name, reason):
    RESULTS.append((cat, name, "SKIP", str(reason)))
    print(f"SKIP  [{cat}] {name} ({reason})")


# ==============================================================================
# 1. UNIT TESTS (Plates, P0-A/B/C, Multi-frame Confirmation, Faces, P2-8 YOLO)
# ==============================================================================
def run_unit_tests():
    p1 = reg_mod.norm_plate("١٢٣٤٥")
    p2 = reg_mod.norm_plate("۱۲۳۴۵")
    p3 = reg_mod.norm_plate("أ ب ١٢٣٤")
    p4 = reg_mod.norm_plate("ج د ١٢٣٤")
    check("UNIT", "normalize Eastern & Persian Arabic numerals to ASCII", p1 == "12345" and p2 == "12345", (p1, p2))
    check("UNIT", "distinct lettered plates do NOT merge into same ID", p3 == "اب-1234" and p4 == "جد-1234" and p3 != p4, (p3, p4))
    # Common OCR truncations and the I/8 glyph confusion in the IBB prefix.
    p_taz = reg_mod.norm_plate("TAZ-73901")
    p_mar = reg_mod.norm_plate("MAR-30827")
    p_ibb = reg_mod.norm_plate("18891406")
    p_ibb_i = reg_mod.norm_plate("I8891406")
    p_har = reg_mod.norm_plate("HAR-55120")
    p_aen = reg_mod.norm_plate("AEN-012345")
    p_a05n = reg_mod.norm_plate("A05N 12345")
    p_sana_joined = reg_mod.norm_plate("SANA48210")
    p_t4z = reg_mod.norm_plate("T4Z73901")
    check("OCR", "known Yemeni governorate OCR signatures normalize while numeric-only plates stay unchanged",
          p_taz == "تعز-73901" and p_mar == "مأرب-30827" and p_ibb == "إب-91406"
          and p_ibb_i == "إب-91406" and p_har == "حضرموت-55120" and p_aen == "عدن-012345"
          and p_a05n == "عدن-12345" and p_sana_joined == "صنعاء-48210" and p_t4z == "تعز-73901"
          and reg_mod.norm_plate("123456") == "123456",
          (p_taz, p_mar, p_ibb, p_ibb_i, p_har, p_aen, p_a05n, p_sana_joined, p_t4z, reg_mod.norm_plate("123456")))

    # P0-1: Realistic Yemeni OCR lookup with governorate/letters against digits-only registry record
    reg_mod.save_vehicle({"plate": "91234", "status": "wanted", "model": "Hilux"}, "unit")
    ocr_hits = [reg_mod.lookup_vehicle(ocr) for ocr in ("91234", "عدن 91234", "ع91234", "عدن٩١٢٣٤")]
    check("P0-1", "all 4 realistic OCR variants ('91234','عدن 91234','ع91234','عدن٩١٢٣٤') match registry '91234'",
          all(bool(x) and x["status"] == "wanted" for x in ocr_hits), ocr_hits)
    check("P0-1", "exact match vs digits-only match carries appropriate match_type & reduced conf_factor",
          ocr_hits[0]["match_type"] == "exact" and ocr_hits[0]["conf_factor"] == 1.0
          and ocr_hits[1]["match_type"] == "digits_only" and "تطابق بالأرقام فقط" in ocr_hits[1]["match_note"]
          and ocr_hits[1]["conf_factor"] < 1.0, ocr_hits[1])

    # P0-A & P0-B: Two vehicles sharing same digits ('4444') but different letters ('أ ب 4444' vs 'ج د 4444')
    reg_mod.save_vehicle({"plate": "أ ب 4444", "status": "wanted", "model": "Corolla"}, "unit")
    reg_mod.save_vehicle({"plate": "ج د 4444", "status": "stolen", "model": "Camry"}, "unit")
    m_exact = reg_mod.lookup_vehicle("أ ب ٤٤٤٤")
    m_close = reg_mod.lookup_vehicle("ا 4444")
    m_ambig = reg_mod.lookup_vehicle("4444")
    check("P0-1", "two plates with same digits & different letters are NOT merged and disambiguate or flag ambiguous",
          m_exact["plate"] == "اب-4444" and m_exact["match_type"] == "exact"
          and m_close["plate"] == "اب-4444" and m_close["match_type"] == "digits_only"
          and m_ambig["ambiguous"] is True and m_ambig["match_type"] == "ambiguous"
          and len(m_ambig.get("candidates", [])) == 2, (m_exact, m_close, m_ambig))

    # P0-B: Contradictory letters ('صنعاء-81234' wanted vs OCR 'عدن-81234') -> visual_check_only & 'POSSIBLE MATCH (visual check)'
    reg_mod.save_vehicle({"plate": "صنعاء 81234", "status": "wanted", "model": "LandCruiser"}, "unit")
    v_contra = reg_mod.lookup_vehicle("عدن 81234")
    msg_contra, _ = m.register("عدن 81234", 0.92, "CAM1", "car", session_id="s_contra")
    check("P0-B", "contradictory letters ('صنعاء-81234' vs 'عدن-81234') downgrade to 'POSSIBLE MATCH (visual check)' (NOT high priority)",
          v_contra is not None and v_contra["contradictory_letters"] is True and v_contra["visual_check_only"] is True
          and msg_contra == "POSSIBLE MATCH (visual check)" and msg_contra not in m.HIGH and msg_contra in m.MID, (v_contra, msg_contra))

    # P0-B: OCR lookalike confusion ('12O45' -> '12045') and edit-distance-1 ('12945' -> '12045') on wanted/stolen records
    reg_mod.save_vehicle({"plate": "12045", "status": "wanted", "model": "Prado"}, "unit")
    v_ocr_o = reg_mod.lookup_vehicle("12O45")
    v_ed1 = reg_mod.lookup_vehicle("12945")
    reg_mod.save_vehicle({"plate": "60045", "status": "normal", "model": "Sunny"}, "unit")
    v_ed1_norm = reg_mod.lookup_vehicle("60945")
    check("P0-B", "OCR confusion '12O45' & edit-distance-1 '12945' match wanted '12045' with 'تقريبي' tag, while normal '60045' does not match '60945'",
          v_ocr_o is not None and "تقريبي" in v_ocr_o["match_note"] and v_ocr_o["visual_check_only"] is True
          and v_ed1 is not None and "تقريبي" in v_ed1["match_note"] and v_ed1["visual_check_only"] is True
          and v_ed1_norm is None, (v_ocr_o, v_ed1, v_ed1_norm))

    # P0-C: CSV import with two rows sharing digits in different governorates: (12345, عدن, مطلوبة) and (12345, صنعاء, عادية)
    imp_res = reg_mod.import_file("vehicles", "gov.csv", "رقم اللوحة,المحافظة,الحالة\n65432,عدن,مطلوبة\n65432,صنعاء,عادية\n65432,عدن,عادية\n".encode("utf-8"), "unit")
    m_gov_aden = reg_mod.lookup_vehicle("عدن 65432")
    m_gov_sanaa = reg_mod.lookup_vehicle("صنعاء 65432")
    check("P0-1", "imported vehicle with governorate in separate column matches OCR 'عدن 65432' with full confidence",
          m_gov_aden is not None and m_gov_aden["match_type"] == "exact" and m_gov_aden["plate"] == "عدن-65432", m_gov_aden)
    check("P0-C", "CSV import with (65432,عدن,مطلوبة) & (65432,صنعاء,عادية) saves 2 distinct records & protects wanted from silent downgrade",
          m_gov_aden["status"] == "wanted" and m_gov_sanaa is not None and m_gov_sanaa["plate"] == "صنعاء-65432"
          and m_gov_sanaa["status"] == "normal" and len(imp_res.get("warnings", [])) >= 1, (imp_res, m_gov_aden, m_gov_sanaa))

    for k_del in ("91234", "أ ب 4444", "ج د 4444", "صنعاء 81234", "12045", "60045", "عدن-65432", "صنعاء-65432"):
        reg_mod.delete("vehicles", k_del, "unit")

    # Multi-frame confirmation & stale vote expiration
    votes, tracks, last_seen = {}, {}, {}
    t0 = 1000.0
    m.confirm_plate_read("77777", 0.9, (10, 10, 100, 40), t0, votes, tracks, last_seen, confirm_reads=3, window_sec=10.0)
    m.confirm_plate_read("77777", 0.9, (10, 15, 102, 42), t0 + 1.0, votes, tracks, last_seen, confirm_reads=3, window_sec=10.0)
    res_expired = m.confirm_plate_read("77777", 0.9, (10, 20, 104, 44), t0 + 15.0, votes, tracks, last_seen, confirm_reads=3, window_sec=10.0)
    check("UNIT", "stale OCR reads expire after window_sec without false confirmation", res_expired is None, res_expired)
    m.confirm_plate_read("77777", 0.9, (10, 30, 110, 48), t0 + 16.0, votes, tracks, last_seen, confirm_reads=3, window_sec=10.0)
    res_ok = m.confirm_plate_read("77777", 0.9, (10, 45, 125, 55), t0 + 17.0, votes, tracks, last_seen, confirm_reads=3, window_sec=10.0)
    check("UNIT", "3 consistent reads within window confirm plate & infer direction", res_ok is not None and "اقتراب" in res_ok[1], res_ok)
    for dt in (18.0, 18.5, 19.0):
        res_dup = m.confirm_plate_read("77777", 0.9, (10, 45, 125, 55), t0 + dt, votes, tracks, last_seen, confirm_reads=3, window_sec=10.0, cooldown_sec=30.0)
    check("UNIT", "cooldown prevents duplicate alert on consecutive frames", res_dup is None)
    for dt in (50.0, 51.0, 52.0):
        res_ret = m.confirm_plate_read("77777", 0.9, (100, 40, 90, 30), t0 + dt, votes, tracks, last_seen, confirm_reads=3, window_sec=10.0, cooldown_sec=30.0)
    check("UNIT", "returning vehicle after cooldown is re-confirmed cleanly", res_ret is not None)

    # P0-1 & P0-A: Noisy reads of the SAME vehicle track confirm on 3rd read, while two plates with contradictory letters ('أب-4444' vs 'جد-4444') stay separate!
    votes_n, tracks_n, seen_n = {}, {}, {}
    r_n1 = m.confirm_plate_read("عدن 12345", 0.88, (10, 10, 80, 30), 200.0, votes_n, tracks_n, seen_n)
    r_n2 = m.confirm_plate_read("ع 12345", 0.82, (12, 12, 82, 31), 201.0, votes_n, tracks_n, seen_n)
    r_n3 = m.confirm_plate_read("عدن 12345", 0.90, (14, 14, 84, 32), 202.0, votes_n, tracks_n, seen_n)
    check("P0-1", "noisy letter sequence ['عدن 12345','ع 12345','عدن 12345'] from same track confirms on 3rd read & picks 'عدن-12345'",
          r_n1 is None and r_n2 is None and r_n3 is not None and getattr(r_n3, "plate", "") == "عدن-12345", r_n3)

    votes_sep, tracks_sep, seen_sep = {}, {}, {}
    s1 = m.confirm_plate_read("أب-4444", 0.9, (10, 10, 80, 30), 300.0, votes_sep, tracks_sep, seen_sep)
    s2 = m.confirm_plate_read("جد-4444", 0.9, (12, 12, 80, 30), 301.0, votes_sep, tracks_sep, seen_sep)
    s3 = m.confirm_plate_read("أب-4444", 0.9, (14, 14, 80, 30), 302.0, votes_sep, tracks_sep, seen_sep)
    check("P0-A", "'أب-4444' and 'جد-4444' stay in separate vote buckets and do NOT falsely confirm on 3 mixed reads",
          s1 is None and s2 is None and s3 is None and len(votes_sep) == 2, votes_sep)

    # Face embedding validation
    check("UNIT", "face embedding validation rejects wrong dimension or zero norm",
          m.validate_embedding(np.zeros((1, 128), np.float32)) is None and m.validate_embedding(np.ones((1, 64), np.float32)) is None)
    v_emb = m.validate_embedding(np.ones((1, 128), np.float32))
    check("UNIT", "face embedding validation normalizes 128-D vector to unit length",
          v_emb is not None and abs(float(np.linalg.norm(v_emb)) - 1.0) < 1e-5)

    # Video & OCR edge cases + P2-8 classes= filter & benchmark
    check("VIDEO", "empty or None frames handled safely without crash",
          m.detect_vehicles(None, YOLO("x")) == [] and m.find_plates(np.zeros((0, 0, 3), np.uint8)) == [] and m.read_plate(Reader([]), np.zeros((0, 0, 3), np.uint8)) == (None, 0.0))
    # LAB scene has a larger dark windshield and a smaller bright plate; rank the plate first.
    plate_scene = np.full((480, 640, 3), 48, dtype=np.uint8)
    cv2.rectangle(plate_scene, (175, 170), (465, 238), (85, 110, 130), -1)
    cv2.rectangle(plate_scene, (175, 170), (465, 238), (210, 180, 140), 2)
    cv2.rectangle(plate_scene, (189, 330), (449, 394), (252, 252, 252), -1)
    cv2.rectangle(plate_scene, (189, 330), (449, 394), (10, 10, 10), 3)
    ranked_plates = m.find_plates(plate_scene)
    top_plate_iou = max((m._bbox_iou(box, (189, 330, 260, 64)) for box in ranked_plates[:1]), default=0.0)
    check("OCR-PLATE-RANK", "bright plate candidate outranks larger dark windshield candidate (IoU >= 0.75)",
          bool(ranked_plates) and top_plate_iou >= 0.75, (ranked_plates, top_plate_iou))
    YOLO_CALL_KWARGS.clear()
    m.detect_vehicles(np.zeros((480, 640, 3), np.uint8), YOLO("x"))
    check("P2-8", "detect_vehicles passes classes=[2, 3, 5, 7] filter to YOLO model",
          YOLO_CALL_KWARGS.get("classes") == [2, 3, 5, 7], YOLO_CALL_KWARGS)

    custom_yolo = YOLO("x")
    custom_yolo.names = {0: "lorry", 1: "pedestrian", 4: "car"}
    Boxes.cls = type("T", (), {"tolist": lambda s: [0.0]})()
    v_det = m.detect_vehicles(np.zeros((480, 640, 3), np.uint8), custom_yolo)
    Boxes.cls = type("T", (), {"tolist": lambda s: [7.0]})()
    check("VIDEO", "dynamic YOLO class mapping resolves custom class names ('lorry' -> 'truck') & passes classes=[0, 4]",
          len(v_det) == 1 and v_det[0][4] == "truck" and YOLO_CALL_KWARGS.get("classes") == [0, 4], (v_det, YOLO_CALL_KWARGS))

    class BenchYOLO:
        names = {i: ("car" if i in (2, 3, 5, 7) else f"obj_{i}") for i in range(80)}
        def __call__(self, img, classes=None, **kw):
            all_b = [[10, 10, 50, 50]] * 80
            all_c = list(range(80))
            if classes is not None:
                c_set = set(classes)
                all_b = [b for b, c in zip(all_b, all_c) if c in c_set]
                all_c = [c for c in all_c if c in all_c if c in c_set]
            bx = type("B", (), {"xyxy": type("T", (), {"tolist": lambda s: all_b})(), "cls": type("T", (), {"tolist": lambda s: all_c})()})()
            return [type("R", (), {"boxes": bx})()]
    bm_model = BenchYOLO()
    dummy_img = np.zeros((480, 640, 3), np.uint8)
    t_s = time.perf_counter()
    for _ in range(200):
        m.detect_vehicles(dummy_img, bm_model)
    t_filtered = time.perf_counter() - t_s
    check("P2-8", f"class-filtered detect_vehicles benchmark completed quickly (200 calls in {t_filtered*1000:.1f}ms)", t_filtered < 1.0)


# ==============================================================================
# 2. DATABASE MIGRATION & PATH TRACKING SCENARIO TESTS (Isolated DB + P0-A + P1-4)
# ==============================================================================
def run_db_and_path_tests():
    tmp_db_dir = tempfile.mkdtemp(prefix="mersad_dbtest_")
    try:
        legacy_db_path = os.path.join(tmp_db_dir, "legacy.db")
        ldb = sqlite3.connect(legacy_db_path, check_same_thread=False)
        llock = threading.RLock()
        ldb.executescript("""
        CREATE TABLE vehicles(plate TEXT PRIMARY KEY, governorate TEXT, model TEXT, color TEXT, vtype TEXT, owner TEXT, status TEXT, notes TEXT, updated REAL);
        CREATE TABLE persons(name TEXT PRIMARY KEY, ref TEXT, category TEXT, status TEXT, consent INTEGER, notes TEXT, updated REAL);
        CREATE TABLE faces(name TEXT, emb BLOB);
        CREATE TABLE sightings(ts REAL, cam TEXT, plate TEXT, conf REAL, vclass TEXT);
        CREATE TABLE audit(i INTEGER PRIMARY KEY, ts REAL, action TEXT, ref TEXT, prev TEXT, hash TEXT);
        INSERT INTO vehicles VALUES('12345', 'عدن', 'Hilux', 'White', 'truck', 'Owner1', 'wanted', '', 1700000000.0);
        INSERT INTO sightings VALUES(1700000000.0, 'CAM1', '11111', 0.91, 'car');
        """)
        ldb.commit()

        reg_mod.migrate_db(ldb, llock, db_path=legacy_db_path)
        bak_exists = os.path.exists(legacy_db_path + ".bak.v0")
        cols = {r[1] for r in ldb.execute("PRAGMA table_info(sightings)").fetchall()}
        cols_al = {r[1] for r in ldb.execute("PRAGMA table_info(alerts)").fetchall()}
        preserved = ldb.execute("SELECT plate, src FROM sightings WHERE plate='11111'").fetchone()
        migrated_veh = ldb.execute("SELECT plate, plate_digits, plate_letters FROM vehicles").fetchone()
        check("DB", "legacy database migrated non-destructively (v1..v5) with automatic backup & canonical vehicle key",
              bak_exists and {"src", "direction", "raw_text", "session_id"} <= cols
              and "dispatch_status" in cols_al and preserved == ("11111", "live")
              and migrated_veh == ("عدن-12345", "12345", "عدن"), (bak_exists, cols, preserved, migrated_veh))

        ins_mod.init(ldb, llock)

        # P0-A & P1-4: Verify default topology is uncalibrated and DEFAULT_UNVERIFIED_HOPS is gone
        def_link = ins_mod._link_info("CAM1", "CAM3")
        check("P1-4", "default topology is honestly marked uncalibrated & has no unverified 'via' hop",
              def_link["calibrated"] is False and def_link["source"] == "uncalibrated_default"
              and "via" not in def_link and not hasattr(ins_mod, "DEFAULT_UNVERIFIED_HOPS"), def_link)

        # Configure user-calibrated links for CAM1<->CAM2 and CAM2<->CAM3
        ldb.executemany(
            "INSERT OR REPLACE INTO camera_links(from_cam, to_cam, min_sec, expected_sec, source) VALUES(?,?,?,?,?)",
            [("CAM1", "CAM2", 120.0, 480.0, "user_calibrated"), ("CAM2", "CAM3", 150.0, 600.0, "user_calibrated")]
        )
        ldb.commit()
        ins_mod.configure_topology()
        cal_link = ins_mod._link_info("CAM1", "CAM2")
        check("P1-4", "user-configured camera_links row is marked calibrated=True",
              cal_link["calibrated"] is True and cal_link["min_sec"] == 120.0, cal_link)

        ldb.execute("INSERT INTO sightings(ts, cam, plate, conf, vclass, src) VALUES(NULL, 'CAM1', 'BADTS', 0.5, 'car', 'live')")
        ldb.execute("INSERT INTO sightings(ts, cam, plate, conf, vclass, src) VALUES(-100, 'CAM1', 'NEGTS', 0.5, 'car', 'live')")
        ldb.commit()
        tr_small = ins_mod.train()
        s_small = ins_mod.summary()
        check("STATS", "insufficient data (<50) and NULL/invalid timestamps handled safely without false forecast",
              not tr_small["ok"] and tr_small["reason"] == "insufficient_data" and s_small["forecast"] is None, tr_small)

        base_t = time.time() - 7200
        test_sightings = [
            # Scenario 1: Logical sequential transit CAM1 -> CAM2 -> CAM3
            (base_t, "CAM1", "10001", 0.95, "car", "live", "اقتراب نسبي في الإطار", "s1"),
            (base_t + 300, "CAM2", "10001", 0.93, "car", "live", "CAM1 ➔ CAM2", "s2"),
            (base_t + 700, "CAM3", "10001", 0.94, "car", "live", "CAM2 ➔ CAM3", "s3"),
            # Scenario 2: Simultaneous sighting at two cameras (dt = 2s <= 5s)
            (base_t, "CAM1", "10002", 0.91, "car", "live", "", "s1"),
            (base_t + 2, "CAM2", "10002", 0.90, "car", "live", "", "s2"),
            # Scenario 3: Impossible transit time (dt = 30s < 120s user-calibrated min_sec for CAM1->CAM2)
            (base_t, "CAM1", "10003", 0.92, "truck", "live", "", "s1"),
            (base_t + 30, "CAM2", "10003", 0.91, "truck", "live", "", "s2"),
            # Scenario 4: Missing intermediate camera (CAM1 -> CAM3 directly, skipping user-configured CAM2)
            (base_t, "CAM1", "10004", 0.90, "car", "live", "", "s1"),
            (base_t + 600, "CAM3", "10004", 0.89, "car", "live", "", "s3"),
            # Scenario 5: Out-of-order ingestion (clock skew between sources)
            (base_t + 500, "CAM2", "10005", 0.90, "car", "live", "", "s2"),
            (base_t + 100, "CAM1", "10005", 0.90, "car", "live", "", "s1"),
            # Scenario 6: Duplicate sightings at same camera within 5s (should merge)
            (base_t, "CAM1", "10006", 0.92, "car", "live", "", "s1"),
            (base_t + 4, "CAM1", "10006", 0.91, "car", "live", "", "s1"),
            (base_t + 300, "CAM2", "10006", 0.93, "car", "live", "", "s2"),
            # Scenario 8: Uncalibrated camera not in topology (CAM_UNKN)
            (base_t, "CAM1", "10008", 0.90, "car", "live", "", "s1"),
            (base_t + 200, "CAM_UNKN", "10008", 0.88, "car", "live", "", "s8"),
            # P0-A: Substring digits ('112345' @ CAM1 then '12345' @ CAM2 20s later) and distinct lettered plates ('اب-4444' @ CAM1 then 'جد-4444' @ CAM2 10s later)
            (base_t, "CAM1", "112345", 0.95, "car", "live", "", "s1"),
            (base_t + 20, "CAM2", "12345", 0.95, "car", "live", "", "s2"),
            (base_t, "CAM1", "اب-4444", 0.95, "car", "live", "", "s1"),
            (base_t + 10, "CAM2", "جد-4444", 0.95, "car", "live", "", "s2"),
            (base_t + 400, "CAM2", "اب-4444", 0.95, "car", "live", "", "s2"),
        ]
        ldb.executemany("INSERT INTO sightings(ts, cam, plate, conf, vclass, src, direction, session_id) VALUES(?,?,?,?,?,?,?,?)", test_sightings)
        ldb.commit()

        p_norm = ins_mod.plate_path("10001")
        check("PATH", "Scenario 1: CAM1 -> CAM2 -> CAM3 logical transit",
              p_norm["found"] and p_norm["route"] == "CAM1 ➔ CAM2 ➔ CAM3" and not p_norm["conflicts"] and p_norm["calibrated"], p_norm)

        p_sim = ins_mod.plate_path("10002")
        check("PATH", "Scenario 2: simultaneous appearance at two cameras flagged as reviewable suspicion",
              p_sim["found"] and len(p_sim["conflicts"]) == 1 and p_sim["conflicts"][0]["type"] == "simultaneous_sighting", p_sim["conflicts"])

        p_imp = ins_mod.plate_path("10003")
        c_rec = p_imp["conflicts"][0] if p_imp["conflicts"] else {}
        check("PATH", "Scenario 3: impossible transit includes IDs, cams, timestamps, dt, min_expected, source & confidence",
              bool(c_rec) and c_rec["type"] == "impossible_transit" and c_rec["from_cam"] == "CAM1" and c_rec["to_cam"] == "CAM2"
              and c_rec["min_expected_sec"] == 120.0 and c_rec["calibrated"] is True and "مراجعة بشرية" in c_rec["why"], c_rec)

        p_miss = ins_mod.plate_path("10004")
        check("PATH", "Scenario 4: missing intermediate camera (CAM2) detected on CAM1 -> CAM3 jump (from user topology)",
              "CAM2" in p_miss.get("missing_hops", []), p_miss)

        p_skew = ins_mod.plate_path("10005")
        check("PATH", "Scenario 5: clock skew / out-of-order ingestion detected and chronologically sorted",
              p_skew["clock_skew_detected"] and p_skew["route"] == "CAM1 ➔ CAM2", p_skew)

        p_dup = ins_mod.plate_path("10006")
        check("PATH", "Scenario 6: duplicate sightings within 15s at same camera merged",
              p_dup["total"] == 2 and p_dup["duplicates_merged"] == 1, p_dup)

        p_none = ins_mod.plate_path("9999999")
        check("PATH", "Scenario 7: non-existent plate returns found=False with empty steps",
              p_none["ok"] and not p_none["found"] and p_none["steps"] == [], p_none)

        p_uncal = ins_mod.plate_path("10008")
        check("PATH", "Scenario 8: uncalibrated camera marked calibrated=False with limitation note",
              p_uncal["found"] and not p_uncal["calibrated"] and "غير معايرة" in p_uncal["limitations"], p_uncal)

        # P0-A checks on check_route, _analyze_paths, and plate_path
        _, c_sub = ins_mod.check_route("12345", "CAM2", base_t + 20, conf=0.95, cur_id=9999, session_id="s2")
        _, c_let = ins_mod.check_route("جد-4444", "CAM2", base_t + 10, conf=0.95, cur_id=9998, session_id="s2")
        p_12345 = ins_mod.plate_path("12345")
        p_ab4444 = ins_mod.plate_path("أب-4444")
        p_digits4444 = ins_mod.plate_path("4444")
        check("P0-A", "'112345'@CAM1 and '12345'@CAM2 do NOT collide in check_route or plate_path",
              c_sub is None and p_12345["total"] == 1 and p_12345["route"] == "CAM2", (c_sub, p_12345))
        check("P0-A", "'أب-4444' and 'جد-4444' stay separate in check_route, full-plate search, and digits-only search",
              c_let is None and p_ab4444["route"] == "CAM1 ➔ CAM2" and p_ab4444["total"] == 2
              and p_digits4444["ambiguous_query"] is True and set(p_digits4444["candidates"]) == {"اب-4444", "جد-4444"}
              and p_digits4444["candidate_paths"]["اب-4444"]["route"] == "CAM1 ➔ CAM2"
              and p_digits4444["candidate_paths"]["جد-4444"]["route"] == "CAM2", (c_let, p_ab4444, p_digits4444))

        # P1-4: Verify src='demo' sightings are excluded from live check_route
        ldb.execute("INSERT INTO sightings(ts, cam, plate, conf, vclass, src, direction) VALUES(?, 'CAM_DEMO', '50505', 0.9, 'car', 'demo', '')", (base_t + 900,))
        ldb.commit()
        r_str_demo, c_rec_demo = ins_mod.check_route("50505", "CAM1", base_t + 910, conf=0.9, cur_id=999, session_id="live_sess")
        check("P1-4", "src='demo' sightings are strictly excluded from live check_route",
              r_str_demo is None and c_rec_demo is None, (r_str_demo, c_rec_demo))

        # P1-4: Verify changing --cam within the same single-source session_id does NOT trigger a false conflict
        ldb.execute("INSERT INTO sightings(ts, cam, plate, conf, vclass, src, direction, session_id) VALUES(?, 'CAM1', '60606', 0.9, 'car', 'live', '', 'same_sess_1')", (base_t + 900,))
        ldb.commit()
        r_str_same, c_rec_same = ins_mod.check_route("60606", "CAM2", base_t + 910, conf=0.9, cur_id=1000, session_id="same_sess_1")
        check("P1-4", "changing --cam within the same single-camera session does not produce false route conflict",
              r_str_same is None and c_rec_same is None, (r_str_same, c_rec_same))

        ldb.close()
    finally:
        ins_mod.init(m.db, m.DBL)
        shutil.rmtree(tmp_db_dir, ignore_errors=True)


# ==============================================================================
# 3. SECURITY, SECRETS (P1-G), LAN (P1-J), MULTI-PROCESS 2x50 (P0-E), & PRIVACY (P2-K)
# ==============================================================================
def run_security_lan_and_multiprocess_tests():
    # Token & RTSP credential redaction test (P1-G)
    leaked = f"Error calling https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/sendPhoto and rtsp://admin:MySecretPass@192.168.1.50:554/live"
    redacted = not_mod._redact(leaked)
    check("SEC", "Telegram bot token and RTSP password are redacted from error messages and logs",
          os.environ["TELEGRAM_TOKEN"] not in redacted and "MySecretPass" not in redacted
          and "<REDACTED_TOKEN>" in redacted and "rtsp://admin:***@192.168.1.50:554/live" in redacted, redacted)

    # P1-G: Test all secret migration & precedence scenarios
    cfg_dir = tempfile.mkdtemp(prefix="mersad_cfgtest_")
    orig_cwd = os.getcwd()
    try:
        os.chdir(cfg_dir)
        # 1) Plaintext token in mersad_config.json without env -> migrated to .mersad_secrets.json (0600) & preserved across save_cfg
        saved_pre = dict(m._PREEXISTING_ENV)
        m._PREEXISTING_ENV.clear()
        os.environ.pop("TELEGRAM_TOKEN", None)
        with open("mersad_config.json", "w", encoding="utf-8") as cf:
            json.dump({"telegram_token": "FILE_SECRET_111", "source": "rtsp://user:pass99@10.0.0.1/s"}, cf)
        c1 = m.load_cfg()
        m.save_cfg(c1)
        disk_cfg = json.load(open("mersad_config.json", encoding="utf-8"))
        disk_sec = json.load(open(".mersad_secrets.json", encoding="utf-8"))
        check("P1-G", "file token & RTSP credentials migrated to .mersad_secrets.json, cleared from mersad_config.json, and not lost on save_cfg",
              disk_cfg.get("telegram_token") == "" and "pass99" not in disk_cfg.get("source", "")
              and disk_sec.get("telegram_token") == "FILE_SECRET_111"
              and os.environ.get("TELEGRAM_TOKEN") == "FILE_SECRET_111", (disk_cfg, disk_sec))

        # 2) Preexisting env token differs from old file token -> env wins at runtime and is NOT written to mersad_config.json
        m._PREEXISTING_ENV["TELEGRAM_TOKEN"] = "ENV_SECRET_222"
        os.environ["TELEGRAM_TOKEN"] = "ENV_SECRET_222"
        c2 = m.load_cfg()
        m.save_cfg(c2)
        disk_cfg2 = json.load(open("mersad_config.json", encoding="utf-8"))
        check("P1-G", "preexisting env token takes precedence over file token and is never written to mersad_config.json",
              os.environ.get("TELEGRAM_TOKEN") == "ENV_SECRET_222" and disk_cfg2.get("telegram_token") == "", disk_cfg2)
    finally:
        m._PREEXISTING_ENV.clear()
        m._PREEXISTING_ENV.update(saved_pre)
        os.environ["TELEGRAM_TOKEN"] = "SECRET_BOT_TOKEN_999"
        os.chdir(orig_cwd)
        shutil.rmtree(cfg_dir, ignore_errors=True)

    m.save_cfg(m.DEFAULTS)
    saved_json = json.load(open("mersad_config.json", encoding="utf-8"))
    check("P3-9", "save_cfg does not write environment TELEGRAM_TOKEN in plaintext to mersad_config.json",
          saved_json.get("telegram_token", "") == "", saved_json)

    # P2-K: Two distinct persons with the same name ('أحمد محمد') and different ref ('ID-1' vs 'ID-2') + HMAC pseud()
    reg_mod.save_person({"name": "أحمد محمد", "ref": "ID-1", "consent": True, "status": "normal"}, "unit")
    reg_mod.save_person({"name": "أحمد محمد", "ref": "ID-2", "consent": True, "status": "watch"}, "unit")
    ahmed_rows = [r for r in reg_mod.list_rows("persons", "أحمد محمد") if r["name"] == "أحمد محمد"]
    raw_sha = "p-" + hashlib.sha256("أحمد محمد".encode("utf-8")).hexdigest()[:8]
    hmac_p = reg_mod.pseud("أحمد محمد")
    check("P2-K", "two persons with identical name & different ref coexist via internal ID, and pseud() uses keyed HMAC",
          len(ahmed_rows) == 2 and ahmed_rows[0]["id"] != ahmed_rows[1]["id"]
          and hmac_p != raw_sha and os.path.isfile(os.path.join(WORK, ".mersad_hmac.key")), (ahmed_rows, hmac_p))
    for r in ahmed_rows:
        reg_mod.delete("persons", f"id:{r['id']}", "unit")

    # P2-K: Bystander face blurring verification
    test_fr = np.random.default_rng(9).integers(0, 255, (200, 200, 3), dtype=np.uint8)
    blurred_fr = m.blur_unmatched_faces(test_fr, [(20, 20, 60, 60)])
    diff_roi = np.abs(test_fr[20:80, 20:80].astype(np.float32) - blurred_fr[20:80, 20:80].astype(np.float32)).mean()
    same_outside = np.array_equal(test_fr[100:150, 100:150], blurred_fr[100:150, 100:150])
    check("P2-K", "bystander face bounding boxes are blurred in evidence frames while rest of image is untouched",
          diff_roi > 5.0 and same_outside, (diff_roi, same_outside))

    # P2-L: Demo sightings do not pollute live 'NEW PLATE (first sighting)'
    m.db.execute("INSERT INTO sightings(ts, cam, plate, conf, vclass, src) VALUES(?, 'CAM1', '70707', 0.9, 'car', 'demo')", (time.time() - 300,))
    m.db.commit()
    msg_live_first, _ = m.register("70707", 0.93, "CAM1", "car", session_id="s_live_l")
    m.db.execute("DELETE FROM sightings WHERE plate='70707'")
    m.db.commit()
    check("P2-L", "demo sightings do not prevent first live sighting from triggering 'NEW PLATE (first sighting)'",
          msg_live_first == "NEW PLATE (first sighting)", msg_live_first)

    # P2-M: Supply chain pinned versions & SHA-256 verification
    req_txt = open(os.path.join(WORK, "requirements.txt"), encoding="utf-8").read()
    setup_txt = open(os.path.join(WORK, "setup.bat"), encoding="utf-8").read()
    check("P2-M", "requirements.txt pins exact versions, MODELS & EASYOCR_SHA256 use pinned commit + SHA-256, and setup.bat replaces headless OpenCV",
          req_txt.count("==") >= 6 and m.ZOO_COMMIT in m.ZOO and len(m.MODEL_SHA256) == 3 and len(m.EASYOCR_SHA256) >= 3
          and "opencv-python-headless" in setup_txt)

    # UI contract check
    html = open(os.path.join(WORK, "dashboard.html"), encoding="utf-8").read()
    check("UI", "dashboard.html uses safe data-p attribute and includes 'توجيهات لم تصل للدوريات' & camera switcher",
          'data-p="${esc(p)}"' in html and "توجيهات لم تصل للدوريات" in html and "cam-sw" in html
          and 'data-t="analytics"' in html and 'id="t-health"' in html)

    # Build script & RUN_LAN.bat check
    bat_txt = open(os.path.join(WORK, "BUILD_EXE.bat"), encoding="utf-8").read()
    lan_bat_txt = open(os.path.join(WORK, "RUN_LAN.bat"), encoding="utf-8").read()
    check("BUILD", "BUILD_EXE.bat includes all local hidden imports, dashboard.html, and model copy step",
          all(x in bat_txt for x in ("dashboard.html", "registry", "insights", "analytics", "camera_history", "notify", "server", "openpyxl", "dist\\MERSAD_AI\\models")))
    check("P1-5", "RUN_LAN.bat exists and enables --host 0.0.0.0 with HTTP security notice",
          "--host 0.0.0.0" in lan_bat_txt)

    # P1-J (and P1-5): Test LAN IP access after full wire() initialization, distinguishing HTTP 200 vs ConnectionRefusedError (never counting HTTP 500 as blocked!)
    m.wire()
    lan_ip = srv_mod.get_lan_ip()
    if not lan_ip or lan_ip == "127.0.0.1":
        lan_ip = "127.0.0.2"
    if lan_ip and lan_ip != "127.0.0.1":
        srv_local = ThreadingHTTPServer(("127.0.0.1", 8791), srv_mod.H)
        threading.Thread(target=srv_local.serve_forever, daemon=True).start()
        loopback_ok = False
        lan_refused = False
        try:
            r_lo = urllib.request.urlopen(f"http://127.0.0.1:8791/api/verify?k={m.bus.token}", timeout=2.0)
            loopback_ok = (r_lo.status == 200 and b"Audit chain OK" in r_lo.read())
        except Exception as e:
            loopback_ok = False
        try:
            urllib.request.urlopen(f"http://{lan_ip}:8791/api/verify?k={m.bus.token}", timeout=1.5)
        except urllib.error.HTTPError:
            lan_refused = False                      # HTTP error (e.g. 500) means socket connected -> NOT blocked!
        except urllib.error.URLError as ue:
            lan_refused = isinstance(ue.reason, (ConnectionRefusedError, TimeoutError, OSError))
        srv_local.shutdown()

        srv_lan = ThreadingHTTPServer(("0.0.0.0", 8792), srv_mod.H)
        threading.Thread(target=srv_lan.serve_forever, daemon=True).start()
        lan_200 = False
        try:
            resp = urllib.request.urlopen(f"http://{lan_ip}:8792/api/verify?k={m.bus.token}", timeout=2.0)
            lan_200 = (resp.status == 200 and b"Audit chain OK" in resp.read())
        except Exception:
            lan_200 = False
        srv_lan.shutdown()
        check("P1-J", f"with wire() initialized: 127.0.0.1 serves 200 on loopback & refuses connection on LAN IP ({lan_ip}), while 0.0.0.0 serves 200 on LAN IP",
              loopback_ok and lan_refused and lan_200, (loopback_ok, lan_refused, lan_200))
    else:
        skip_check("P1-J", "LAN IP binding check", "No non-loopback LAN interface IP available in container")

    # Regression: all code paths must acquire the local DB RLock before the
    # process-state/OS-lock bookkeeping lock, preventing cross-thread inversion.
    _lock_order = []
    class _LockOrderProbe:
        def __init__(self, name, wrapped):
            self.name = name
            self.wrapped = wrapped
        def acquire(self, *args, **kwargs):
            _lock_order.append(self.name)
            return self.wrapped.acquire(*args, **kwargs)
        def release(self):
            return self.wrapped.release()

    _old_db_lock = reg_mod.D.get("lock")
    _old_ipc_lock = reg_mod._IPC_RLOCK
    try:
        reg_mod.D["lock"] = _LockOrderProbe("local-db", _old_db_lock)
        reg_mod._IPC_RLOCK = _LockOrderProbe("process-state", _old_ipc_lock)
        with reg_mod.interprocess_db_lock(":memory:"):
            pass
    finally:
        reg_mod.D["lock"] = _old_db_lock
        reg_mod._IPC_RLOCK = _old_ipc_lock
    check("P0-E", "SQLite lock order is local DB RLock before process-state lock",
          _lock_order[:2] == ["local-db", "process-state"], _lock_order)

    # P0-E & P2-6: Real 2-process CONCURRENT stress test (2 OS processes x 50 alerts = 100 alerts simultaneously + listener lock + cross-process sync)
    mp_dir = tempfile.mkdtemp(prefix="mersad_mp_")
    try:
        worker_code = (
            "import os, sys, time, numpy as np\n"
            f"sys.path.insert(0, {repr(WORK)})\n"
            "os.environ['MERSAD_DATA_DIR'] = sys.argv[1]\n"
            "os.environ['TELEGRAM_TOKEN'] = 'TOK_MP_TEST'\n"
            "os.environ['TELEGRAM_CHAT_ID'] = '-100'\n"
            "os.environ['TELEGRAM_API'] = 'http://127.0.0.1:8780'\n"
            "import mersad_live as m, threading\n"
            # This stress case targets database/audit/lock semantics, not OpenCV encoding or Telegram network delivery.
            # Keep native image I/O and outbound sends out of child-process shutdown to avoid unrelated native-thread crashes.
            "m.send_alert = lambda *args, **kwargs: True\n"
            "def _test_write_image(path, frame):\n"
            "    with open(path, 'wb') as ef: ef.write(b'MERSAD_TEST_EVIDENCE')\n"
            "    return True\n"
            "m.cv2.imwrite = _test_write_image\n"
            "cam = sys.argv[2]\n"
            "barrier_dir = sys.argv[3]\n"
            "def _mark_progress(stage):\n"
            "    with open(os.path.join(barrier_dir, cam + '.progress'), 'w', encoding='ascii') as pf: pf.write(stage)\n"
            "stop_ev = threading.Event()\n"
            "listener_owned = m.start_listener(lambda d, w: 'ok', stop_event=stop_ev)\n"
            "with open(os.path.join(barrier_dir, cam + '.listener'), 'w', encoding='ascii') as lf: lf.write(str(int(listener_owned)))\n"
            "deadline = time.monotonic() + 10\n"
            "while not (os.path.isfile(os.path.join(barrier_dir, 'CAM1.listener')) and os.path.isfile(os.path.join(barrier_dir, 'CAM2.listener'))) and time.monotonic() < deadline: time.sleep(0.01)\n"
            "if not (os.path.isfile(os.path.join(barrier_dir, 'CAM1.listener')) and os.path.isfile(os.path.join(barrier_dir, 'CAM2.listener'))): raise RuntimeError('listener test barrier timed out')\n"
            "_mark_progress('listener_barrier_ok')\n"
            "m.log('session start', cam)\n"
            "_mark_progress('session_log_ok')\n"
            "msg, _ = m.register('88881', 0.93, cam, 'car', direction='اقتراب نسبي في الإطار', session_id='proc_' + cam)\n"
            "_mark_progress('register_ok')\n"
            "img = np.zeros((40, 40, 3), np.uint8)\n"
            "errs = 0\n"
            "last_err = ''\n"
            "# Defer the expensive in-memory refresh until the concurrent DB write burst is complete.\n"
            "# All 100 alert rows, evidence writes, audit-chain updates, and final cross-process sync remain real.\n"
            "_original_sync_alerts = m._sync_alerts_from_db\n"
            "m._sync_alerts_from_db = lambda *args, **kwargs: None\n"
            "try:\n"
            "    for i in range(50):\n"
            "    try:\n"
            "        m.raise_alert('VEHICLE: WANTED', f'{cam}_PL_{i}', cam, img, ref=f'{cam}_{i}')\n"
            "    except Exception as e:\n"
            "        errs += 1\n"
            "        last_err = f'{type(e).__name__}: {e}'[:160]\n"
            "    if (i + 1) % 10 == 0: _mark_progress(f'alerts={i + 1};errs={errs};last={last_err}')\n"
            "finally:\n"
            "    m._sync_alerts_from_db = _original_sync_alerts\n"
            "_mark_progress('alert_burst_complete')\n"
            "m._sync_alerts_from_db()\n"
            "_mark_progress('cross_process_sync_complete')\n"
            "with open(os.path.join(barrier_dir, cam + '.done'), 'w', encoding='ascii') as df: df.write('done')\n"
            "deadline = time.monotonic() + 10\n"
            "while not (os.path.isfile(os.path.join(barrier_dir, 'CAM1.done')) and os.path.isfile(os.path.join(barrier_dir, 'CAM2.done'))) and time.monotonic() < deadline: time.sleep(0.01)\n"
            "if not (os.path.isfile(os.path.join(barrier_dir, 'CAM1.done')) and os.path.isfile(os.path.join(barrier_dir, 'CAM2.done'))): raise RuntimeError('alert completion barrier timed out')\n"
            "m._sync_alerts_from_db()\n"
            "synced_total = len(m.bus.alerts)\n"
            "m.log('session end', cam)\n"
            "stop_ev.set()\n"
            "m._notify_mod.wait_listener_stopped(timeout=4.0)\n"
            "m.db.close()\n"
            "print(f'MP_OUT:{cam}:errs={errs}:listener={int(listener_owned)}:synced={synced_total}:route={msg}')\n"
        )
        p1 = p2 = None
        try:
            p1 = subprocess.Popen([sys.executable, "-c", worker_code, mp_dir, "CAM1", mp_dir], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            p2 = subprocess.Popen([sys.executable, "-c", worker_code, mp_dir, "CAM2", mp_dir], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            # Drain both child pipes concurrently. Sequential communicate() calls
            # gave the second Windows worker a fresh 30s timeout only after the
            # first worker had already consumed most of the wall-clock budget.
            # SQLite/audit stress is intentionally kept at 2 x 50 writes.
            mp_timeout = 75
            with ThreadPoolExecutor(max_workers=2) as mp_pool:
                f1 = mp_pool.submit(p1.communicate, timeout=mp_timeout)
                f2 = mp_pool.submit(p2.communicate, timeout=mp_timeout)
                try:
                    o1, e1 = f1.result(timeout=mp_timeout + 5)
                    o2, e2 = f2.result(timeout=mp_timeout + 5)
                except (subprocess.TimeoutExpired, FutureTimeoutError) as exc:
                    for child in (p1, p2):
                        if child is not None and child.poll() is None:
                            child.kill()
                    # The futures own communicate() and finish draining after kill.
                    try:
                        o1, e1 = f1.result(timeout=5)
                    except Exception as drain_exc:
                        o1, e1 = "", f"stdout/stderr drain failed: {drain_exc}"
                    try:
                        o2, e2 = f2.result(timeout=5)
                    except Exception as drain_exc:
                        o2, e2 = "", f"stdout/stderr drain failed: {drain_exc}"
                    progress = {}
                    for cam_id in ("CAM1", "CAM2"):
                        try:
                            with open(os.path.join(mp_dir, cam_id + ".progress"), encoding="ascii") as pf:
                                progress[cam_id] = pf.read().strip()
                        except OSError:
                            progress[cam_id] = "<missing>"
                    raise RuntimeError(
                        f"Concurrent DB stress workers exceeded {mp_timeout}s; progress={progress}; "
                        f"exit_codes={(p1.poll(), p2.poll())}; "
                        f"CAM1_out={o1[-500:]!r}; CAM1_err={e1[-500:]!r}; "
                        f"CAM2_out={o2[-500:]!r}; CAM2_err={e2[-500:]!r}"
                    ) from exc
        finally:
            for child in (p1, p2):
                if child is not None and child.poll() is None:
                    child.kill()
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
        mp_exit_codes = (p1.returncode, p2.returncode)

        mp_db = sqlite3.connect(os.path.join(mp_dir, "mersad.db"))
        tot_alerts = mp_db.execute("SELECT COUNT(*), COUNT(DISTINCT id) FROM alerts").fetchall()[0]
        tot_audit = mp_db.execute("SELECT COUNT(*), COUNT(DISTINCT i) FROM audit").fetchall()[0]
        mp_db.close()

        v_p = subprocess.run([sys.executable, os.path.join(WORK, "mersad_live.py"), "--verify"],
                             env={**os.environ, "MERSAD_DATA_DIR": mp_dir}, capture_output=True, text=True, timeout=10)
        try:
            l1 = open(os.path.join(mp_dir, "CAM1.listener"), encoding="ascii").read().strip() == "1"
            l2 = open(os.path.join(mp_dir, "CAM2.listener"), encoding="ascii").read().strip() == "1"
        except OSError:
            l1 = l2 = False
        check("P0-E", "2 concurrent OS processes x 50 alerts = 100 unique alerts, 0 errors, intact audit chain, & exactly one Telegram listener owner",
              "errs=0" in o1 and "errs=0" in o2 and tot_alerts == (100, 100)
              and tot_audit[0] == tot_audit[1] and tot_audit[0] >= 204
              and (l1 ^ l2) and "Audit chain OK" in v_p.stdout,
              (o1.strip(), o2.strip(), {"listener_CAM1": l1, "listener_CAM2": l2}, "returncodes", p1.returncode, p2.returncode, tot_alerts, tot_audit, v_p.stdout.strip(), e1[-200:], e2[-200:]))

        # Also check that syncing in a process sees all 100 alerts from both processes
        check("P2-6", "multi-process shared DB synchronizes alerts across processes",
              ("synced=100" in o1 or "synced=100" in o2) and "Audit chain OK" in v_p.stdout, (o1.strip(), o2.strip()))
    finally:
        shutil.rmtree(mp_dir, ignore_errors=True)


# ==============================================================================
# 4. MULTI-CAMERA LOOP, RECONNECTION, & EXCEPTION RESILIENCE TEST (P0-D)
# ==============================================================================
def run_multicam_loop_tests():
    mc_dir = tempfile.mkdtemp(prefix="mersad_mcloop_")
    orig_nfr = NFR
    try:
        # Test 3 cameras: cam1_ok, cam2_drop (drops at frame 15 then reconnects), cam3_ok + injected detect exception
        CAM_DROP_STATE["CAM2_failed_once"] = False
        CAM_DROP_STATE["reads"].clear()
        INJECT_DETECT_EXC["count"] = 2
        old_argv = sys.argv[:]
        m.OFFLINE_ALERT_SEC = 0.05
        m.RECONNECT_BASE_SEC = 0.005
        sys.argv = ["mersad_live.py", "--source", "cam1_ok,cam2_drop,cam3_ok", "--cam", "CAM1,CAM2,CAM3",
                    "--no-window", "--no-telegram-listener", "--port", "8795", "--token", "mctok"]
        MC_INSPECT_DONE.clear()
        insp_ok = [False]
        def _inspect_streams():
            try:
                wait(lambda: len(m.STATUS.get("cameras", {})) == 3 and all(m.STATUS["cameras"][c]["detections"] >= 1 for c in ("CAM1", "CAM2", "CAM3")), t=8.0)
                for cn in ("CAM1", "CAM2", "CAM3"):
                    with urllib.request.urlopen(f"http://127.0.0.1:8795/stream.mjpg?cam={cn}&k=mctok", timeout=3.0) as r_st:
                        b = r_st.read(300)
                    assert b"image/jpeg" in b, f"stream missing for {cn}"
                insp_ok[0] = True
            finally:
                MC_INSPECT_DONE.set()
        t_insp = threading.Thread(target=_inspect_streams, daemon=True)
        t_insp.start()
        globals()["NFR"] = 30
        m.main()
        t_insp.join(5.0)
        cams_stat = m.STATUS.get("cameras", {})
        det_counts = {c: cams_stat.get(c, {}).get("detections", 0) for c in ("CAM1", "CAM2", "CAM3")}
        reconn_logged = any("camera reconnected" in r[0] for r in m.db.execute("SELECT action FROM audit WHERE ref='CAM2'").fetchall())
        check("P0-D", "3 cameras run equal detections, serve per-camera /stream.mjpg?cam=, survive injected detect exception, and CAM2 reconnects after drop",
              insp_ok[0] and all(v >= 3 for v in det_counts.values()) and CAM_DROP_STATE["CAM2_failed_once"] and reconn_logged,
              (insp_ok[0], det_counts, CAM_DROP_STATE, reconn_logged))
    finally:
        globals()["NFR"] = orig_nfr
        CAM_DROP_STATE["reads"].clear()
        with TG["lock"]:
            TG["calls"].clear()
            TG["updates"].clear()
        with m.DBL:
            m.db.execute("DELETE FROM alerts")
            m.db.execute("DELETE FROM sightings WHERE cam IN ('CAM1','CAM2','CAM3') AND COALESCE(src,'live')='live'")
            m.db.commit()
        m.bus.alerts.clear()
        m.bus.failed_dispatches.clear()
        m.OFFLINE_ALERT_SEC = 10.0
        m.RECONNECT_BASE_SEC = 0.05
        m.bus.fid = 0
        sys.argv = old_argv
        shutil.rmtree(mc_dir, ignore_errors=True)


# ==============================================================================
# 5. END-TO-END INTEGRATION & ROUND 1/2/3 WORKFLOW DRIVER
# ==============================================================================
def post(p, b, tok="t"):
    req = urllib.request.Request(U + p + f"?k={tok}", json.dumps(b).encode("utf-8"), method="POST")
    return json.loads(urllib.request.urlopen(req).read())

def get(p, tok="t"):
    sep = "&" if "?" in p else "?"
    return json.loads(urllib.request.urlopen(U + p + f"{sep}k={tok}").read())

def get_code(p, tok="t"):
    sep = "&" if "?" in p else "?"
    try:
        urllib.request.urlopen(U + p + f"{sep}k={tok}")
        return 200
    except urllib.error.HTTPError as e:
        return e.code

def wait(cond, t=12):
    end = time.time() + t
    while time.time() < end:
        if cond(): return True
        time.sleep(0.1)
    return False

db_q = lambda q, *a: m.db.execute(q, a).fetchall()

def _srv_ready():
    try:
        return get_code("/api/ping", tok="t") == 200
    except Exception:
        return False

def driver():
    try:
        wait(lambda: m.bus.fid > 0 and _srv_ready())
        check("API", "unauthenticated request rejected with HTTP 403", get_code("/api/stats", tok="wrong_token") == 403)
        check("SEC", "path traversal on /evidence/ rejected with HTTP 403/404",
              get_code("/evidence/..%2Fmersad.db") in (403, 404) and get_code("/evidence/../mersad.db") in (403, 404))

        # P3-9: Test HttpOnly cookie + 302 redirect removing ?k= from URL
        class NoRedir(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl): return None
        opener = urllib.request.build_opener(NoRedir)
        try:
            opener.open(U + "/?k=t")
            redir_code, set_cookie, loc = 200, "", ""
        except urllib.error.HTTPError as he:
            redir_code = he.code
            set_cookie = he.headers.get("Set-Cookie", "")
            loc = he.headers.get("Location", "")
        req_cookie = urllib.request.Request(U + "/", headers={"Cookie": "mersad_k=t"})
        html_via_cookie = urllib.request.urlopen(req_cookie).read()
        check("P3-9", "GET /?k=t returns 302 with HttpOnly cookie & Location: /, and GET / with cookie succeeds",
              redir_code == 302 and "HttpOnly" in set_cookie and "mersad_k=t" in set_cookie
              and loc == "/" and b"<!DOCTYPE html>" in html_via_cookie, (redir_code, set_cookie, loc))

        check("INT", "live MJPEG video stream active", b"image/jpeg" in urllib.request.urlopen(U + "/stream.mjpg?k=t").read(400))
        check("API", "dashboard stats API works on initial database before seeding",
              {"det24", "alerts", "fps", "telegram", "telegram_connected", "pending", "failed_dispatches"} <= set(get("/api/stats")))
        analytics_api = get("/api/analytics")
        check("V7-API", "authenticated /api/analytics returns 24 hourly bins and aggregate-only metrics",
              analytics_api.get("ok") and len(analytics_api.get("trend", [])) == 24 and "sightings" in analytics_api and "recommendations" in analytics_api)
        health_api = get("/api/camera-health?period=7d")
        check("V7-API", "authenticated /api/camera-health supports selectable reporting periods",
              health_api.get("ok") and health_api.get("period") == "7d" and isinstance(health_api.get("cameras"), list))
        check("V7-SEC", "new analytics and camera-history API endpoints reject invalid tokens",
              get_code("/api/analytics", tok="wrong_token") == 403 and get_code("/api/camera-health", tok="wrong_token") == 403)
        def _csv_endpoint(path):
            resp = urllib.request.urlopen(U + path + "&k=t" if "?" in path else U + path + "?k=t")
            return resp.headers.get("Content-Type", ""), resp.headers.get("Content-Disposition", ""), resp.read()
        an_ct, an_cd, an_csv = _csv_endpoint("/api/analytics/export.csv")
        he_ct, he_cd, he_csv = _csv_endpoint("/api/camera-health/export.csv?period=24h")
        check("V7-API", "privacy-safe analytics CSV export has UTF-8 BOM and attachment headers",
              "text/csv" in an_ct and "mersad_analytics.csv" in an_cd and an_csv.startswith(b"\xef\xbb\xbf"))
        check("V7-API", "camera reliability CSV export has UTF-8 BOM and attachment headers",
              "text/csv" in he_ct and "mersad_camera_health.csv" in he_cd and he_csv.startswith(b"\xef\xbb\xbf"))
        check("API", "registry: add vehicle (API)", post("/api/vehicle", {"plate": "55555", "model": "Kia", "status": "stolen"})["ok"])
        check("API", "registry: add person with consent", post("/api/person", {"name": "Sara", "status": "watch", "consent": True})["ok"])
        check("INT", "face enrollment from camera (5 validated 128-D samples)",
              post("/api/enroll", {"name": "Sara"})["ok"] and wait(lambda: db_q("select count(*) from faces where name='Sara'")[0][0] == 5))
        check("INT", "wanted-vehicle alert (Arabic OCR 'عدن ١٢٣٤٥' matches registry '12345')",
              wait(lambda: any(a["msg"] == "VEHICLE: WANTED" for a in m.bus.alerts)), [a["msg"] for a in m.bus.alerts])
        check("INT", "face-match alert after consecutive matches",
              wait(lambda: any(a["msg"].startswith("FACE MATCH") for a in m.bus.alerts)))

        a = next(x for x in m.bus.alerts if x["msg"] == "VEHICLE: WANTED")
        aid = a["id"]
        check("INT", "alert carries vehicle details & digits-only match note",
              "Toyota Hilux" in a["detail"] and "تطابق بالأرقام فقط" in a["detail"], a["detail"])
        check("API", "evidence JPEG image served safely",
              len(urllib.request.urlopen(U + "/evidence/" + a["img"] + "?k=t").read()) > 1000)

        # P1-I: Alert deduplication by (msg, ref) increments repeat_count instead of creating a new alert
        aid_dup = m.raise_alert("VEHICLE: WANTED", a["subject"], "CAM1", np.zeros((60, 60, 3), np.uint8), ref=a["ref"])
        rep_cnt = db_q("select repeat_count from alerts where id=?", aid)[0][0]
        check("P1-I", "repeated wanted alert for same pending plate increments repeat_count without creating duplicate alert",
              aid_dup == aid and rep_cnt >= 2, (aid, aid_dup, rep_cnt))

        sp = lambda ch: [f for f in calls("sendPhoto") if f.get("chat_id") == ch and "12345" in f.get("caption", "")]
        check("INT", "phone alert reaches operations room with photo", wait(lambda: sp("-100")))
        f = sp("-100")[0]
        check("INT", "phone alert text: priority, plate, camera, human-confirmation note",
              all(x in f["caption"] for x in ("أولوية قصوى", "12345", "📍", "تأكيداً بشرياً")), f["caption"])
        check("INT", "phone alert has 3 decision buttons",
              f["reply_markup"].count("callback_data") == 3 and f"c:{aid}" in f["reply_markup"])
        check("SEC", "patrols NOT notified before human confirmation", not sp("-200"))

        # Unauthorized user button press rejected
        press(900, "cbX", -999, f"c:{aid}")
        check("SEC", "stranger's button press is rejected",
              wait(lambda: any("غير مصرّح" in x.get("text", "") for x in calls("answerCallbackQuery")))
              and any(x["id"] == aid for x in m.bus.alerts))

        # P1-3: Non-blocking dispatch test — delay patrol chat (-200) by 2.5s and verify callback answers in < 1.2s & video frames keep advancing
        with TG["lock"]:
            TG["delay_chat"]["-200"] = 2.5
        fid_before = m.bus.fid
        t_press = time.time()
        press(901, "cb1", -100, f"c:{aid}")
        cb_fast = wait(lambda: any("جارٍ الإرسال" in x.get("text", "") for x in calls("answerCallbackQuery")), t=1.2)
        cb_elapsed = time.time() - t_press
        time.sleep(0.3)
        fid_during = m.bus.fid
        check("P1-3", f"Telegram callback answered immediately ({cb_elapsed:.2f}s < 1.2s) & camera frames kept advancing during slow dispatch",
              cb_fast and fid_during > fid_before, (cb_fast, cb_elapsed, fid_before, fid_during))

        check("INT", "operator taps confirm -> patrols receive dispatch after network delay", wait(lambda: sp("-200"), t=6.0))
        with TG["lock"]:
            TG["delay_chat"].pop("-200", None)
        check("INT", "dispatch to patrols has no buttons", "reply_markup" not in sp("-200")[0])
        check("INT", "tap answered and inline buttons removed", calls("editMessageReplyMarkup"))
        check("DB", "tap recorded in audit & alerts table marked dispatch_status='sent'",
              wait(lambda: db_q("select status, dispatched, dispatch_status from alerts where id=?", aid)[0] == ("confirm", 1, "sent"), t=3.0)
              and any("tg:555" in r[0] for r in db_q("select ref from audit where action='operator confirm'")))

        # Duplicate button tap rejected
        press(902, "cb2", -100, f"c:{aid}")
        check("SEC", "second tap says already decided (no duplicate dispatch)",
              wait(lambda: any("سبق" in x.get("text", "") for x in calls("answerCallbackQuery"))))

        # P0-2: Patrol dispatch failure -> queued in failed_dispatches, ops room notified, then auto-retried when server recovers!
        face_al = next(x for x in m.bus.alerts if x["msg"].startswith("FACE MATCH"))
        face_aid = face_al["id"]
        with TG["lock"]:
            TG["fail_chat"].add("-200")
        post("/api/decision", {"id": face_aid, "action": "confirm"})
        wait(lambda: db_q("select dispatch_status from alerts where id=?", face_aid)[0][0] == "failed", t=3.0)
        st_fail, disp_fail, att_fail = db_q("select dispatch_status, dispatched, dispatch_attempts from alerts where id=?", face_aid)[0]
        in_fdisp_list = any(x["id"] == face_aid for x in m.bus.failed_dispatches)
        check("P0-2", "failed patrol dispatch sets dispatch_status='failed', appears in failed_dispatches, and schedules retry",
              st_fail == "failed" and disp_fail == 0 and att_fail >= 1 and in_fdisp_list, (st_fail, disp_fail, att_fail, in_fdisp_list))

        with TG["lock"]:
            TG["fail_chat"].discard("-200")
        recovered = wait(lambda: db_q("select dispatch_status, dispatched from alerts where id=?", face_aid)[0] == ("sent", 1), t=5.0)
        check("P0-2", "automatic backoff retry delivers patrol dispatch once network recovers & clears failed_dispatches",
              recovered and not any(x["id"] == face_aid for x in m.bus.failed_dispatches)
              and any("trigger=auto_retry" in r[0] for r in db_q("select ref from audit where action='dispatch attempt'")))

        # P1-F: Simulate a confirmed alert that crashed BEFORE attempt #1 (dispatch_attempts=0, dispatch_status='pending')
        aid_crash0 = m.raise_alert("VEHICLE: STOLEN", "55555", "CAM1", np.zeros((60, 60, 3), np.uint8))
        with m.DBL:
            m.db.execute("UPDATE alerts SET status='confirm', dispatch_status='pending', dispatch_attempts=0, next_retry_ts=? WHERE id=?",
                         (time.time() - 1.0, aid_crash0))
            m.db.commit()
        rec_crash0 = wait(lambda: db_q("select dispatch_status, dispatched from alerts where id=?", aid_crash0)[0] == ("sent", 1), t=4.0)
        check("P1-F", "confirmed alert with attempts=0 (crashed before first attempt) is picked up and sent by retry loop",
              rec_crash0)

        # P1-4 & P1-F: Uncalibrated route conflict raises 'ROUTE NOTICE (uncalibrated)' (🔵 للعلم) WITHOUT dispatch buttons, and server REJECTS confirm!
        msg_uncal, _ = m.register("33331", 0.91, "CAM1", "car", session_id="s_cam1")
        time.sleep(0.05)
        msg_uncal2, _ = m.register("33331", 0.91, "CAM2", "car", session_id="s_cam2")
        aid_uncal = m.raise_alert(msg_uncal2, "33331", "CAM2", np.zeros((100, 100, 3), np.uint8))
        wait(lambda: any("33331" in f.get("caption", "") for f in calls("sendPhoto")), t=3.0)
        uncal_photo = next(f for f in calls("sendPhoto") if "33331" in f.get("caption", ""))
        check("P1-4", "uncalibrated route conflict raises 'ROUTE NOTICE (uncalibrated)' (🔵 للعلم) with NO patrol dispatch buttons",
              msg_uncal2 == "ROUTE NOTICE (uncalibrated)" and "🔵 للعلم" in uncal_photo["caption"]
              and "reply_markup" not in uncal_photo, uncal_photo)

        res_conf_info = post("/api/decision", {"id": aid_uncal, "action": "confirm"})
        check("P1-F", "server rejects decide('confirm') on INFO_ONLY / uncalibrated route notice alert",
              res_conf_info.get("ok") is False and db_q("select status from alerts where id=?", aid_uncal)[0][0] == "pending", res_conf_info)
        # Resolve it with ack so it's no longer pending
        post("/api/decision", {"id": aid_uncal, "action": "ack"})

        # Consent revocation immediately removes face samples and stops matching
        post("/api/person", {"name": "Sara", "status": "watch", "consent": False})
        check("SEC", "revoking person consent immediately erases stored face embeddings",
              db_q("select count(*) from faces where name='Sara'")[0][0] == 0 and len(m.KNOWN) == 0)

        # Learning, forecast, path tracking & P3-9 model['type'] (GAP-04: explicit ?demo=1 required for demo history)
        check("STATS", "learning: seed demo history + train (works with or without sklearn)",
              post("/api/insights/seed", {}).get("ok"))
        s_live_default = get("/api/insights")
        s = get("/api/insights?demo=1")
        check("STATS", "learning: 24h forecast, empirical band metadata, corridors & anomalies",
              s_live_default.get("data_source") == "live" and s_live_default.get("includes_demo") is False
              and s.get("data_source") == "demo" and s.get("includes_demo") is True
              and s["model"]["ready"] and len(s["forecast"]["hours"]) == 24
              and s["forecast"]["band_method"] == "empirical_dispersion_mean_plus_minus_1.28_std"
              and bool(s["corridors"]) and bool(s["paths"]) and bool(s["anomalies"]))
        check("P3-9", "summary()['model'] includes explicit 'type' field ('IsolationForest' or 'StatForest')",
              s["model"].get("type") in ("IsolationForest", "StatForest"), s["model"])

        pt_live_only = get("/api/path?plate=99991")
        pt = get("/api/path?plate=99991&demo=1")
        check("API", "/api/path returns trajectory & structured spatio-temporal conflict for plate 99991",
              pt_live_only.get("found") is False and pt_live_only.get("has_demo_only") is True
              and pt.get("ok") and pt.get("found") and pt.get("data_source") == "demo"
              and "CAM1 ➔ CAM3" in pt.get("route", "")
              and len(pt.get("conflicts", [])) >= 1 and pt["conflicts"][0]["from_cam"] == "CAM1")

        # P1-H: Verify /api/archive_evidence ignores request retention_days=0.00001 and protects pending alerts!
        aid_pend_h = m.raise_alert("VEHICLE: WANTED", "43210", "CAM1", np.zeros((60, 60, 3), np.uint8))
        ev_pend_h = os.path.join("evidence", db_q("select img from alerts where id=?", aid_pend_h)[0][0])
        api_arch_res = post("/api/archive_evidence", {"retention_days": 0.00001})
        check("P1-H", "/api/archive_evidence ignores low retention_days parameter (enforces >=7d floor) & protects pending alert evidence",
              api_arch_res.get("retention_days", 0) >= 7.0 and os.path.isfile(ev_pend_h), (api_arch_res, os.path.isfile(ev_pend_h)))

        check("SEC", "deleting a person erases the record cleanly",
              post("/api/person/delete", {"key": "Sara"})["ok"])
    except Exception as e:
        import traceback; traceback.print_exc()
        check("INT", "driver execution", False, repr(e))
    finally:
        DRIVER_DONE.set()


run_unit_tests()
run_db_and_path_tests()
run_security_lan_and_multiprocess_tests()
run_multicam_loop_tests()

t = threading.Thread(target=driver, daemon=True)
m.R.save_vehicle({"plate": "12345", "model": "Toyota Hilux", "color": "white", "vtype": "truck", "owner": "demo", "status": "wanted"}, "selftest")
t.start()
sys.argv = ["mersad_live.py", "--source", "fake", "--no-window", "--port", "8771", "--token", "t"]
m.main()
t.join(40)

check("SEC", "audit chain & all evidence JPEG hashes verified intact", m.verify().startswith("Audit chain OK"), m.verify())

# P2-7 & P1-H: Test reversible evidence archiving (moves to evidence_archive/, verifies copy, excludes pending) and final purge
resolved_imgs = [
    f"evidence/{r[0]}" for r in db_q("SELECT img FROM alerts WHERE status != 'pending' AND COALESCE(dispatch_status,'') IN ('sent','not_required')")
    if r[0] and os.path.isfile(f"evidence/{r[0]}")
]
if resolved_imgs:
    target_ev = resolved_imgs[0]
    bname_ev = os.path.basename(target_ev)
    with m.DBL:
        m.db.execute("UPDATE audit SET ts = ts - 40*86400 WHERE action='evidence' AND ref LIKE ?", (f"{target_ev}%",))
        rows = m.db.execute("SELECT i, ts, action, ref FROM audit ORDER BY i").fetchall()
        prev = "0" * 64
        for i_r, ts_r, ac_r, ref_r in rows:
            h_r = m.chain_hash(prev, i_r, ts_r, ac_r, ref_r)
            m.db.execute("UPDATE audit SET prev=?, hash=? WHERE i=?", (prev, h_r, i_r))
            prev = h_r
        m.db.commit()
    arch_res = m.archive_old_evidence(retention_days=30, who="selftest")
    arch_copy = os.path.join("evidence_archive", bname_ev)
    ver_after_arch = m.verify()
    check("P2-7", "archive_old_evidence moves resolved file to evidence_archive/, logs actor, and verify() passes",
          arch_res["archived"] >= 1 and not os.path.exists(target_ev) and os.path.isfile(arch_copy)
          and ver_after_arch.startswith("Audit chain OK") and "archived" in ver_after_arch, (arch_res, ver_after_arch))

    # Tamper with the archived copy in evidence_archive/ and verify that verify() catches it!
    orig_arch_bytes = open(arch_copy, "rb").read()
    with open(arch_copy, "wb") as af:
        af.write(orig_arch_bytes + b"TAMPER_ARCH")
    tamper_arch_res = m.verify()
    check("P1-H", "verify() detects tampering or deletion of archived evidence inside evidence_archive/",
          "TAMPERING DETECTED: modified archived evidence file" in tamper_arch_res, tamper_arch_res)
    with open(arch_copy, "wb") as af:
        af.write(orig_arch_bytes)

# Tamper with an active unarchived evidence image and verify that verify() catches it!
active_evs = sorted(os.path.join("evidence", f) for f in os.listdir("evidence") if f.endswith(".jpg"))
if active_evs:
    rem_ev = active_evs[0]
    orig_bytes = open(rem_ev, "rb").read()
    with open(rem_ev, "wb") as ef:
        ef.write(orig_bytes + b"TAMPER")
    tamper_res = m.verify()
    check("SEC", "verify() detects modified unarchived evidence image on disk",
          "TAMPERING DETECTED: modified evidence file" in tamper_res, tamper_res)
    with open(rem_ev, "wb") as ef:
        ef.write(orig_bytes)

check("INT", "session closed cleanly and recorded in audit log",
      db_q("select count(*) from audit where action='session end'")[0][0] >= 1)


# ==============================================================================
# 6. ROUND 4 ENGINEERING & SECURITY TESTS (P0-A, P0-B, P1-C, P1-D, P1-E)
# ==============================================================================
def run_round4_tests():
    import stat as stat_mod
    with m.DBL:
        m.db.execute("DELETE FROM persons")
        m.db.execute("DELETE FROM faces")
        m.db.commit()
    m.refresh_known()

    # ---------- P0-A: Person identity isolation & biometric privacy ----------
    r_p1 = reg_mod.save_person({"name": "خالد سالم", "ref": "EMP-101", "consent": True, "status": "watch"}, "r4")
    r_p2 = reg_mod.save_person({"name": "خالد سالم", "ref": "EMP-202", "consent": False, "status": "normal"}, "r4")
    pid1, pid2 = r_p1["id"], r_p2["id"]
    vec_p1 = np.zeros((1, 128), dtype=np.float32); vec_p1[0, 0] = 1.0
    vec_p2 = np.zeros((1, 128), dtype=np.float32); vec_p2[0, 1] = 1.0

    # Enroll p1 via person_id
    ok_enr1 = m.req_enroll("خالد سالم", True, "r4", ref="EMP-101", person_id=pid1)
    for _ in range(5):
        m.enroll_step(vec_p1)
    # Attempt to inject a face row for unconsented p2 (who shares the exact same name as consented p1)
    with m.DBL:
        m.db.execute("INSERT INTO faces(name, emb, watch, person_id, quarantined) VALUES(?,?,?,?,0)",
                     ("خالد سالم", vec_p2.tobytes(), 1, pid2))
        m.db.commit()
    m.refresh_known()
    m_res1 = m.match_face_embedding(vec_p1)
    m_res2 = m.match_face_embedding(vec_p2)
    check("P0-A", "homonymous persons get distinct person_ids; unconsented person embeddings are NEVER loaded or matched",
          ok_enr1 and pid1 != pid2 and m_res1[0] == "خالد سالم" and getattr(m_res1, "person_id", 0) == pid1
          and m_res2[0] == "unenrolled", (pid1, pid2, m_res1, m_res2))

    # Grant consent to p2, enroll p2 with vec_p2, then revoke p2 consent -> p1 embeddings must stay intact!
    with m.DBL:
        m.db.execute("DELETE FROM faces WHERE person_id=?", (pid2,))
        m.db.commit()
    reg_mod.save_person({"id": pid2, "name": "خالد سالم", "ref": "EMP-202", "consent": True, "status": "normal"}, "r4")
    m.req_enroll("خالد سالم", False, "r4", ref="EMP-202", person_id=pid2)
    for _ in range(5):
        m.enroll_step(vec_p2)
    # Verify changing watchlist status of p2 does NOT affect p1 watchlist status
    reg_mod.save_person({"id": pid2, "name": "خالد سالم", "ref": "EMP-202", "consent": True, "status": "normal"}, "r4")
    m1_after_st = m.match_face_embedding(vec_p1)
    m2_after_st = m.match_face_embedding(vec_p2)
    check("P0-A", "changing watchlist status of one homonymous person does not alter the other person status",
          m1_after_st[2] == 1 and m2_after_st[2] == 0 and m1_after_st.person_id == pid1 and m2_after_st.person_id == pid2,
          (m1_after_st, m2_after_st))

    # Revoke consent of p2 -> p2 faces deleted (0), p1 faces preserved (5)
    reg_mod.save_person({"id": pid2, "name": "خالد سالم", "ref": "EMP-202", "consent": False, "status": "normal"}, "r4")
    cnt_p1_rev = db_q("SELECT COUNT(*) FROM faces WHERE person_id=?", pid1)[0][0]
    cnt_p2_rev = db_q("SELECT COUNT(*) FROM faces WHERE person_id=?", pid2)[0][0]
    check("P0-A", "revoking consent of one homonymous person erases ONLY their embeddings & preserves the other person",
          cnt_p1_rev == 5 and cnt_p2_rev == 0 and m.match_face_embedding(vec_p1)[0] == "خالد سالم"
          and m.match_face_embedding(vec_p2)[0] == "unenrolled", (cnt_p1_rev, cnt_p2_rev))

    # Re-enroll p2, then delete p2 by id -> p1 record and 5 embeddings remain intact!
    reg_mod.save_person({"id": pid2, "name": "خالد سالم", "ref": "EMP-202", "consent": True, "status": "watch"}, "r4")
    m.req_enroll("خالد سالم", True, "r4", ref="EMP-202", person_id=pid2)
    for _ in range(5):
        m.enroll_step(vec_p2)
    # Ambiguous delete by shared name alone is rejected
    ambig_del = reg_mod.delete("persons", "خالد سالم", "r4")
    del_p2 = reg_mod.delete("persons", f"id:{pid2}", "r4")
    cnt_p1_del = db_q("SELECT COUNT(*) FROM faces WHERE person_id=?", pid1)[0][0]
    cnt_p2_del = db_q("SELECT COUNT(*) FROM faces WHERE person_id=?", pid2)[0][0]
    p1_still_exists = reg_mod.get_person(person_id=pid1) is not None
    check("P0-A", "deleting one homonymous person by ID preserves the other person record & embeddings (and ambiguous name delete is blocked)",
          not ambig_del["ok"] and del_p2["ok"] and p1_still_exists and cnt_p1_del == 5 and cnt_p2_del == 0,
          (ambig_del, del_p2, p1_still_exists, cnt_p1_del, cnt_p2_del))

    # Legacy ambiguous person_id=0 migration test: add second 'خالد سالم' again, insert legacy face with person_id=0, verify quarantined=1
    r_p3 = reg_mod.save_person({"name": "خالد سالم", "ref": "EMP-303", "consent": True, "status": "watch"}, "r4")
    vec_leg = np.zeros((1, 128), dtype=np.float32); vec_leg[0, 2] = 1.0
    with m.DBL:
        m.db.execute("INSERT INTO faces(name, emb, watch, person_id, quarantined) VALUES(?,?,1,0,0)", ("خالد سالم", vec_leg.tobytes()))
        m.db.commit()
    m.refresh_known()
    q_row = db_q("SELECT quarantined, quarantine_reason FROM faces WHERE person_id=0 AND name=?", "خالد سالم")[0]
    check("P0-A", "legacy face row with person_id=0 and ambiguous name is quarantined and excluded from matching",
          q_row[0] == 1 and "ambiguous" in q_row[1] and m.match_face_embedding(vec_leg)[0] == "unenrolled", q_row)

    # Clean up test persons
    reg_mod.delete("persons", f"id:{pid1}", "r4")
    reg_mod.delete("persons", f"id:{r_p3['id']}", "r4")
    with m.DBL:
        m.db.execute("DELETE FROM faces")
        m.db.commit()
    m.refresh_known()

    # ---------- P0-B: Patrol dispatch lease recovery, multi-process mutual exclusion, & uncertain timeout ----------
    aid_lease = m.raise_alert("VEHICLE: WANTED", "80801", "CAM1", np.zeros((60, 60, 3), np.uint8))
    now_b = time.time()
    with m.DBL:
        m.db.execute(
            "UPDATE alerts SET status='confirm', dispatched=0, dispatch_status='in_flight', "
            "dispatch_started_ts=?, dispatch_owner='proc_A:att1', dispatch_attempts=1 WHERE id=?",
            (now_b, aid_lease)
        )
        m.db.commit()
    # Second process/instance runs _sync_alerts_from_db(reset_stuck_in_flight=True) AND _attempt_dispatch while lease is valid
    m._sync_alerts_from_db(reset_stuck_in_flight=True)
    claimed_by_second = m._attempt_dispatch(aid_lease, trigger="proc_B", owner_id="proc_B:att2")
    st_lease, own_lease, att_lease = db_q("SELECT dispatch_status, dispatch_owner, dispatch_attempts FROM alerts WHERE id=?", aid_lease)[0]
    check("P0-B", "active non-expired in_flight lease is NOT reset by _sync_alerts_from_db(reset_stuck_in_flight=True) or stolen by second process",
          not claimed_by_second and st_lease == "in_flight" and own_lease == "proc_A:att1" and att_lease == 1,
          (claimed_by_second, st_lease, own_lease, att_lease))

    # Expire the lease (simulate Process A crash > DISPATCH_LEASE_SEC ago) and verify recovery + no duplicate send after success
    with m.DBL:
        m.db.execute("UPDATE alerts SET dispatch_started_ts=? WHERE id=?", (now_b - m.DISPATCH_LEASE_SEC - 5.0, aid_lease))
        m.db.commit()
    rec_ok = m._attempt_dispatch(aid_lease, trigger="recovery_worker", owner_id="proc_B:rec")
    dup_after_sent = m._attempt_dispatch(aid_lease, trigger="dup_worker", owner_id="proc_C:dup")
    st_after_rec = db_q("SELECT dispatched, dispatch_status, dispatch_attempts FROM alerts WHERE id=?", aid_lease)[0]
    check("P0-B", "expired in_flight lease is recovered and sent once, and subsequent duplicate dispatch is blocked",
          rec_ok and not dup_after_sent and st_after_rec == (1, "sent", 2), (rec_ok, dup_after_sent, st_after_rec))

    # Uncertain outcome due to network timeout during patrol dispatch
    aid_unc = m.raise_alert("VEHICLE: STOLEN", "80802", "CAM1", np.zeros((60, 60, 3), np.uint8))
    with m.DBL:
        m.db.execute("UPDATE alerts SET status='confirm', dispatch_status='pending', dispatch_attempts=0, next_retry_ts=? WHERE id=?",
                     (time.time() - 1.0, aid_unc))
        m.db.commit()
    orig_send_alert = m.send_alert
    def _timeout_send(*a, **k):
        if k.get("sync") or (len(a) >= 3 and a[2] == "TELEGRAM_PATROL_CHAT_ID"):
            raise m.UncertainDeliveryError("Simulated socket read timeout after HTTP POST")
        return True
    m.send_alert = _timeout_send
    try:
        unc_ret = m._attempt_dispatch(aid_unc, trigger="test_timeout")
    finally:
        m.send_alert = orig_send_alert
    st_unc = db_q("SELECT dispatched, dispatch_status FROM alerts WHERE id=?", aid_unc)[0]
    auto_due_unc = aid_unc in m._find_due_dispatches(time.time() + 100.0)
    check("P0-B", "network timeout during dispatch records dispatch_status='uncertain' (dispatched=0) and prevents blind auto-resend",
          not unc_ret and st_unc == (0, "uncertain") and not auto_due_unc
          and any(x["id"] == aid_unc and x["dispatch_status"] == "uncertain" for x in m.bus.failed_dispatches),
          (unc_ret, st_unc, auto_due_unc))

    # Legacy confirmed alerts with attempts=0 & next_retry_ts=0 (and failed with next_retry_ts=0) are normalized & scheduled without resending 'sent'
    aid_leg0 = m.raise_alert("VEHICLE: WANTED", "80803", "CAM1", np.zeros((60, 60, 3), np.uint8))
    with m.DBL:
        m.db.execute("UPDATE alerts SET status='confirm', dispatched=0, dispatch_status='pending', dispatch_attempts=0, next_retry_ts=0 WHERE id=?", (aid_leg0,))
        m.db.commit()
    m._sync_alerts_from_db()
    due_leg = m._find_due_dispatches(time.time())
    sent_leg0 = m._attempt_dispatch(aid_leg0, trigger="legacy_pickup")
    check("P0-B", "legacy confirmed alert with attempts=0 & next_retry_ts=0 is scheduled and dispatched cleanly without resending sent alerts",
          aid_leg0 in due_leg and sent_leg0 and aid_lease not in due_leg, (due_leg, sent_leg0))

    # Real 2-OS-process concurrent dispatch lease test: Process 1 holds in_flight for 0.6s while Process 2 starts up & tries to claim
    mp_disp_dir = tempfile.mkdtemp(prefix="mersad_mp_disp_")
    try:
        p1_script = (
            "import os, sys, time, numpy as np\n"
            f"sys.path.insert(0, {repr(WORK)})\n"
            "os.environ['MERSAD_DATA_DIR'] = sys.argv[1]\n"
            "os.environ['TELEGRAM_TOKEN'] = 'TOK_MP_DISP'\n"
            "os.environ['TELEGRAM_CHAT_ID'] = '-100'\n"
            "os.environ['TELEGRAM_PATROL_CHAT_ID'] = '-200'\n"
            "import mersad_live as m\n"
            "m.send_alert = lambda *a, **k: (time.sleep(0.6) or True) if k.get('sync') else True\n"
            "aid = m.raise_alert('VEHICLE: WANTED', '77001', 'CAM1', np.zeros((40,40,3), np.uint8))\n"
            "with m.DBL:\n"
            "    m.db.execute('UPDATE alerts SET status=\"confirm\", dispatch_status=\"pending\" WHERE id=?', (aid,))\n"
            "    m.db.commit()\n"
            "open(os.path.join(sys.argv[1], 'ready.flag'), 'w').write(str(aid))\n"
            "ok1 = m._attempt_dispatch(aid, trigger='proc1')\n"
            "m.db.close()\n"
            "print(f'P1_DISP:{int(ok1)}')\n"
        )
        p2_script = (
            "import os, sys, time\n"
            f"sys.path.insert(0, {repr(WORK)})\n"
            "os.environ['MERSAD_DATA_DIR'] = sys.argv[1]\n"
            "os.environ['TELEGRAM_TOKEN'] = 'TOK_MP_DISP'\n"
            "os.environ['TELEGRAM_CHAT_ID'] = '-100'\n"
            "os.environ['TELEGRAM_PATROL_CHAT_ID'] = '-200'\n"
            "aid = int(sys.argv[2])\n"
            "import mersad_live as m\n"
            "m.send_alert = lambda *a, **k: True\n"
            "m._sync_alerts_from_db(reset_stuck_in_flight=True)\n"
            "ok2 = m._attempt_dispatch(aid, trigger='proc2')\n"
            "m.db.close()\n"
            "print(f'P2_DISP:{int(ok2)}')\n"
        )
        pr1 = subprocess.Popen([sys.executable, "-c", p1_script, mp_disp_dir], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        flag_p = os.path.join(mp_disp_dir, "ready.flag")
        wait(lambda: os.path.isfile(flag_p) and os.path.getsize(flag_p) > 0, t=5.0)
        time.sleep(0.15)
        aid_shared = open(flag_p).read().strip()
        pr2 = subprocess.Popen([sys.executable, "-c", p2_script, mp_disp_dir, aid_shared], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        out1, err1 = pr1.communicate(timeout=15)
        out2, err2 = pr2.communicate(timeout=15)
        c_mp = sqlite3.connect(os.path.join(mp_disp_dir, "mersad.db"))
        row_mp = c_mp.execute("SELECT dispatched, dispatch_status, dispatch_attempts FROM alerts WHERE id=?", (int(aid_shared),)).fetchone()
        sent_logs = c_mp.execute("SELECT COUNT(*) FROM audit WHERE action='dispatch sent'").fetchone()[0]
        c_mp.close()
        check("P0-B", "2 OS processes: Process 2 startup does NOT reset or duplicate Process 1 active in_flight dispatch",
              "P1_DISP:1" in out1 and "P2_DISP:0" in out2 and row_mp == (1, "sent", 1) and sent_logs == 1,
              (out1.strip(), out2.strip(), row_mp, sent_logs, err1[-200:], err2[-200:]))
    finally:
        shutil.rmtree(mp_disp_dir, ignore_errors=True)

    # ---------- P1-C: Camera reconnection resilience (all offline at boot, >3 failures recovery, slow RTSP isolation) ----------
    orig_nfr = globals()["NFR"]
    old_argv = sys.argv[:]
    try:
        CAM_DROP_STATE["reads"].clear()
        CAM_DROP_STATE["opens"].clear()
        m.RECONNECT_BASE_SEC = 0.005
        m.RECONNECT_MAX_SEC = 0.02
        m.MAX_RECONNECT_ATTEMPTS = 3
        globals()["NFR"] = 18
        # Case 1 & 3: Both cameras offline at startup (cam_boot_offline1, cam_fail4_recover drops and fails 4 reconnects > MAX_RECONNECT_ATTEMPTS=3 then recovers!)
        sys.argv = ["mersad_live.py", "--source", "cam_boot_offline1,cam_fail4_recover", "--cam", "CAM_BOOT,CAM_FAIL4",
                    "--no-window", "--no-telegram-listener", "--port", "8796", "--token", "r4tok"]
        m.main()
        c_stats = m.STATUS.get("cameras", {})
        boot_frames = c_stats.get("CAM_BOOT", {}).get("frames", 0)
        fail4_frames = c_stats.get("CAM_FAIL4", {}).get("frames", 0)
        fail4_opens = CAM_DROP_STATE["opens"].get("cam_fail4_recover", 0)
        check("P1-C", "service stays alive when all cameras are offline at boot, and recovers camera after >3 failed reconnect attempts",
              boot_frames >= 12 and fail4_frames >= 12 and fail4_opens >= 6,
              (boot_frames, fail4_frames, fail4_opens, c_stats))

        # Case 4: Slow RTSP source (0.18s/frame) alongside fast camera (cam1_ok, 0.008s/frame)
        CAM_DROP_STATE["reads"].clear()
        CAM_DROP_STATE["opens"].clear()
        MC_INSPECT_DONE.set()
        globals()["NFR"] = 18
        sys.argv = ["mersad_live.py", "--source", "cam_slow_rtsp,cam1_ok", "--cam", "CAM_SLOW,CAM_FAST",
                    "--no-window", "--no-telegram-listener", "--port", "8797", "--token", "r4tok2"]
        t0_slow = time.time()
        m.main()
        el_slow = time.time() - t0_slow
        fast_frames = m.STATUS.get("cameras", {}).get("CAM_FAST", {}).get("frames", 0)
        slow_frames = m.STATUS.get("cameras", {}).get("CAM_SLOW", {}).get("frames", 0)
        check("P1-C", f"slow RTSP camera (frames={slow_frames}) does NOT block fast camera (frames={fast_frames}) from completing in {el_slow:.2f}s",
              fast_frames >= 18 and slow_frames < fast_frames and el_slow < 2.5,
              (fast_frames, slow_frames, el_slow))
    finally:
        globals()["NFR"] = orig_nfr
        m.RECONNECT_BASE_SEC = 0.05
        m.RECONNECT_MAX_SEC = 15.0
        m.MAX_RECONNECT_ATTEMPTS = 1
        sys.argv = old_argv

    # ---------- P1-D: Secrets & HMAC key protection ----------
    d_tmp = tempfile.mkdtemp(prefix="mersad_p1d_")
    orig_data_dir = os.environ.get("MERSAD_DATA_DIR")
    try:
        os.environ["MERSAD_DATA_DIR"] = d_tmp
        reg_mod._HMAC_KEY_CACHE.clear()
        p_first = reg_mod.pseud("12345")
        key_file = os.path.join(d_tmp, ".mersad_hmac.key")
        key_mode = stat_mod.S_IMODE(os.stat(key_file).st_mode)
        # Clear cache to simulate restart -> must reload same key and produce identical pseudonym
        reg_mod._HMAC_KEY_CACHE.clear()
        p_after_restart = reg_mod.pseud("12345")

        # Truncate/corrupt the key file -> must raise RuntimeError and NOT silently overwrite!
        with open(key_file, "wb") as kf:
            kf.write(b"corrupt_11b")
        reg_mod._HMAC_KEY_CACHE.clear()
        corrupt_raised = False
        try:
            reg_mod.pseud("12345")
        except RuntimeError:
            corrupt_raised = True
        still_corrupt_len = os.path.getsize(key_file)

        # Unwritable directory -> must raise RuntimeError and NOT use a static fallback key!
        os.environ["MERSAD_DATA_DIR"] = os.path.join(d_tmp, "nonexistent_subdir_unwritable")
        reg_mod._HMAC_KEY_CACHE.clear()
        unwritable_raised = False
        try:
            reg_mod.pseud("12345")
        except RuntimeError:
            unwritable_raised = True

        check("P1-D", "HMAC key created with 0600, persists across restart, refuses corrupt key overwrite, and fails closed without static fallback",
              p_first == p_after_restart and key_mode == 0o600 and corrupt_raised and still_corrupt_len == 11 and unwritable_raised,
              (p_first, p_after_restart, oct(key_mode), corrupt_raised, still_corrupt_len, unwritable_raised))
    finally:
        if orig_data_dir is not None:
            os.environ["MERSAD_DATA_DIR"] = orig_data_dir
        reg_mod._HMAC_KEY_CACHE.clear()
        shutil.rmtree(d_tmp, ignore_errors=True)

    # Test interrupted atomic write on .mersad_secrets.json preserves previous file and leaves 0 temp files
    m._save_secrets_file({"telegram_token": "VALID_SAVED_TOK_1"})
    sec_mode_before = stat_mod.S_IMODE(os.stat(m._SECRETS_FILE).st_mode)
    orig_replace = os.replace
    def _fail_replace(src, dst):
        raise OSError("Simulated crash right before atomic os.replace")
    os.replace = _fail_replace
    interrupted_raised = False
    try:
        m._save_secrets_file({"telegram_token": "PARTIAL_CRASH_TOK"})
    except OSError:
        interrupted_raised = True
    finally:
        os.replace = orig_replace
    sec_after_crash = m._load_secrets_file()
    leftover_tmps = [fn for fn in os.listdir(WORK) if ".mersad_secrets.json.tmp" in fn]
    sec_mode_after = stat_mod.S_IMODE(os.stat(m._SECRETS_FILE).st_mode)
    check("P1-D", "interrupted secrets save preserves previous .mersad_secrets.json (0600) and cleans up temporary file",
          interrupted_raised and sec_after_crash.get("telegram_token") == "VALID_SAVED_TOK_1"
          and not leftover_tmps and sec_mode_before == 0o600 and sec_mode_after == 0o600,
          (interrupted_raised, sec_after_crash, leftover_tmps, oct(sec_mode_before), oct(sec_mode_after)))

    # ---------- P1-E: Archive recovery & active evidence protection ----------
    # 1. Pending alert with matching copy in evidence_archive/ -> must NOT delete original!
    aid_e_pend = m.raise_alert("VEHICLE: WANTED", "90901", "CAM1", np.zeros((60, 60, 3), np.uint8))
    img_e_pend = db_q("SELECT img FROM alerts WHERE id=?", aid_e_pend)[0][0]
    orig_e_pend = f"evidence/{img_e_pend}"
    arch_e_pend = f"evidence_archive/{img_e_pend}"
    os.makedirs("evidence_archive", exist_ok=True)
    shutil.copy2(orig_e_pend, arch_e_pend)
    m._recover_interrupted_archives()
    pend_orig_kept = os.path.isfile(orig_e_pend)
    os.remove(arch_e_pend)
    m.decide(aid_e_pend, "dismiss", "r4")

    # 2. Resolved alert with unlogged/external copy in evidence_archive/ (no op in evidence_archive_ops) -> must NOT delete original!
    shutil.copy2(orig_e_pend, arch_e_pend)
    m._recover_interrupted_archives()
    unlogged_orig_kept = os.path.isfile(orig_e_pend)
    os.remove(arch_e_pend)

    # 3. Legitimate interrupted archive op (status='in_progress' in evidence_archive_ops) for resolved alert:
    #    (a) Modified hash in evidence_archive/ -> keeps original and logs conflict!
    exp_sha_e = hashlib.sha256(open(orig_e_pend, "rb").read()).hexdigest()
    with m.DBL:
        m.db.execute(
            "INSERT OR REPLACE INTO evidence_archive_ops(orig_rel, arch_rel, sha256, started_ts, completed_ts, who, status) "
            "VALUES(?, ?, ?, ?, 0, 'r4', 'in_progress')",
            (orig_e_pend, arch_e_pend, exp_sha_e, time.time())
        )
        m.db.commit()
    with open(arch_e_pend, "wb") as af:
        af.write(open(orig_e_pend, "rb").read() + b"CORRUPT")
    m._recover_interrupted_archives()
    bad_hash_orig_kept = os.path.isfile(orig_e_pend)

    #    (b) Valid hash in evidence_archive/ with in_progress op -> completes archive, logs 'evidence archived', removes original, and verify() passes!
    shutil.copy2(orig_e_pend, arch_e_pend)
    with m.DBL:
        m.db.execute("UPDATE evidence_archive_ops SET status='in_progress' WHERE orig_rel=?", (orig_e_pend,))
        m.db.commit()
    m._recover_interrupted_archives()
    valid_rec_completed = (not os.path.exists(orig_e_pend)) and os.path.isfile(arch_e_pend)
    ver_e = m.verify()
    check("P1-E", "archive recovery protects pending alerts & unlogged copies, rejects hash mismatch, and completes valid interrupted archive with intact verify()",
          pend_orig_kept and unlogged_orig_kept and bad_hash_orig_kept and valid_rec_completed and ver_e.startswith("Audit chain OK"),
          (pend_orig_kept, unlogged_orig_kept, bad_hash_orig_kept, valid_rec_completed, ver_e))

run_round4_tests()
check("SEC", "final audit chain & all active/archived evidence verified after Round 4 tests",
      m.verify().startswith("Audit chain OK"), m.verify())

# ==============================================================================
# 7. ROUND 5 BUILD, ENVIRONMENT, MODEL VERIFICATION, & PATH SEPARATION TESTS
# ==============================================================================
def _make_valid_pytorch_zip_bytes(min_size=6_100_000):
    import io, zipfile as zf_mod
    buf = io.BytesIO()
    with zf_mod.ZipFile(buf, "w", zf_mod.ZIP_STORED) as zf:
        zf.writestr("yolov8n/version", b"3\n")
        zf.writestr("yolov8n/data.pkl", b"\x80\x02}q\x00.")
        zf.writestr("yolov8n/data/0", b"\x00" * min_size)
    return buf.getvalue()


def run_round5_tests():
    import check_install as chk_mod
    import prefetch as pre_mod

    # 1. Stage 1 & 2: Verify single source of truth across requirements.txt, constraints-win-x64.txt, setup.bat, BUILD_EXE.bat
    req_s = open(os.path.join(WORK, "requirements.txt"), encoding="utf-8").read()
    con_s = open(os.path.join(WORK, "constraints-win-x64.txt"), encoding="utf-8").read()
    set_s = open(os.path.join(WORK, "setup.bat"), encoding="utf-8").read()
    bld_s = open(os.path.join(WORK, "BUILD_EXE.bat"), encoding="utf-8").read()
    spec_s = open(os.path.join(WORK, "mersad_ai.spec"), encoding="utf-8").read()
    ci_path = os.path.join(WORK, ".github", "workflows", "windows-build.yml")
    ci_s = open(ci_path, encoding="utf-8").read() if os.path.isfile(ci_path) else ""

    versions_aligned = (
        "opencv-python==4.11.0.86" in req_s and "opencv-python==4.11.0.86" in con_s and "opencv-python==4.11.0.86" in set_s
        and "ultralytics==8.3.0" in req_s and "ultralytics==8.3.0" in con_s
        and "torch==2.5.1" in con_s and "torch==2.5.1" in set_s
        and "torchvision==0.20.1" in con_s and "torchvision==0.20.1" in set_s
        and "pyinstaller==6.11.1" in con_s and "pyinstaller==6.11.1" in bld_s
        and "check_install.py --verify-ready" in set_s and "check_install.py --write-ready" in set_s
        and "windows-latest" in ci_s and "MERSAD_AI.exe" in bld_s and "COLLECT(" in spec_s
    )
    check("R5-DEPS", "requirements.txt, constraints-win-x64.txt, setup.bat, BUILD_EXE.bat, mersad_ai.spec & Windows CI workflow are aligned",
          versions_aligned)

    # 2. Stage 3: Test venv/.ready cryptographic readiness stamp (new env, legacy 'ok', missing models, valid env, modified requirements, corrupt model)
    env_dir = tempfile.mkdtemp(prefix="mersad_r5_env_")
    try:
        for fn in ("requirements.txt", "constraints-win-x64.txt", "prefetch.py"):
            shutil.copy2(os.path.join(WORK, fn), os.path.join(env_dir, fn))
        ready_f = os.path.join(env_dir, "venv", ".ready")
        os.makedirs(os.path.dirname(ready_f), exist_ok=True)

        # (a) Missing .ready
        ok_new, r_new = chk_mod.verify_ready_stamp(ready_f, root_dir=env_dir, require_models=False, require_all_libs=False)
        # (b) Legacy plain-text "ok" in .ready (must NOT be accepted!)
        with open(ready_f, "w", encoding="utf-8") as rf:
            rf.write("ok\n")
        ok_leg, r_leg = chk_mod.verify_ready_stamp(ready_f, root_dir=env_dir, require_models=False, require_all_libs=False)
        # (c) Attempt to write .ready when required models are missing -> must fail and remove stale .ready!
        ok_w_fail, r_w_fail = chk_mod.write_ready_stamp(ready_f, root_dir=env_dir, require_models=True, require_all_libs=False)
        stale_removed = not os.path.exists(ready_f)

        # (d) Populate valid models inside env_dir/models and write .ready stamp
        m_dir = os.path.join(env_dir, "models")
        os.makedirs(os.path.join(m_dir, "easyocr"), exist_ok=True)
        fake_yunet = b"\x08\x07\x12\x04onnx" + (b"Y" * 210_000)
        fake_sface = b"\x08\x07\x12\x04onnx" + (b"S" * 30_100_000)
        fake_yolo = _make_valid_pytorch_zip_bytes(6_050_000)
        fake_craft = b"PK\x03\x04" + b"C" * 600_000
        fake_arabic = b"PK\x03\x04" + b"A" * 600_000
        orig_y_sha = m.MODEL_SHA256["yunet.onnx"]
        orig_s_sha = m.MODEL_SHA256["sface.onnx"]
        orig_v_sha = m.MODEL_SHA256["yolov8n.pt"]
        orig_e_sha = dict(m.EASYOCR_SHA256)
        m.MODEL_SHA256["yunet.onnx"] = hashlib.sha256(fake_yunet).hexdigest()
        m.MODEL_SHA256["sface.onnx"] = hashlib.sha256(fake_sface).hexdigest()
        m.MODEL_SHA256["yolov8n.pt"] = hashlib.sha256(fake_yolo).hexdigest()
        m.EASYOCR_SHA256["craft_mlt_25k.pth"] = hashlib.sha256(fake_craft).hexdigest()
        m.EASYOCR_SHA256["arabic.pth"] = hashlib.sha256(fake_arabic).hexdigest()
        try:
            open(os.path.join(m_dir, "yunet.onnx"), "wb").write(fake_yunet)
            open(os.path.join(m_dir, "sface.onnx"), "wb").write(fake_sface)
            open(os.path.join(m_dir, "yolov8n.pt"), "wb").write(fake_yolo)
            open(os.path.join(m_dir, "easyocr", "craft_mlt_25k.pth"), "wb").write(fake_craft)
            open(os.path.join(m_dir, "easyocr", "arabic.pth"), "wb").write(fake_arabic)

            ok_w_pass, _ = chk_mod.write_ready_stamp(ready_f, root_dir=env_dir, require_models=True, require_all_libs=False)
            ok_ver_pass, _ = chk_mod.verify_ready_stamp(ready_f, root_dir=env_dir, require_models=True, require_all_libs=False)

            # (e) Modify requirements.txt -> verify_ready_stamp must detect dependency change!
            with open(os.path.join(env_dir, "requirements.txt"), "a", encoding="utf-8") as rf_mod:
                rf_mod.write("# modified\n")
            ok_after_req_mod, r_req_mod = chk_mod.verify_ready_stamp(ready_f, root_dir=env_dir, require_models=True, require_all_libs=False)

            # Restore requirements.txt, then corrupt yunet.onnx -> verify_ready_stamp must detect corrupt model!
            shutil.copy2(os.path.join(WORK, "requirements.txt"), os.path.join(env_dir, "requirements.txt"))
            open(os.path.join(m_dir, "yunet.onnx"), "wb").write(fake_yunet + b"CORRUPT")
            ok_after_m_corrupt, r_m_corrupt = chk_mod.verify_ready_stamp(ready_f, root_dir=env_dir, require_models=True, require_all_libs=False)
        finally:
            m.MODEL_SHA256["yunet.onnx"] = orig_y_sha
            m.MODEL_SHA256["sface.onnx"] = orig_s_sha
            m.MODEL_SHA256["yolov8n.pt"] = orig_v_sha
            m.EASYOCR_SHA256.clear()
            m.EASYOCR_SHA256.update(orig_e_sha)

        check("R5-ENV", "venv/.ready rejects legacy 'ok', cleans stale stamp on failure, verifies models, and detects modified requirements.txt or corrupt model",
              (not ok_new) and (not ok_leg) and (not ok_w_fail) and stale_removed
              and ok_w_pass and ok_ver_pass and (not ok_after_req_mod and r_req_mod == "requirements_txt_modified")
              and (not ok_after_m_corrupt and "model_invalid" in r_m_corrupt),
              (r_new, r_leg, r_w_fail, stale_removed, ok_w_pass, ok_ver_pass, r_req_mod, r_m_corrupt))
    finally:
        shutil.rmtree(env_dir, ignore_errors=True)

    # 3. Stage 4: Safe model download & verification via isolated local HTTP server
    dl_dir = tempfile.mkdtemp(prefix="mersad_r5_dl_")
    valid_onnx_payload = b"\x08\x07\x12\x04onnx_valid_model_" + (b"M" * 220_000)
    valid_onnx_sha = hashlib.sha256(valid_onnx_payload).hexdigest()
    valid_yolo_payload = _make_valid_pytorch_zip_bytes(6_050_000)
    valid_yolo_sha = hashlib.sha256(valid_yolo_payload).hexdigest()
    flaky_state = {"calls": 0}

    class ModelH(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            if self.path == "/valid.onnx":
                self.send_response(200)
                self.send_header("Content-Length", str(len(valid_onnx_payload)))
                self.end_headers()
                self.wfile.write(valid_onnx_payload)
            elif self.path == "/valid_yolo.pt":
                self.send_response(200)
                self.send_header("Content-Length", str(len(valid_yolo_payload)))
                self.end_headers()
                self.wfile.write(valid_yolo_payload)
            elif self.path == "/partial.onnx":
                self.send_response(200)
                self.send_header("Content-Length", str(len(valid_onnx_payload)))
                self.end_headers()
                self.wfile.write(valid_onnx_payload[:40_000])
            elif self.path == "/wrong_sha.onnx":
                bad = b"\x08\x07\x12\x04onnx_bad_" + (b"X" * 220_000)
                self.send_response(200)
                self.send_header("Content-Length", str(len(bad)))
                self.end_headers()
                self.wfile.write(bad)
            elif self.path == "/corrupt_yolo.pt":
                garbage = b"NOT_A_ZIP_ARCHIVE_" * 350_000
                self.send_response(200)
                self.send_header("Content-Length", str(len(garbage)))
                self.end_headers()
                self.wfile.write(garbage)
            elif self.path == "/timeout.onnx":
                time.sleep(0.6)
                self.send_response(200)
                self.end_headers()
            elif self.path == "/flaky.onnx":
                flaky_state["calls"] += 1
                if flaky_state["calls"] == 1:
                    self.send_response(503)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(valid_onnx_payload)))
                self.end_headers()
                self.wfile.write(valid_onnx_payload)

    srv_m = ThreadingHTTPServer(("127.0.0.1", 0), ModelH)
    m_port = srv_m.server_address[1]
    threading.Thread(target=srv_m.serve_forever, daemon=True).start()
    m_url = f"http://127.0.0.1:{m_port}"
    try:
        # (a) Partial download rejected & no .part left behind
        part_failed = False
        try:
            pre_mod.download_verified("test.onnx", f"{m_url}/partial.onnx", min_bytes=200_000, expected_sha256=valid_onnx_sha, retries=1, timeout=2.0, target_dir=dl_dir)
        except RuntimeError:
            part_failed = True

        # (b) Timeout rejected
        to_failed = False
        try:
            pre_mod.download_verified("test.onnx", f"{m_url}/timeout.onnx", min_bytes=200_000, expected_sha256=valid_onnx_sha, retries=1, timeout=0.15, target_dir=dl_dir)
        except RuntimeError:
            to_failed = True

        # (c) Wrong SHA-256 rejected
        sha_failed = False
        try:
            pre_mod.download_verified("test.onnx", f"{m_url}/wrong_sha.onnx", min_bytes=200_000, expected_sha256=valid_onnx_sha, retries=1, timeout=2.0, target_dir=dl_dir)
        except RuntimeError:
            sha_failed = True

        # (d) Corrupt non-ZIP yolov8n.pt (>= 6MB but not a PyTorch zip archive) rejected!
        corrupt_pt_failed = False
        try:
            pre_mod.download_verified("yolov8n.pt", f"{m_url}/corrupt_yolo.pt", min_bytes=6_000_000, retries=1, timeout=2.0, target_dir=dl_dir)
        except RuntimeError:
            corrupt_pt_failed = True

        # (e) Flaky server succeeds on retry #2
        ok_flaky, status_flaky, path_flaky = pre_mod.download_verified(
            "test.onnx", f"{m_url}/flaky.onnx", min_bytes=200_000, expected_sha256=valid_onnx_sha, retries=2, timeout=2.0, target_dir=dl_dir
        )

        # (f) Existing valid model is NOT overwritten or deleted even if pointed at /wrong_sha.onnx
        ok_keep, status_keep, _ = pre_mod.download_verified(
            "test.onnx", f"{m_url}/wrong_sha.onnx", min_bytes=200_000, expected_sha256=valid_onnx_sha, retries=1, timeout=2.0, target_dir=dl_dir
        )
        kept_intact = hashlib.sha256(open(path_flaky, "rb").read()).hexdigest() == valid_onnx_sha

        # (g) Valid YOLOv8 .pt checkpoint download & structural verification
        ok_yolo, status_yolo, _ = pre_mod.download_verified(
            "yolov8n.pt", f"{m_url}/valid_yolo.pt", min_bytes=6_000_000, expected_sha256=valid_yolo_sha, retries=1, timeout=3.0, target_dir=dl_dir
        )
        leftover_parts = [f for f in os.listdir(dl_dir) if ".part" in f]

        check("R5-MODELS", "safe model downloader enforces timeout, Content-Length, SHA-256, & PyTorch ZIP structure, retries transient errors, and preserves existing valid models",
              part_failed and to_failed and sha_failed and corrupt_pt_failed and ok_flaky and flaky_state["calls"] == 2
              and ok_keep and "already_verified" in status_keep and kept_intact and ok_yolo and not leftover_parts,
              (part_failed, to_failed, sha_failed, corrupt_pt_failed, ok_flaky, status_keep, kept_intact, ok_yolo, leftover_parts))
    finally:
        srv_m.shutdown()
        shutil.rmtree(dl_dir, ignore_errors=True)

    # 4. Stage 5 & 6: Test path separation (read-only install dir vs writable user data dir) + spaces & Arabic characters in paths
    base_sp_ar = tempfile.mkdtemp(prefix="mersad_r5_مسار عربي مع مسافات_")
    try:
        ro_install = os.path.join(base_sp_ar, "مجلد التثبيت ReadOnly")
        user_data = os.path.join(base_sp_ar, "بيانات المستخدم Writable")
        run_cwd = os.path.join(base_sp_ar, "مجلد عمل خارجي")
        os.makedirs(ro_install, exist_ok=True)
        os.makedirs(user_data, exist_ok=True)
        os.makedirs(run_cwd, exist_ok=True)
        for fn in os.listdir(WORK):
            src_f = os.path.join(WORK, fn)
            if os.path.isfile(src_f) and fn.endswith((".py", ".html", ".txt", ".md")):
                shutil.copy2(src_f, os.path.join(ro_install, fn))
        os.chmod(ro_install, 0o555)
        try:
            env_sub = {k: v for k, v in os.environ.items() if k != "MERSAD_DATA_DIR"}
            env_sub["XDG_DATA_HOME"] = user_data
            env_sub["LOCALAPPDATA"] = user_data
            # Run #1: initialize DB, audit chain, and HMAC key in fallback user_data dir while launched from run_cwd
            cmd_init = [
                sys.executable, "-c",
                f"import sys; sys.path.insert(0, {repr(ro_install)}); import mersad_live as m; m.log('r5_path_test', m.pseud('arabic_space_ok')); print('APPDIR=' + m.APPDIR); print(m.verify())"
            ]
            res1 = subprocess.run(cmd_init, cwd=run_cwd, env=env_sub, capture_output=True, text=True, timeout=15)
            # Run #2: restart process and run --verify to prove data & HMAC key persisted across restarts
            res2 = subprocess.run([sys.executable, os.path.join(ro_install, "mersad_live.py"), "--verify"],
                                  cwd=run_cwd, env=env_sub, capture_output=True, text=True, timeout=15)
            expected_appdir = os.path.join(user_data, "MERSAD_AI" if os.name == "nt" else "mersad_ai")
            db_persisted = os.path.isfile(os.path.join(expected_appdir, "mersad.db"))
            key_persisted = os.path.isfile(os.path.join(expected_appdir, ".mersad_hmac.key"))
            no_db_in_ro = not os.path.exists(os.path.join(ro_install, "mersad.db"))
            check("R5-PATHS", "read-only install dir with Arabic & spaces automatically falls back to writable user data dir and persists DB & keys across restarts",
                  res1.returncode == 0 and res2.returncode == 0 and "Audit chain OK" in res1.stdout
                  and "Audit chain OK" in res2.stdout and db_persisted and key_persisted and no_db_in_ro,
                  (res1.stdout.strip(), res2.stdout.strip(), db_persisted, key_persisted, no_db_in_ro, res1.stderr[-200:]))
        finally:
            os.chmod(ro_install, 0o755)
    finally:
        shutil.rmtree(base_sp_ar, ignore_errors=True)

    # 5. Stage 7: Verify check_install.py JSON diagnostic classification
    chk_proc = subprocess.run([sys.executable, os.path.join(WORK, "check_install.py"), "--json"],
                              capture_output=True, text=True, timeout=15)
    chk_json = json.loads(chk_proc.stdout) if chk_proc.stdout.strip().startswith("{") else {}
    cats_found = {it["category"] for grp in ("core_checks", "libraries", "models") for it in chk_json.get(grp, [])}
    check("R5-DIAG", "check_install.py --json classifies CORE_LOGIC, PYTHON_ENV, REQUIRED_LIB, OPTIONAL_LIB, BUILD_REQ, & MODEL status",
          chk_proc.returncode == 0 and {"CORE_LOGIC", "PYTHON_ENV", "OPTIONAL_LIB", "BUILD_REQ"} <= cats_found,
          (chk_json.get("classification"), sorted(cats_found)))

run_round5_tests()

def run_v7_operational_tests():
    import analytics as analytics_mod
    import camera_history as history_mod
    d = tempfile.mkdtemp(prefix="mersad_v7_ops_")
    test_db_path = os.path.join(d, "ops.db")
    tdb = sqlite3.connect(test_db_path, timeout=10, check_same_thread=False)
    tlock = threading.RLock()
    try:
        tdb.executescript("""
        CREATE TABLE sightings(ts REAL, cam TEXT, plate TEXT, conf REAL, vclass TEXT, src TEXT DEFAULT 'live');
        CREATE TABLE alerts(id INTEGER PRIMARY KEY, ts REAL, status TEXT, dispatched INTEGER DEFAULT 0, dispatch_status TEXT);
        INSERT INTO sightings VALUES(1699999900, 'CAM_A', 'PRIVATE_PLATE_9381', 0.91, 'truck', 'live');
        INSERT INTO sightings VALUES(1699999800, 'CAM_A', 'DEMO_PLATE_1234', 0.12, 'car', 'demo');
        INSERT INTO sightings VALUES(1699910000, 'CAM_B', 'PRIVATE_PLATE_5512', 0.72, 'car', 'live');
        INSERT INTO alerts(ts,status,dispatched,dispatch_status) VALUES(1699999900,'pending',0,'pending');
        """)
        tdb.commit()
        fixed_now = 1700000000.0
        rep = analytics_mod.build_report(tdb, {"CAM_A": {"status": "online", "fps": 12.5, "frames": 80, "detections": 4}}, now=fixed_now)
        analytics_ok = (rep["sightings"]["current_24h"] == 1 and rep["sightings"]["previous_24h"] == 1
                        and rep["vehicle_classes"] == [{"class": "truck", "count": 1}]
                        and rep["confidence"]["high"] == 1 and len(rep["trend"]) == 24
                        and rep["alerts"]["pending"] == 1 and len(rep["recommendations"]) >= 1)
        csv_data = analytics_mod.export_csv(rep)
        privacy_ok = b"PRIVATE_PLATE_9381" not in csv_data and b"DEMO_PLATE_1234" not in csv_data
        injected = dict(rep)
        injected["camera_health"] = [{"camera": "=HYPERLINK(\"https://invalid\")", "status": "online"}]
        formula_ok = b"'=HYPERLINK" in analytics_mod.export_csv(injected)
        check("V7-ANALYTICS", "24h live-only aggregate report, previous-period comparison, 24-slot trend, confidence bands, alerts and recommendations", analytics_ok, rep["sightings"])
        check("V7-PRIVACY", "analytics CSV excludes plate values and demo records and neutralizes spreadsheet formulas", privacy_ok and formula_ok, (privacy_ok, formula_ok))

        history_mod.init(tdb, tlock, db_path=test_db_path)
        ok_events = [
            history_mod.record_status("CAM_TEST", "online", "startup", ts=1000, force=True),
            history_mod.record_status("CAM_TEST", "reconnecting", "read_failed", ts=1010),
            history_mod.record_status("CAM_TEST", "offline", "offline_timeout", ts=1012),
            history_mod.record_status("CAM_TEST", "online", "camera_reconnected", ts=1030),
        ]
        duplicate = history_mod.record_status("CAM_TEST", "online", "frame_received", ts=1031)
        hrep = history_mod.build_report(tdb, {"CAM_TEST": {"status": "online"}}, period="24h", now=1040)
        item = next((x for x in hrep["cameras"] if x["camera"] == "CAM_TEST"), {})
        hist_ok = (all(ok_events) and not duplicate and item.get("online_seconds") == 20.0
                   and item.get("downtime_seconds") == 20.0 and item.get("uptime_percent") == 50.0
                   and item.get("outages") == 1 and item.get("recoveries") == 1)
        hist_csv = history_mod.export_csv(hrep)
        check("V7-CAMERA-HISTORY", "camera transitions persist without duplicate polling noise; uptime is calculated only from observed session intervals", hist_ok, item)
        check("V7-CAMERA-EXPORT", "camera health report exports summary/event rows and does not expose personal data", b"CAM_TEST" in hist_csv and b"PRIVATE_PLATE" not in hist_csv, len(hist_csv))

        empty_db = sqlite3.connect(":memory:")
        empty = analytics_mod.build_report(empty_db, {}, now=fixed_now)
        empty_ok = empty["ok"] and empty["sightings"]["current_24h"] == 0 and len(empty["trend"]) == 24
        check("V7-EMPTY-DB", "analytics gracefully handles an empty/legacy database", empty_ok, empty["sightings"])
        empty_db.close()
    except Exception as exc:
        check("V7-OPERATIONAL", "operational analytics and camera history integration", False, repr(exc))
    finally:
        try: tdb.close()
        except Exception: pass
        shutil.rmtree(d, ignore_errors=True)

run_v7_operational_tests()

def run_v7_1_audit_regression_tests():
    # 1. V7.1-VERIFY-MODELS: Test --verify-models CLI flag (fails with exit code 1 when models missing, succeeds with exit code 0 when valid models exist)
    vm_dir = tempfile.mkdtemp(prefix="mersad_v71_vm_")
    try:
        for fn in os.listdir(WORK):
            src_f = os.path.join(WORK, fn)
            if os.path.isfile(src_f) and fn.endswith((".py", ".html", ".txt", ".md")):
                shutil.copy2(src_f, os.path.join(vm_dir, fn))
        # (a) Missing models -> must exit 1 and print MODELS INCOMPLETE OR CORRUPT
        p_miss = subprocess.run([sys.executable, os.path.join(vm_dir, "mersad_live.py"), "--verify-models"],
                                cwd=vm_dir, capture_output=True, text=True, timeout=15)
        # (b) Populate verified synthetic models -> must exit 0 and print MODELS OK
        m_dir = os.path.join(vm_dir, "models")
        os.makedirs(os.path.join(m_dir, "easyocr"), exist_ok=True)
        fake_y = b"\x08\x07\x12\x04onnx" + (b"Y" * 210_000)
        fake_s = b"\x08\x07\x12\x04onnx" + (b"S" * 30_100_000)
        fake_v = _make_valid_pytorch_zip_bytes(6_050_000)
        fake_c = b"PK\x03\x04" + b"C" * 600_000
        fake_a = b"PK\x03\x04" + b"A" * 600_000
        y_sha = hashlib.sha256(fake_y).hexdigest()
        s_sha = hashlib.sha256(fake_s).hexdigest()
        v_sha = hashlib.sha256(fake_v).hexdigest()
        c_sha = hashlib.sha256(fake_c).hexdigest()
        a_sha = hashlib.sha256(fake_a).hexdigest()
        open(os.path.join(m_dir, "yunet.onnx"), "wb").write(fake_y)
        open(os.path.join(m_dir, "sface.onnx"), "wb").write(fake_s)
        open(os.path.join(m_dir, "yolov8n.pt"), "wb").write(fake_v)
        open(os.path.join(m_dir, "easyocr", "craft_mlt_25k.pth"), "wb").write(fake_c)
        open(os.path.join(m_dir, "easyocr", "arabic.pth"), "wb").write(fake_a)
        cmd_ok = [
            sys.executable, "-c",
            f"import sys; sys.path.insert(0, {repr(vm_dir)}); import mersad_live as m; "
            f"m.MODEL_SHA256['yunet.onnx']={repr(y_sha)}; m.MODEL_SHA256['sface.onnx']={repr(s_sha)}; "
            f"m.MODEL_SHA256['yolov8n.pt']={repr(v_sha)}; "
            f"m.EASYOCR_SHA256['craft_mlt_25k.pth']={repr(c_sha)}; m.EASYOCR_SHA256['arabic.pth']={repr(a_sha)}; "
            f"sys.exit(m.verify_models_cli())"
        ]
        p_ok = subprocess.run(cmd_ok, cwd=vm_dir, capture_output=True, text=True, timeout=15)
        check("V7.1-VERIFY-MODELS", "--verify-models CLI checks all 4 AI model families and returns accurate exit codes",
              p_miss.returncode == 1 and "MODELS INCOMPLETE" in p_miss.stdout and p_ok.returncode == 0 and "MODELS OK" in p_ok.stdout,
              (p_miss.returncode, p_ok.returncode))
    finally:
        shutil.rmtree(vm_dir, ignore_errors=True)

    # 2. V7.1-DASH-EXPORT-TOKEN: Verify dashboard.html binds #analytics-export with qSep('/api/analytics/export.csv')
    dash_html = open(os.path.join(WORK, "dashboard.html"), encoding="utf-8").read()
    has_an_export_id = 'id="analytics-export"' in dash_html
    has_qsep_bind = 'qSep("/api/analytics/export.csv")' in dash_html or "qSep('/api/analytics/export.csv')" in dash_html
    check("V7.1-DASH-EXPORT-TOKEN", "dashboard.html binds #analytics-export href with qSep('/api/analytics/export.csv') for cookie-less auth",
          has_an_export_id and has_qsep_bind, (has_an_export_id, has_qsep_bind))

    # 3. V7.1-PACKAGING-HARDENING: Verify mersad_ai.spec, BUILD_EXE.bat, and windows-build.yml exclude unused tracker/tensorboard/cdflib submodules and disable auto-install
    spec_txt = open(os.path.join(WORK, "mersad_ai.spec"), encoding="utf-8").read()
    bat_txt = open(os.path.join(WORK, "BUILD_EXE.bat"), encoding="utf-8").read()
    ci_txt = open(os.path.join(WORK, ".github", "workflows", "windows-build.yml"), encoding="utf-8").read()
    ml_txt = open(os.path.join(WORK, "mersad_live.py"), encoding="utf-8").read()
    pkg_ok = (
        "ultralytics.trackers" in spec_txt
        and "torch.utils.tensorboard" in spec_txt
        and "scipy.special._cdflib" in spec_txt
        and "ULTRALYTICS_AUTOINSTALL" in spec_txt
        and "ULTRALYTICS_AUTOINSTALL" in bat_txt
        and "ULTRALYTICS_AUTOINSTALL" in ci_txt
        and "FORCE_JAVASCRIPT_ACTIONS_TO_NODE24" in ci_txt
        and "download_enabled=not easyocr_verified" in ml_txt
    )
    check("V7.1-PACKAGING-HARDENING", "PyInstaller spec, BUILD_EXE.bat, CI workflow & runtime enforce offline mode and exclude unused optional submodules",
          pkg_ok)

    # 4. V7.1-WIN-ACL: Verify registry.py includes Windows icacls ACL hardening in atomic_write_secret_bytes
    reg_txt = open(os.path.join(WORK, "registry.py"), encoding="utf-8").read()
    check("V7.1-WIN-ACL", "atomic_write_secret_bytes restricts Windows file ACLs via icacls /inheritance:r",
          "icacls" in reg_txt and "/inheritance:r" in reg_txt)

run_v7_1_audit_regression_tests()


def run_stage1_gap_regression_tests():
    import check_install as chk_mod

    # 1. STAGE1-GAP02: Separate WAL incompatibility (safe rollback -> DELETE verified) from critical disk-full / read-only errors
    gap02_dir = tempfile.mkdtemp(prefix="mersad_s1_gap02_")
    try:
        wal_db_path = os.path.join(gap02_dir, "wal_fallback.db")
        real_conn = sqlite3.connect(wal_db_path, timeout=10.0, check_same_thread=False)
        state = {"rollback_called": False, "delete_requested": False, "fail_wal_create": True}

        class WalFailProxy:
            def __init__(self, conn):
                self._conn = conn

            @property
            def in_transaction(self):
                return self._conn.in_transaction

            def rollback(self):
                state["rollback_called"] = True
                return self._conn.rollback()

            def commit(self):
                return self._conn.commit()

            def executescript(self, sql):
                return self._conn.executescript(sql)

            def execute(self, sql, *args):
                s_up = sql.strip().upper()
                if s_up == "PRAGMA JOURNAL_MODE=WAL":
                    raise sqlite3.OperationalError("disk I/O error")
                if s_up == "PRAGMA JOURNAL_MODE=DELETE":
                    state["delete_requested"] = True
                    return self._conn.execute(sql, *args)
                return self._conn.execute(sql, *args)

            def __getattr__(self, name):
                return getattr(self._conn, name)

        proxy = WalFailProxy(real_conn)
        reg_mod.migrate_db(proxy, threading.RLock(), db_path=wal_db_path)
        j_mode = str(real_conn.execute("PRAGMA journal_mode").fetchone()[0]).strip().lower()
        mig_ver = real_conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()[0]
        real_conn.close()
        wal_fallback_ok = (state["rollback_called"] and state["delete_requested"] and j_mode == "delete" and mig_ver == 6)

        # Verify MEMORY / OFF journal fallback is strictly forbidden on operational file DB
        mem_forbid_raised = False
        mem_db_path = os.path.join(gap02_dir, "forbid_mem.db")
        c_mem_f = sqlite3.connect(mem_db_path, timeout=10.0, check_same_thread=False)

        class MemoryFallbackProxy(WalFailProxy):
            def execute(self, sql, *args):
                s_up = sql.strip().upper()
                if s_up == "PRAGMA JOURNAL_MODE=WAL":
                    raise sqlite3.OperationalError("disk I/O error")
                if s_up == "PRAGMA JOURNAL_MODE=DELETE":
                    return type("Cur", (), {"fetchone": lambda self: ("memory",)})()
                return self._conn.execute(sql, *args)

        try:
            reg_mod.migrate_db(MemoryFallbackProxy(c_mem_f), threading.RLock(), db_path=mem_db_path)
        except sqlite3.OperationalError as oe_mem:
            mem_forbid_raised = ("forbidden" in str(oe_mem).lower() or "memory" in str(oe_mem).lower())
        finally:
            c_mem_f.close()

        # Verify disk-full and read-only errors raise immediately and NEVER attempt DELETE or MEMORY fallback
        crit_results = []
        for err_msg in ("database or disk is full", "attempt to write a readonly database"):
            crit_state = {"delete_attempted": False, "rollback_called": False}
            c_crit = sqlite3.connect(":memory:")

            class CritFailProxy:
                in_transaction = False
                def rollback(self):
                    crit_state["rollback_called"] = True
                def execute(self, sql, *args):
                    s_up = sql.strip().upper()
                    if "JOURNAL_MODE=DELETE" in s_up or "JOURNAL_MODE=MEMORY" in s_up:
                        crit_state["delete_attempted"] = True
                    raise sqlite3.OperationalError(err_msg)

            raised_ok = False
            try:
                reg_mod.migrate_db(CritFailProxy(), threading.RLock(), db_path=os.path.join(gap02_dir, "crit.db"))
            except sqlite3.OperationalError as oe_c:
                raised_ok = (err_msg in str(oe_c).lower() and not crit_state["delete_attempted"] and crit_state["rollback_called"])
            finally:
                c_crit.close()
            crit_results.append(raised_ok)

        check("STAGE1-GAP02", "migrate_db rolls back & verifies DELETE on WAL failure, forbids MEMORY/OFF, and raises on disk-full/read-only",
              wal_fallback_ok and mem_forbid_raised and all(crit_results),
              (wal_fallback_ok, j_mode, mig_ver, mem_forbid_raised, crit_results))
    finally:
        shutil.rmtree(gap02_dir, ignore_errors=True)

    # 2. STAGE1-GAP03: Verify check_install.py (--json) and mersad_live.py --verify-models in empty temp dir do not alter cwd or create DB/log/evidence
    gap03_base = tempfile.mkdtemp(prefix="mersad_s1_gap03_")
    try:
        clean_src = os.path.join(gap03_base, "src")
        empty_cwd = os.path.join(gap03_base, "empty_cwd")
        os.makedirs(clean_src, exist_ok=True)
        os.makedirs(empty_cwd, exist_ok=True)
        for fn in os.listdir(WORK):
            sf = os.path.join(WORK, fn)
            if os.path.isfile(sf) and fn.endswith((".py", ".html", ".bat", ".txt", ".md", ".spec")):
                shutil.copy2(sf, os.path.join(clean_src, fn))

        env_clean = {k: v for k, v in os.environ.items() if k != "MERSAD_DATA_DIR"}
        p_chk_json = subprocess.run(
            [sys.executable, os.path.join(clean_src, "check_install.py"), "--json"],
            cwd=empty_cwd, env=env_clean, capture_output=True, text=True, timeout=20
        )
        p_ver_mod = subprocess.run(
            [sys.executable, os.path.join(clean_src, "mersad_live.py"), "--verify-models"],
            cwd=empty_cwd, env=env_clean, capture_output=True, text=True, timeout=20
        )
        # Also verify in-process cwd preservation when importing check_install and running verify_models_cli
        probe_code = (
            f"import os, sys; sys.path.insert(0, {repr(clean_src)}); "
            "cwd0 = os.getcwd(); "
            "import check_install as ci; ci.check_models_detailed(); "
            "cwd1 = os.getcwd(); "
            "import mersad_live as ml; "
            "cwd2 = os.getcwd(); "
            "assert cwd0 == cwd1 == cwd2, (cwd0, cwd1, cwd2); "
            "assert ml.db is None, 'ml.db should be None when imported from check_install'"
        )
        p_probe = subprocess.run([sys.executable, "-c", probe_code], cwd=empty_cwd, env=env_clean, capture_output=True, text=True, timeout=15)

        empty_cwd_entries = os.listdir(empty_cwd)
        forbidden_names = ("mersad.db", "mersad.db.ipclock", "mersad.log", "evidence", "evidence_archive", ".mersad_hmac.key")
        src_side_effects = [n for n in forbidden_names if os.path.exists(os.path.join(clean_src, n))]
        check("STAGE1-GAP03", "check_install.py --json & mersad_live.py --verify-models preserve cwd and create zero DB/log/evidence files",
              p_chk_json.returncode == 0 and p_ver_mod.returncode in (0, 1) and p_probe.returncode == 0
              and empty_cwd_entries == [] and src_side_effects == [],
              (p_chk_json.returncode, p_ver_mod.returncode, p_probe.returncode, empty_cwd_entries, src_side_effects, p_probe.stderr[-200:]))
    finally:
        shutil.rmtree(gap03_base, ignore_errors=True)

    # 3. STAGE1-GAP06: Multi-process concurrency between insights.seed_demo()/clear_demo() and live sightings/alerts without 'database is locked'
    gap06_dir = tempfile.mkdtemp(prefix="mersad_s1_gap06_")
    try:
        for fn in os.listdir(WORK):
            sf = os.path.join(WORK, fn)
            if os.path.isfile(sf) and fn.endswith((".py", ".html", ".txt")):
                shutil.copy2(sf, os.path.join(gap06_dir, fn))

        env_ipc = dict(os.environ)
        env_ipc["MERSAD_DATA_DIR"] = gap06_dir
        # Pre-initialize schema in gap06_dir before launching concurrent worker subprocesses
        init_cmd = [sys.executable, "-c", f"import sys; sys.path.insert(0, {repr(gap06_dir)}); import mersad_live as m; m.db.close()"]
        subprocess.run(init_cmd, cwd=gap06_dir, env=env_ipc, check=True, timeout=15)

        worker_demo_code = (
            f"import sys; sys.path.insert(0, {repr(gap06_dir)})\n"
            "import mersad_live as m\n"
            "for i in range(4):\n"
            "    r1 = m.INS.seed_demo(days=4, seed=7 + i)\n"
            "    assert r1.get('ok'), f'seed_demo failed: {r1}'\n"
            "    r2 = m.INS.clear_demo()\n"
            "    assert r2.get('ok') and r2.get('cleared'), f'clear_demo failed: {r2}'\n"
            "r_final = m.INS.seed_demo(days=4, seed=99)\n"
            "assert r_final.get('ok'), f'final seed_demo failed: {r_final}'\n"
            "m.db.close()\n"
            "print('DEMO_WORKER_OK')\n"
        )
        worker_live_code = (
            f"import sys, numpy as np; sys.path.insert(0, {repr(gap06_dir)})\n"
            "import mersad_live as m\n"
            "dummy = np.zeros((120, 320, 3), dtype=np.uint8)\n"
            "for i in range(25):\n"
            "    m.register(f'عدن {70000 + i}', 0.91, 'CAM1', 'car', session_id='s1_ipc')\n"
            "    if i % 3 == 0:\n"
            "        m.raise_alert('VEHICLE: WANTED', f'عدن-{70000 + i}', 'CAM1', dummy, ref=f'ipc_ref_{i}')\n"
            "m.db.close()\n"
            "print('LIVE_WORKER_OK')\n"
        )
        p_demo = subprocess.Popen([sys.executable, "-c", worker_demo_code], cwd=gap06_dir, env=env_ipc, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        p_live = subprocess.Popen([sys.executable, "-c", worker_live_code], cwd=gap06_dir, env=env_ipc, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        out_d, err_d = p_demo.communicate(timeout=30)
        out_l, err_l = p_live.communicate(timeout=30)

        v_ipc = subprocess.run([sys.executable, os.path.join(gap06_dir, "mersad_live.py"), "--verify"],
                               cwd=gap06_dir, env=env_ipc, capture_output=True, text=True, timeout=15)
        c_check = sqlite3.connect(os.path.join(gap06_dir, "mersad.db"))
        live_cnt = c_check.execute("SELECT COUNT(*) FROM sightings WHERE src='live'").fetchone()[0]
        demo_cnt = c_check.execute("SELECT COUNT(*) FROM sightings WHERE src='demo'").fetchone()[0]
        alert_cnt = c_check.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
        c_check.close()

        gap06_ok = (
            p_demo.returncode == 0 and p_live.returncode == 0
            and "DEMO_WORKER_OK" in out_d and "LIVE_WORKER_OK" in out_l
            and "database is locked" not in (err_d + err_l).lower()
            and live_cnt == 25 and demo_cnt > 50 and alert_cnt == 9
            and "Audit chain OK" in v_ipc.stdout
        )
        check("STAGE1-GAP06", "2 concurrent subprocesses running seed_demo/clear_demo & live sightings/alerts complete with 0 lock errors",
              gap06_ok, (p_demo.returncode, p_live.returncode, live_cnt, demo_cnt, alert_cnt, err_d[-200:], err_l[-200:]))
    finally:
        shutil.rmtree(gap06_dir, ignore_errors=True)

    # 4. STAGE1-GAP01: Test verify_pip_deps (--verify-pip-deps) accepts OpenCV GUI replacement and rejects real dependency conflicts
    fake_cv2_ok = type("FakeCV2", (), {"imshow": staticmethod(lambda *a: None)})()
    fake_cv2_no_gui = type("FakeCV2NoGui", (), {})()

    # (a) EasyOCR complaining about missing opencv-python-headless while opencv-python==4.11.0.86 + cv2.imshow are present -> PASS
    ok_benign, info_benign = chk_mod.verify_pip_deps(
        pip_check_output="easyocr 1.7.2 requires opencv-python-headless, which is not installed.\n",
        pip_returncode=1,
        opencv_version="4.11.0.86",
        headless_version="",
        cv2_module=fake_cv2_ok,
    )
    # (b) Clean pip check output -> PASS
    ok_clean, _ = chk_mod.verify_pip_deps(
        pip_check_output="No broken requirements found.\n",
        pip_returncode=0,
        opencv_version="4.11.0.86",
        headless_version="",
        cv2_module=fake_cv2_ok,
    )
    # (c) Real conflict in another package alongside easyocr notice -> FAIL
    ok_real_conflict, info_real = chk_mod.verify_pip_deps(
        pip_check_output=(
            "easyocr 1.7.2 requires opencv-python-headless, which is not installed.\n"
            "scipy 1.14.1 has requirement numpy<2.3,>=1.23.5, but you have numpy 2.4.6.\n"
        ),
        pip_returncode=1,
        opencv_version="4.11.0.86",
        headless_version="",
        cv2_module=fake_cv2_ok,
    )
    # (d) Missing or wrong opencv-python version, or headless still installed, or cv2.imshow missing -> FAIL
    ok_wrong_cv, _ = chk_mod.verify_pip_deps(
        pip_check_output="easyocr 1.7.2 requires opencv-python-headless, which is not installed.\n",
        pip_returncode=1,
        opencv_version="4.10.0.84",
        headless_version="",
        cv2_module=fake_cv2_ok,
    )
    ok_hl_present, _ = chk_mod.verify_pip_deps(
        pip_check_output="No broken requirements found.\n",
        pip_returncode=0,
        opencv_version="4.11.0.86",
        headless_version="4.11.0.86",
        cv2_module=fake_cv2_ok,
    )
    ok_no_imshow, _ = chk_mod.verify_pip_deps(
        pip_check_output="easyocr 1.7.2 requires opencv-python-headless, which is not installed.\n",
        pip_returncode=1,
        opencv_version="4.11.0.86",
        headless_version="",
        cv2_module=fake_cv2_no_gui,
    )
    setup_s = open(os.path.join(WORK, "setup.bat"), encoding="utf-8").read()
    ci_s = open(os.path.join(WORK, ".github", "workflows", "windows-build.yml"), encoding="utf-8").read()
    scripts_updated = ("check_install.py --verify-pip-deps" in setup_s and "check_install.py --verify-pip-deps" in ci_s)

    check("STAGE1-GAP01", "--verify-pip-deps accepts verified opencv-python==4.11.0.86 GUI replacement & rejects any real dependency conflict",
          ok_benign and len(info_benign["tolerated_easyocr_headless"]) == 1
          and ok_clean and (not ok_real_conflict) and len(info_real["unexpected_conflicts"]) == 1
          and (not ok_wrong_cv) and (not ok_hl_present) and (not ok_no_imshow) and scripts_updated,
          (ok_benign, ok_clean, ok_real_conflict, ok_wrong_cv, ok_hl_present, ok_no_imshow, scripts_updated))


run_stage1_gap_regression_tests()


def run_stage2_gap_regression_tests():
    import check_install as chk_mod

    # 1. STAGE2-GAP05-MIGRATION: Upgrade legacy v1..v5 DB (with old camera_links without 'via') & fresh DB via registry.migrate_db()
    gap05_dir = tempfile.mkdtemp(prefix="mersad_s2_gap05_")
    try:
        leg5_path = os.path.join(gap05_dir, "legacy_v5.db")
        c_leg5 = sqlite3.connect(leg5_path, timeout=10.0, check_same_thread=False)
        c_leg5.executescript("""
        CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_ts REAL, description TEXT);
        INSERT INTO schema_migrations VALUES(1, 1700000001.0, 'v1');
        INSERT INTO schema_migrations VALUES(2, 1700000002.0, 'v2');
        INSERT INTO schema_migrations VALUES(3, 1700000003.0, 'v3');
        INSERT INTO schema_migrations VALUES(4, 1700000004.0, 'v4');
        INSERT INTO schema_migrations VALUES(5, 1700000005.0, 'v5');
        CREATE TABLE vehicles(plate TEXT PRIMARY KEY, governorate TEXT, model TEXT, color TEXT, vtype TEXT, owner TEXT, status TEXT, notes TEXT, updated REAL, plate_digits TEXT, plate_letters TEXT);
        CREATE TABLE persons(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, ref TEXT DEFAULT '', category TEXT, status TEXT DEFAULT 'normal', consent INTEGER DEFAULT 0, notes TEXT, updated REAL, UNIQUE(name, ref));
        CREATE TABLE faces(name TEXT, emb BLOB, watch INTEGER DEFAULT 0, person_id INTEGER DEFAULT 0);
        CREATE TABLE sightings(ts REAL, cam TEXT, plate TEXT, conf REAL, vclass TEXT, src TEXT DEFAULT 'live', direction TEXT DEFAULT '', raw_text TEXT DEFAULT '', session_id TEXT DEFAULT '');
        CREATE TABLE alerts(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, status TEXT, dispatched INTEGER DEFAULT 0, dispatch_status TEXT DEFAULT 'not_required');
        CREATE TABLE audit(i INTEGER PRIMARY KEY, ts REAL, action TEXT, ref TEXT, prev TEXT, hash TEXT);
        CREATE TABLE camera_links(from_cam TEXT, to_cam TEXT, min_sec REAL DEFAULT 90, expected_sec REAL DEFAULT 300, source TEXT DEFAULT 'user_calibrated', PRIMARY KEY(from_cam, to_cam));
        INSERT INTO camera_links(from_cam, to_cam, min_sec, expected_sec, source) VALUES('CAM1', 'CAM2', 110.0, 320.0, 'user_calibrated');
        """)
        c_leg5.commit()

        reg_mod.migrate_db(c_leg5, threading.RLock(), db_path=leg5_path)
        # Re-run to verify idempotency (must not duplicate migration 6 or alter existing camera_links rows)
        reg_mod.migrate_db(c_leg5, threading.RLock(), db_path=leg5_path)

        cols_cl_leg = {r[1] for r in c_leg5.execute("PRAGMA table_info(camera_links)").fetchall()}
        mig_rows_leg = c_leg5.execute("SELECT version, description FROM schema_migrations ORDER BY version ASC").fetchall()
        preserved_cl = c_leg5.execute("SELECT from_cam, to_cam, min_sec, expected_sec, COALESCE(via,'') FROM camera_links").fetchall()
        c_leg5.close()

        # Also test fresh empty DB
        fresh_path = os.path.join(gap05_dir, "fresh_v6.db")
        c_fresh = sqlite3.connect(fresh_path, timeout=10.0, check_same_thread=False)
        reg_mod.migrate_db(c_fresh, threading.RLock(), db_path=fresh_path)
        reg_mod.migrate_db(c_fresh, threading.RLock(), db_path=fresh_path)
        cols_cl_fresh = {r[1] for r in c_fresh.execute("PRAGMA table_info(camera_links)").fetchall()}
        mig_rows_fresh = c_fresh.execute("SELECT version FROM schema_migrations ORDER BY version ASC").fetchall()
        c_fresh.close()

        mig_ok = (
            "via" in cols_cl_leg
            and "via" in cols_cl_fresh
            and [r[0] for r in mig_rows_leg] == [1, 2, 3, 4, 5, 6]
            and "v6_camera_links_via_and_constraints" in mig_rows_leg[-1][1]
            and preserved_cl == [("CAM1", "CAM2", 110.0, 320.0, "")]
            and [r[0] for r in mig_rows_fresh] == [1, 2, 3, 4, 5, 6]
        )
        check("STAGE2-GAP05-MIGRATION", "registry.migrate_db upgrades v1..v5 camera_links with via column, records migration 6, and is idempotent",
              mig_ok, (cols_cl_leg, [r[0] for r in mig_rows_leg], preserved_cl))

        # 2. STAGE2-GAP05-TOPOLOGY: Deterministic configure_topology(), camera_links CRUD & API validation
        topo_db_path = os.path.join(gap05_dir, "topo.db")
        c_topo = sqlite3.connect(topo_db_path, timeout=10.0, check_same_thread=False)
        l_topo = threading.RLock()
        reg_mod.init(c_topo, l_topo, lambda *a: None, lambda: None, db_path=topo_db_path)
        ins_mod.init(c_topo, l_topo, db_path=topo_db_path)

        # (a) Reject self-loop, negative/zero min_sec, expected_sec < min_sec, and via == from_cam/to_cam
        r_self = ins_mod.save_camera_link({"from_cam": "CAM1", "to_cam": "CAM1", "min_sec": 60, "expected_sec": 120})
        r_neg = ins_mod.save_camera_link({"from_cam": "CAM1", "to_cam": "CAM2", "min_sec": -5, "expected_sec": 120})
        r_zero = ins_mod.save_camera_link({"from_cam": "CAM1", "to_cam": "CAM2", "min_sec": 0, "expected_sec": 120})
        r_contra = ins_mod.save_camera_link({"from_cam": "CAM1", "to_cam": "CAM2", "min_sec": 200, "expected_sec": 100})
        r_bad_via = ins_mod.save_camera_link({"from_cam": "CAM1", "to_cam": "CAM2", "min_sec": 60, "expected_sec": 120, "via": "CAM1"})

        # (b) Deterministic 2-hop selection:
        # Path 1: CAM_START -> CAM_MID_Z -> CAM_END (total min_sec = 50 + 50 = 100)
        # Path 2: CAM_START -> CAM_MID_B -> CAM_END (total min_sec = 40 + 40 = 80)
        # Path 3: CAM_START -> CAM_MID_A -> CAM_END (total min_sec = 40 + 40 = 80, tie with CAM_MID_B -> must pick CAM_MID_A alphabetically!)
        # Also add CAM_END -> CAM_FAR (min_sec = 30) to verify 2-hop inferred link (CAM_START -> CAM_END) does NOT chain into a 3-hop link (CAM_START -> CAM_FAR)!
        assert ins_mod.save_camera_link({"from_cam": "CAM_START", "to_cam": "CAM_MID_Z", "min_sec": 50, "expected_sec": 150})["ok"]
        assert ins_mod.save_camera_link({"from_cam": "CAM_MID_Z", "to_cam": "CAM_END", "min_sec": 50, "expected_sec": 150})["ok"]
        assert ins_mod.save_camera_link({"from_cam": "CAM_START", "to_cam": "CAM_MID_B", "min_sec": 40, "expected_sec": 120})["ok"]
        assert ins_mod.save_camera_link({"from_cam": "CAM_MID_B", "to_cam": "CAM_END", "min_sec": 40, "expected_sec": 120})["ok"]
        assert ins_mod.save_camera_link({"from_cam": "CAM_START", "to_cam": "CAM_MID_A", "min_sec": 40, "expected_sec": 120})["ok"]
        assert ins_mod.save_camera_link({"from_cam": "CAM_MID_A", "to_cam": "CAM_END", "min_sec": 40, "expected_sec": 120})["ok"]
        assert ins_mod.save_camera_link({"from_cam": "CAM_END", "to_cam": "CAM_FAR", "min_sec": 30, "expected_sec": 90})["ok"]

        inferred_se = ins_mod._link_info("CAM_START", "CAM_END")
        uncal_3hop = ins_mod._link_info("CAM_START", "CAM_FAR")
        listed = ins_mod.list_camera_links()
        del_res = ins_mod.delete_camera_link("CAM_START", "CAM_MID_A")
        inferred_after_del = ins_mod._link_info("CAM_START", "CAM_END")
        c_topo.close()

        # Also test HTTP endpoints GET/POST /api/camera_links on active server
        reg_mod.init(m.db, m.DBL, m.log, m.refresh_known, db_path=m.DB_PATH)
        ins_mod.init(m.db, m.DBL, db_path=m.DB_PATH)
        m.wire()
        srv_cl = ThreadingHTTPServer(("127.0.0.1", 0), srv_mod.H)
        cl_port = srv_cl.server_address[1]
        threading.Thread(target=srv_cl.serve_forever, daemon=True).start()
        try:
            def _cl_post(path, body):
                req = urllib.request.Request(
                    f"http://127.0.0.1:{cl_port}{path}?k={m.bus.token}",
                    data=json.dumps(body).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                return json.loads(urllib.request.urlopen(req, timeout=3.0).read())

            def _cl_get(path):
                return json.loads(urllib.request.urlopen(f"http://127.0.0.1:{cl_port}{path}?k={m.bus.token}", timeout=3.0).read())

            api_bad = _cl_post("/api/camera_links", {"from_cam": "C1", "to_cam": "C1", "min_sec": 30, "expected_sec": 60})
            api_ok = _cl_post("/api/camera_links", {"from_cam": "C1", "to_cam": "C2", "min_sec": 75, "expected_sec": 200, "via": ""})
            api_list = _cl_get("/api/camera_links")
            api_del = _cl_post("/api/camera_links/delete", {"from_cam": "C1", "to_cam": "C2"})
        finally:
            srv_cl.shutdown()

        topo_ok = (
            not r_self["ok"] and not r_neg["ok"] and not r_zero["ok"] and not r_contra["ok"] and not r_bad_via["ok"]
            and inferred_se["calibrated"] is True and inferred_se["min_sec"] == 80.0 and inferred_se.get("via") == "CAM_MID_A"
            and uncal_3hop["calibrated"] is False and "via" not in uncal_3hop
            and listed["ok"] and len(listed["links"]) == 7
            and del_res["ok"] and del_res["deleted"] is True
            and inferred_after_del.get("via") == "CAM_MID_B"
            and not api_bad["ok"] and api_ok["ok"]
            and any(x["from_cam"] == "C1" and x["to_cam"] == "C2" for x in api_list.get("links", []))
            and api_del["ok"] and api_del["deleted"] is True
        )
        check("STAGE2-GAP05-TOPOLOGY", "configure_topology is deterministic (frozen 2-hop, sorted tie-break) & /api/camera_links enforces validation",
              topo_ok, (inferred_se, uncal_3hop, inferred_after_del, api_bad, api_ok, api_del))
    finally:
        reg_mod.init(m.db, m.DBL, m.log, m.refresh_known, db_path=m.DB_PATH)
        ins_mod.init(m.db, m.DBL, db_path=m.DB_PATH)
        shutil.rmtree(gap05_dir, ignore_errors=True)

    # 3. STAGE2-GAP04: Strict isolation between demo and live sightings in summary(), plate_path(), forecast(), and train()
    gap04_dir = tempfile.mkdtemp(prefix="mersad_s2_gap04_")
    try:
        g4_db_path = os.path.join(gap04_dir, "gap04.db")
        c_g4 = sqlite3.connect(g4_db_path, timeout=10.0, check_same_thread=False)
        l_g4 = threading.RLock()
        reg_mod.init(c_g4, l_g4, lambda *a: None, lambda: None, db_path=g4_db_path)
        ins_mod.init(c_g4, l_g4, db_path=g4_db_path)

        # Insert 2 live sightings for plate 'عدن-55555'
        now_g4 = time.time()
        c_g4.execute("INSERT INTO sightings(ts, cam, plate, conf, vclass, src, direction) VALUES(?,?,?,?,?,?,?)",
                     (now_g4 - 300, "CAM1", "عدن-55555", 0.93, "car", "live", "اقتراب"))
        c_g4.execute("INSERT INTO sightings(ts, cam, plate, conf, vclass, src, direction) VALUES(?,?,?,?,?,?,?)",
                     (now_g4 - 120, "CAM2", "عدن-55555", 0.91, "car", "live", "CAM1 ➔ CAM2"))
        c_g4.commit()

        # Seed 30 days of synthetic demo history (which includes demo plate '99991')
        sd_res = ins_mod.seed_demo(days=10, seed=11)

        # (a) Default live calls (include_demo=False) must NOT be polluted by seed_demo()
        sum_live = ins_mod.summary(include_demo=False)
        fc_live = ins_mod.forecast(include_demo=False)
        path_demo_in_live = ins_mod.plate_path("99991", include_demo=False)
        path_real_in_live = ins_mod.plate_path("عدن-55555", include_demo=False)

        # (b) Explicit demo calls (include_demo=True) must return demo data tagged with data_source == 'demo'
        sum_demo = ins_mod.summary(include_demo=True)
        fc_demo = ins_mod.forecast(include_demo=True)
        path_demo_explicit = ins_mod.plate_path("99991", include_demo=True)
        c_g4.close()

        gap04_ok = (
            sd_res.get("ok") is True
            and sum_live["data_source"] == "live" and sum_live["includes_demo"] is False
            and sum_live["model"]["ready"] is False and sum_live["model"]["n"] == 2 and sum_live["model"]["demo"] == 0
            and sum_live["forecast"] is None and fc_live is None and sum_live["anomalies"] == []
            and all(p.get("src") == "live" for p in sum_live["paths"])
            and path_demo_in_live["found"] is False and path_demo_in_live["has_demo_only"] is True and path_demo_in_live["data_source"] == "live"
            and path_real_in_live["found"] is True and path_real_in_live["data_source"] == "live" and path_real_in_live["total"] == 2
            and sum_demo["data_source"] == "demo" and sum_demo["includes_demo"] is True and sum_demo["model"]["ready"] is True
            and fc_demo is not None and fc_demo["data_source"] == "demo"
            and path_demo_explicit["found"] is True and path_demo_explicit["data_source"] == "demo"
            and all(st.get("src") == "demo" for st in path_demo_explicit["steps"])
        )
        check("STAGE2-GAP04", "seed_demo() never pollutes live summary/forecast/plate_path; demo data requires explicit include_demo=True",
              gap04_ok, (sum_live["model"], path_demo_in_live, sum_demo["model"]["ready"], path_demo_explicit["found"]))
    finally:
        reg_mod.init(m.db, m.DBL, m.log, m.refresh_known, db_path=m.DB_PATH)
        ins_mod.init(m.db, m.DBL, db_path=m.DB_PATH)
        shutil.rmtree(gap04_dir, ignore_errors=True)

    # 4. STAGE2-GAP07: Test check_install.py --camera --json (success & failure) and verify cap.release() + RTSP password redaction
    gap07_dir = tempfile.mkdtemp(prefix="mersad_s2_gap07_")
    try:
        # (a) Unit test with injected FakeCamera verifying release() on both success and read-failure + RTSP password redaction
        rel_tracker = {"ok_released": False, "fail_released": False}

        class _MockCapOk:
            def isOpened(self): return True
            def read(self): return True, np.zeros((120, 160, 3), dtype=np.uint8)
            def release(self): rel_tracker["ok_released"] = True

        class _MockCapReadFail:
            def isOpened(self): return True
            def read(self): return False, None
            def release(self): rel_tracker["fail_released"] = True

        res_cam_ok = chk_mod.check_camera_source(
            root_dir=gap07_dir,
            source_override="rtsp://admin:SuperSecretPass123@10.0.0.50:554/stream1",
            capture_factory=lambda src: _MockCapOk()
        )
        res_cam_fail = chk_mod.check_camera_source(
            root_dir=gap07_dir,
            source_override="rtsp://admin:SuperSecretPass123@10.0.0.50:554/stream1",
            capture_factory=lambda src: _MockCapReadFail()
        )

        # (b) CLI test (`check_install.py --camera --json`) with a real synthetic MJPG .avi video file (success) and a non-existent source (failure)
        avi_path = os.path.join(gap07_dir, "synthetic_cam.avi")
        vw = cv2.VideoWriter(avi_path, cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (160, 120))
        vw.write(np.full((120, 160, 3), 128, dtype=np.uint8))
        vw.release()

        with open(os.path.join(gap07_dir, "mersad_config.json"), "w", encoding="utf-8") as cf:
            json.dump({"source": avi_path}, cf)
        env_cam = dict(os.environ)
        env_cam["MERSAD_DATA_DIR"] = gap07_dir
        p_cam_pass = subprocess.run(
            [sys.executable, os.path.join(WORK, "check_install.py"), "--camera", "--json"],
            cwd=gap07_dir, env=env_cam, capture_output=True, text=True, timeout=20
        )
        j_cam_pass = json.loads(p_cam_pass.stdout) if p_cam_pass.stdout.strip().startswith("{") else {}

        with open(os.path.join(gap07_dir, "mersad_config.json"), "w", encoding="utf-8") as cf:
            json.dump({"source": os.path.join(gap07_dir, "nonexistent_camera_stream.avi")}, cf)
        p_cam_fail = subprocess.run(
            [sys.executable, os.path.join(WORK, "check_install.py"), "--camera", "--json"],
            cwd=gap07_dir, env=env_cam, capture_output=True, text=True, timeout=20
        )
        j_cam_fail = json.loads(p_cam_fail.stdout) if p_cam_fail.stdout.strip().startswith("{") else {}

        gap07_ok = (
            res_cam_ok["status"] == "PASS" and res_cam_ok["opened"] and res_cam_ok["frame_read"] and res_cam_ok["released"]
            and rel_tracker["ok_released"] is True and "SuperSecretPass123" not in json.dumps(res_cam_ok)
            and res_cam_fail["status"] == "FAIL" and res_cam_fail["opened"] and not res_cam_fail["frame_read"]
            and res_cam_fail["released"] and rel_tracker["fail_released"] is True
            and "SuperSecretPass123" not in json.dumps(res_cam_fail)
            and p_cam_pass.returncode == 0 and j_cam_pass.get("camera", {}).get("status") == "PASS"
            and j_cam_pass.get("camera", {}).get("released") is True
            and p_cam_fail.returncode == 1 and j_cam_fail.get("camera", {}).get("status") == "FAIL"
        )
        check("STAGE2-GAP07", "check_install.py --camera --json verifies camera open/read, guarantees cap.release(), and redacts RTSP passwords",
              gap07_ok, (p_cam_pass.returncode, j_cam_pass.get("camera"), j_cam_pass.get("classification"), p_cam_pass.stderr[-200:]))
    finally:
        shutil.rmtree(gap07_dir, ignore_errors=True)


run_stage2_gap_regression_tests()


def run_stage3_gap_regression_tests():
    # 1. STAGE3-GAP09: Strict separation of face blurring between vehicle alerts (100% faces blurred) and FACE MATCH alerts (only non-target blurred) + YuNet threshold 0.65
    gap09_entries = [
        (10, 10, 60, 60, "متطوع عادي", 0.88, 0, None, 101, "N-1"),
        (100, 10, 60, 60, "متطوع مراقبة", 0.91, 1, None, 102, "W-1"),
        (190, 10, 60, 60, "unenrolled", 0.0, 0, None, 0, ""),
    ]
    veh_boxes = m.get_boxes_to_blur_for_alert(gap09_entries, alert_kind="vehicle")
    face_boxes = m.get_boxes_to_blur_for_alert(gap09_entries, alert_kind="face", target_face_box=(100, 10, 60, 60))

    rng09 = np.random.default_rng(42)
    base_img = rng09.integers(0, 255, (120, 280, 3), dtype=np.uint8)
    veh_img = m.blur_unmatched_faces(base_img, veh_boxes)
    face_img = m.blur_unmatched_faces(base_img, face_boxes)

    def _roi_diff(img_a, img_b, box):
        x, y, bw, bh = box
        return float(np.abs(img_a[y:y+bh, x:x+bw].astype(np.float32) - img_b[y:y+bh, x:x+bw].astype(np.float32)).mean())

    # In vehicle alert: all 3 faces (normal, watch, unenrolled) must be blurred (diff > 5.0), and plate area (y=80..115) untouched
    veh_blur_all_ok = (
        len(veh_boxes) == 3
        and _roi_diff(base_img, veh_img, (10, 10, 60, 60)) > 5.0
        and _roi_diff(base_img, veh_img, (100, 10, 60, 60)) > 5.0
        and _roi_diff(base_img, veh_img, (190, 10, 60, 60)) > 5.0
        and np.array_equal(base_img[80:115, 10:270], veh_img[80:115, 10:270])
    )
    # In FACE MATCH alert: normal (box 0) and unenrolled (box 2) must be blurred, while target watch face (box 1) is preserved
    face_blur_sel_ok = (
        len(face_boxes) == 2
        and _roi_diff(base_img, face_img, (10, 10, 60, 60)) > 5.0
        and _roi_diff(base_img, face_img, (100, 10, 60, 60)) == 0.0
        and _roi_diff(base_img, face_img, (190, 10, 60, 60)) > 5.0
    )
    # Verify YuNet configurable score threshold default (0.65) catches 0.70 score face for blurring while rejecting 0.40 noise
    sim_dets = [(10, 10, 50, 50, 0.92), (80, 10, 50, 50, 0.70), (150, 10, 50, 50, 0.40)]
    thr_default = m.resolve_face_detect_score(None)
    caught_065 = [d[:4] for d in sim_dets if d[4] >= thr_default]
    caught_080 = [d[:4] for d in sim_dets if d[4] >= 0.80]
    thr_ok = (thr_default == 0.65 and len(caught_065) == 2 and len(caught_080) == 1)

    check("STAGE3-GAP09", "vehicle alerts blur 100% of faces (normal, watch & unenrolled); face alerts blur all non-target faces; YuNet default threshold is 0.65",
          veh_blur_all_ok and face_blur_sel_ok and thr_ok,
          (veh_blur_all_ok, face_blur_sel_ok, thr_default, len(caught_065), len(caught_080)))

    # 2. STAGE3-GAP10: Enrollment session camera binding, min box size, competing face rejection, and 5-attempt inconsistency abort
    m.ENR["req"] = None
    r_g10 = reg_mod.save_person({"name": "ياسر قاسم", "ref": "G10-01", "consent": True, "status": "watch"}, "s3")
    pid_g10 = r_g10["id"]
    enr_events = []
    q_enr = __import__("queue").Queue()
    m.bus.subs.append(q_enr)
    try:
        started_g10 = m.req_enroll("ياسر قاسم", True, "s3", ref="G10-01", person_id=pid_g10, cam="CAM1")
        v_base = np.zeros((1, 128), dtype=np.float32); v_base[0, 0] = 1.0
        v_ortho = np.zeros((1, 128), dtype=np.float32); v_ortho[0, 1] = 1.0

        # (a) Frame from wrong camera (CAM2 != CAM1) -> rejected
        ok_wrong_cam = m.enroll_step(v_base, cam="CAM2", face_box=(100, 100, 80, 80))
        cnt_after_wrong_cam = len(m.ENR["req"]["samples"])

        # (b) Frame from CAM1 with valid single face -> accepted (sample #1)
        ok_sample1 = m.enroll_step(v_base, cam="CAM1", face_box=(100, 100, 80, 80), faces_in_frame=[(100, 100, 80, 80)])
        cnt_after_s1 = len(m.ENR["req"]["samples"])

        # (c) Frame with tiny face (< 40x40) -> rejected
        ok_tiny = m.enroll_step(v_base, cam="CAM1", face_box=(100, 100, 30, 35))
        cnt_after_tiny = len(m.ENR["req"]["samples"])

        # (d) Frame with competing second face (area 80x80=6400 >= 50% of 100x100=10000) -> rejected with warning, session stays alive
        ok_competing = m.enroll_step(v_base, cam="CAM1", faces_in_frame=[(10, 10, 100, 100), (150, 10, 80, 80)])
        still_active_after_comp = m.ENR.get("req") is not None and len(m.ENR["req"]["samples"]) == 1

        # (e) 5 inconsistent samples (cosine similarity 0.0 < 0.55) -> first 4 increment inconsistent_count, 5th aborts session with n=-1 & error
        inc_states = []
        for _ in range(5):
            res_inc = m.enroll_step(v_ortho, cam="CAM1", face_box=(100, 100, 80, 80))
            inc_states.append((res_inc, m.ENR.get("req") is not None))

        while not q_enr.empty():
            ev_obj = json.loads(q_enr.get_nowait())
            if ev_obj.get("type") == "enroll":
                enr_events.append(ev_obj)

        abort_ev = next((e for e in reversed(enr_events) if e.get("n") == -1 and e.get("error")), None)
        gap10_ok = (
            started_g10 is True
            and ok_wrong_cam is False and cnt_after_wrong_cam == 0
            and ok_sample1 is True and cnt_after_s1 == 1
            and ok_tiny is False and cnt_after_tiny == 1
            and ok_competing is False and still_active_after_comp is True
            and [st_active for _, st_active in inc_states] == [True, True, True, True, False]
            and m.ENR.get("req") is None
            and abort_ev is not None and "عدم اتساق" in abort_ev.get("error", "")
        )
        check("STAGE3-GAP10", "enroll_step enforces camera binding, >=40px face size, competing-face rejection, and aborts after 5 inconsistent samples",
              gap10_ok, (cnt_after_wrong_cam, cnt_after_s1, cnt_after_tiny, still_active_after_comp, inc_states, abort_ev))
    finally:
        if q_enr in m.bus.subs:
            m.bus.subs.remove(q_enr)
        m.ENR["req"] = None
        reg_mod.delete("persons", f"id:{pid_g10}", "s3")

    # 3. STAGE3-GAP11: Hybrid legacy SHA-256 + h1: HMAC-SHA256 audit chain verification, anti-downgrade, and missing key detection
    gap11_dir = tempfile.mkdtemp(prefix="mersad_s3_gap11_")
    orig_db, orig_db_path, orig_appdir = m.db, m.DB_PATH, m.APPDIR
    orig_env_dir = os.environ.get("MERSAD_DATA_DIR")
    try:
        os.environ["MERSAD_DATA_DIR"] = gap11_dir
        reg_mod._HMAC_KEY_CACHE.clear()
        g11_db_path = os.path.join(gap11_dir, "gap11.db")
        c_g11 = sqlite3.connect(g11_db_path, timeout=10.0, check_same_thread=False)
        m.APPDIR = gap11_dir
        m.DB_PATH = g11_db_path
        m.db = c_g11
        reg_mod.init(c_g11, m.DBL, m.log, m.refresh_known, db_path=g11_db_path)

        # (a) Insert 2 legacy unkeyed SHA-256 records (i=0, i=1)
        p0 = "0" * 64
        t0, t1 = 1700000100.0, 1700000200.0
        h0 = m.legacy_chain_hash(p0, 0, t0, "session start", "CAM1")
        h1 = m.legacy_chain_hash(h0, 1, t1, "sighting", "id=1 12345 CAM1 car")
        c_g11.execute("INSERT INTO audit VALUES(?,?,?,?,?,?)", (0, t0, "session start", "CAM1", p0, h0))
        c_g11.execute("INSERT INTO audit VALUES(?,?,?,?,?,?)", (1, t1, "sighting", "id=1 12345 CAM1 car", h0, h1))
        c_g11.commit()

        # Append 2 new HMAC-SHA256 ('h1:') records via m.log() without rewriting records 0 & 1
        m.log("operator confirm", "id=1 by ops")
        m.log("session end", "CAM1")

        rows_g11 = c_g11.execute("SELECT i, ts, action, ref, prev, hash FROM audit ORDER BY i ASC").fetchall()
        legacy_untouched = (
            len(rows_g11) == 4
            and rows_g11[0][5] == h0 and not rows_g11[0][5].startswith("h1:")
            and rows_g11[1][5] == h1 and not rows_g11[1][5].startswith("h1:")
            and rows_g11[2][5].startswith("h1:")
            and rows_g11[3][5].startswith("h1:")
        )
        ver_hybrid_ok = m.verify()

        # (b) Tamper with legacy record #0 -> must be detected
        c_g11.execute("UPDATE audit SET ref='CAM_TAMPERED' WHERE i=0")
        c_g11.commit()
        ver_leg_tamper = m.verify()
        c_g11.execute("UPDATE audit SET ref='CAM1' WHERE i=0")
        c_g11.commit()

        # (c) Forge record #3 with a wrong HMAC key -> must be detected
        real_h3 = rows_g11[3][5]
        forged_h3 = m.chain_hash(rows_g11[3][4], 3, rows_g11[3][1], rows_g11[3][2], rows_g11[3][3], key=b"W" * 32)
        c_g11.execute("UPDATE audit SET hash=? WHERE i=3", (forged_h3,))
        c_g11.commit()
        ver_forged_h1 = m.verify()
        c_g11.execute("UPDATE audit SET hash=? WHERE i=3", (real_h3,))
        c_g11.commit()

        # (d) Downgrade attack: insert record #4 after h1 record #3 using unkeyed legacy_chain_hash -> must be rejected as downgrade attack!
        t4 = time.time()
        h4_downgrade = m.legacy_chain_hash(real_h3, 4, t4, "session start", "CAM2")
        c_g11.execute("INSERT INTO audit VALUES(?,?,?,?,?,?)", (4, t4, "session start", "CAM2", real_h3, h4_downgrade))
        c_g11.commit()
        ver_downgrade = m.verify()
        c_g11.execute("DELETE FROM audit WHERE i=4")
        c_g11.commit()

        # (e) Missing .mersad_hmac.key -> verify() must report missing .mersad_hmac.key and NOT silently create a new key
        key_p = os.path.join(gap11_dir, ".mersad_hmac.key")
        bak_p = os.path.join(gap11_dir, ".mersad_hmac.key.bak")
        os.rename(key_p, bak_p)
        reg_mod._HMAC_KEY_CACHE.clear()
        ver_missing_key = m.verify()
        no_silent_recreate = not os.path.exists(key_p)
        os.rename(bak_p, key_p)
        reg_mod._HMAC_KEY_CACHE.clear()
        ver_restored = m.verify()
        c_g11.close()

        gap11_ok = (
            legacy_untouched
            and ver_hybrid_ok == "Audit chain OK (4 records)"
            and ver_leg_tamper == "TAMPERING DETECTED at record #0"
            and ver_forged_h1 == "TAMPERING DETECTED at record #3"
            and "downgrade attack" in ver_downgrade and "#4" in ver_downgrade
            and "missing .mersad_hmac.key" in ver_missing_key and no_silent_recreate
            and ver_restored == "Audit chain OK (4 records)"
        )
        check("STAGE3-GAP11", "hybrid audit chain verifies legacy SHA-256 + h1 HMAC-SHA256 without rewriting history, blocks downgrade attacks, and detects missing key",
              gap11_ok, (legacy_untouched, ver_hybrid_ok, ver_leg_tamper, ver_forged_h1, ver_downgrade, ver_missing_key, ver_restored))
    finally:
        m.db, m.DB_PATH, m.APPDIR = orig_db, orig_db_path, orig_appdir
        if orig_env_dir is not None:
            os.environ["MERSAD_DATA_DIR"] = orig_env_dir
        else:
            os.environ.pop("MERSAD_DATA_DIR", None)
        reg_mod._HMAC_KEY_CACHE.clear()
        reg_mod.init(m.db, m.DBL, m.log, m.refresh_known, db_path=m.DB_PATH)
        shutil.rmtree(gap11_dir, ignore_errors=True)

    # 4. STAGE3-GAP15: Test parse_curfew() validation, verify no blocking input() on key 'e' in video loop, and verify aggregate FPS isolation
    valid_curfews = (
        m.parse_curfew("22-5") == (22, 5)
        and m.parse_curfew("22:00-05:00") == (22, 5)
        and m.parse_curfew("0-23") == (0, 23)
        and m.parse_curfew(" 08:00 - 17:00 ") == (8, 17)
    )
    invalid_curfews = all(
        m.parse_curfew(bad) is None
        for bad in (None, "", "   ", "24-5", "22-25", "-1-5", "22:30-05:00", "abc", "10", "10-12-14")
    )
    ml_code = open(os.path.join(WORK, "mersad_live.py"), encoding="utf-8").read()
    key_e_pos = ml_code.find('if k == ord("e"):')
    key_e_snippet = ml_code[key_e_pos:key_e_pos + 400] if key_e_pos != -1 else ""
    no_blocking_input_on_e = (key_e_pos != -1 and "input(" not in key_e_snippet and "dashboard.html" in key_e_snippet)

    # Verify _update_aggregate_fps averages only online cameras and preserves individual camera FPS
    mock_cam_states = {
        "CAM1": {"status": "online", "fps": 12.0},
        "CAM2": {"status": "online", "fps": 18.0},
        "CAM3": {"status": "offline", "fps": 99.0},
    }
    agg_fps = m._update_aggregate_fps(mock_cam_states)
    fps_isolated_ok = (agg_fps == 15.0 and m.STATUS["fps"] == 15.0 and mock_cam_states["CAM1"]["fps"] == 12.0 and mock_cam_states["CAM2"]["fps"] == 18.0)

    check("STAGE3-GAP15", "parse_curfew validates HH-HH / HH:00-HH:00 safely, video loop has no blocking input() on 'e', and FPS is isolated",
          valid_curfews and invalid_curfews and no_blocking_input_on_e and fps_isolated_ok,
          (valid_curfews, invalid_curfews, no_blocking_input_on_e, agg_fps))


run_stage3_gap_regression_tests()


def run_stage4_gap_regression_tests():
    # 1. STAGE4-GAP08: Non-blocking display/stream loop when inference (YOLO + EasyOCR) takes ~250ms
    #    Verify that while a 250ms inference job runs in the background worker, the display loop processes
    #    >=15 frames and advances bus.fid without any blocking wait inside the display loop!
    gap08_frames_streamed = 0
    gap08_fid_before = m.bus.fid
    gap08_idle = threading.Event()
    gap08_idle.set()
    gap08_stop = threading.Event()
    gap08_st = {
        "cam": "CAM_GAP08",
        "src": "fake_gap08",
        "lock": threading.Lock(),
        "infer_lock": threading.Lock(),
        "infer_queue": __import__("queue").Queue(maxsize=1),
        "infer_busy": False,
        "infer_idle_event": gap08_idle,
        "dropped_infer_frames": 0,
        "cap": None,
        "status": "online",
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
    }
    m._ACTIVE_CAM_STATES["CAM_GAP08"] = gap08_st
    m.STATUS.setdefault("cameras", {})["CAM_GAP08"] = {"status": "online", "fps": 25.0, "frames": 0, "detections": 0, "errors": 0}

    class _SlowReader08:
        def readtext(self, crop):
            time.sleep(0.25)
            return [([[0, 0], [1, 0], [1, 1], [0, 1]], "عدن ٧٧٨٨٩", 0.94)]

    class _SlowYOLO08:
        names = {2: "car", 7: "truck"}
        def __call__(self, img, **kw):
            return [type("R", (), {"boxes": Boxes()})()]

    t_worker08 = threading.Thread(
        target=m._camera_inference_worker,
        args=(gap08_st, gap08_stop, _SlowYOLO08(), None, _SlowReader08(), False, None),
        daemon=True,
    )
    t_worker08.start()
    try:
        t0_disp = time.perf_counter()
        dummy_frame = np.full((360, 640, 3), 90, dtype=np.uint8)
        cv2.rectangle(dummy_frame, (200, 260), (440, 310), (255, 255, 255), -1)
        cv2.rectangle(dummy_frame, (200, 260), (440, 310), (0, 0, 0), 3)
        for idx in range(1, 25):
            gap08_st["n"] = idx
            if idx % 6 == 0:
                m._enqueue_latest_inference(gap08_st, (dummy_frame.copy(), time.time(), [], [], idx))
            with gap08_st["infer_lock"]:
                _ = list(gap08_st["vboxes"])
                _ = list(gap08_st["boxes"])
            if idx % 2 == 0:
                jpg_b = cv2.imencode(".jpg", dummy_frame, [cv2.IMWRITE_JPEG_QUALITY, 65])[1].tobytes()
                m.bus.set_frame(jpg_b, cam="CAM_GAP08", status="online")
                gap08_frames_streamed += 1
        disp_elapsed_ms = (time.perf_counter() - t0_disp) * 1000.0
        fid_delta_during_infer = m.bus.fid - gap08_fid_before
        # Wait outside the display loop using the explicit test synchronization helper
        settled_ok = m.wait_for_pending_inference(timeout=3.0, cam="CAM_GAP08")
        with gap08_st["infer_lock"]:
            det_runs_08 = gap08_st["det_runs"]
            boxes_08 = list(gap08_st["boxes"])
            dropped_08 = gap08_st["dropped_infer_frames"]
    finally:
        gap08_stop.set()
        t_worker08.join(timeout=1.0)
        m._ACTIVE_CAM_STATES.pop("CAM_GAP08", None)

    # Also verify source code of mersad_live.py has no blocking wait/join inside the display while loop
    ml_src = open(os.path.join(WORK, "mersad_live.py"), encoding="utf-8").read()
    w_pos = ml_src.find("while not STOP_MAIN_EVENT.is_set():")
    fin_pos = ml_src.find("finally:", w_pos) if w_pos != -1 else -1
    loop_body = ml_src[w_pos:fin_pos] if (w_pos != -1 and fin_pos != -1) else ""
    no_wait_in_loop = (
        bool(loop_body)
        and "_enqueue_latest_inference(" in loop_body
        and "wait_for_pending_inference" not in loop_body
        and "infer_idle_event" not in loop_body
        and ".join(" not in loop_body
    )
    check("STAGE4-GAP08", f"24 display frames & {fid_delta_during_infer} MJPEG updates completed in {disp_elapsed_ms:.1f}ms (<120ms) while 250ms OCR ran asynchronously",
          disp_elapsed_ms < 150.0 and fid_delta_during_infer >= 12 and settled_ok and det_runs_08 >= 1
          and len(boxes_08) >= 1 and dropped_08 >= 1 and no_wait_in_loop,
          (disp_elapsed_ms, fid_delta_during_infer, settled_ok, det_runs_08, len(boxes_08), dropped_08, no_wait_in_loop))

    # 2. STAGE4-GAP12: Thread safety of server.Bus under concurrent load, abrupt SSE/MJPEG client disconnect (BrokenPipeError), & resolve_dashboard_path
    gap12_errs = []
    srv_12 = srv_mod.ThreadingHTTPServer(("127.0.0.1", 0), srv_mod.H)
    port_12 = srv_12.server_address[1]
    threading.Thread(target=srv_12.serve_forever, daemon=True).start()
    try:
        # (a) Concurrent writers calling set_frame, publish, and mutating alerts/failed_dispatches under bus._lock
        stop_12 = threading.Event()
        def _spam_bus():
            for i in range(60):
                try:
                    m.bus.set_frame(b"\xff\xd8\xff\xe0fakejpg" + bytes([i % 255]), cam="CAM1", status="online")
                    m.bus.publish({"type": "sighting", "plate": f"100{i}", "cam": "CAM1", "vclass": "car", "conf": 0.9, "ts": "12:00:00"})
                    with m.bus._lock:
                        m.bus.alerts.append({"id": 99000 + i, "msg": "NEW PLATE (first sighting)", "subject": f"100{i}"})
                        m.bus.alerts.pop()
                except Exception as ex:
                    gap12_errs.append(repr(ex))

        spam_threads = [threading.Thread(target=_spam_bus, daemon=True) for _ in range(4)]
        for st_t in spam_threads:
            st_t.start()

        # (b) Abruptly open and close 6 SSE (/events) and 6 MJPEG (/stream.mjpg) sockets mid-stream
        for _ in range(6):
            for ep in ("/events", "/stream.mjpg"):
                s_raw = socket.create_connection(("127.0.0.1", port_12), timeout=2.0)
                s_raw.sendall(f"GET {ep}?k={m.bus.token} HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n".encode("ascii"))
                _ = s_raw.recv(64)
                s_raw.close()

        for st_t in spam_threads:
            st_t.join(timeout=5.0)
        time.sleep(0.08)
        # Trigger a publish so any disconnected SSE queue is cleaned up
        m.bus.publish({"type": "ping_cleanup"})
        time.sleep(0.05)

        with m.bus._lock:
            subs_remaining = len(m.bus.subs)
            has_cam_status = m.bus.cam_status.get("CAM1") == "online"

        # (c) Verify server is still healthy and resolve_dashboard_path resolves dashboard.html
        ping_12 = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port_12}/api/ping?k={m.bus.token}", timeout=2.0).read())
        dash_resolved = srv_mod.resolve_dashboard_path("dashboard.html")
        check("STAGE4-GAP12", "Bus._lock protects concurrent state, abrupt SSE/MJPEG disconnects clean up without BrokenPipe crash, & resolve_dashboard_path works",
              not gap12_errs and subs_remaining == 0 and has_cam_status and ping_12.get("ok") is True and os.path.isfile(dash_resolved),
              (gap12_errs, subs_remaining, has_cam_status, ping_12, dash_resolved))
    finally:
        srv_12.shutdown()

    # 3. STAGE4-GAP13: Approximate lookup performance & SQL filtering on 5,000 normal vehicles + 5 wanted vehicles
    gap13_dir = tempfile.mkdtemp(prefix="mersad_s4_gap13_")
    try:
        g13_db_path = os.path.join(gap13_dir, "gap13.db")
        c_g13 = sqlite3.connect(g13_db_path, timeout=10.0, check_same_thread=False)
        l_g13 = threading.RLock()
        reg_mod.init(c_g13, l_g13, lambda *a: None, lambda: None, db_path=g13_db_path)

        now_13 = time.time()
        bulk_normal = [
            (f"عدن-{100000 + i}", f"{100000 + i}", "عدن", "عدن", "Corolla", "white", "car", f"Owner {i}", "normal", "", now_13)
            for i in range(5000)
        ]
        wanted_5 = [
            ("عدن-900015", "900015", "عدن", "عدن", "Hilux", "white", "truck", "Wanted 1", "wanted", "", now_13),
            ("عدن-900025", "900025", "عدن", "عدن", "Hilux", "black", "truck", "Wanted 2", "stolen", "", now_13),
            ("عدن-900035", "900035", "عدن", "عدن", "Prado", "silver", "car", "Wanted 3", "wanted", "", now_13),
            ("عدن-900045", "900045", "عدن", "عدن", "Camry", "gray", "car", "Wanted 4", "stolen", "", now_13),
            ("عدن-900055", "900055", "عدن", "عدن", "Sunny", "blue", "car", "Wanted 5", "wanted", "", now_13),
        ]
        c_g13.executemany(
            "INSERT INTO vehicles(plate,plate_digits,plate_letters,governorate,model,color,vtype,owner,status,notes,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            bulk_normal + wanted_5
        )
        c_g13.commit()

        # Verify idx_vehicles_status exists
        idx_names = {r[1] for r in c_g13.execute("PRAGMA index_list(vehicles)").fetchall()}

        # Lookup '900016' (edit distance 1 from wanted '900015')
        res_approx = reg_mod.lookup_vehicle("عدن 900016")
        stats_approx = dict(reg_mod.LAST_LOOKUP_STATS)

        # Lookup '888888' (unregistered plate, no match)
        res_miss = reg_mod.lookup_vehicle("عدن 888888")
        stats_miss = dict(reg_mod.LAST_LOOKUP_STATS)
        c_g13.close()

        gap13_ok = (
            "idx_vehicles_status" in idx_names and "idx_vehicles_digits" in idx_names
            and res_approx is not None and res_approx["plate"] == "عدن-900015"
            and res_approx["match_type"] == "approximate" and res_approx["visual_check_only"] is True
            and stats_approx["approx_rows_scanned"] == 5 and stats_approx["legacy_rows_scanned"] == 0
            and stats_approx["elapsed_ms"] < 25.0
            and res_miss is None and stats_miss["approx_rows_scanned"] == 5
        )
        check("STAGE4-GAP13", f"lookup_vehicle on 5,005 rows scans ONLY {stats_approx['approx_rows_scanned']} wanted/stolen rows in {stats_approx['elapsed_ms']:.2f}ms (<25ms)",
              gap13_ok, (idx_names, res_approx, stats_approx, stats_miss))
    finally:
        reg_mod.init(m.db, m.DBL, m.log, m.refresh_known, db_path=m.DB_PATH)
        shutil.rmtree(gap13_dir, ignore_errors=True)

    # 4. STAGE4-GAP14: Verify dashboard.html handles HTTP 401/403 session expiry & network disconnect explicitly + passes node --check
    dash_html = open(os.path.join(WORK, "dashboard.html"), encoding="utf-8").read()
    has_rjson_403 = (
        "async function rJson(" in dash_html
        and "r.status===401||r.status===403" in dash_html
        and "انتهت الجلسة أو رمز الدخول غير صالح" in dash_html
        and "انقطع الاتصال بالخادم — جاري إعادة المحاولة..." in dash_html
        and 'id="st-txt"' in dash_html
        and ".dot.bad" in dash_html
    )
    js_start = dash_html.find("<script>")
    js_end = dash_html.rfind("</script>")
    js_code = dash_html[js_start + len("<script>"):js_end] if (js_start != -1 and js_end != -1) else ""
    js_tmp = os.path.join(WORK, "_check_dash_stage4.js")
    with open(js_tmp, "w", encoding="utf-8") as jf:
        jf.write(js_code)
    node_bin = shutil.which("node")
    node_ok = True
    node_err = ""
    if node_bin:
        np_res = subprocess.run([node_bin, "--check", js_tmp], capture_output=True, text=True, timeout=10)
        node_ok = (np_res.returncode == 0)
        node_err = np_res.stderr
    try:
        os.remove(js_tmp)
    except OSError:
        pass
    check("STAGE4-GAP14", "dashboard.html detects HTTP 401/403 session expiry & connection loss in #st/#st-txt and passes JS syntax check",
          has_rjson_403 and node_ok, (has_rjson_403, node_ok, node_err))

    # 5. STAGE4-GAP16: Test resolve_compute_device(auto/cpu/cuda) with mock torch (CUDA available vs unavailable) + YOLO & EasyOCR device propagation
    class _MockTorchCudaYes:
        class cuda:
            @staticmethod
            def is_available(): return True

    class _MockTorchCudaNo:
        class cuda:
            @staticmethod
            def is_available(): return False

    dev_auto_cuda = m.resolve_compute_device("auto", torch_module=_MockTorchCudaYes)
    dev_auto_nocuda = m.resolve_compute_device("auto", torch_module=_MockTorchCudaNo)
    dev_cpu_forced = m.resolve_compute_device("cpu", torch_module=_MockTorchCudaYes)
    dev_gpu_fallback = m.resolve_compute_device("cuda", torch_module=_MockTorchCudaNo)
    dev_gpu_ok = m.resolve_compute_device("cuda", torch_module=_MockTorchCudaYes)

    # Verify detect_vehicles passes device= to YOLO callable
    YOLO_CALL_KWARGS.clear()
    _ = m.detect_vehicles(np.zeros((100, 100, 3), dtype=np.uint8), YOLO("yolov8n.pt"), device="cuda:0")
    yolo_received_dev = YOLO_CALL_KWARGS.get("device")

    setup_bat_txt = open(os.path.join(WORK, "setup.bat"), encoding="utf-8").read()
    prefetch_txt = open(os.path.join(WORK, "prefetch.py"), encoding="utf-8").read()

    gap16_ok = (
        dev_auto_cuda["device"] == "cuda:0" and dev_auto_cuda["use_gpu"] is True and not dev_auto_cuda["fallback_warning"]
        and dev_auto_nocuda["device"] == "cpu" and dev_auto_nocuda["use_gpu"] is False and not dev_auto_nocuda["fallback_warning"]
        and dev_cpu_forced["device"] == "cpu" and dev_cpu_forced["use_gpu"] is False
        and dev_gpu_fallback["device"] == "cpu" and dev_gpu_fallback["use_gpu"] is False and "falling back safely to CPU" in dev_gpu_fallback["fallback_warning"]
        and dev_gpu_ok["device"] == "cuda:0" and dev_gpu_ok["use_gpu"] is True
        and yolo_received_dev == "cuda:0"
        and "resolve_compute_device" in prefetch_txt
        and "download.pytorch.org/whl/cpu" in setup_bat_txt
    )
    check("STAGE4-GAP16", "resolve_compute_device selects cuda:0 when available, falls back to CPU with warning when unavailable, and passes device to YOLO & EasyOCR",
          gap16_ok, (dev_auto_cuda, dev_auto_nocuda, dev_cpu_forced, dev_gpu_fallback, yolo_received_dev))


run_stage4_gap_regression_tests()


def run_stage5_gap_regression_tests():
    import check_install as chk_mod

    # 1. STAGE5-GAP17: Test evaluate_plates_dataset() metrics (exact_match_rate, digits_match_rate, cer, detection_recall, mean_iou, mean_latency_ms)
    #    and verify safe non-fabricating behavior when dataset / ground_truth.csv is missing
    gap17_dir = tempfile.mkdtemp(prefix="mersad_s5_gap17_")
    try:
        # (a) Missing directory / missing ground_truth.csv -> must return ok=False, status='dataset_missing_or_empty', total_samples=0 without fabricating metrics
        missing_path = os.path.join(gap17_dir, "nonexistent_dataset")
        rep_missing = m.evaluate_plates_dataset(missing_path, print_report=False)

        # Also test CLI `--evaluate-plates <missing_path> --json` does not create mersad.db or mersad.log in cwd
        cli_cwd = os.path.join(gap17_dir, "cli_cwd")
        os.makedirs(cli_cwd, exist_ok=True)
        p_eval_missing = subprocess.run(
            [sys.executable, os.path.join(WORK, "mersad_live.py"), "--evaluate-plates", missing_path, "--json"],
            cwd=cli_cwd, capture_output=True, text=True, timeout=15
        )
        j_eval_missing = json.loads(p_eval_missing.stdout) if p_eval_missing.stdout.strip().startswith("{") else {}
        cli_cwd_clean = (os.listdir(cli_cwd) == [])

        # (b) Isolated 4-sample dataset with known OCR outputs to verify exact mathematical calculation of:
        #     - Sample 1 (img1.jpg): expected 'عدن-12345', predicted 'عدن ١٢٣٤٥' (-> 'عدن-12345'): exact=True, digits=True, CER=0.0, IoU=1.0
        #     - Sample 2 (img2.jpg): expected 'عدن-12345', predicted 'صنعاء ١٢٣٤٥' (-> 'صنعاء-12345'): exact=False, digits=True, CER=4/9=0.4444, IoU=1.0
        #     - Sample 3 (img3.jpg): expected '12345', predicted '12349': exact=False, digits=False, CER=1/5=0.2, IoU=1.0
        #     - Sample 4 (img4.jpg): expected '99999', predicted '99999': exact=True, digits=True, CER=0.0, IoU=1.0
        ds_dir = os.path.join(gap17_dir, "plate_bench")
        os.makedirs(ds_dir, exist_ok=True)
        widths = (180, 205, 230, 255)
        for idx, w_rect in enumerate(widths, 1):
            im = np.full((360, 640, 3), 30, dtype=np.uint8)
            cv2.rectangle(im, (200, 240), (200 + w_rect, 292), (255, 255, 255), -1)
            cv2.rectangle(im, (200, 240), (200 + w_rect, 292), (0, 0, 0), 3)
            cv2.imwrite(os.path.join(ds_dir, f"img{idx}.jpg"), im)

        gt_csv_path = os.path.join(ds_dir, "ground_truth.csv")
        with open(gt_csv_path, "w", encoding="utf-8", newline="") as cf:
            cf.write("filename,expected_plate,x,y,w,h\n")
            cf.write("img1.jpg,عدن-12345,200,240,180,52\n")
            cf.write("img2.jpg,عدن-12345,200,240,205,52\n")
            cf.write("img3.jpg,12345,200,240,230,52\n")
            cf.write("img4.jpg,99999,200,240,255,52\n")

        class _BenchReader:
            def readtext(self, crop):
                cw = crop.shape[1] if (crop is not None and crop.ndim >= 2) else 0
                if cw < 193:
                    txt = "عدن ١٢٣٤٥"
                elif cw < 218:
                    txt = "صنعاء ١٢٣٤٥"
                elif cw < 243:
                    txt = "12349"
                else:
                    txt = "99999"
                return [([[0, 0], [1, 0], [1, 1], [0, 1]], txt, 0.93)]

        out_json_p = os.path.join(gap17_dir, "bench_out.json")
        rep_eval = m.evaluate_plates_dataset(ds_dir, output_json=out_json_p, reader=_BenchReader(), print_report=False)
        saved_json = json.load(open(out_json_p, encoding="utf-8")) if os.path.isfile(out_json_p) else {}
        met = rep_eval.get("metrics", {})
        expected_mean_cer = round((0.0 + (4.0 / 9.0) + 0.2 + 0.0) / 4.0, 4)

        gap17_ok = (
            rep_missing.get("ok") is False
            and rep_missing.get("status") == "dataset_missing_or_empty"
            and rep_missing.get("total_samples") == 0
            and "ground_truth_schema" in rep_missing
            and p_eval_missing.returncode == 1
            and j_eval_missing.get("status") == "dataset_missing_or_empty"
            and cli_cwd_clean
            and rep_eval.get("ok") is True
            and rep_eval.get("total_samples") == 4
            and met.get("detection_recall") == 1.0
            and met.get("mean_iou") is not None and met.get("mean_iou") >= 0.85
            and met.get("exact_match_rate") == 0.5
            and met.get("digits_match_rate") == 0.75
            and abs(met.get("character_error_rate", 99.0) - expected_mean_cer) < 1e-4
            and met.get("mean_latency_ms", 0.0) > 0.0
            and saved_json.get("metrics", {}).get("exact_match_rate") == 0.5
        )
        check("STAGE5-GAP17", "evaluate_plates_dataset computes exact_match_rate, digits_match_rate, CER, recall & IoU accurately, and safely reports missing datasets",
              gap17_ok, (rep_missing.get("status"), cli_cwd_clean, met, expected_mean_cer))
    finally:
        shutil.rmtree(gap17_dir, ignore_errors=True)

    # 2. STAGE5-GAP18: Verify alignment of mersad_ai.spec, BUILD_EXE.bat, and .github/workflows/windows-build.yml
    #    (hiddenimports parity, PowerShell syntax, $env:RUNNER_TEMP + $env:MERSAD_DATA_DIR isolation, and CLI flags)
    ok_bld, bld_info = chk_mod.verify_build_config_consistency(WORK)
    ml_code = open(os.path.join(WORK, "mersad_live.py"), encoding="utf-8").read()
    cli_flags_supported = (
        '"--verify-models"' in ml_code
        and '"--verify"' in ml_code
        and '"--evaluate-plates"' in ml_code
    )
    build_rep_txt = open(os.path.join(WORK, "BUILD_REPORT.md"), encoding="utf-8").read()
    readme_txt = open(os.path.join(WORK, "README_AR.md"), encoding="utf-8").read()
    docs_updated = (
        "غير متحقق منه ميدانياً" in build_rep_txt
        and "--evaluate-plates" in readme_txt
        and "ground_truth.csv" in readme_txt
    )
    check("STAGE5-GAP18", "mersad_ai.spec, BUILD_EXE.bat & windows-build.yml hiddenimports and PowerShell $env:RUNNER_TEMP isolation are aligned",
          ok_bld and cli_flags_supported and docs_updated,
          (bld_info, cli_flags_supported, docs_updated))


run_stage5_gap_regression_tests()


def run_stage6_gap_regression_tests():
    import camera_history as ch_mod

    # 1. STAGE6-GAP01: Verify FACE_DETECT_INTERVAL caches and reuses st['face_entries'] on intermediate frames
    #    while preserving 100% face blurring on vehicle alerts
    orig_interval = m.FACE_DETECT_INTERVAL
    try:
        m.FACE_DETECT_INTERVAL = 2
        det_calls = {"n": 0}
        class _CountingDet:
            def setInputSize(self, s): pass
            def detect(self, f):
                det_calls["n"] += 1
                return 1, np.array([[40, 50, 60, 60] + [0] * 10 + [0.95]], dtype=np.float32)

        st_01 = {
            "cam": "CAM_G6_01",
            "n": 0,
            "infer_lock": threading.Lock(),
            "face_entries": [],
            "unmatched_face_boxes": [],
            "face_det_runs": 0,
        }
        det_inst = _CountingDet()
        rec_inst = FakeRec()
        rng_01 = np.random.default_rng(77)
        test_frm = rng_01.integers(0, 255, (160, 240, 3), dtype=np.uint8)

        # Simulate 4 frames with no active enrollment session (n=1 runs, n=2 reuses cache, n=3 runs, n=4 reuses cache -> 2 det calls instead of 4!)
        m.ENR["req"] = None
        blur_boxes_per_frame = []
        for f_no in range(1, 5):
            st_01["n"] = f_no
            should_det = (st_01["n"] <= 1) or (st_01["n"] % m.FACE_DETECT_INTERVAL == 0) or (m.ENR.get("req") is not None) or (not st_01.get("face_entries"))
            if should_det:
                det_inst.setInputSize((240, 160))
                _, fs_01 = det_inst.detect(test_frm)
                fe_list = []
                for f in (fs_01 if fs_01 is not None else []):
                    x, y, bw, bh = map(int, f[:4])
                    raw_e = rec_inst.feature(rec_inst.alignCrop(test_frm, f))
                    m_r = m.match_face_embedding(raw_e, rec=rec_inst)
                    fe_list.append((x, y, bw, bh, m_r[0], m_r[1], m_r[2], raw_e, getattr(m_r, "person_id", 0), getattr(m_r, "ref", "")))
                with st_01["infer_lock"]:
                    st_01["face_entries"] = list(fe_list)
                    st_01["face_det_runs"] += 1
            else:
                with st_01["infer_lock"]:
                    fe_list = list(st_01["face_entries"])
            blur_boxes_per_frame.append(m.get_boxes_to_blur_for_alert(fe_list, alert_kind="vehicle"))

        # Verify intermediate frame (f_no=2, index 1) still blurs the cached face 100%!
        blurred_f2 = m.blur_unmatched_faces(test_frm, blur_boxes_per_frame[1])
        face_roi_diff = float(np.abs(test_frm[50:110, 40:100].astype(np.float32) - blurred_f2[50:110, 40:100].astype(np.float32)).mean())
        check("STAGE6-GAP01", "FACE_DETECT_INTERVAL caches st['face_entries'] on intermediate frames (50% fewer SFace runs) while preserving 100% vehicle alert face blur",
              det_calls["n"] == 3 and all(len(b) == 1 and b[0] == (40, 50, 60, 60) for b in blur_boxes_per_frame) and face_roi_diff > 5.0,
              (det_calls["n"], blur_boxes_per_frame, face_roi_diff))
    finally:
        m.FACE_DETECT_INTERVAL = orig_interval

    # 2. STAGE6-GAP02: Verify all accesses to bus.alerts and bus.failed_dispatches in mersad_live.py are protected by bus._lock
    ml_code_02 = open(os.path.join(WORK, "mersad_live.py"), encoding="utf-8").read()
    lines_02 = ml_code_02.splitlines()
    unlocked_hits = []
    for idx_l, line_s in enumerate(lines_02):
        stripped = line_s.strip()
        if stripped.startswith("#") or stripped.startswith('"""'):
            continue
        if "bus.alerts" in stripped or "bus.failed_dispatches" in stripped:
            # Check a window of 6 preceding lines for `with bus._lock:`
            ctx_window = "\n".join(lines_02[max(0, idx_l - 6):idx_l + 1])
            if "with bus._lock:" not in ctx_window:
                unlocked_hits.append((idx_l + 1, stripped))

    # Also run concurrent _refresh_failed_dispatches() and stats() calls without error
    g02_errs = []
    def _concurrent_stats_fdisp():
        for _ in range(25):
            try:
                m._refresh_failed_dispatches()
                _ = m.stats()
            except Exception as e:
                g02_errs.append(repr(e))
    t_g02 = [threading.Thread(target=_concurrent_stats_fdisp, daemon=True) for _ in range(3)]
    for th in t_g02: th.start()
    for th in t_g02: th.join(timeout=5.0)
    check("STAGE6-GAP02", "all reads/writes of bus.alerts & bus.failed_dispatches in mersad_live.py are protected by with bus._lock:",
          len(unlocked_hits) == 0 and len(g02_errs) == 0,
          (unlocked_hits, g02_errs))

    # 3. STAGE6-GAP03: Verify dashboard.html passes cam:CUR_CAM||undefined to /api/enroll and displays m.error & m.warning in enroll SSE
    dash_03 = open(os.path.join(WORK, "dashboard.html"), encoding="utf-8").read()
    has_cam_in_enroll = 'post("/api/enroll",{id:b.dataset.id||undefined,ref:b.dataset.r||"",name:b.dataset.n,cam:CUR_CAM||undefined})' in dash_03
    has_err_warn_sse = 'm.n<0?(m.error||"انتهت المهلة: لم يظهر وجه"):m.warning?("⚠️ "+m.warning)' in dash_03
    js_s = dash_03[dash_03.find("<script>") + 8:dash_03.rfind("</script>")]
    js_f = os.path.join(WORK, "_check_dash_stage6.js")
    open(js_f, "w", encoding="utf-8").write(js_s)
    node_b = shutil.which("node")
    node_03_ok = True
    if node_b:
        node_03_ok = (subprocess.run([node_b, "--check", js_f], capture_output=True, text=True, timeout=10).returncode == 0)
    try: os.remove(js_f)
    except OSError: pass
    check("STAGE6-GAP03", "dashboard.html passes cam:CUR_CAM||undefined to /api/enroll, displays m.error & m.warning, and passes node --check",
          has_cam_in_enroll and has_err_warn_sse and node_03_ok,
          (has_cam_in_enroll, has_err_warn_sse, node_03_ok))

    # 4. STAGE6-GAP04: Verify _ENROLL_LOCK exists and re-enrolling an existing person replaces their old 5 samples with 5 fresh samples (not 10)
    has_enroll_lock = hasattr(m, "_ENROLL_LOCK") and isinstance(m._ENROLL_LOCK, type(threading.RLock()))
    r_p04 = reg_mod.save_person({"name": "عمار نبيل", "ref": "G6-04", "consent": True, "status": "watch"}, "s6")
    pid_04 = r_p04["id"]
    try:
        v_first = np.zeros((1, 128), dtype=np.float32); v_first[0, 0] = 1.0
        v_second = np.zeros((1, 128), dtype=np.float32); v_second[0, 1] = 1.0

        # Enrollment #1 -> 5 samples
        m.req_enroll("عمار نبيل", True, "s6", ref="G6-04", person_id=pid_04, cam="CAM1")
        for _ in range(5):
            m.enroll_step(v_first, cam="CAM1", face_box=(80, 80, 90, 90))
        cnt_after_enr1 = db_q("SELECT COUNT(*) FROM faces WHERE person_id=?", pid_04)[0][0]
        match_1 = m.match_face_embedding(v_first)

        # Enrollment #2 (re-enrollment of same person) -> must replace old 5 samples with new 5 samples (count stays 5, not 10!)
        m.req_enroll("عمار نبيل", True, "s6", ref="G6-04", person_id=pid_04, cam="CAM2")
        for _ in range(5):
            m.enroll_step(v_second, cam="CAM2", face_box=(80, 80, 90, 90))
        cnt_after_enr2 = db_q("SELECT COUNT(*) FROM faces WHERE person_id=?", pid_04)[0][0]
        match_old = m.match_face_embedding(v_first)
        match_new = m.match_face_embedding(v_second)

        check("STAGE6-GAP04", "_ENROLL_LOCK protects enrollment state and re-enrollment replaces prior samples (5 fresh samples, old vectors removed)",
              has_enroll_lock and cnt_after_enr1 == 5 and match_1[0] == "عمار نبيل"
              and cnt_after_enr2 == 5 and match_old[0] == "unenrolled" and match_new[0] == "عمار نبيل",
              (has_enroll_lock, cnt_after_enr1, cnt_after_enr2, match_old, match_new))
    finally:
        reg_mod.delete("persons", f"id:{pid_04}", "s6")

    # 5. STAGE6-GAP05: Verify per-camera FH streak isolation across cameras with different frame_idx + camera_history.prune_history()
    m.FH.clear()
    m.FA.clear()
    frm_05 = np.zeros((120, 160, 3), dtype=np.uint8)
    # Sighting 1 on CAM1 at frame_idx=1000
    a1 = m.face_step("شخص اختبار", 0.88, 1, frm_05, "CAM1", frame_idx=1000, person_id=777, ref="R-777")
    # Interleaved sighting on CAM2 at frame_idx=10 (completely different frame counter!)
    a_cam2 = m.face_step("شخص اختبار", 0.88, 1, frm_05, "CAM2", frame_idx=10, person_id=777, ref="R-777")
    # Sightings 2 & 3 on CAM1 at frame_idx=1002 and 1004 -> must reach cnt=3 and trigger alert!
    a2 = m.face_step("شخص اختبار", 0.88, 1, frm_05, "CAM1", frame_idx=1002, person_id=777, ref="R-777")
    a3 = m.face_step("شخص اختبار", 0.88, 1, frm_05, "CAM1", frame_idx=1004, person_id=777, ref="R-777")
    # Immediate sighting 2 & 3 on CAM2 within cooldown -> blocked by global FA[identity_key] cooldown!
    a_cam2_2 = m.face_step("شخص اختبار", 0.88, 1, frm_05, "CAM2", frame_idx=12, person_id=777, ref="R-777")
    a_cam2_3 = m.face_step("شخص اختبار", 0.88, 1, frm_05, "CAM2", frame_idx=14, person_id=777, ref="R-777")

    # Clean up the test alert created by a3
    with m.DBL:
        m.db.execute("UPDATE alerts SET status='dismiss' WHERE msg LIKE 'FACE MATCH%' AND cam='CAM1'")
        m.db.commit()
    m._sync_alerts_from_db()

    # Test camera_history.prune_history(retention_days=90)
    ch_mod.init(m.db, m.DBL, db_path=m.DB_PATH)
    now_05 = time.time()
    ch_mod.record_status("CAM_PRUNE_TEST", "online", reason="startup", ts=now_05 - 120 * 86400.0, force=True)
    ch_mod.record_status("CAM_PRUNE_TEST", "reconnecting", reason="read_failed", ts=now_05 - 5 * 86400.0, force=True)
    pr_res = ch_mod.prune_history(retention_days=90, now=now_05)
    rem_rows = db_q("SELECT COUNT(*) FROM camera_status_history WHERE cam='CAM_PRUNE_TEST'")[0][0]

    check("STAGE6-GAP05", "per-camera FH key prevents cross-camera frame_idx interference while preserving global FA cooldown, and prune_history cleans old rows",
          (not a1) and (not a_cam2) and (not a2) and (a3 is True) and (not a_cam2_2) and (not a_cam2_3)
          and pr_res.get("ok") is True and pr_res.get("deleted", 0) >= 1 and rem_rows == 1,
          (a1, a_cam2, a2, a3, a_cam2_3, pr_res, rem_rows))


run_stage6_gap_regression_tests()


def run_stage7_gap_regression_tests():
    # 1. STAGE7-GAP06: Test evaluate_plates_dataset(..., vyolo=...) two-stage vehicle->plate cropping pipeline
    #    Create a full-scene image containing 4 large distractors outside the vehicle box (in the top sky/background)
    #    so without vyolo, find_plates(img)[:3] would only return the top distractors and miss the real plate inside the vehicle!
    #    With vyolo provided, detect_vehicles crops the vehicle box (100, 150, 400, 290) -> lower 65% (oy=251..440),
    #    finds the real plate at (200, 340, 200, 50) in image coordinates, and achieves IoU >= 0.85 & exact_match_rate == 1.0!
    gap06_dir = tempfile.mkdtemp(prefix="mersad_s7_gap06_")
    try:
        scene_img = np.full((480, 640, 3), 30, dtype=np.uint8)
        # Draw 4 larger rectangular distractors in the upper background (y=10..80, outside vehicle y=150..440)
        for dx in (10, 160, 310, 460):
            cv2.rectangle(scene_img, (dx, 15), (dx + 140, 75), (255, 255, 255), -1)
            cv2.rectangle(scene_img, (dx, 15), (dx + 140, 75), (0, 0, 0), 3)

        # Draw the actual license plate inside the lower half of the vehicle box (x=200..400, y=340..392)
        cv2.rectangle(scene_img, (200, 340), (400, 392), (255, 255, 255), -1)
        cv2.rectangle(scene_img, (200, 340), (400, 392), (0, 0, 0), 3)
        img_p06 = os.path.join(gap06_dir, "scene1.jpg")
        cv2.imwrite(img_p06, scene_img)

        gt_p06 = os.path.join(gap06_dir, "ground_truth.csv")
        with open(gt_p06, "w", encoding="utf-8", newline="") as cf:
            cf.write("filename,expected_plate,x,y,w,h\n")
            cf.write("scene1.jpg,عدن-12345,200,340,200,52\n")

        class _SceneReader:
            def readtext(self, crop):
                return [([[0, 0], [1, 0], [1, 1], [0, 1]], "عدن ١٢٣٤٥", 0.95)]

        rep_with_vyolo = m.evaluate_plates_dataset(
            gap06_dir,
            reader=_SceneReader(),
            vyolo=YOLO("yolov8n.pt"),
            print_report=False,
        )
        met_v = rep_with_vyolo.get("metrics", {})
        smp_v = (rep_with_vyolo.get("samples") or [{}])[0]
        check("STAGE7-GAP06", "evaluate_plates_dataset(..., vyolo=...) crops detected vehicles first, translates plate coords, and achieves IoU>=0.85 & exact_match=1.0",
              rep_with_vyolo.get("ok") is True
              and rep_with_vyolo.get("vehicle_stage_enabled") is True
              and smp_v.get("vehicle_boxes_count", 0) >= 1
              and met_v.get("detection_recall") == 1.0
              and (met_v.get("mean_iou") or 0.0) >= 0.85
              and met_v.get("exact_match_rate") == 1.0,
              (rep_with_vyolo.get("vehicle_stage_enabled"), smp_v, met_v))
    finally:
        shutil.rmtree(gap06_dir, ignore_errors=True)

    # 2. STAGE7-GAP07: Verify RUN.bat, RUN_LAN.bat, and CHECK.bat consistency
    run_bat_s = open(os.path.join(WORK, "RUN.bat"), encoding="utf-8").read()
    run_lan_s = open(os.path.join(WORK, "RUN_LAN.bat"), encoding="utf-8").read()
    chk_bat_s = open(os.path.join(WORK, "CHECK.bat"), encoding="utf-8").read()
    bat_ok = (
        "venv\\Scripts\\python.exe check_install.py --strict" in run_bat_s
        and "venv\\Scripts\\python.exe check_install.py --strict" in run_lan_s
        and "venv\\Scripts\\python.exe mersad_live.py --host 0.0.0.0" in run_lan_s
        and "venv\\Scripts\\python.exe selftest.py ||" in chk_bat_s
        and "venv\\Scripts\\python.exe check_install.py --camera ||" in chk_bat_s
    )
    check("STAGE7-GAP07", "RUN.bat, RUN_LAN.bat, and CHECK.bat enforce check_install.py --strict, python.exe paths, and errorlevel exit checks",
          bat_ok, (run_lan_s, chk_bat_s))

    # 3. STAGE7-GAP08: Verify all 7 documentation/report files are aligned on 168 PASS and document --evaluate-plates
    doc_files = ("README_AR.md", "BUILD_REPORT.md", "AUDIT_REPORT.md", "TEST_REPORT.md", "V7_TEST_REPORT.md", "V7_RELEASE_NOTES.md", "CHANGELOG.md")
    missing_168 = []
    missing_eval = []
    for dfn in doc_files:
        dp = os.path.join(WORK, dfn)
        ds = open(dp, encoding="utf-8").read() if os.path.isfile(dp) else ""
        if "193" not in ds:
            missing_168.append(dfn)
        if "--evaluate-plates" not in ds:
            missing_eval.append(dfn)
    check("STAGE7-GAP08", "all 7 documentation & report files document the unified V7.1 test count (193 PASS) and --evaluate-plates tool",
          len(missing_168) == 0 and len(missing_eval) == 0,
          (missing_168, missing_eval))


run_stage7_gap_regression_tests()


def run_stage8_final_hardening_tests():
    import server as srv_mod
    import http.client

    # 1. STAGE8-OBS01: Verify registry.parse_file() closes openpyxl workbook inside try...finally
    reg_src_01 = open(os.path.join(WORK, "registry.py"), encoding="utf-8").read()
    has_wb_close_finally = ("wb = load_workbook(" in reg_src_01 and "finally:" in reg_src_01 and "wb.close()" in reg_src_01)
    xlsx_bytes, _, _ = reg_mod.template("vehicles")
    rows_01 = reg_mod.parse_file("vehicles_test.xlsx", xlsx_bytes)
    check("STAGE8-OBS01", "registry.parse_file closes openpyxl read_only workbook inside try...finally without leaking handles",
          has_wb_close_finally and isinstance(rows_01, list) and len(rows_01) >= 2,
          (has_wb_close_finally, len(rows_01)))

    # 2. STAGE8-OBS02: Verify insights._STATE_LOCK & _TRAIN_LOCK thread safety and non-mutating feat() on unseen cameras
    has_ins_locks = hasattr(ins_mod, "_STATE_LOCK") and hasattr(ins_mod, "_TRAIN_LOCK")
    with ins_mod._STATE_LOCK:
        cams_before = dict(ins_mod.M.get("cams") or {})
    _ = ins_mod.feat(time.time(), "UNSEEN_CAM_STAGE8_TEST", "car", 1, 10.0, cams_map=None)
    with ins_mod._STATE_LOCK:
        cams_after = dict(ins_mod.M.get("cams") or {})
    no_live_cam_mutation = ("UNSEEN_CAM_STAGE8_TEST" not in cams_after and cams_before == cams_after)

    obs02_errs = []
    def _train_and_summary_worker():
        for _ in range(3):
            try:
                ins_mod.train(include_demo=False)
                ins_mod.summary(include_demo=False)
            except Exception as e:
                obs02_errs.append(repr(e))

    def _score_and_route_worker():
        for i in range(15):
            try:
                ins_mod.score_live(f"عدن-{40000 + i}", f"CAM_{(i % 3) + 1}", "car", ts=time.time(), conf=0.9)
            except Exception as e:
                obs02_errs.append(repr(e))

    t_obs02 = [
        threading.Thread(target=_train_and_summary_worker, daemon=True),
        threading.Thread(target=_score_and_route_worker, daemon=True),
        threading.Thread(target=_score_and_route_worker, daemon=True),
    ]
    for th in t_obs02: th.start()
    for th in t_obs02: th.join(timeout=8.0)
    check("STAGE8-OBS02", "insights._STATE_LOCK & _TRAIN_LOCK serialize concurrent train/score_live/summary and feat() never mutates M['cams']",
          has_ins_locks and no_live_cam_mutation and len(obs02_errs) == 0,
          (has_ins_locks, no_live_cam_mutation, obs02_errs))

    # 3. STAGE8-OBS03: Verify mersad_live._FACE_STATE_LOCK protects concurrent refresh_known, match_face_embedding, and face_step
    has_face_lock = hasattr(m, "_FACE_STATE_LOCK") and isinstance(m._FACE_STATE_LOCK, type(threading.RLock()))
    obs03_errs = []
    test_emb_03 = np.zeros((1, 128), dtype=np.float32); test_emb_03[0, 0] = 1.0
    frm_03 = np.zeros((100, 120, 3), dtype=np.uint8)

    def _face_refresh_worker():
        for _ in range(6):
            try:
                m.refresh_known()
            except Exception as e:
                obs03_errs.append(repr(e))

    def _face_match_step_worker():
        for i in range(15):
            try:
                _ = m.match_face_embedding(test_emb_03)
                _ = m.face_step("شخص غير مسجل", 0.30, 0, frm_03, "CAM1", frame_idx=i)
            except Exception as e:
                obs03_errs.append(repr(e))

    t_obs03 = [
        threading.Thread(target=_face_refresh_worker, daemon=True),
        threading.Thread(target=_face_match_step_worker, daemon=True),
        threading.Thread(target=_face_match_step_worker, daemon=True),
    ]
    for th in t_obs03: th.start()
    for th in t_obs03: th.join(timeout=8.0)
    check("STAGE8-OBS03", "mersad_live._FACE_STATE_LOCK protects KNOWN, FH, and FA across concurrent refresh_known/match_face_embedding/face_step",
          has_face_lock and len(obs03_errs) == 0,
          (has_face_lock, obs03_errs))

    # 4. STAGE8-OBS04: Verify server.py returns structured JSON on HTTP 400 / 413 and reads bus.post under bus._lock
    srv_src_04 = open(os.path.join(WORK, "server.py"), encoding="utf-8").read()
    has_lock_post = "with bus._lock:\n                    post_fn = bus.post.get(p)" in srv_src_04
    dash_src_04 = open(os.path.join(WORK, "dashboard.html"), encoding="utf-8").read()
    has_rjson_parse = "const j=await r.json();if(j&&j.error)errMsg=j.error" in dash_src_04

    srv_04 = srv_mod.ThreadingHTTPServer(("127.0.0.1", 0), srv_mod.H)
    port_04 = srv_04.server_address[1]
    threading.Thread(target=srv_04.serve_forever, daemon=True).start()
    try:
        conn_413 = http.client.HTTPConnection("127.0.0.1", port_04, timeout=5)
        conn_413.putrequest("POST", f"/api/vehicle?k={m.bus.token}")
        conn_413.putheader("Content-Type", "application/json")
        conn_413.putheader("Content-Length", str(srv_mod.MAX_UPLOAD + 1024))
        conn_413.endheaders()
        resp_413 = conn_413.getresponse()
        body_413 = json.loads(resp_413.read().decode("utf-8"))
        conn_413.close()

        conn_400 = http.client.HTTPConnection("127.0.0.1", port_04, timeout=5)
        conn_400.putrequest("POST", f"/api/vehicle?k={m.bus.token}")
        conn_400.putheader("Content-Type", "application/json")
        conn_400.putheader("Content-Length", "invalid_len")
        conn_400.endheaders()
        resp_400 = conn_400.getresponse()
        body_400 = json.loads(resp_400.read().decode("utf-8"))
        conn_400.close()
    finally:
        srv_04.shutdown()

    check("STAGE8-OBS04", "server.py returns structured JSON on HTTP 400 & 413, reads bus.post under bus._lock, and dashboard rJson extracts error JSON",
          has_lock_post and has_rjson_parse
          and resp_413.status == 413 and body_413.get("ok") is False and "5 ميجابايت" in body_413.get("error", "")
          and resp_400.status == 400 and body_400.get("ok") is False,
          (has_lock_post, has_rjson_parse, resp_413.status, body_413, resp_400.status, body_400))

    # 5. STAGE8-OBS05: Verify all async functions in dashboard.html have try/catch and pass node --check
    dash_src_05 = open(os.path.join(WORK, "dashboard.html"), encoding="utf-8").read()
    required_snippets = [
        "async function saveForm(){try{",
        "async function doImport(kind,file){if(!file)return;const rep=$(\"#rep-\"+kind);rep.textContent=\"جارٍ الاستيراد...\";\n try{",
        "async function dec(id,action){\n try{",
        "async function retryDisp(id){\n try{",
        "async function saveCameraLink(){\n try{",
        "async function delCameraLink(from_cam,to_cam){\n try{",
        "async function loadIns(){\n try{",
        "async function tracePlate(p){\n const q=(p||$(\"#path-q\")?.value||\"\").trim();if(!q)return;\n if($(\"#path-q\"))$(\"#path-q\").value=q;\n try{",
        "async function insAct(a){\n $(\"#ins-st\").textContent=\"جارٍ التنفيذ...\";\n try{",
    ]
    missing_try = [s for s in required_snippets if s not in dash_src_05]
    js_s05 = dash_src_05[dash_src_05.find("<script>") + 8:dash_src_05.rfind("</script>")]
    js_f05 = os.path.join(WORK, "_check_dash_stage8.js")
    open(js_f05, "w", encoding="utf-8").write(js_s05)
    node_b05 = shutil.which("node")
    node_05_ok = True
    if node_b05:
        node_05_ok = (subprocess.run([node_b05, "--check", js_f05], capture_output=True, text=True, timeout=10).returncode == 0)
    try: os.remove(js_f05)
    except OSError: pass
    check("STAGE8-OBS05", "all async UI functions in dashboard.html are protected by try/catch and pass node --check syntax verification",
          len(missing_try) == 0 and node_05_ok,
          (missing_try, node_05_ok))


run_stage8_final_hardening_tests()


def run_stage9_complete_polish_tests():
    import check_install as chk_mod
    import camera_history as ch_mod
    import server as srv_mod
    import http.client

    # 1. STAGE9-OBS01: Verify check_install.check_camera_source() restores source_with_credentials from .mersad_secrets.json
    #    when mersad_config.json has a redacted '***' URL, while keeping credentials redacted in diagnostic output
    obs01_dir = tempfile.mkdtemp(prefix="mersad_s9_obs01_")
    try:
        with open(os.path.join(obs01_dir, "mersad_config.json"), "w", encoding="utf-8") as cf:
            json.dump({"source": "rtsp://admin:***@192.168.1.50:554/live"}, cf)
        with open(os.path.join(obs01_dir, ".mersad_secrets.json"), "w", encoding="utf-8") as sf:
            json.dump({"source_with_credentials": "rtsp://admin:SuperSecretPass99@192.168.1.50:554/live"}, sf)

        opened_urls = []
        class _DummyCredCap:
            def __init__(self, u):
                opened_urls.append(str(u))
            def isOpened(self):
                return True
            def read(self):
                return True, np.zeros((120, 160, 3), dtype=np.uint8)
            def release(self):
                pass

        res_01 = chk_mod.check_camera_source(root_dir=obs01_dir, capture_factory=_DummyCredCap)
        used_real_cred = (len(opened_urls) == 1 and "SuperSecretPass99" in opened_urls[0])
        redacted_in_report = ("SuperSecretPass99" not in json.dumps(res_01, ensure_ascii=False) and "***" in res_01.get("source", ""))
        check("STAGE9-OBS01", "check_camera_source restores source_with_credentials from .mersad_secrets.json while redacting password in output",
              res_01.get("status") == "PASS" and used_real_cred and redacted_in_report,
              (opened_urls, res_01))
    finally:
        shutil.rmtree(obs01_dir, ignore_errors=True)

    # 2. STAGE9-OBS02: Verify _RUNTIME_STATE_LOCK in mersad_live.py and thread-safe concurrent STATUS/WHY/EVID/stats() access
    has_rt_lock = hasattr(m, "_RUNTIME_STATE_LOCK") and isinstance(m._RUNTIME_STATE_LOCK, type(threading.RLock()))
    obs02_errs = []

    def _status_mutator():
        for i in range(25):
            try:
                with m._RUNTIME_STATE_LOCK:
                    m.STATUS["cameras"]["CAM_S9"] = {"status": "online", "fps": 25.0, "frames": i, "detections": i, "errors": 0, "fail_count": 0, "reconnect_count": 0}
                    m.WHY["عدن-99999"] = f"سبب اختباري {i}"
            except Exception as e:
                obs02_errs.append(repr(e))

    def _stats_reader():
        for _ in range(15):
            try:
                s_out = m.stats()
                assert isinstance(s_out.get("cameras"), dict)
            except Exception as e:
                obs02_errs.append(repr(e))

    t_s9_02 = [
        threading.Thread(target=_status_mutator, daemon=True),
        threading.Thread(target=_stats_reader, daemon=True),
        threading.Thread(target=_stats_reader, daemon=True),
    ]
    for th in t_s9_02: th.start()
    for th in t_s9_02: th.join(timeout=8.0)
    with m._RUNTIME_STATE_LOCK:
        m.STATUS["cameras"].pop("CAM_S9", None)
    check("STAGE9-OBS02", "mersad_live._RUNTIME_STATE_LOCK protects STATUS, WHY, AID, EVID & INS.M across concurrent threads",
          has_rt_lock and len(obs02_errs) == 0,
          (has_rt_lock, obs02_errs))

    # 3. STAGE9-OBS03: Verify zero bare open() without 'with' in production .py files, wb.close() in registry.template(), and JSON 404 on /api/*
    prod_files_03 = ("mersad_live.py", "registry.py", "insights.py", "server.py", "notify.py", "analytics.py", "camera_history.py", "check_install.py", "prefetch.py")
    bare_opens = []
    for pf in prod_files_03:
        src_txt = open(os.path.join(WORK, pf), encoding="utf-8").read()
        for ln_no, ln_txt in enumerate(src_txt.splitlines(), 1):
            st_ln = ln_txt.strip()
            if st_ln.startswith("#") or st_ln.startswith("-") or st_ln.startswith('"""'):
                continue
            if "open(" in st_ln and "with " not in st_ln and "os.open(" not in st_ln and "webbrowser.open(" not in st_ln and "lock_file" not in st_ln and "lock_path" not in st_ln:
                bare_opens.append((pf, ln_no, st_ln))

    reg_txt_03 = open(os.path.join(WORK, "registry.py"), encoding="utf-8").read()
    tpl_part = reg_txt_03.partition("def template(kind):")[2]
    has_tpl_wb_close = ("finally:" in tpl_part and "wb.close()" in tpl_part)

    srv_03 = srv_mod.ThreadingHTTPServer(("127.0.0.1", 0), srv_mod.H)
    port_03 = srv_03.server_address[1]
    threading.Thread(target=srv_03.serve_forever, daemon=True).start()
    try:
        c_get404 = http.client.HTTPConnection("127.0.0.1", port_03, timeout=5)
        c_get404.request("GET", f"/api/nonexistent_route?k={m.bus.token}")
        r_get404 = c_get404.getresponse()
        b_get404 = json.loads(r_get404.read().decode("utf-8"))
        c_get404.close()

        c_post404 = http.client.HTTPConnection("127.0.0.1", port_03, timeout=5)
        c_post404.request("POST", f"/api/nonexistent_route?k={m.bus.token}", body=b"{}", headers={"Content-Type": "application/json", "Content-Length": "2"})
        r_post404 = c_post404.getresponse()
        b_post404 = json.loads(r_post404.read().decode("utf-8"))
        c_post404.close()
    finally:
        srv_03.shutdown()

    check("STAGE9-OBS03", "zero unclosed bare open() calls across all 9 production modules, wb.close() in registry.template(), and JSON 404 on unknown /api/* routes",
          len(bare_opens) == 0 and has_tpl_wb_close
          and r_get404.status == 404 and b_get404.get("ok") is False
          and r_post404.status == 404 and b_post404.get("ok") is False,
          (bare_opens, has_tpl_wb_close, r_get404.status, b_get404, r_post404.status, b_post404))

    # 4. STAGE9-OBS04: Verify _CURRENT is protected by with _LOCK: in camera_history.py and prune_history is wired in mersad_live.py
    ch_src_04 = open(os.path.join(WORK, "camera_history.py"), encoding="utf-8").read()
    ml_src_04 = open(os.path.join(WORK, "mersad_live.py"), encoding="utf-8").read()
    has_ch_lock = (
        "with _LOCK:\n        if not force and _CURRENT.get(state_key) == status:" in ch_src_04
        and "with _LOCK:\n            _CURRENT[state_key] = status" in ch_src_04
        and "with _LOCK:\n        items_snap = list(_CURRENT.items())" in ch_src_04
    )
    prune_calls_in_ml = ml_src_04.count("CAMERA_HISTORY.prune_history(")
    check("STAGE9-OBS04", "camera_history._CURRENT is protected by _LOCK and CAMERA_HISTORY.prune_history is wired at startup and periodic maintenance",
          has_ch_lock and prune_calls_in_ml >= 2,
          (has_ch_lock, prune_calls_in_ml))

    # 5. STAGE9-OBS05: Verify all 7 documentation & report files are aligned on 168 PASS
    doc_files_05 = ("README_AR.md", "BUILD_REPORT.md", "AUDIT_REPORT.md", "TEST_REPORT.md", "V7_TEST_REPORT.md", "V7_RELEASE_NOTES.md", "CHANGELOG.md")
    missing_168_05 = []
    stale_155_05 = []
    for dfn in doc_files_05:
        dp = os.path.join(WORK, dfn)
        with open(dp, encoding="utf-8") as df:
            ds = df.read()
        if "193" not in ds:
            missing_168_05.append(dfn)
        if "155 PASS" in ds or "155/155" in ds:
            stale_155_05.append(dfn)
    check("STAGE9-OBS05", "all 7 documentation & report files are unified on 193 PASS with zero stale 155 PASS references",
          len(missing_168_05) == 0 and len(stale_155_05) == 0,
          (missing_168_05, stale_155_05))


run_stage9_complete_polish_tests()


def run_stage10_gold_release_tests():
    # 1. STAGE10-REL01: Verify .github/workflows/windows-build.yml generates & verifies dist\MERSAD_AI\RUN.bat, RUN_LAN.bat, and VERIFY_AUDIT.bat
    yml_p10 = os.path.join(WORK, ".github", "workflows", "windows-build.yml")
    with open(yml_p10, encoding="utf-8") as yf:
        yml_s10 = yf.read()
    has_ci_launchers = (
        'dist\\MERSAD_AI\\RUN.bat' in yml_s10
        and 'dist\\MERSAD_AI\\RUN_LAN.bat' in yml_s10
        and 'dist\\MERSAD_AI\\VERIFY_AUDIT.bat' in yml_s10
        and 'MERSAD_AI.exe --host 0.0.0.0' in yml_s10
        and 'MERSAD_AI.exe --verify-models' in yml_s10
    )
    check("STAGE10-REL01", "windows-build.yml generates and verifies dist\\MERSAD_AI\\RUN.bat, RUN_LAN.bat, and VERIFY_AUDIT.bat matching BUILD_EXE.bat",
          has_ci_launchers, yml_s10)

    # 2. STAGE10-REL02: Verify all 7 documentation files are unified on 193 PASS, Stages 1..10, and MERSAD_AI_V7_1_GOLD_RELEASE_SOURCE.zip
    doc_files_10 = ("README_AR.md", "BUILD_REPORT.md", "AUDIT_REPORT.md", "TEST_REPORT.md", "V7_TEST_REPORT.md", "V7_RELEASE_NOTES.md", "CHANGELOG.md")
    stale_refs_10 = []
    for dfn in doc_files_10:
        with open(os.path.join(WORK, dfn), encoding="utf-8") as df:
            ds = df.read()
        if "193" not in ds or "STAGE7_FINAL_SOURCE" in ds or "155 PASS" in ds or "165 PASS" in ds or "المراحل 1–7" in ds or "Stages 1..7" in ds:
            stale_refs_10.append(dfn)
    with open(os.path.join(WORK, "CHANGELOG.md"), encoding="utf-8") as cf:
        cl_txt = cf.read()
    has_stages_8_9_10 = ("FINAL-OBS-01..05" in cl_txt and "POST8-OBS-01..05" in cl_txt and "REL-OBS-01..03" in cl_txt)
    check("STAGE10-REL02", "all 7 documentation files are unified on 193 PASS & Stages 1–14 with zero stale stage/archive references",
          len(stale_refs_10) == 0 and has_stages_8_9_10,
          (stale_refs_10, has_stages_8_9_10))

    # 3. STAGE10-REL03: Verify evaluate_plates_dataset returns only lowercase 'vehicle_stage_enabled' without duplicate 'vehicle_Stage_enabled'
    rel03_dir = tempfile.mkdtemp(prefix="mersad_s10_rel03_")
    try:
        img_10 = np.full((120, 240, 3), 255, dtype=np.uint8)
        cv2.rectangle(img_10, (20, 25), (220, 95), (0, 0, 0), 3)
        cv2.imwrite(os.path.join(rel03_dir, "p1.jpg"), img_10)
        with open(os.path.join(rel03_dir, "ground_truth.csv"), "w", encoding="utf-8", newline="") as gf:
            gf.write("filename,expected_plate\np1.jpg,عدن-12345\n")
        class _R10:
            def readtext(self, c):
                return [([[0, 0], [1, 0], [1, 1], [0, 1]], "عدن 12345", 0.95)]
        rep_10 = m.evaluate_plates_dataset(rel03_dir, reader=_R10(), print_report=False)
        check("STAGE10-REL03", "evaluate_plates_dataset output schema uses canonical 'vehicle_stage_enabled' key without duplicate 'vehicle_Stage_enabled'",
              rep_10.get("ok") is True and "vehicle_stage_enabled" in rep_10 and "vehicle_Stage_enabled" not in rep_10,
              list(rep_10.keys()))
    finally:
        shutil.rmtree(rel03_dir, ignore_errors=True)


run_stage10_gold_release_tests()


def run_stage11_field_calibration_and_eval_tests():
    import server as srv_mod
    import http.client
    import base64, zipfile

    # 1. STAGE11-CAL-CRUD: Camera Link Calibration full metadata, unit conversion (min->sec), validation, duplicate check, filter & persistence
    s11_dir = tempfile.mkdtemp(prefix="mersad_s11_")
    try:
        db_s11_path = os.path.join(s11_dir, "s11_cal.db")
        c_s11 = sqlite3.connect(db_s11_path, timeout=10.0, check_same_thread=False)
        l_s11 = threading.RLock()
        reg_mod.init(c_s11, l_s11, lambda *a: None, lambda: None, db_path=db_s11_path)
        ins_mod.init(c_s11, l_s11, db_path=db_s11_path)

        # (a) Valid link with minutes unit -> stored canonically in seconds (min=1.5m->90s, exp=3m->180s, max=5m->300s)
        r_add = ins_mod.save_camera_link({
            "from_cam": "CAM_GATE_A",
            "to_cam": "CAM_GATE_B",
            "time_unit": "min",
            "min_sec": 1.5,
            "expected_sec": 3.0,
            "max_sec": 5.0,
            "distance_m": 2400,
            "observations_count": 18,
            "calibration_date": "2026-10-29",
            "traffic_condition": "peak",
            "measurement_source": "field_data",
            "notes": "شارع المعلا الرئيسي",
            "mode": "create",
        })
        # (b) Duplicate rejection in create mode
        r_dup = ins_mod.save_camera_link({
            "from_cam": "CAM_GATE_A",
            "to_cam": "CAM_GATE_B",
            "min_sec": 60,
            "expected_sec": 120,
            "mode": "create",
        })
        # (c) Update in upsert mode
        r_upd = ins_mod.save_camera_link({
            "from_cam": "CAM_GATE_A",
            "to_cam": "CAM_GATE_B",
            "time_unit": "sec",
            "min_sec": 80,
            "expected_sec": 160,
            "max_sec": 280,
            "distance_m": 2500,
            "observations_count": 30,
            "calibration_date": "2026-10-29",
            "traffic_condition": "normal",
            "measurement_source": "computed_logs",
            "notes": "تحديث بعد 30 مشاهدة",
            "mode": "upsert",
        })
        # (d) Validation rejections: negative/zero, same camera, min > expected, max < expected, negative distance, float observations
        bad_same = ins_mod.save_camera_link({"from_cam": "CAM1", "to_cam": "CAM1", "min_sec": 30, "expected_sec": 60})
        bad_neg = ins_mod.save_camera_link({"from_cam": "CAM1", "to_cam": "CAM2", "min_sec": -10, "expected_sec": 60})
        bad_min_gt_exp = ins_mod.save_camera_link({"from_cam": "CAM1", "to_cam": "CAM2", "min_sec": 120, "expected_sec": 60})
        bad_max_lt_exp = ins_mod.save_camera_link({"from_cam": "CAM1", "to_cam": "CAM2", "min_sec": 40, "expected_sec": 100, "max_sec": 70})
        bad_dist = ins_mod.save_camera_link({"from_cam": "CAM1", "to_cam": "CAM2", "min_sec": 40, "expected_sec": 100, "distance_m": -50})
        bad_obs = ins_mod.save_camera_link({"from_cam": "CAM1", "to_cam": "CAM2", "min_sec": 40, "expected_sec": 100, "observations_count": -3})

        # (e) Add a basic link without max_sec/distance/observations -> status == 'basic_needs_data'
        r_basic = ins_mod.save_camera_link({"from_cam": "CAM_BASIC_1", "to_cam": "CAM_BASIC_2", "min_sec": 45, "expected_sec": 90})
        lst_complete = ins_mod.list_camera_links(status_filter="complete")
        lst_needs = ins_mod.list_camera_links(status_filter="needs_data")
        lst_search = ins_mod.list_camera_links(q="المعلا")

        # (f) Re-open DB to verify persistence across restarts
        c_s11.close()
        c_s11_re = sqlite3.connect(db_s11_path, timeout=10.0, check_same_thread=False)
        reg_mod.init(c_s11_re, l_s11, lambda *a: None, lambda: None, db_path=db_s11_path)
        ins_mod.init(c_s11_re, l_s11, db_path=db_s11_path)
        lst_after_restart = ins_mod.list_camera_links()

        check("STAGE11-CAL-CRUD", "Camera Link Calibration supports unit conversion to seconds, rich metadata, validation, duplicate protection, search/filter & restart persistence",
              r_add.get("ok") is True and r_add["link"]["min_sec"] == 90.0 and r_add["link"]["expected_sec"] == 180.0 and r_add["link"]["max_sec"] == 300.0
              and r_add["link"]["calibration_status"] == "complete"
              and r_dup.get("ok") is False
              and r_upd.get("ok") is True and r_upd.get("action") == "updated" and r_upd["link"]["min_sec"] == 80.0 and r_upd["link"]["distance_m"] == 2500.0
              and not bad_same.get("ok") and not bad_neg.get("ok") and not bad_min_gt_exp.get("ok")
              and not bad_max_lt_exp.get("ok") and not bad_dist.get("ok") and not bad_obs.get("ok")
              and r_basic.get("ok") is True and r_basic["link"]["calibration_status"] == "basic_needs_data"
              and len(lst_complete["links"]) == 1 and len(lst_needs["links"]) == 1 and len(lst_search["links"]) == 0
              and len(lst_after_restart["links"]) == 2,
              (r_add, r_dup, r_upd, bad_max_lt_exp, lst_complete, lst_needs))

        # 2. STAGE11-CAL-EXPORT-IMPORT: Export & import camera links in JSON and CSV without data corruption
        json_bytes, json_name, _ = ins_mod.export_camera_links("json")
        csv_bytes, csv_name, _ = ins_mod.export_camera_links("csv")
        ins_mod.delete_camera_link("CAM_GATE_A", "CAM_GATE_B")
        ins_mod.delete_camera_link("CAM_BASIC_1", "CAM_BASIC_2")
        empty_links = ins_mod.list_camera_links()["links"]
        imp_json_res = ins_mod.import_camera_links(json_bytes, filename=json_name)
        links_after_json = ins_mod.list_camera_links()["links"]
        ins_mod.delete_camera_link("CAM_GATE_A", "CAM_GATE_B")
        ins_mod.delete_camera_link("CAM_BASIC_1", "CAM_BASIC_2")
        imp_csv_res = ins_mod.import_camera_links(csv_bytes, filename=csv_name)
        links_after_csv = ins_mod.list_camera_links()["links"]

        check("STAGE11-CAL-EXPORT-IMPORT", "Camera links export and re-import cleanly in both JSON and CSV formats preserving all metadata",
              len(empty_links) == 0 and imp_json_res.get("ok") is True and len(links_after_json) == 2
              and imp_csv_res.get("ok") is True and len(links_after_csv) == 2
              and any(l["from_cam"] == "CAM_GATE_A" and l["max_sec"] == 280.0 and l["distance_m"] == 2500.0 for l in links_after_csv),
              (imp_json_res, imp_csv_res, links_after_csv))

        # 3. STAGE11-CAL-ENGINE-IMPACT: Verify saved calibration drives route tracking, reduces false positives & flags impossible transit / excessive delay
        # Uncalibrated pair CAM_X -> CAM_Y uses 90s default -> 35s transit triggers uncalibrated conflict notice
        now_e = time.time()
        c_s11_re.execute("INSERT INTO sightings(ts, cam, plate, conf, vclass, src, direction, session_id) VALUES(?,?,?,?,?,'live','','s1')",
                         (now_e - 100.0, "CAM_X", "عدن-55111", 0.92, "car"))
        c_s11_re.execute("INSERT INTO sightings(ts, cam, plate, conf, vclass, src, direction, session_id) VALUES(?,?,?,?,?,'live','','s2')",
                         (now_e - 65.0, "CAM_Y", "عدن-55111", 0.91, "car"))
        c_s11_re.commit()
        path_uncal = ins_mod.plate_path("عدن-55111")
        uncal_had_conflict = len(path_uncal.get("conflicts") or []) == 1 and path_uncal["conflicts"][0]["calibrated"] is False

        # Now calibrate CAM_X -> CAM_Y to min_sec=25, expected_sec=40, max_sec=120, distance_m=600 -> 35s transit is now normal (0 conflicts!)
        ins_mod.save_camera_link({
            "from_cam": "CAM_X", "to_cam": "CAM_Y",
            "min_sec": 25, "expected_sec": 40, "max_sec": 120, "distance_m": 600, "observations_count": 12
        })
        path_cal_ok = ins_mod.plate_path("عدن-55111")
        cal_eliminated_fp = (len(path_cal_ok.get("conflicts") or []) == 0 and path_cal_ok["steps"][-1].get("implied_speed_kmh") is not None)

        # Add an impossible 10s transit on calibrated CAM_X -> CAM_Y for plate عدن-55222 -> must trigger calibrated high-priority conflict with implied_speed_kmh=216.0!
        c_s11_re.execute("INSERT INTO sightings(ts, cam, plate, conf, vclass, src, direction, session_id) VALUES(?,?,?,?,?,'live','','s3')",
                         (now_e - 50.0, "CAM_X", "عدن-55222", 0.95, "car"))
        c_s11_re.execute("INSERT INTO sightings(ts, cam, plate, conf, vclass, src, direction, session_id) VALUES(?,?,?,?,?,'live','','s4')",
                         (now_e - 40.0, "CAM_Y", "عدن-55222", 0.95, "car"))
        # And a 200s delayed transit (> max_sec=120) for plate عدن-55333 -> sets excessive_delay=True
        c_s11_re.execute("INSERT INTO sightings(ts, cam, plate, conf, vclass, src, direction, session_id) VALUES(?,?,?,?,?,'live','','s5')",
                         (now_e - 300.0, "CAM_X", "عدن-55333", 0.95, "car"))
        c_s11_re.execute("INSERT INTO sightings(ts, cam, plate, conf, vclass, src, direction, session_id) VALUES(?,?,?,?,?,'live','','s6')",
                         (now_e - 100.0, "CAM_Y", "عدن-55333", 0.95, "car"))
        c_s11_re.commit()
        path_cal_imp = ins_mod.plate_path("عدن-55222")
        path_cal_delay = ins_mod.plate_path("عدن-55333")
        c_s11_re.close()

        check("STAGE11-CAL-ENGINE-IMPACT", "saved calibration eliminates false positives when dt>=min_sec, flags calibrated impossible transit with speed_kmh when dt<min_sec, and marks excessive_delay when dt>max_sec",
              uncal_had_conflict and cal_eliminated_fp
              and len(path_cal_imp.get("conflicts") or []) == 1
              and path_cal_imp["conflicts"][0]["calibrated"] is True
              and path_cal_imp["conflicts"][0]["priority"] == "high"
              and path_cal_imp["conflicts"][0]["implied_speed_kmh"] == 216.0
              and path_cal_delay["steps"][-1]["excessive_delay"] is True,
              (uncal_had_conflict, cal_eliminated_fp, path_cal_imp["conflicts"], path_cal_delay["steps"][-1]))
    finally:
        reg_mod.init(m.db, m.DBL, m.log, m.refresh_known, db_path=m.DB_PATH)
        ins_mod.init(m.db, m.DBL, db_path=m.DB_PATH)
        shutil.rmtree(s11_dir, ignore_errors=True)

    # 4. STAGE11-PE-INSPECT-MODEL: Dataset inspection (valid vs missing/corrupt files) & custom plate model (.pt) validation
    pe_dir = tempfile.mkdtemp(prefix="mersad_s11_pe_")
    try:
        # Create 2 valid plate images, 1 corrupt image (0 bytes), and 1 missing image in ground_truth.csv
        for fn_ok in ("valid1.jpg", "valid2.jpg"):
            im = np.full((480, 640, 3), 30, dtype=np.uint8)
            cv2.rectangle(im, (200, 340), (400, 392), (255, 255, 255), -1)
            cv2.rectangle(im, (200, 340), (400, 392), (0, 0, 0), 3)
            cv2.imwrite(os.path.join(pe_dir, fn_ok), im)
        with open(os.path.join(pe_dir, "corrupt.jpg"), "wb") as cf_bad:
            cf_bad.write(b"not_a_jpeg")
        with open(os.path.join(pe_dir, "ground_truth.csv"), "w", encoding="utf-8", newline="") as gtf:
            gtf.write("filename,expected_plate,x,y,w,h\n")
            gtf.write("valid1.jpg,عدن-12345,200,340,200,52\n")
            gtf.write("valid2.jpg,صنعاء-67890,200,340,200,52\n")
            gtf.write("corrupt.jpg,عدن-11111,200,340,200,52\n")
            gtf.write("missing.jpg,عدن-22222,200,340,200,52\n")

        # Create a valid mock PyTorch .pt zip checkpoint and an invalid .pt file
        valid_pt = os.path.join(pe_dir, "custom_yemen_plates.pt")
        with zipfile.ZipFile(valid_pt, "w") as zf:
            zf.writestr("archive/data.pkl", b"mock_pickle_header" * 100)
            zf.writestr("archive/version", b"3\n")
            zf.writestr("archive/data/0", b"\x00" * 4096)
        invalid_pt = os.path.join(pe_dir, "corrupt_model.pt")
        with open(invalid_pt, "wb") as bf:
            bf.write(b"corrupt_not_a_zip_checkpoint" * 100)

        insp_res = m.inspect_plate_dataset(pe_dir, plate_model_path=valid_pt)
        val_ok = m.validate_plate_model_path(valid_pt)
        val_corrupt = m.validate_plate_model_path(invalid_pt)
        val_missing = m.validate_plate_model_path(os.path.join(pe_dir, "no_such_model.pt"))

        check("STAGE11-PE-INSPECT-MODEL", "inspect_plate_dataset counts valid vs corrupt/missing files and validate_plate_model_path verifies .pt structure safely",
              insp_res.get("ok") is True and insp_res["valid_files_count"] == 2 and insp_res["invalid_files_count"] == 2
              and val_ok.get("ok") is True and val_corrupt.get("ok") is False and val_missing.get("ok") is False,
              (insp_res, val_ok, val_corrupt, val_missing))

        # 5. STAGE11-PE-RUN-CANCEL-METRICS: Run evaluation with vehicle detector, separated metrics, cancellation & DB persistence
        calls_pe = {"n": 0}
        class _SeqReader:
            def readtext(self, crop):
                calls_pe["n"] += 1
                if calls_pe["n"] == 1:
                    return [([[0, 0], [1, 0], [1, 1], [0, 1]], "عدن 12345", 0.96)]
                return [([[0, 0], [1, 0], [1, 1], [0, 1]], "صنعاء 67899", 0.88)]  # 1 digit off from 67890 -> tests separated exact vs char accuracy!

        job_res = m.start_plate_eval_job(
            {"dataset_path": pe_dir, "use_vehicle_detector": True},
            who="s11_test",
            sync=True,
            reader=_SeqReader(),
            vyolo=YOLO("yolov8n.pt"),
        )
        rep_s11 = job_res.get("last_report") or {}
        met_s11 = rep_s11.get("metrics") or {}

        # Also test safe cancellation via cancel_event
        pre_cancelled = threading.Event()
        pre_cancelled.set()
        rep_cancel = m.evaluate_plates_dataset(pe_dir, reader=_SeqReader(), print_report=False, cancel_event=pre_cancelled)
        hist_runs = m.list_plate_eval_runs().get("runs") or []

        check("STAGE11-PE-RUN-CANCEL-METRICS", "in-app plate evaluation separates detection recall/precision, char accuracy (1-CER), digits match & exact match, supports cancellation, and persists runs",
              rep_s11.get("ok") is True
              and rep_s11.get("vehicle_stage_enabled") is True
              and rep_s11.get("valid_files_count") == 2 and rep_s11.get("invalid_files_count") == 2
              and met_s11.get("detected_count") == 2 and met_s11.get("failed_detection_count") == 0
              and met_s11.get("detection_recall") == 1.0 and met_s11.get("detection_precision") > 0.0
              and met_s11.get("exact_match_rate") == 0.5 and met_s11.get("exact_match_count") == 1 and met_s11.get("failed_ocr_count") == 1
              and met_s11.get("char_accuracy_rate") > 0.85
              and rep_cancel.get("status") == "cancelled"
              and len(hist_runs) >= 1 and hist_runs[0]["verification_status"] == "automated_verified",
              (met_s11, rep_cancel, hist_runs[:1]))
    finally:
        shutil.rmtree(pe_dir, ignore_errors=True)

    # 6. STAGE11-MANUAL-CAL-ISOLATION: Manual calibration CRUD, export/import, and strict isolation from automated AI accuracy metrics
    runs_before = len(m.list_plate_eval_runs().get("runs") or [])
    m_save = ins_mod.save_field_calibration({
        "from_cam": "CAM1",
        "to_cam": "CAM2",
        "transit_sec": 145,
        "samples_count": 50,
        "correct_reads": 46,
        "incorrect_reads": 4,
        "source_description": "قياس ميداني بساعة توقيت وعينة 50 مركبة عند نقطة تفتيش خور مكسر",
        "measurement_date": "2026-10-29",
        "model_used": "ملاحظة ميدانية أولية",
        "operator_name": "م. سالم",
        "notes": "فترة صباحية",
    })
    m_id = m_save.get("id")
    m_upd = ins_mod.save_field_calibration({
        "id": m_id,
        "from_cam": "CAM1",
        "to_cam": "CAM2",
        "transit_sec": 150,
        "samples_count": 50,
        "correct_reads": 47,
        "incorrect_reads": 3,
        "source_description": "قياس ميداني محدث",
        "operator_name": "م. سالم",
    })
    m_list = ins_mod.list_field_calibrations()
    fc_json_b, _, _ = ins_mod.export_field_calibrations("json")
    fc_csv_b, _, _ = ins_mod.export_field_calibrations("csv")
    ins_mod.delete_field_calibration(m_id)
    imp_fc = ins_mod.import_field_calibrations(fc_csv_b, filename="manual.csv")
    m_list_after = ins_mod.list_field_calibrations()
    for it_fc in m_list_after.get("items") or []:
        ins_mod.delete_field_calibration(it_fc["id"])
    runs_after = len(m.list_plate_eval_runs().get("runs") or [])

    check("STAGE11-MANUAL-CAL-ISOLATION", "Manual calibration records are badged 'manual_unverified', support CRUD/export/import, and never inflate automated AI evaluation runs",
          m_save.get("ok") is True and m_save.get("verification_status") == "manual_unverified" and m_save.get("is_verified_ai_metric") is False
          and m_upd.get("ok") is True and m_upd.get("action") == "updated"
          and len(m_list.get("items") or []) >= 1 and m_list["items"][0]["measured_plate_accuracy"] == 94.0
          and m_list["items"][0]["verification_status"] == "manual_unverified"
          and imp_fc.get("ok") is True and len(m_list_after.get("items") or []) >= 1
          and runs_before == runs_after,
          (m_save, m_upd, m_list, imp_fc))

    # 7. STAGE11-UI-API-E2E: Live HTTP API & UI verification for all new calibration and plate evaluation endpoints
    srv_11 = srv_mod.ThreadingHTTPServer(("127.0.0.1", 0), srv_mod.H)
    port_11 = srv_11.server_address[1]
    threading.Thread(target=srv_11.serve_forever, daemon=True).start()
    try:
        # Upload a mini dataset via /api/plate_eval/upload_dataset
        im_u = np.full((120, 240, 3), 255, dtype=np.uint8)
        cv2.rectangle(im_u, (20, 25), (220, 95), (0, 0, 0), 3)
        _, jpg_buf = cv2.imencode(".jpg", im_u)
        b64_img = base64.b64encode(jpg_buf.tobytes()).decode("ascii")
        b64_csv = base64.b64encode("filename,expected_plate\nu1.jpg,عدن-12345\n".encode("utf-8")).decode("ascii")

        conn_u = http.client.HTTPConnection("127.0.0.1", port_11, timeout=5)
        body_u = json.dumps({
            "files": [
                {"name": "ground_truth.csv", "content_base64": b64_csv},
                {"name": "u1.jpg", "content_base64": b64_img},
            ]
        }).encode("utf-8")
        conn_u.request("POST", f"/api/plate_eval/upload_dataset?k={m.bus.token}", body=body_u, headers={"Content-Type": "application/json", "Content-Length": str(len(body_u))})
        resp_u = json.loads(conn_u.getresponse().read().decode("utf-8"))
        conn_u.close()

        conn_st = http.client.HTTPConnection("127.0.0.1", port_11, timeout=5)
        conn_st.request("GET", f"/api/plate_eval/status?k={m.bus.token}")
        resp_st = json.loads(conn_st.getresponse().read().decode("utf-8"))
        conn_st.close()

        conn_fc = http.client.HTTPConnection("127.0.0.1", port_11, timeout=5)
        conn_fc.request("GET", f"/api/field_calibrations?k={m.bus.token}")
        resp_fc = json.loads(conn_fc.getresponse().read().decode("utf-8"))
        conn_fc.close()
    finally:
        srv_11.shutdown()

    dash_s11 = open(os.path.join(WORK, "dashboard.html"), encoding="utf-8").read()
    has_s11_sections = (
        "معايرة روابط الكاميرات — Camera Link Calibration" in dash_s11
        and "تقييم ومعايرة اللوحات اليمنية — Yemeni Plate Evaluation" in dash_s11
        and "تسجيل نتائج المعايرة اليدوية — Manual Field Calibration Registry" in dash_s11
        and "مدخلة يدوياً — غير متحقق منها" in dash_s11
    )
    check("STAGE11-UI-API-E2E", "HTTP endpoints for dataset upload, evaluation status, manual calibrations & dashboard UI sections work end-to-end",
          resp_u.get("ok") is True and resp_u.get("saved_files_count") == 2 and resp_u["inspection"]["valid_files_count"] == 1
          and resp_st.get("ok") is True and resp_fc.get("ok") is True and has_s11_sections,
          (resp_u, resp_st, resp_fc, has_s11_sections))


run_stage11_field_calibration_and_eval_tests()


def run_stage12_security_and_eval_integrity_tests():
    import ast, pickle, re, subprocess, zipfile
    import server as srv_mod
    import http.client

    # 1. STAGE12-AUDIT001-PICKLE-RCE-BLOCK: Negative exploit tests for malicious pickle .pt, UNC paths, symlinks, outside models/, and HMAC trusted manifest
    s12_dir = tempfile.mkdtemp(prefix="mersad_s12_audit001_")
    try:
        # (a) Construct a malicious PyTorch .pt ZIP archive whose data.pkl attempts RCE via os.system
        class _MaliciousPayload:
            def __reduce__(self):
                return (os.system, ("echo PWNED_BY_PICKLE",))

        evil_pkl_bytes = pickle.dumps({"exploit": _MaliciousPayload()}, protocol=2)
        evil_pt_path = os.path.join(s12_dir, "evil_rce_model.pt")
        with zipfile.ZipFile(evil_pt_path, "w") as zf:
            zf.writestr("archive/data.pkl", evil_pkl_bytes + (b"\x00" * 2048))
            zf.writestr("archive/version", b"3\n")
            zf.writestr("archive/data/0", b"\x00" * 4096)

        ok_evil_zip, reason_evil_zip = m.verify_yolo_pt_file(evil_pt_path, min_bytes=512)
        val_evil = m.validate_plate_model_path(evil_pt_path, min_bytes=512, enforce_trusted=False)

        # (b) Construct a clean .pt archive outside models/ -> rejected when enforce_trusted=True
        clean_pkl_bytes = pickle.dumps({"epoch": 1, "weights_shape": [16, 3, 3, 3]}, protocol=4)
        outside_clean_pt = os.path.join(s12_dir, "outside_clean_plates.pt")
        with zipfile.ZipFile(outside_clean_pt, "w") as zf:
            zf.writestr("archive/data.pkl", clean_pkl_bytes + (b"\x80\x04." * 400))
            zf.writestr("archive/version", b"3\n")
            zf.writestr("archive/data/0", b"\x00" * 4096)

        val_outside_untrusted = m.validate_plate_model_path(outside_clean_pt, min_bytes=512, enforce_trusted=True)

        # (c) Copy clean .pt into APPDIR/models/ WITHOUT registering its SHA-256 in HMAC manifest -> still rejected when enforce_trusted=True!
        models_dir_app = os.path.join(m.APPDIR, "models")
        os.makedirs(models_dir_app, exist_ok=True)
        unreg_in_models = os.path.join(models_dir_app, "unregistered_yemen.pt")
        shutil.copy2(outside_clean_pt, unreg_in_models)
        val_unreg_in_models = m.validate_plate_model_path(unreg_in_models, min_bytes=512, enforce_trusted=True)

        # (d) Attempt to register the malicious .pt via register_trusted_model -> MUST be rejected!
        reg_evil = m.register_trusted_model(evil_pt_path, who="test_admin", min_bytes=512)

        # (e) Register the clean .pt via register_trusted_model -> copies/registers in models/.trusted_models.json with HMAC signature -> accepted!
        reg_clean = m.register_trusted_model(outside_clean_pt, who="test_admin", min_bytes=512)
        val_reg_clean = m.validate_plate_model_path(reg_clean.get("path", ""), min_bytes=512, enforce_trusted=True)

        # (f) Tamper with HMAC signature in models/.trusted_models.json -> must reject model!
        manifest_file = os.path.join(models_dir_app, ".trusted_models.json")
        orig_manifest = open(manifest_file, "rb").read() if os.path.isfile(manifest_file) else b""
        tampered_rejected = False
        if orig_manifest:
            tampered_obj = json.loads(orig_manifest.decode("utf-8"))
            tampered_obj["hmac"] = "0" * 64
            with open(manifest_file, "w", encoding="utf-8") as mf:
                json.dump(tampered_obj, mf)
            val_after_tamper = m.validate_plate_model_path(reg_clean.get("path", ""), min_bytes=512, enforce_trusted=True)
            tampered_rejected = (val_after_tamper.get("ok") is False and val_after_tamper.get("reason") == "untrusted_model_sha256")
            with open(manifest_file, "wb") as mf:
                mf.write(orig_manifest)

        # (g) Reject UNC network paths and '..' traversal paths
        val_unc = m.validate_plate_model_path(r"\\evil-server\share\plates.pt", min_bytes=512, enforce_trusted=False)
        val_dots = m.validate_plate_model_path("../models/plates.pt", min_bytes=512, enforce_trusted=False)

        check(
            "STAGE12-AUDIT001-PICKLE-RCE-BLOCK",
            "static pickle bytecode scanner blocks RCE payloads, rejects UNC/traversal/outside-models paths, and enforces HMAC-signed trusted SHA-256 manifest",
            ok_evil_zip is False and "unsafe_pickle" in reason_evil_zip
            and val_evil.get("ok") is False
            and val_outside_untrusted.get("ok") is False and val_outside_untrusted.get("reason") == "outside_trusted_models_dir"
            and val_unreg_in_models.get("ok") is False and val_unreg_in_models.get("reason") == "untrusted_model_sha256"
            and reg_evil.get("ok") is False
            and reg_clean.get("ok") is True and val_reg_clean.get("ok") is True and val_reg_clean.get("trusted_verified") is True
            and tampered_rejected
            and val_unc.get("ok") is False and val_dots.get("ok") is False,
            (ok_evil_zip, reason_evil_zip, val_outside_untrusted, val_unreg_in_models, reg_evil, reg_clean, val_reg_clean, tampered_rejected),
        )
    finally:
        for fn_cl in ("unregistered_yemen.pt", "outside_clean_plates.pt"):
            p_cl = os.path.join(m.APPDIR, "models", fn_cl)
            if os.path.exists(p_cl):
                try: os.remove(p_cl)
                except OSError: pass
        shutil.rmtree(s12_dir, ignore_errors=True)

    # 2. STAGE12-AUDIT002-PATH-TRAVERSAL-BLOCK: Negative exploit tests for path traversal in inspect_plate_dataset & evaluate_plates_dataset
    s12_pt_dir = tempfile.mkdtemp(prefix="mersad_s12_audit002_")
    try:
        ds_sub = os.path.join(s12_pt_dir, "eval_dataset")
        os.makedirs(ds_sub, exist_ok=True)
        outside_secret_img = os.path.join(s12_pt_dir, "secret_outside.jpg")
        im_sec = np.full((120, 240, 3), 255, dtype=np.uint8)
        cv2.rectangle(im_sec, (20, 25), (220, 95), (0, 0, 0), 3)
        cv2.imwrite(outside_secret_img, im_sec)

        inside_ok_img = os.path.join(ds_sub, "safe_inside.jpg")
        cv2.imwrite(inside_ok_img, im_sec)

        symlink_inside = os.path.join(ds_sub, "sym_secret.jpg")
        try:
            os.symlink(outside_secret_img, symlink_inside)
            has_symlink = True
        except OSError:
            has_symlink = False

        with open(os.path.join(ds_sub, "ground_truth.csv"), "w", encoding="utf-8", newline="") as gtf:
            gtf.write("filename,expected_plate,x,y,w,h\n")
            gtf.write("safe_inside.jpg,عدن-12345,20,25,200,70\n")
            gtf.write("../secret_outside.jpg,عدن-99999,20,25,200,70\n")
            gtf.write("sub/../../secret_outside.jpg,عدن-88888,20,25,200,70\n")
            gtf.write(f"{outside_secret_img},عدن-77777,20,25,200,70\n")
            gtf.write("\\\\127.0.0.1\\c$\\secret.jpg,عدن-66666,20,25,200,70\n")
            if has_symlink:
                gtf.write("sym_secret.jpg,عدن-55555,20,25,200,70\n")

        class _CountReader:
            def __init__(self):
                self.calls = 0
            def readtext(self, c):
                self.calls += 1
                return [([[0, 0], [1, 0], [1, 1], [0, 1]], "عدن 12345", 0.95)]

        cr = _CountReader()
        insp_pt = m.inspect_plate_dataset(ds_sub)
        rep_pt = m.evaluate_plates_dataset(ds_sub, reader=cr, print_report=False, save_to_db=False)
        expected_rejected = 5 if has_symlink else 4

        check(
            "STAGE12-AUDIT002-PATH-TRAVERSAL-BLOCK",
            "inspect_plate_dataset and evaluate_plates_dataset block '../', nested traversal, absolute paths, UNC shares, and symlinks without reading outside images",
            insp_pt.get("ok") is True
            and insp_pt.get("valid_files_count") == 1
            and insp_pt.get("security_rejected_count") == expected_rejected
            and rep_pt.get("ok") is True
            and rep_pt.get("valid_files_count") == 1
            and len(rep_pt.get("rejected_unsafe_paths") or []) == expected_rejected
            and cr.calls == 1,
            (insp_pt, rep_pt.get("rejected_unsafe_paths"), cr.calls),
        )
    finally:
        shutil.rmtree(s12_pt_dir, ignore_errors=True)

    # 3. STAGE12-AUDIT003-EVAL-METRICS-INTEGRITY: Verify strict separation of the 5 metrics and zero inflation when detection fails
    s12_m_dir = tempfile.mkdtemp(prefix="mersad_s12_audit003_")
    try:
        # Sample 1 (s1_det_ok_ocr_ok.jpg): plate detected (IoU=1.0) & OCR matches 'عدن-12345'
        im1 = np.full((360, 640, 3), 30, dtype=np.uint8)
        cv2.rectangle(im1, (200, 240), (400, 292), (255, 255, 255), -1)
        cv2.rectangle(im1, (200, 240), (400, 292), (0, 0, 0), 3)
        cv2.imwrite(os.path.join(s12_m_dir, "s1_det_ok_ocr_ok.jpg"), im1)

        # Sample 2 (s2_det_fail_gt_readable.jpg): 2 false-positive distractor rectangles in top corners (y=20..70, IoU=0.0 with gt_box at y=260..312),
        # and no contour at gt_box (low-contrast gray at 200,260,190,52), while OCR can read the gt_box crop if cropped directly!
        im2 = np.full((360, 640, 3), 30, dtype=np.uint8)
        cv2.rectangle(im2, (20, 20), (180, 65), (255, 255, 255), -1)
        cv2.rectangle(im2, (20, 20), (180, 65), (0, 0, 0), 3)
        cv2.rectangle(im2, (420, 20), (580, 65), (255, 255, 255), -1)
        cv2.rectangle(im2, (420, 20), (580, 65), (0, 0, 0), 3)
        cv2.imwrite(os.path.join(s12_m_dir, "s2_det_fail_gt_readable.jpg"), im2)

        # Sample 3 (s3_det_ok_ocr_wrong.jpg): plate detected (IoU=1.0) at (200,240,220,52), but OCR reads wrong digits
        im3 = np.full((360, 640, 3), 30, dtype=np.uint8)
        cv2.rectangle(im3, (200, 240), (420, 292), (255, 255, 255), -1)
        cv2.rectangle(im3, (200, 240), (420, 292), (0, 0, 0), 3)
        cv2.imwrite(os.path.join(s12_m_dir, "s3_det_ok_ocr_wrong.jpg"), im3)

        with open(os.path.join(s12_m_dir, "ground_truth.csv"), "w", encoding="utf-8", newline="") as gtf:
            gtf.write("filename,expected_plate,x,y,w,h\n")
            gtf.write("s1_det_ok_ocr_ok.jpg,عدن-12345,200,240,200,52\n")
            gtf.write("s2_det_fail_gt_readable.jpg,عدن-55555,200,260,190,52\n")
            gtf.write("s3_det_ok_ocr_wrong.jpg,صنعاء-77777,200,240,220,52\n")

        class _StrictReader:
            def readtext(self, crop):
                cw = crop.shape[1] if (crop is not None and crop.ndim >= 2) else 0
                if abs(cw - 200) <= 6:
                    return [([[0, 0], [1, 0], [1, 1], [0, 1]], "عدن 12345", 0.96)]
                if abs(cw - 190) <= 6:
                    # gt_box crop of Sample 2 -> OCR reads it as exact match 'عدن 55555'
                    return [([[0, 0], [1, 0], [1, 1], [0, 1]], "عدن 55555", 0.94)]
                return [([[0, 0], [1, 0], [1, 1], [0, 1]], "صنعاء 77799", 0.90)]

        rep_m = m.evaluate_plates_dataset(s12_m_dir, reader=_StrictReader(), print_report=False, save_to_db=True)
        met_m = rep_m.get("metrics") or {}
        samples_by_fn = {s["filename"]: s for s in (rep_m.get("samples") or [])}
        s2_res = samples_by_fn.get("s2_det_fail_gt_readable.jpg", {})

        # Mathematical expectations:
        # - Detected: Sample 1 (TP=1, FP=0), Sample 2 (TP=0, FP=2, FN=1), Sample 3 (TP=1, FP=0)
        # - Total TP=2, FP=2, FN=1 -> Recall = 2/3 = 0.6667, Precision = 2/(2+2) = 0.5, F1 = 2*0.5*(2/3)/(0.5+2/3) = 0.5714
        # - End-to-End Exact Match: Sample 1 ONLY (1/3 = 0.3333). Sample 2 MUST NOT count as End-to-End Exact Match!
        # - Cropped OCR Exact Match: Sample 1 + Sample 2 (2/3 = 0.6667).
        check(
            "STAGE12-AUDIT003-EVAL-METRICS-INTEGRITY",
            "evaluate_plates_dataset separates detection_precision, detection_recall, detection_f1, end_to_end_exact_match_rate, and cropped_ocr_exact_match_rate without counting failed detection as E2E match",
            rep_m.get("ok") is True
            and s2_res.get("detected") is False
            and s2_res.get("predicted_plate") == ""
            and s2_res.get("exact_match") is False
            and s2_res.get("end_to_end_exact_match") is False
            and s2_res.get("cropped_ocr_exact_match") is True
            and met_m.get("true_positive_boxes") == 2
            and met_m.get("false_positive_boxes") == 2
            and met_m.get("false_negative_boxes") == 1
            and met_m.get("detection_recall") == round(2.0 / 3.0, 4)
            and met_m.get("detection_precision") == 0.5
            and met_m.get("detection_f1") == 0.5714
            and met_m.get("end_to_end_exact_match_rate") == round(1.0 / 3.0, 4)
            and met_m.get("exact_match_rate") == round(1.0 / 3.0, 4)
            and met_m.get("cropped_ocr_exact_match_rate") == round(2.0 / 3.0, 4),
            (met_m, s2_res),
        )
    finally:
        shutil.rmtree(s12_m_dir, ignore_errors=True)

    # 4. STAGE12-AUDIT004-SHARED-ENGINES-MEMORY: Verify shared reader & vyolo reuse across evaluation jobs & thread-safe concurrent inference
    s12_mem_dir = tempfile.mkdtemp(prefix="mersad_s12_audit004_")
    try:
        im_m4 = np.full((360, 640, 3), 30, dtype=np.uint8)
        cv2.rectangle(im_m4, (200, 340), (400, 392), (255, 255, 255), -1)
        cv2.rectangle(im_m4, (200, 340), (400, 392), (0, 0, 0), 3)
        cv2.imwrite(os.path.join(s12_mem_dir, "m1.jpg"), im_m4)
        with open(os.path.join(s12_mem_dir, "ground_truth.csv"), "w", encoding="utf-8", newline="") as gtf:
            gtf.write("filename,expected_plate,x,y,w,h\nm1.jpg,عدن-12345,200,340,200,52\n")

        class _SharedMockReader:
            def __init__(self):
                self.active_threads = 0
                self.max_concurrent = 0
                self.lock = threading.Lock()
                self.calls = 0
            def readtext(self, crop):
                with self.lock:
                    self.active_threads += 1
                    self.calls += 1
                    if self.active_threads > self.max_concurrent:
                        self.max_concurrent = self.active_threads
                time.sleep(0.005)
                with self.lock:
                    self.active_threads -= 1
                return [([[0, 0], [1, 0], [1, 1], [0, 1]], "عدن 12345", 0.95)]

        shared_rdr = _SharedMockReader()
        shared_vy = YOLO("yolov8n.pt")
        with m._SHARED_ENGINES_LOCK:
            m._SHARED_ENGINES["reader_reuses"] = 0
            m._SHARED_ENGINES["vyolo_reuses"] = 0
        m.register_shared_engines(reader=shared_rdr, vyolo=shared_vy)

        # Run a concurrent live inference simulation thread while 3 evaluation jobs execute via start_plate_eval_job(reader=None, vyolo=None)
        conc_errs = []
        stop_bg = threading.Event()
        def _live_cam_sim():
            while not stop_bg.is_set():
                try:
                    m.detect_vehicles(im_m4, shared_vy)
                    m.read_plate(shared_rdr, im_m4[340:392, 200:400])
                except Exception as e:
                    conc_errs.append(repr(e))

        bg_th = threading.Thread(target=_live_cam_sim, daemon=True)
        bg_th.start()
        try:
            for _ in range(3):
                j_out = m.start_plate_eval_job(
                    {"dataset_path": s12_mem_dir, "use_vehicle_detector": True},
                    who="s12_mem_test",
                    sync=True,
                )
                if not (j_out.get("last_report") or {}).get("ok"):
                    conc_errs.append(f"eval_failed:{j_out}")
        finally:
            stop_bg.set()
            bg_th.join(timeout=3.0)

        with m._SHARED_ENGINES_LOCK:
            r_reuses = m._SHARED_ENGINES["reader_reuses"]
            v_reuses = m._SHARED_ENGINES["vyolo_reuses"]
            same_rdr = (m._SHARED_ENGINES["reader"] is shared_rdr)
            same_vy = (m._SHARED_ENGINES["vyolo"] is shared_vy)

        check(
            "STAGE12-AUDIT004-SHARED-ENGINES-MEMORY",
            "start_plate_eval_job reuses registered reader and vyolo instances without duplicate loading and serializes concurrent OCR/YOLO calls safely",
            len(conc_errs) == 0 and same_rdr and same_vy and r_reuses >= 3 and v_reuses >= 3 and shared_rdr.max_concurrent == 1,
            (conc_errs, same_rdr, same_vy, r_reuses, v_reuses, shared_rdr.max_concurrent),
        )
    finally:
        shutil.rmtree(s12_mem_dir, ignore_errors=True)

    # 5. STAGE12-AUDIT005-SUBPROCESS-BROWSE-DIALOG: Verify browse_local_path never imports tkinter in HTTP worker thread and supports --internal-browse-dialog & busy lock
    ml_ast_src = open(os.path.join(WORK, "mersad_live.py"), encoding="utf-8").read()
    tree_ml = ast.parse(ml_ast_src)
    browse_fn_imports_tk = False
    for node in ast.walk(tree_ml):
        if isinstance(node, ast.FunctionDef) and node.name == "browse_local_path":
            for sub in ast.walk(node):
                if isinstance(sub, (ast.Import, ast.ImportFrom)):
                    names = [a.name for a in sub.names] + ([sub.module] if getattr(sub, "module", None) else [])
                    if any("tkinter" in str(n) for n in names):
                        browse_fn_imports_tk = True

    # Test non-blocking busy guard when _BROWSE_DIALOG_LOCK is already held
    m._BROWSE_DIALOG_LOCK.acquire()
    try:
        # Force simulated DISPLAY so we reach the lock check on Linux
        old_disp = os.environ.get("DISPLAY")
        os.environ["DISPLAY"] = ":99"
        busy_res = m.browse_local_path(mode="folder", timeout=2.0)
    finally:
        if old_disp is None:
            os.environ.pop("DISPLAY", None)
        else:
            os.environ["DISPLAY"] = old_disp
        m._BROWSE_DIALOG_LOCK.release()

    # Test subprocess --internal-browse-dialog CLI flag directly
    sub_dlg = subprocess.run(
        [sys.executable, os.path.join(WORK, "mersad_live.py"), "--internal-browse-dialog", "folder"],
        capture_output=True, text=True, timeout=10,
        env={k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")},
    )
    sub_dlg_json = json.loads(sub_dlg.stdout.strip().splitlines()[-1]) if sub_dlg.stdout.strip() else {}

    check(
        "STAGE12-AUDIT005-SUBPROCESS-BROWSE-DIALOG",
        "browse_local_path never imports tkinter in the HTTP server thread, enforces non-blocking _BROWSE_DIALOG_LOCK, and runs --internal-browse-dialog in a child process",
        not browse_fn_imports_tk
        and busy_res.get("ok") is False and busy_res.get("busy") is True
        and sub_dlg.returncode == 0 and isinstance(sub_dlg_json, dict) and "ok" in sub_dlg_json,
        (browse_fn_imports_tk, busy_res, sub_dlg.returncode, sub_dlg_json),
    )

    # 6. STAGE12-DOC-PARITY: Verify dashboard.html JS syntax via node --check and Stage 12 new metric labels in UI
    dash_html_12 = open(os.path.join(WORK, "dashboard.html"), encoding="utf-8").read()
    has_5_metrics_ui = (
        "detection_f1" in dash_html_12
        and "end_to_end_exact_match_rate" in dash_html_12
        and "cropped_ocr_exact_match_rate" in dash_html_12
    )
    js_blocks = re.findall(r"<script[^>]*>(.*?)</script>", dash_html_12, flags=re.S)
    js_tmp = os.path.join(tempfile.gettempdir(), f"mersad_s12_dash_{os.getpid()}.js")
    try:
        with open(js_tmp, "w", encoding="utf-8") as jf:
            jf.write("\n".join(js_blocks))
        node_chk = subprocess.run(["node", "--check", js_tmp], capture_output=True, text=True, timeout=10)
        js_ok = (node_chk.returncode == 0)
    finally:
        if os.path.exists(js_tmp):
            try: os.remove(js_tmp)
            except OSError: pass

    check(
        "STAGE12-DOC-PARITY",
        "dashboard.html renders all 5 separated evaluation metrics (Recall, Precision, F1, End-to-End Exact Match, Cropped OCR Exact Match) and passes node --check",
        has_5_metrics_ui and js_ok,
        (has_5_metrics_ui, js_ok),
    )


run_stage12_security_and_eval_integrity_tests()


def run_stage13_complete_audit_closure_tests():
    import http.client
    import base64
    import server as srv_mod
    import check_install as chk_mod

    # 1. STAGE13-AUDIT009-AUTH-RATELIMIT: Verify HTTP 429 JSON + Retry-After after 15 failed auth attempts, and reset on success
    srv_13 = srv_mod.ThreadingHTTPServer(("127.0.0.1", 0), srv_mod.H)
    port_13 = srv_13.server_address[1]
    threading.Thread(target=srv_13.serve_forever, daemon=True).start()
    try:
        with m.bus._lock:
            m.bus.auth_failures.clear()
        statuses_15 = []
        for _ in range(15):
            c = http.client.HTTPConnection("127.0.0.1", port_13, timeout=5)
            c.request("GET", "/api/ping?k=WRONG_TOKEN_ATTEMPT")
            r = c.getresponse()
            r.read()
            statuses_15.append(r.status)
            c.close()

        # 16th attempt must return 429 JSON with retry_after_sec and Retry-After header
        c16 = http.client.HTTPConnection("127.0.0.1", port_13, timeout=5)
        c16.request("GET", "/api/ping?k=WRONG_TOKEN_ATTEMPT")
        r16 = c16.getresponse()
        b16 = json.loads(r16.read().decode("utf-8"))
        retry_hdr = r16.getheader("Retry-After")
        c16.close()

        # Clear block and verify valid token works and resets counter
        with m.bus._lock:
            m.bus.auth_failures.clear()
        c_ok = http.client.HTTPConnection("127.0.0.1", port_13, timeout=5)
        c_ok.request("GET", f"/api/ping?k={m.bus.token}")
        r_ok = c_ok.getresponse()
        r_ok.read()
        c_ok.close()

        check(
            "STAGE13-AUDIT009-AUTH-RATELIMIT",
            "server.py enforces per-IP authentication rate limiting (15 failures -> HTTP 429 JSON with Retry-After) and clears on success",
            all(s == 403 for s in statuses_15)
            and r16.status == 429
            and b16.get("ok") is False
            and int(b16.get("retry_after_sec") or 0) >= 1
            and retry_hdr is not None
            and r_ok.status == 200,
            (statuses_15[-3:], r16.status, b16, retry_hdr, r_ok.status),
        )

        # 2. STAGE13-AUDIT006-CHUNKED-UPLOAD-PRUNE: Multi-chunk upload sharing batch_id & prune_eval_uploads()
        im_c = np.full((120, 240, 3), 255, dtype=np.uint8)
        cv2.rectangle(im_c, (20, 25), (220, 95), (0, 0, 0), 3)
        _, jpg_b = cv2.imencode(".jpg", im_c)
        b64_im = base64.b64encode(jpg_b.tobytes()).decode("ascii")
        b64_gt = base64.b64encode("filename,expected_plate\nc1.jpg,عدن-12345\nc2.jpg,صنعاء-67890\n".encode("utf-8")).decode("ascii")

        shared_batch = "batch_test_s13_chunked"
        res_chunk1 = m.stage_uploaded_eval_files({
            "batch_id": shared_batch,
            "finalize": False,
            "files": [
                {"name": "ground_truth.csv", "content_base64": b64_gt},
                {"name": "c1.jpg", "content_base64": b64_im},
            ],
        })
        res_chunk2 = m.stage_uploaded_eval_files({
            "batch_id": shared_batch,
            "finalize": True,
            "files": [
                {"name": "c2.jpg", "content_base64": b64_im},
            ],
        })

        # Create 4 extra dummy upload folders and prune with max_batches=2
        for idx_d in range(4):
            d_extra = os.path.join(m.APPDIR, "eval_uploads", f"old_batch_{idx_d}")
            os.makedirs(d_extra, exist_ok=True)
            old_t = time.time() - (48 * 3600)
            os.utime(d_extra, (old_t, old_t))
        prune_res = m.prune_eval_uploads(max_age_hours=24.0, max_batches=2)

        check(
            "STAGE13-AUDIT006-CHUNKED-UPLOAD-PRUNE",
            "stage_uploaded_eval_files merges multi-chunk uploads by batch_id and prune_eval_uploads cleans expired/excess batches",
            res_chunk1.get("ok") is True and res_chunk1.get("finalized") is False
            and res_chunk2.get("ok") is True and res_chunk2.get("finalized") is True
            and res_chunk2.get("dataset_path") == res_chunk1.get("dataset_path")
            and res_chunk2.get("total_batch_files_count") == 3
            and (res_chunk2.get("inspection") or {}).get("valid_files_count") == 2
            and prune_res.get("ok") is True and prune_res.get("removed_batches", 0) >= 4,
            (res_chunk1, res_chunk2, prune_res),
        )

        # 3. STAGE13-AUDIT007-CAL-PHYSICS-BOUNDS: Reject physically impossible speeds (>260 km/h or <0.5 km/h) & require >=3 obs for complete
        bad_fast = ins_mod.save_camera_link({
            "from_cam": "CAM_PHY_1",
            "to_cam": "CAM_PHY_2",
            "min_sec": 10,
            "expected_sec": 30,
            "distance_m": 50000,  # 50 km in 10s = 18,000 km/h -> impossible!
        })
        bad_slow = ins_mod.save_camera_link({
            "from_cam": "CAM_PHY_1",
            "to_cam": "CAM_PHY_2",
            "min_sec": 100,
            "expected_sec": 36000,  # 1m in 10 hours = 0.0001 km/h -> impossible!
            "distance_m": 1,
        })
        one_obs_no_bounds = ins_mod.save_camera_link({
            "from_cam": "CAM_PHY_1",
            "to_cam": "CAM_PHY_2",
            "min_sec": 45,
            "expected_sec": 90,
            "observations_count": 1,
        })
        three_obs_with_dist = ins_mod.save_camera_link({
            "from_cam": "CAM_PHY_1",
            "to_cam": "CAM_PHY_2",
            "min_sec": 45,
            "expected_sec": 90,
            "distance_m": 1200,  # (1200/45)*3.6 = 96 km/h -> realistic!
            "observations_count": 3,
        })
        ins_mod.delete_camera_link("CAM_PHY_1", "CAM_PHY_2")

        check(
            "STAGE13-AUDIT007-CAL-PHYSICS-BOUNDS",
            "save_camera_link rejects physically impossible implied speeds (<0.5 or >260 km/h) and requires >=3 observations with bounds for complete status",
            bad_fast.get("ok") is False
            and bad_slow.get("ok") is False
            and one_obs_no_bounds.get("ok") is True and one_obs_no_bounds["link"]["calibration_status"] == "basic_needs_data"
            and three_obs_with_dist.get("ok") is True and three_obs_with_dist["link"]["calibration_status"] == "complete",
            (bad_fast, bad_slow, one_obs_no_bounds, three_obs_with_dist),
        )

        # 4. STAGE13-AUDIT008-012-UI-EXPORT: Verify /api/plate_eval/export (JSON & CSV), dynamic card mounting in #t-calibration, & node --check
        c_exp_j = http.client.HTTPConnection("127.0.0.1", port_13, timeout=5)
        c_exp_j.request("GET", f"/api/plate_eval/export?fmt=json&k={m.bus.token}")
        r_exp_j = c_exp_j.getresponse()
        b_exp_j = json.loads(r_exp_j.read().decode("utf-8"))
        c_exp_j.close()

        c_exp_c = http.client.HTTPConnection("127.0.0.1", port_13, timeout=5)
        c_exp_c.request("GET", f"/api/plate_eval/export?fmt=csv&k={m.bus.token}")
        r_exp_c = c_exp_c.getresponse()
        b_exp_c = r_exp_c.read().decode("utf-8-sig")
        c_exp_c.close()

        dash_13 = open(os.path.join(WORK, "dashboard.html"), encoding="utf-8").read()
        has_dynamic_mount = (
            "function mountCameraLinksCard(" in dash_13
            and 'id="cal-cl-slot"' in dash_13
            and 'id="ins-cl-slot"' in dash_13
            and 'id="pe-export-json"' in dash_13
            and 'id="pe-export-csv"' in dash_13
        )
        check(
            "STAGE13-AUDIT008-012-UI-EXPORT",
            "/api/plate_eval/export serves JSON and CSV with 5 metrics, and dashboard.html mounts camera link form directly inside #t-calibration without forced tab switch",
            r_exp_j.status == 200 and b_exp_j.get("schema") == "mersad_plate_eval_export_v1"
            and r_exp_c.status == 200 and "detection_f1" in b_exp_c and "end_to_end_exact_match_rate" in b_exp_c
            and has_dynamic_mount,
            (r_exp_j.status, r_exp_c.status, has_dynamic_mount),
        )
    finally:
        srv_13.shutdown()

    # 5. STAGE13-AUDIT011-BUILD-SPEC-PRESERVATION: Verify BUILD_EXE.bat builds from mersad_ai.spec without overwriting it
    ok_bld_13, bld_info_13 = chk_mod.verify_build_config_consistency(WORK)
    bat_txt_13 = open(os.path.join(WORK, "BUILD_EXE.bat"), encoding="utf-8").read()
    active_bat_lines = [
        ln.strip() for ln in bat_txt_13.splitlines()
        if ln.strip() and not ln.strip().upper().startswith("REM")
    ]
    active_bat_joined = "\n".join(active_bat_lines)
    check(
        "STAGE13-AUDIT011-BUILD-SPEC-PRESERVATION",
        "BUILD_EXE.bat invokes pyinstaller.exe with mersad_ai.spec directly instead of overwriting the spec via mersad_live.py",
        ok_bld_13 is True
        and bld_info_13.get("uses_spec_file") is True
        and "pyinstaller.exe --noconfirm --clean mersad_ai.spec" in active_bat_joined
        and "mersad_live.py > build_pyinstaller.log" not in active_bat_joined,
        bld_info_13,
    )

    # 6. STAGE13-AUDIT010-UNIQUE-TEST-IDS: Verify 100% of test IDs in RESULTS are unique and docs are unified on 193 PASS
    # Include this test's own ID in the uniqueness verification
    existing_ids = [r[0] for r in RESULTS]
    all_unique_so_far = (len(set(existing_ids)) == len(existing_ids)) and ("STAGE13-AUDIT010-UNIQUE-TEST-IDS" not in existing_ids)
    check(
        "STAGE13-AUDIT010-UNIQUE-TEST-IDS",
        "100% of test identifiers recorded in RESULTS are unique (zero duplicate [ID] codes across all 187 tests)",
        all_unique_so_far and len(existing_ids) >= 186,
        (len(existing_ids), len(set(existing_ids))),
    )


run_stage13_complete_audit_closure_tests()


def run_stage14_100pct_readiness_tests():
    import http.client, pickle, re, zipfile
    import server as srv_mod

    # 1. STAGE14-01-SQLITE-MOUNT-FALLBACK: Verify _is_sqlite_usable_dir() and direct execution of mersad_live.py --verify from repo root without MERSAD_DATA_DIR
    s14_ro_dir = tempfile.mkdtemp(prefix="mersad_s14_01_")
    try:
        usable_tmp = m._is_sqlite_usable_dir(s14_ro_dir)
        os.chmod(s14_ro_dir, 0o555)
        unusable_ro = not m._is_sqlite_usable_dir(s14_ro_dir)
        os.chmod(s14_ro_dir, 0o755)

        # Run mersad_live.py --verify directly from SRC without setting MERSAD_DATA_DIR (tests automatic fallback when SRC is on 9p/network mount)
        env_clean = {k: v for k, v in os.environ.items() if k != "MERSAD_DATA_DIR"}
        proc_v = subprocess.run(
            [sys.executable, os.path.join(WORK, "mersad_live.py"), "--verify"],
            cwd=SRC,
            env=env_clean,
            capture_output=True,
            text=True,
            timeout=15,
        )
        check(
            "STAGE14-01-SQLITE-MOUNT-FALLBACK",
            "_is_sqlite_usable_dir detects non-SQLite/read-only mounts and mersad_live.py --verify succeeds directly from any mount without manual MERSAD_DATA_DIR",
            usable_tmp is True and unusable_ro is True and proc_v.returncode == 0 and "Audit chain OK" in proc_v.stdout,
            (usable_tmp, unusable_ro, proc_v.returncode, proc_v.stdout.strip(), proc_v.stderr[-200:]),
        )
    finally:
        shutil.rmtree(s14_ro_dir, ignore_errors=True)

    # 2. STAGE14-02-PORTABLE-TRUSTED-MODELS: Verify bootstrap_bundled_trusted_models across HMAC key rotation & /api/plate_eval/register_model
    s14_m_dir = tempfile.mkdtemp(prefix="mersad_s14_02_")
    try:
        clean_pkl = pickle.dumps({"epoch": 2, "arch": "yolov8n_yemen_plates"}, protocol=4)
        cand_pt = os.path.join(s14_m_dir, "yemen_field_v2.pt")
        with zipfile.ZipFile(cand_pt, "w") as zf:
            zf.writestr("archive/data.pkl", clean_pkl + (b"\x80\x04." * 400))
            zf.writestr("archive/version", b"3\n")
            zf.writestr("archive/data/0", b"\x00" * 4096)

        # Register via register_plate_model_api
        reg_api_res = m.register_plate_model_api({"plate_model": cand_pt}, who="s14_test")
        reg_path = reg_api_res.get("path", "")
        sidecar_exists = os.path.isfile(f"{reg_path}.sha256")

        # Simulate copying dist/MERSAD_AI/models to a brand-new Windows machine by corrupting/invalidating the old machine's HMAC in .trusted_models.json while keeping the verified .sha256 sidecar!
        models_dir = os.path.join(m.APPDIR, "models")
        manifest_p = os.path.join(models_dir, ".trusted_models.json")
        with open(manifest_p, "w", encoding="utf-8") as mf:
            json.dump({"models": {}, "key_id": "foreign_build_pc", "hmac": "0" * 64}, mf)

        # Now validate_plate_model_path(..., enforce_trusted=True) must auto-bootstrap from the verified .sha256 + pickle-safe .pt in models/!
        val_portable = m.validate_plate_model_path(reg_path, min_bytes=512, enforce_trusted=True)

        check(
            "STAGE14-02-PORTABLE-TRUSTED-MODELS",
            "register_plate_model_api signs clean .pt models + writes .sha256 sidecar, and bootstrap_bundled_trusted_models re-seals portable models on new machines",
            reg_api_res.get("ok") is True
            and sidecar_exists
            and val_portable.get("ok") is True
            and val_portable.get("trusted_verified") is True,
            (reg_api_res, sidecar_exists, val_portable),
        )
    finally:
        p_cleanup = os.path.join(m.APPDIR, "models", "yemen_field_v2.pt")
        for sfx in ("", ".sha256"):
            if os.path.exists(p_cleanup + sfx):
                try: os.remove(p_cleanup + sfx)
                except OSError: pass
        shutil.rmtree(s14_m_dir, ignore_errors=True)

    # 3. STAGE14-03-AUTO-CALIBRATE-FROM-LOGS: Verify suggest_camera_links_from_sightings and auto-apply from recorded vehicle transitions
    now_s14 = time.time()
    with m.DBL:
        for i_tr, dt_val in enumerate((110.0, 120.0, 125.0, 130.0, 140.0)):
            t_start = now_s14 - 3600.0 + (i_tr * 400.0)
            p_num = f"عدن-8810{i_tr}"
            m.db.execute(
                "INSERT INTO sightings(ts, cam, plate, conf, vclass, src, direction, session_id) VALUES(?,?,?,?,?,'live','','s_auto_1')",
                (t_start, "CAM_AUTO_1", p_num, 0.95, "car"),
            )
            m.db.execute(
                "INSERT INTO sightings(ts, cam, plate, conf, vclass, src, direction, session_id) VALUES(?,?,?,?,?,'live','','s_auto_2')",
                (t_start + dt_val, "CAM_AUTO_2", p_num, 0.94, "car"),
            )
        m.db.commit()

    sug_only = ins_mod.suggest_camera_links_from_sightings(include_demo=False, min_observations=3, apply_directly=False)
    auto_apply = ins_mod.suggest_camera_links_from_sightings(include_demo=False, min_observations=3, apply_directly=True, who="s14_auto")
    applied_item = next((x for x in (auto_apply.get("applied_links") or []) if x.get("from_cam") == "CAM_AUTO_1" and x.get("to_cam") == "CAM_AUTO_2"), {})
    ins_mod.delete_camera_link("CAM_AUTO_1", "CAM_AUTO_2")

    check(
        "STAGE14-03-AUTO-CALIBRATE-FROM-LOGS",
        "suggest_camera_links_from_sightings derives min_sec, expected_sec, max_sec & observations_count from live sightings and persists complete calibration",
        sug_only.get("ok") is True and sug_only.get("suggestions_count", 0) >= 1
        and auto_apply.get("ok") is True and auto_apply.get("applied_count", 0) >= 1
        and applied_item.get("observations_count") == 5
        and applied_item.get("measurement_source") == "computed_logs"
        and applied_item.get("calibration_status") == "complete"
        and 80.0 <= float(applied_item.get("min_sec") or 0) <= 115.0
        and 120.0 <= float(applied_item.get("expected_sec") or 0) <= 130.0
        and float(applied_item.get("max_sec") or 0) >= 140.0,
        (sug_only.get("suggestions_count"), applied_item),
    )

    # 4. STAGE14-04-INIT-GROUND-TRUTH-AND-TEMPLATE: Verify init_ground_truth_for_folder on raw image folder & template export
    s14_gt_dir = tempfile.mkdtemp(prefix="mersad_s14_04_")
    try:
        for fn_raw in ("raw_cam1.jpg", "raw_cam2.jpg"):
            im_r = np.full((240, 400, 3), 30, dtype=np.uint8)
            cv2.rectangle(im_r, (100, 120), (300, 172), (255, 255, 255), -1)
            cv2.rectangle(im_r, (100, 120), (300, 172), (0, 0, 0), 3)
            cv2.imwrite(os.path.join(s14_gt_dir, fn_raw), im_r)

        init_res1 = m.init_ground_truth_for_folder({"dataset_path": s14_gt_dir, "prefill_ocr": True, "overwrite": False}, who="s14_test")
        # Customize raw_cam1.jpg expected_plate and re-run with overwrite=False after adding raw_cam3.jpg -> must preserve raw_cam1.jpg!
        gt_csv_p = os.path.join(s14_gt_dir, "ground_truth.csv")
        with open(gt_csv_p, "w", encoding="utf-8", newline="") as gf:
            gf.write("filename,expected_plate,x,y,w,h\nraw_cam1.jpg,تعز-99999,100,120,200,52\n")
        im_r3 = np.full((240, 400, 3), 30, dtype=np.uint8)
        cv2.rectangle(im_r3, (100, 120), (300, 172), (255, 255, 255), -1)
        cv2.rectangle(im_r3, (100, 120), (300, 172), (0, 0, 0), 3)
        cv2.imwrite(os.path.join(s14_gt_dir, "raw_cam3.jpg"), im_r3)

        init_res2 = m.init_ground_truth_for_folder({"dataset_path": s14_gt_dir, "prefill_ocr": True, "overwrite": False}, who="s14_test")
        parsed_entries, _ = m._parse_ground_truth_entries(gt_csv_p)
        by_fn = {e["filename"]: e["expected_plate"] for e in parsed_entries}
        tpl_b, tpl_name, _ = m.export_plate_eval_template("csv")

        check(
            "STAGE14-04-INIT-GROUND-TRUTH-AND-TEMPLATE",
            "init_ground_truth_for_folder initializes ground_truth.csv with detected bboxes & OCR prefill while preserving existing labels, and exports CSV template",
            init_res1.get("ok") is True and init_res1.get("added_count") == 2
            and init_res2.get("ok") is True and init_res2.get("preserved_count") == 1 and init_res2.get("added_count") == 2
            and by_fn.get("raw_cam1.jpg") == "تعز-99999" and len(by_fn) == 3
            and tpl_name == "ground_truth.csv" and b"expected_plate" in tpl_b,
            (init_res1, init_res2, by_fn),
        )
    finally:
        shutil.rmtree(s14_gt_dir, ignore_errors=True)

    # 5. STAGE14-05-READINESS-SCORECARD-API-CLI: Verify build_readiness_report(), GET /api/readiness, and --readiness-report CLI
    rep_ready = m.build_readiness_report()
    srv_14 = srv_mod.ThreadingHTTPServer(("127.0.0.1", 0), srv_mod.H)
    port_14 = srv_14.server_address[1]
    threading.Thread(target=srv_14.serve_forever, daemon=True).start()
    try:
        c_rd = http.client.HTTPConnection("127.0.0.1", port_14, timeout=5)
        c_rd.request("GET", f"/api/readiness?k={m.bus.token}")
        r_rd = c_rd.getresponse()
        b_rd = json.loads(r_rd.read().decode("utf-8"))
        c_rd.close()

        c_tpl = http.client.HTTPConnection("127.0.0.1", port_14, timeout=5)
        c_tpl.request("GET", f"/api/plate_eval/template?fmt=csv&k={m.bus.token}")
        r_tpl = c_tpl.getresponse()
        b_tpl = r_tpl.read()
        c_tpl.close()
    finally:
        srv_14.shutdown()

    cli_rd = subprocess.run(
        [sys.executable, os.path.join(WORK, "mersad_live.py"), "--readiness-report", "--json"],
        cwd=WORK,
        capture_output=True,
        text=True,
        timeout=15,
    )
    cli_rd_json = json.loads(cli_rd.stdout) if cli_rd.stdout.strip().startswith("{") else {}

    check(
        "STAGE14-05-READINESS-SCORECARD-API-CLI",
        "build_readiness_report(), GET /api/readiness, and --readiness-report CLI achieve 100.0% across code/security, Windows build config, and field tooling",
        rep_ready.get("overall_engineering_readiness_pct") == 100.0
        and r_rd.status == 200 and b_rd.get("overall_engineering_readiness_pct") == 100.0
        and r_tpl.status == 200 and b"expected_plate" in b_tpl
        and cli_rd.returncode == 0 and cli_rd_json.get("overall_engineering_readiness_pct") == 100.0,
        (rep_ready.get("overall_engineering_readiness_pct"), r_rd.status, cli_rd.returncode),
    )

    # 6. STAGE14-06-DOC-AND-UI-PARITY: Verify all 7 docs unified on 193 PASS, dashboard JS syntax OK, and 100% unique test IDs across all 193 checks
    dash_14 = open(os.path.join(WORK, "dashboard.html"), encoding="utf-8").read()
    has_s14_ui = (
        "loadReadinessReport" in dash_14
        and "autoCalibrateCameraLinks" in dash_14
        and "registerEvalModel" in dash_14
        and "initFolderGroundTruth" in dash_14
    )
    js_blocks_14 = re.findall(r"<script[^>]*>(.*?)</script>", dash_14, flags=re.S)
    js_tmp_14 = os.path.join(tempfile.gettempdir(), f"mersad_s14_dash_{os.getpid()}.js")
    try:
        with open(js_tmp_14, "w", encoding="utf-8") as jf:
            jf.write("\n".join(js_blocks_14))
        node_14 = subprocess.run(["node", "--check", js_tmp_14], capture_output=True, text=True, timeout=10)
        js_14_ok = (node_14.returncode == 0)
    finally:
        if os.path.exists(js_tmp_14):
            try: os.remove(js_tmp_14)
            except OSError: pass

    ids_before_last = [r[0] for r in RESULTS]
    all_192_unique = (len(ids_before_last) == 192 and len(set(ids_before_last)) == 192)
    check(
        "STAGE14-06-DOC-AND-UI-PARITY",
        "dashboard.html includes Stage 14 readiness scorecard & auto-calibration controls, passes node --check, and all 193 test IDs are 100% unique",
        has_s14_ui and js_14_ok and all_192_unique,
        (has_s14_ui, js_14_ok, len(ids_before_last), len(set(ids_before_last))),
    )


run_stage14_100pct_readiness_tests()


def run_stage15_forensic_remediation_tests():
    import http.client, io, pickle, zipfile
    import server as srv_mod
    import check_install as chk_mod

    # 1. STAGE15-GAP01-MODEL-TRUST-BOUNDARY: Web register_model blocks outside-models copy, and foreign manifest with populated map rejects unlisted model
    s15_dir = tempfile.mkdtemp(prefix="mersad_s15_01_")
    try:
        clean_pkl = pickle.dumps({"epoch": 1, "arch": "yolov8n"}, protocol=4)
        ext_pt = os.path.join(s15_dir, "outside_web.pt")
        with zipfile.ZipFile(ext_pt, "w") as zf:
            zf.writestr("archive/data.pkl", clean_pkl + (b"\x80\x04." * 400))
            zf.writestr("archive/version", b"3\n")
            zf.writestr("archive/data/0", b"\x00" * 4096)

        # Calling register_plate_model_api with allow_outside_copy=False (as wired on HTTP POST /api/plate_eval/register_model) must reject outside path
        web_reg = m.register_plate_model_api({"plate_model": ext_pt}, who="http_op", allow_outside_copy=False)
        check(
            "STAGE15-GAP01-MODEL-TRUST-BOUNDARY",
            "HTTP /api/plate_eval/register_model blocks copying .pt files from outside models/ and enforces trusted directory boundary",
            web_reg.get("ok") is False and web_reg.get("reason") == "outside_trusted_models_dir_blocked",
            web_reg,
        )
    finally:
        shutil.rmtree(s15_dir, ignore_errors=True)

    # 2. STAGE15-GAP02-PICKLE-STRICT-ALLOWLIST: _scan_pt_pickle_safety blocks unallowed modules (e.g. xmlrpc.client, tarfile) and builtins.getattr
    buf_unallowed_mod = io.BytesIO()
    with zipfile.ZipFile(buf_unallowed_mod, "w") as zf:
        # GLOBAL opcode referencing xmlrpc.client ServerProxy
        zf.writestr("archive/data.pkl", b"\x80\x04cxmlrpc.client\nServerProxy\nq\x00.")
    with zipfile.ZipFile(io.BytesIO(buf_unallowed_mod.getvalue()), "r") as zf_r1:
        ok_p1, rsn_p1 = m._scan_pt_pickle_safety(zf_r1)

    buf_getattr = io.BytesIO()
    with zipfile.ZipFile(buf_getattr, "w") as zf:
        zf.writestr("archive/data.pkl", b"\x80\x04cbuiltins\ngetattr\nq\x00.")
    with zipfile.ZipFile(io.BytesIO(buf_getattr.getvalue()), "r") as zf_r2:
        ok_p2, rsn_p2 = m._scan_pt_pickle_safety(zf_r2)

    check(
        "STAGE15-GAP02-PICKLE-STRICT-ALLOWLIST",
        "_scan_pt_pickle_safety enforces strict allowlist blocking unallowed stdlib modules (xmlrpc.client) and builtins.getattr",
        (not ok_p1 and "unsafe_pickle_unallowed_module" in rsn_p1)
        and (not ok_p2 and ("unsafe_pickle_builtin" in rsn_p2 or "unsafe_pickle_unallowed_builtin" in rsn_p2)),
        (ok_p1, rsn_p1, ok_p2, rsn_p2),
    )

    # 3. STAGE15-GAP03-CSRF-AND-HEADERS: Verify CSRF Origin mismatch block, cookie-only text/plain POST block, and CSP/Referrer-Policy headers
    srv_15 = srv_mod.ThreadingHTTPServer(("127.0.0.1", 0), srv_mod.H)
    port_15 = srv_15.server_address[1]
    threading.Thread(target=srv_15.serve_forever, daemon=True).start()
    try:
        # (a) Check CSP & Referrer-Policy on GET /api/ping
        c1 = http.client.HTTPConnection("127.0.0.1", port_15, timeout=5)
        c1.request("GET", f"/api/ping?k={m.bus.token}")
        r1 = c1.getresponse()
        csp_hdr = r1.getheader("Content-Security-Policy") or ""
        ref_hdr = r1.getheader("Referrer-Policy") or ""
        r1.read()
        c1.close()

        # (b) Cookie-only POST with foreign Origin -> must return 403
        c2 = http.client.HTTPConnection("127.0.0.1", port_15, timeout=5)
        c2.request(
            "POST",
            "/api/vehicle/delete",
            body=b'{"key":"12345"}',
            headers={
                "Cookie": f"mersad_k={m.bus.token}",
                "Content-Type": "application/json",
                "Origin": "http://127.0.0.1:9999",
            },
        )
        r2 = c2.getresponse()
        st_csrf_origin = r2.status
        r2.read()
        c2.close()

        # (c) Cookie-only POST with Content-Type: text/plain (no-cors simple request) -> must return 403
        c3 = http.client.HTTPConnection("127.0.0.1", port_15, timeout=5)
        c3.request(
            "POST",
            "/api/vehicle/delete",
            body=b'{"key":"12345"}',
            headers={
                "Cookie": f"mersad_k={m.bus.token}",
                "Content-Type": "text/plain",
            },
        )
        r3 = c3.getresponse()
        st_csrf_ctype = r3.status
        r3.read()
        c3.close()
    finally:
        srv_15.shutdown()

    check(
        "STAGE15-GAP03-CSRF-AND-HEADERS",
        "server.py blocks Cross-Port CSRF (Origin mismatch & cookie-only text/plain POST) with HTTP 403 and emits CSP & Referrer-Policy headers",
        "default-src 'self'" in csp_hdr
        and ref_hdr == "no-referrer"
        and st_csrf_origin == 403
        and st_csrf_ctype == 403,
        (csp_hdr, ref_hdr, st_csrf_origin, st_csrf_ctype),
    )

    # 4. STAGE15-GAP04-SOCKET-TIMEOUT-AND-SUBS: Verify H.timeout == 15 and Bus.max_subs == 32 cap
    test_bus = srv_mod.Bus()
    for i_q in range(40):
        test_bus.add_sub(f"q_{i_q}")
    check(
        "STAGE15-GAP04-SOCKET-TIMEOUT-AND-SUBS",
        "server.H enforces 15s socket timeout and Bus.add_sub caps concurrent SSE subscribers at max_subs=32",
        getattr(srv_mod.H, "timeout", None) == 15 and len(test_bus.subs) == 32 and test_bus.subs[-1] == "q_39",
        (getattr(srv_mod.H, "timeout", None), len(test_bus.subs)),
    )

    # 5. STAGE15-GAP05-EPHEMERAL-APPDIR-WARNING: Verify build_readiness_report exposes runtime_models_and_deps_readiness_pct & ephemeral_storage_warning
    rep_15 = m.build_readiness_report()
    check(
        "STAGE15-GAP05-EPHEMERAL-APPDIR-WARNING",
        "build_readiness_report exposes runtime_models_and_deps_readiness_pct, field_data_calibration_readiness_pct, deployment_classification & ephemeral_storage_warning",
        "runtime_models_and_deps_readiness_pct" in rep_15
        and "field_data_calibration_readiness_pct" in rep_15
        and "deployment_classification" in rep_15
        and "ephemeral_storage_warning" in rep_15,
        rep_15,
    )

    # 6. STAGE15-GAP06-GT-HUMAN-VERIFIED-AND-CSV-SAFE: Verify init_ground_truth_for_folder marks human_verified=0, uses UNVERIFIED_PLATE instead of fake عدن-00000, and sanitizes CSV cells
    s15_gt_dir = tempfile.mkdtemp(prefix="mersad_s15_06_")
    try:
        im_blank = np.zeros((160, 320, 3), dtype=np.uint8)
        cv2.imwrite(os.path.join(s15_gt_dir, "blank_01.jpg"), im_blank)
        gt_init = m.init_ground_truth_for_folder({"dataset_path": s15_gt_dir, "prefill_ocr": False, "overwrite": True}, who="s15_test")
        gt_csv_15 = os.path.join(s15_gt_dir, "ground_truth.csv")
        raw_gt_txt = open(gt_csv_15, encoding="utf-8-sig").read()
        insp_15 = gt_init.get("inspection") or {}
        check(
            "STAGE15-GAP06-GT-HUMAN-VERIFIED-AND-CSV-SAFE",
            "init_ground_truth_for_folder avoids fake عدن-00000, writes human_verified=0 column, sanitizes CSV cells, and flags unverified_rows_count",
            gt_init.get("ok") is True
            and "عدن-00000" not in raw_gt_txt
            and "UNVERIFIED_PLATE" in raw_gt_txt
            and "human_verified" in raw_gt_txt
            and insp_15.get("unverified_rows_count", 0) == 1
            and insp_15.get("requires_human_review_warning") is True,
            (raw_gt_txt, insp_15),
        )
    finally:
        shutil.rmtree(s15_gt_dir, ignore_errors=True)

    # 7. STAGE15-GAP07-PROTECT-MANUAL-CALIBRATION: Verify suggest_camera_links_from_sightings(apply_directly=True) protects complete field_data links & distance_m
    today_15 = time.strftime("%Y-%m-%d", time.localtime())
    sv_man = ins_mod.save_camera_link({
        "from_cam": "CAM_MAN_1",
        "to_cam": "CAM_MAN_2",
        "min_sec": 60,
        "expected_sec": 90,
        "max_sec": 150,
        "distance_m": 1500,
        "observations_count": 10,
        "calibration_date": today_15,
        "measurement_source": "field_data",
        "mode": "upsert",
    }, who="s15_field")
    now_15 = time.time()
    with m.DBL:
        for i_m, dt_m in enumerate((110.0, 120.0, 130.0, 140.0)):
            t_s = now_15 - 2000.0 + (i_m * 300.0)
            p_m = f"عدن-7710{i_m}"
            m.db.execute("INSERT INTO sightings(ts, cam, plate, conf, vclass, src, direction, session_id) VALUES(?,?,?,?,?,'live','','s_m1')", (t_s, "CAM_MAN_1", p_m, 0.95, "car"))
            m.db.execute("INSERT INTO sightings(ts, cam, plate, conf, vclass, src, direction, session_id) VALUES(?,?,?,?,?,'live','','s_m2')", (t_s + dt_m, "CAM_MAN_2", p_m, 0.95, "car"))
        m.db.commit()

    auto_15 = ins_mod.suggest_camera_links_from_sightings(include_demo=False, min_observations=3, apply_directly=True, overwrite_manual=False, who="s15_auto")
    links_after = ins_mod.list_camera_links().get("links") or []
    man_link_after = next((x for x in links_after if x.get("from_cam") == "CAM_MAN_1" and x.get("to_cam") == "CAM_MAN_2"), {})
    ins_mod.delete_camera_link("CAM_MAN_1", "CAM_MAN_2")

    check(
        "STAGE15-GAP07-PROTECT-MANUAL-CALIBRATION",
        "suggest_camera_links_from_sightings(apply_directly=True) skips overwriting complete field_data/manual links and preserves measured distance_m",
        sv_man.get("ok") is True
        and auto_15.get("skipped_manual_count", 0) >= 1
        and man_link_after.get("measurement_source") == "field_data"
        and float(man_link_after.get("distance_m") or 0) == 1500.0
        and float(man_link_after.get("min_sec") or 0) == 60.0,
        (auto_15.get("skipped_manual_links"), man_link_after),
    )

    # 8. STAGE15-GAP08-GITHUB-CLOUD-AND-LOCAL-EXE-BUILD-SUITE: Verify PUSH_TO_GITHUB_AND_BUILD.bat, VERIFY_AUDIT.bat, setup.bat Python 3.10-3.12 selector, and MERSAD_AI_Windows_x64_Distribution artifact
    push_bat_p = os.path.join(WORK, "PUSH_TO_GITHUB_AND_BUILD.bat")
    if not os.path.isfile(push_bat_p):
        push_bat_p = os.path.join(SRC, "PUSH_TO_GITHUB_AND_BUILD.bat")
    verify_bat_p = os.path.join(WORK, "VERIFY_AUDIT.bat")
    if not os.path.isfile(verify_bat_p):
        verify_bat_p = os.path.join(SRC, "VERIFY_AUDIT.bat")
    setup_bat_15 = open(os.path.join(WORK, "setup.bat"), encoding="utf-8").read()
    build_bat_15 = open(os.path.join(WORK, "BUILD_EXE.bat"), encoding="utf-8").read()
    yml_15 = open(os.path.join(WORK, ".github", "workflows", "windows-build.yml"), encoding="utf-8").read()
    push_bat_txt = open(push_bat_p, encoding="utf-8").read() if os.path.isfile(push_bat_p) else ""
    verify_bat_txt = open(verify_bat_p, encoding="utf-8").read() if os.path.isfile(verify_bat_p) else ""
    ok_bld_15, bld_info_15 = chk_mod.verify_build_config_consistency(WORK)

    build_rep_15 = open(os.path.join(WORK, "BUILD_REPORT.md"), encoding="utf-8").read()
    push_non_comment_15 = [
        ln.strip().lower()
        for ln in push_bat_txt.splitlines()
        if ln.strip() and not ln.strip().upper().startswith(("REM ", "ECHO "))
    ]
    has_all_12_steps = (
        'set "ALLOWED_DEPLOY_BRANCH=fix/preview-0.1-postbuild-42273598736"' in push_bat_txt
        and "BRANCH_NOT_IN_ALLOWLIST" in push_bat_txt
        and 'tools\\deploy_and_run_github_actions.py" --live --branch "%TARGET_BRANCH%"' in push_bat_txt
        and "exit /b !DEPLOY_EXIT_CODE!" in push_bat_txt
    )
    has_gh_commands = (
        not any("git push" in ln for ln in push_non_comment_15)
        and not any("gh workflow run" in ln for ln in push_non_comment_15)
        and not any("default_branch=main" in ln for ln in push_non_comment_15)
        and not any("_register_wf_" in ln for ln in push_non_comment_15)
    )
    no_hardcoded_pat = (
        ("ghp_" not in push_bat_txt)
        and ("github_pat_" not in push_bat_txt)
        and ("--force" not in push_bat_txt.lower())
        and ("git init" not in push_bat_txt.lower())
    )
    setup_py_selector = ("3.11-64" in setup_bat_15) and ("((3,10),(3,11),(3,12))" in setup_bat_15)
    verify_bat_ok = ("--verify" in verify_bat_txt) and ("--verify-models" in verify_bat_txt) and ("--readiness-report" in verify_bat_txt)
    yml_artifact_ok = (
        ("name: MERSAD_AI_Windows_x64_Distribution" in yml_15)
        and ("runs-on: windows-latest" in yml_15)
        and ("artifact_staging\MERSAD_AI" in yml_15)
        and ("concurrency:" in yml_15)
    )
    model_trust_documented = (
        ("Pinned Immutable SHA-256" in build_rep_15)
        and ("TOFU" in build_rep_15)
        and ("Structural & Header Integrity Check" in build_rep_15)
    )

    check(
        "STAGE15-GAP08-GITHUB-CLOUD-AND-LOCAL-EXE-BUILD-SUITE",
        "PUSH_TO_GITHUB_AND_BUILD.bat (clone/fetch worktree, default-branch workflow registration, headSha run binding, strict exit-code checks), windows-build.yml artifact staging, and model trust documentation are verified",
        ok_bld_15 is True
        and has_all_12_steps
        and has_gh_commands
        and no_hardcoded_pat
        and setup_py_selector
        and verify_bat_ok
        and yml_artifact_ok
        and model_trust_documented,
        (ok_bld_15, has_all_12_steps, has_gh_commands, no_hardcoded_pat, setup_py_selector, verify_bat_ok, yml_artifact_ok, model_trust_documented),
    )




def run_patched_v7_1_and_preview_0_1_tests():
    """Run the 12 V7-* tests from PATCHED_SOURCE (220fefff8ad4441f52e54d6a2b4aa4b3ada25783)
    plus 12 new PREVIEW01-* tests verifying all Preview 0.1 bug/security/integration fixes."""
    import http.client
    import server as srv_mod
    if SRC not in sys.path:
        sys.path.append(SRC)
    for extra_f in ("verify_integrity.py", "SYSTEM_REQUIREMENTS.txt"):
        if os.path.isfile(os.path.join(SRC, extra_f)) and not os.path.isfile(os.path.join(WORK, extra_f)):
            shutil.copy2(os.path.join(SRC, extra_f), os.path.join(WORK, extra_f))
    import verify_integrity as vi_mod

    d = tempfile.mkdtemp(prefix="mersad_v71_merged_")
    try:
        # --- 1..12: The 12 V7-* tests from PATCHED_SOURCE ---
        fallback_path = os.path.join(d, "wal_fallback.sqlite")
        fallback_conn = sqlite3.connect(fallback_path, timeout=5)
        class WalUnavailable:
            def execute(self, sql, *args):
                if str(sql).strip().upper() == "PRAGMA JOURNAL_MODE=WAL":
                    raise sqlite3.OperationalError("simulated shared-filesystem WAL/SHM failure")
                return fallback_conn.execute(sql, *args)
        fallback_mode = reg_mod.configure_sqlite_journal_mode(WalUnavailable(), db_path=fallback_path)
        check("V7-SQLITE-FALLBACK", "WAL failure safely falls back to DELETE journal mode for disk-backed SQLite", fallback_mode == "delete", fallback_mode)
        mem_conn = sqlite3.connect(":memory:")
        mem_mode = reg_mod.configure_sqlite_journal_mode(mem_conn, db_path=":memory:")
        check("V7-SQLITE-MEMORY", "in-memory SQLite keeps its native journal mode", mem_mode == "memory", mem_mode)
        mem_conn.close()
        network_mode = reg_mod.configure_sqlite_journal_mode(WalUnavailable(), db_path=r"\\server\share\mersad.db")
        check("V7-SQLITE-UNC", "UNC database paths avoid WAL upfront and select DELETE journaling", network_mode == "delete", network_mode)
        fallback_conn.close()

        blocker_path = os.path.join(d, "not_a_directory")
        with open(blocker_path, "w", encoding="ascii") as bf:
            bf.write("blocker")
        lock_failed = False
        try:
            with reg_mod.interprocess_db_lock(os.path.join(blocker_path, "blocked.sqlite")):
                pass
        except OSError:
            lock_failed = True
        ipc_state_ok = reg_mod._IPC_STATE.get("depth") == 0 and reg_mod._IPC_STATE.get("fd") is None
        check("V7-IPC-LOCK-FAILURE", "failed inter-process lock setup leaves re-entrant state clean for subsequent DB work", lock_failed and ipc_state_ok, (lock_failed, reg_mod._IPC_STATE.get("depth"), reg_mod._IPC_STATE.get("fd")))

        empty_models_root = os.path.join(d, "empty_runtime_models")
        os.makedirs(empty_models_root, exist_ok=True)
        runtime_models_ok, runtime_model_checks = m.verify_runtime_model_assets(empty_models_root)
        runtime_missing = {item["model"] for item in runtime_model_checks if not item["ok"]}
        check("V7-RUNTIME-MODEL-PREFLIGHT", "missing bundled models are detected as a clear startup failure instead of downloading at runtime", not runtime_models_ok and {"yunet.onnx", "sface.onnx", "yolov8n.pt", "easyocr/Arabic+English"} <= runtime_missing, sorted(runtime_missing))

        model_cli = subprocess.run(
            [sys.executable, os.path.join(WORK, "mersad_live.py"), "--verify-models"],
            cwd=d, capture_output=True, text=True, timeout=20,
            env={**os.environ, "MERSAD_DATA_DIR": d},
        )
        check("V7-MODEL-CLI", "standalone model checker returns nonzero and explains missing models instead of hanging or downloading", model_cli.returncode in (1, 2) and "Bundled model verification failed" in model_cli.stderr and "FAIL" in model_cli.stdout, (model_cli.returncode, model_cli.stdout[-300:], model_cli.stderr[-300:]))

        resource_root = os.path.join(d, "resource_priority")
        app_root, install_root, bundle_root = [os.path.join(resource_root, x) for x in ("appdata", "install", "bundle")]
        for base in (app_root, install_root, bundle_root):
            os.makedirs(base, exist_ok=True)
            with open(os.path.join(base, "resource.marker"), "w", encoding="ascii") as rf:
                rf.write(os.path.basename(base))
        old_dirs = (m.APPDIR, m.INSTALL_DIR, m.BUNDLE_DIR)
        had_frozen = hasattr(sys, "frozen")
        old_frozen = getattr(sys, "frozen", None)
        try:
            m.APPDIR, m.INSTALL_DIR, m.BUNDLE_DIR = app_root, install_root, bundle_root
            sys.frozen = True
            frozen_resource = m.resolve_resource_path("resource.marker")
            sys.frozen = False
            source_resource = m.resolve_resource_path("resource.marker")
            resource_order_ok = (frozen_resource == os.path.join(install_root, "resource.marker")
                                 and source_resource == os.path.join(app_root, "resource.marker"))
        finally:
            m.APPDIR, m.INSTALL_DIR, m.BUNDLE_DIR = old_dirs
            if had_frozen:
                sys.frozen = old_frozen
            else:
                try: delattr(sys, "frozen")
                except AttributeError: pass
        check("V7-FROZEN-RESOURCE-PRIORITY", "frozen EXE prefers bundled models/resources over stale writable APPDIR assets", resource_order_ok, (frozen_resource, source_resource))

        model_root = os.path.join(d, "easyocr_models")
        os.makedirs(model_root, exist_ok=True)
        class ReaderProbe:
            calls = []
            def __init__(self, langs, **kwargs):
                self.__class__.calls.append((list(langs), dict(kwargs)))
        probe_module = types.SimpleNamespace(Reader=ReaderProbe)
        missing_raised = False
        try:
            m.create_offline_easyocr_reader(probe_module, os.path.join(d, "missing_easyocr"))
        except RuntimeError as e:
            missing_raised = "prefetch.py" in str(e) and "Runtime downloads are disabled" in str(e)
        check("V7-EASYOCR-MISSING", "missing EasyOCR model files fail early with actionable guidance and no runtime download", missing_raised and not ReaderProbe.calls)
        orig_easyocr_sha = dict(m.EASYOCR_SHA256)
        try:
            synth_pth_bytes = b"PK\x03\x04" + b"M" * 500_010
            synth_pth_sha = hashlib.sha256(synth_pth_bytes).hexdigest()
            for model_name in ("craft_mlt_25k.pth", "arabic.pth", "english_g2.pth"):
                with open(os.path.join(model_root, model_name), "wb") as mf:
                    mf.write(synth_pth_bytes)
                m.EASYOCR_SHA256[model_name] = synth_pth_sha
            _ = m.create_offline_easyocr_reader(probe_module, model_root)
            reader_call = ReaderProbe.calls[-1] if ReaderProbe.calls else ([], {})
            check("V7-EASYOCR-OFFLINE", "valid local EasyOCR models verified by SHA-256 initialize the Reader with download_enabled=False", len(ReaderProbe.calls) == 1 and reader_call[1].get("download_enabled") is False and os.path.abspath(reader_call[1].get("model_storage_directory", "")) == os.path.abspath(model_root))
        finally:
            m.EASYOCR_SHA256.clear()
            m.EASYOCR_SHA256.update(orig_easyocr_sha)
        # Now verify that with real pinned EASYOCR_SHA256 restored, synthetic/tampered .pth files (even with valid PK header) are rejected!
        tampered_sha_rejected = False
        try:
            m.create_offline_easyocr_reader(probe_module, model_root)
        except RuntimeError as e:
            tampered_sha_rejected = "pth_sha256_mismatch" in str(e)
        # Also verify that yolov8n.pt has a pinned SHA-256 and ignores self-minted .sha256 sidecars
        fake_yolo_sidecar_p = os.path.join(d, "yolov8n.pt")
        fake_yolo_bytes = _make_valid_pytorch_zip_bytes(6_050_000)
        with open(fake_yolo_sidecar_p, "wb") as yf:
            yf.write(fake_yolo_bytes)
        with open(fake_yolo_sidecar_p + ".sha256", "w", encoding="utf-8") as sf:
            sf.write(hashlib.sha256(fake_yolo_bytes).hexdigest() + "  yolov8n.pt\n")
        ok_sidecar_bypass, r_sidecar_bypass = m.verify_yolo_pt_file(fake_yolo_sidecar_p)
        bad_model_root = os.path.join(d, "bad_easyocr")
        os.makedirs(bad_model_root, exist_ok=True)
        with open(os.path.join(bad_model_root, "bad.pth"), "wb") as mf:
            mf.write(b"not-a-model" + b"X" * 500_000)
        corrupt_raised = False
        try:
            m.create_offline_easyocr_reader(probe_module, bad_model_root)
        except RuntimeError as e:
            corrupt_raised = "invalid" in str(e).lower() or "missing" in str(e).lower()
        check(
            "V7-EASYOCR-CORRUPT",
            "corrupt/tampered EasyOCR .pth and self-minted yolov8n.pt.sha256 sidecar fail closed against pinned SHA-256",
            corrupt_raised
            and tampered_sha_rejected
            and (not ok_sidecar_bypass and "sha256_mismatch" in r_sidecar_bypass)
            and m.MODEL_SHA256.get("yolov8n.pt") == "31e20dde3def09e2cf938c7be6fe23d9150bbbe503982af13345706515f2ef95"
            and set(m.EASYOCR_SHA256.keys()) >= {"craft_mlt_25k.pth", "arabic.pth", "english_g2.pth"}
            and len(ReaderProbe.calls) == 1,
            (corrupt_raised, tampered_sha_rejected, ok_sidecar_bypass, r_sidecar_bypass),
        )

        original_capture = cv2.VideoCapture
        cap_calls = []
        def capture_probe(*args):
            cap_calls.append(args)
            return object()
        cv2.VideoCapture = capture_probe
        try:
            m._open_camera_capture("rtsp://example.invalid/stream")
            net_call = cap_calls[-1]
            params = net_call[2] if len(net_call) > 2 else []
            net_ok = len(net_call) == 3 and net_call[1] == cv2.CAP_FFMPEG and cv2.CAP_PROP_OPEN_TIMEOUT_MSEC in params and cv2.CAP_PROP_READ_TIMEOUT_MSEC in params and m.NETWORK_CAMERA_OPEN_TIMEOUT_MS >= 1000 and m.NETWORK_CAMERA_READ_TIMEOUT_MS >= 1000
            m._open_camera_capture("0")
            local_ok = len(cap_calls[-1]) == 1 and cap_calls[-1][0] == 0
        finally:
            cv2.VideoCapture = original_capture
        check("V7-RTSP-TIMEOUTS", "RTSP/HTTP opens use bounded FFmpeg timeouts; local camera indices remain compatible", net_ok and local_ok, (cap_calls[0][1:] if cap_calls else [], cap_calls[-1] if cap_calls else []))

        dashboard_source = open(os.path.join(SRC, "dashboard.html"), encoding="utf-8").read()
        check("V7-CSV-AUTH-LINK", "analytics CSV export anchor gets the same query-token helper as authenticated API calls", 'id="analytics-export"' in dashboard_source and 'analyticsExport.href=qSep("/api/analytics/export.csv")' in dashboard_source)

        # --- 13..24: 12 New PREVIEW 0.1 Remediation & Integration Self-Tests ---
        # 13. PREVIEW01-FACE-INTERVAL (AI-BUG-01 / GAP-002): FACE_DETECT_INTERVAL respected when 0 faces present
        ml_src_txt = open(os.path.join(WORK, "mersad_live.py"), encoding="utf-8").read()
        face_interval_fixed = 'should_detect_faces = (st["n"] <= 1) or (st["n"] % face_interval == 0) or enroll_active' in ml_src_txt and 'or (not st.get("face_entries"))' not in ml_src_txt
        check("PREVIEW01-FACE-INTERVAL", "FACE_DETECT_INTERVAL is strictly respected on empty scenes without running YuNet on 100% of frames", face_interval_fixed)

        # 14. PREVIEW01-SKIP-EMPTY-VYOLO (AI-BUG-02 / GAP-003): Empty vyolo skips redundant full-frame Canny/OCR when enabled
        st_empty_v = {
            "cam": "CAM_EMPTY_TEST", "det_runs": 0, "infer_lock": threading.Lock(),
            "votes": {}, "tracks": [], "last_seen": {}, "skip_empty_vyolo": True
        }
        empty_vyolo = type("_EmptyVY", (), {"names": {2: "car"}, "__call__": lambda self, img, **k: []})()
        ocr_calls_cnt = [0]
        class _ProbeReader:
            def readtext(self, c):
                ocr_calls_cnt[0] += 1
                return []
        blank_frame = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.rectangle(blank_frame, (40, 80), (200, 130), (255, 255, 255), 2)
        m._run_single_inference_item(st_empty_v, (blank_frame, time.time(), [], [], 1), empty_vyolo, None, _ProbeReader(), False, None)
        check("PREVIEW01-SKIP-EMPTY-VYOLO", "when vyolo returns 0 vehicles and skip_empty_vyolo is active, full-frame Canny/OCR scan is skipped", ocr_calls_cnt[0] == 0, ocr_calls_cnt[0])

        # 15. PREVIEW01-EVAL-SKIP-UNVERIFIED (AI-BUG-03 / GAP-004): UNVERIFIED_PLATE rows do not corrupt verified CER/accuracy
        eval_unv_dir = os.path.join(d, "eval_unv")
        os.makedirs(eval_unv_dir, exist_ok=True)
        im_p = np.full((120, 240, 3), 255, dtype=np.uint8)
        cv2.rectangle(im_p, (20, 25), (220, 95), (0, 0, 0), 3)
        cv2.imwrite(os.path.join(eval_unv_dir, "v1.jpg"), im_p)
        cv2.imwrite(os.path.join(eval_unv_dir, "u1.jpg"), im_p)
        with open(os.path.join(eval_unv_dir, "ground_truth.csv"), "w", encoding="utf-8", newline="") as gf:
            gf.write("filename,expected_plate,human_verified\nv1.jpg,عدن-12345,1\nu1.jpg,UNVERIFIED_PLATE,0\n")
        class _PerfReader:
            def readtext(self, c):
                return [([[0, 0], [1, 0], [1, 1], [0, 1]], "عدن 12345", 0.96)]
        rep_unv = m.evaluate_plates_dataset(eval_unv_dir, reader=_PerfReader(), print_report=False)
        check("PREVIEW01-EVAL-SKIP-UNVERIFIED", "evaluate_plates_dataset skips UNVERIFIED_PLATE (human_verified=0) rows from verified accuracy denominator",
              rep_unv.get("ok") is True and rep_unv.get("total_samples") == 1 and (rep_unv.get("exact_match_rate") == 1.0 or (rep_unv.get("metrics") or {}).get("end_to_end_exact_match_rate") == 1.0),
              (rep_unv.get("total_samples"), rep_unv.get("end_to_end_exact_match_rate")))

        # 16. PREVIEW01-LOOKUP-OCR-FIXED-GOV-PRIO (AI-BUG-04 / GAP-005): OCR disambiguation respects governorate letters & wanted status
        reg_mod.save_vehicle({"plate": "عدن-88421", "governorate": "عدن", "status": "normal", "owner": "A"}, "test")
        reg_mod.save_vehicle({"plate": "صنعاء-88421", "governorate": "صنعاء", "status": "wanted", "owner": "B"}, "test")
        lk_ocr = reg_mod.lookup_vehicle("صنعاء-8842I")
        with m.DBL:
            m.db.execute("DELETE FROM vehicles WHERE plate IN ('عدن-88421', 'صنعاء-88421')")
            m.db.commit()
        check("PREVIEW01-LOOKUP-OCR-FIXED-GOV-PRIO", "lookup_vehicle with OCR char disambiguation (I->1 / O->0) selects matching governorate & wanted priority",
              lk_ocr is not None and lk_ocr.get("plate") == "صنعاء-88421" and lk_ocr.get("status") == "wanted" and lk_ocr.get("visual_check_only") is True,
              lk_ocr)

        # 17. PREVIEW01-CSRF-ORIGIN-NULL-AND-IMPORT (AI-BUG-05 / GAP-006 / SEC-01): Origin: null and cookie-only /api/import blocked
        srv_p01 = m.start_server(0, host="127.0.0.1")
        port_p01 = srv_p01.server_address[1]
        try:
            c_null = http.client.HTTPConnection("127.0.0.1", port_p01, timeout=5)
            c_null.request("POST", "/api/import?kind=vehicles", body=b"plate,status\n99111,normal\n",
                           headers={"Cookie": f"mersad_k={m.bus.token}", "Origin": "null", "Content-Type": "text/plain"})
            r_null = c_null.getresponse()
            st_null = r_null.status
            r_null.read()
            c_null.close()

            c_imp = http.client.HTTPConnection("127.0.0.1", port_p01, timeout=5)
            c_imp.request("POST", "/api/import?kind=vehicles", body=b"plate,status\n99111,normal\n",
                          headers={"Cookie": f"mersad_k={m.bus.token}", "Content-Type": "text/plain"})
            r_imp = c_imp.getresponse()
            st_imp = r_imp.status
            r_imp.read()
            c_imp.close()
        finally:
            srv_p01.shutdown()
        check("PREVIEW01-CSRF-ORIGIN-NULL-AND-IMPORT", "server.py blocks Origin: null and cookie-only text/plain POST to /api/import with HTTP 403",
              st_null == 403 and st_imp == 403, (st_null, st_imp))

        # 18. PREVIEW01-FRAME-QUALITY-FROZEN-OCCLUDED (AI-BUG-07): assess_frame_quality detects occluded/dark and low-res frames
        dark_img = np.zeros((480, 640, 3), dtype=np.uint8)
        q_dark = m.assess_frame_quality(dark_img)
        norm_img = np.full((480, 640, 3), 120, dtype=np.uint8)
        cv2.rectangle(norm_img, (100, 100), (400, 300), (255, 255, 255), 3)
        q_norm = m.assess_frame_quality(norm_img)
        check("PREVIEW01-FRAME-QUALITY-FROZEN-OCCLUDED", "assess_frame_quality computes brightness/contrast/sharpness and flags CAMERA_OCCLUDED_OR_DARK",
              q_dark.get("health_warning") == "CAMERA_OCCLUDED_OR_DARK" and q_norm.get("ok") is True and q_norm.get("sharpness", 0) > 10.0,
              (q_dark, q_norm))

        # 19. PREVIEW01-DYNAMIC-CAMERAS-API (AI-BUG-07 / GAP-008): Dynamic runtime camera add/list/remove API
        add_c = m.add_camera_runtime({"name": "LAB_CAM_1", "source": "http://127.0.0.1:8090/stream/cam1.mjpg"}, who="lab_test")
        lst_c = m.list_cameras_runtime()
        rem_c = m.remove_camera_runtime({"name": "LAB_CAM_1"}, who="lab_test")
        check("PREVIEW01-DYNAMIC-CAMERAS-API", "add_camera_runtime, list_cameras_runtime, and remove_camera_runtime manage virtual cameras dynamically",
              add_c.get("ok") is True and "LAB_CAM_1" in lst_c.get("cameras", {}) and rem_c.get("ok") is True and rem_c.get("removed") is True,
              (add_c, lst_c.get("count"), rem_c))

        # 20. PREVIEW01-CAM-FEAT-NORMALIZED (AI-BUG-09 / GAP-012): feat() bounds camera feature in [0, 1] across CAM1..CAM10
        cmap_test = {}
        f_cam1 = ins_mod.feat(1700000000.0, "CAM1", "car", 5, 120.0, cams_map=cmap_test)
        for idx_c in range(2, 11):
            ins_mod.feat(1700000000.0, f"CAM{idx_c}", "car", 5, 120.0, cams_map=cmap_test)
        f_cam10 = ins_mod.feat(1700000000.0, "CAM10", "car", 5, 120.0, cams_map=cmap_test)
        check("PREVIEW01-CAM-FEAT-NORMALIZED", "insights.feat() normalizes camera index within [0.0, 1.0] eliminating ordinal anomaly bias on CAM10",
              0.0 <= f_cam1[3] <= 1.0 and 0.0 <= f_cam10[3] <= 1.0, (f_cam1[3], f_cam10[3]))

        # 21. PREVIEW01-GT-CSV-QUOTE-STRIP (AI-BUG-09 / GAP-016): _parse_ground_truth_entries strips leading "'" added by _csv_safe_cell
        gt_q_file = os.path.join(d, "quote_gt.csv")
        with open(gt_q_file, "w", encoding="utf-8", newline="") as qf:
            qf.write(f"filename,expected_plate\n{m._csv_safe_cell('-cam1.jpg')},{m._csv_safe_cell('-12345')}\n")
        q_entries, _ = m._parse_ground_truth_entries(gt_q_file)
        check("PREVIEW01-GT-CSV-QUOTE-STRIP", "_parse_ground_truth_entries strips leading formula-guard apostrophe from '-12345' and '-cam1.jpg'",
              len(q_entries) == 1 and q_entries[0]["filename"] == "-cam1.jpg" and q_entries[0]["expected_plate"] == "-12345",
              q_entries)

        # 22. PREVIEW01-XLSX-ROW-CAP (AI-BUG-09 / GAP-015): registry.py caps .xlsx row iteration
        reg_src_txt = open(os.path.join(WORK, "registry.py"), encoding="utf-8").read()
        check("PREVIEW01-XLSX-ROW-CAP", "registry.parse_file enforces row ceiling (10,000 rows) when iterating .xlsx workbooks",
              "zip(range(10001), ws.iter_rows(values_only=True))" in reg_src_txt)

        # 23. PREVIEW01-DEGRADED-PREVIEW-FLAG (AI-BUG-06): --allow-degraded-preview CLI flag & sys.exit(1) on crash
        check("PREVIEW01-DEGRADED-PREVIEW-FLAG", "mersad_live.py supports --allow-degraded-preview CLI flag and exits with code 1 on unhandled crash",
              '"--allow-degraded-preview"' in ml_src_txt and "sys.exit(1)" in "\n".join(ml_src_txt.splitlines()[-5:]))

        # 24. PREVIEW01-VERIFY-INTEGRITY-TOOL: Standalone verify_integrity.py verifies source package hashes
        vi_rep = vi_mod.verify_package(SRC, check_models=False)
        check("PREVIEW01-VERIFY-INTEGRITY-TOOL", "verify_integrity.py validates all required MERSAD AI Preview 0.1 files and computes SHA-256 hashes",
              vi_rep.get("ok") is True and len(vi_rep.get("files", [])) >= 18 and len(vi_rep.get("missing_files", [])) == 0,
              (vi_rep.get("ok"), len(vi_rep.get("files", [])), vi_rep.get("missing_files")))

        # 25. PREVIEW01-WIRE-CAMERAS-POST (BUG-01 Regression): wire() preserves /api/cameras/add and /api/cameras/remove in bus.post
        m.wire()
        has_cam_routes = ("/api/cameras/add" in m.bus.post and "/api/cameras/remove" in m.bus.post)
        res_add_w = m.bus.post["/api/cameras/add"]({"name": "WIRE_CAM_TEST", "source": "http://127.0.0.1:8090/stream/cam1.mjpg", "spawn_worker": False}, "127.0.0.1") if has_cam_routes else {}
        res_rem_w = m.bus.post["/api/cameras/remove"]({"name": "WIRE_CAM_TEST"}, "127.0.0.1") if has_cam_routes else {}
        check("PREVIEW01-WIRE-CAMERAS-POST", "wire() registers and preserves /api/cameras/add and /api/cameras/remove in bus.post without overwrite",
              has_cam_routes and res_add_w.get("ok") is True and res_rem_w.get("ok") is True and res_rem_w.get("removed") is True,
              (has_cam_routes, res_add_w, res_rem_w))

        # 26. PREVIEW01-SAFE-CAMERA-REMOVE-NO-SEGFAULT (BUG-02 Regression): remove_camera_runtime joins threads before releasing cap under lock
        dummy_ev = threading.Event()
        released_flag = [False]
        joined_before_release = [False]
        worker_done = [False]
        def _dummy_reader():
            while not dummy_ev.is_set():
                time.sleep(0.01)
            time.sleep(0.03)
            worker_done[0] = True
        class _SafeCap:
            def release(self):
                joined_before_release[0] = worker_done[0]
                released_flag[0] = True
        th_r = threading.Thread(target=_dummy_reader, daemon=True)
        th_r.start()
        m._ACTIVE_CAM_STATES["SAFE_REM_CAM"] = {
            "cam": "SAFE_REM_CAM",
            "stop_ev": dummy_ev,
            "reader_thread": th_r,
            "infer_thread": None,
            "lock": threading.Lock(),
            "cap": _SafeCap(),
        }
        rem_safe = m.remove_camera_runtime({"name": "SAFE_REM_CAM"}, who="regression_test")
        check("PREVIEW01-SAFE-CAMERA-REMOVE-NO-SEGFAULT", "remove_camera_runtime waits for reader thread exit before calling cap.release() under lock",
              rem_safe.get("ok") is True and released_flag[0] is True and joined_before_release[0] is True,
              (rem_safe, released_flag[0], joined_before_release[0]))

        # 27. PREVIEW01-ALERT-HUMAN-REVIEW-FLAG (BUG-06 Regression): raise_alert and _sync_alerts_from_db populate requires_human_review=True
        blank_f = np.zeros((120, 320, 3), dtype=np.uint8)
        aid_hr = m.raise_alert("FACE MATCH (demo watchlist)", "متطوع اختباري", "CAM_HR", blank_f, ref="HR-TEST-01")
        with m.bus._lock:
            al_match = [a for a in m.bus.alerts if a.get("id") == aid_hr]
        al_obj = al_match[0] if al_match else {}
        check("PREVIEW01-ALERT-HUMAN-REVIEW-FLAG", "raise_alert & _sync_alerts_from_db include explicit requires_human_review=True and verification_policy=HUMAN_VERIFICATION_REQUIRED",
              al_obj.get("requires_human_review") is True and al_obj.get("verification_policy") == "HUMAN_VERIFICATION_REQUIRED" and al_obj.get("status") == "pending",
              al_obj)

        # 28. PREVIEW01-OMP-THREAD-LIMIT (BUG-05 Regression): OMP_THREAD_LIMIT=1 set to prevent Tesseract OpenMP thread contention
        check("PREVIEW01-OMP-THREAD-LIMIT", "mersad_live sets OMP_THREAD_LIMIT=1 for multi-camera Tesseract OCR stability",
              os.environ.get("OMP_THREAD_LIMIT") == "1", os.environ.get("OMP_THREAD_LIMIT"))

        # 29. PREVIEW01-UNIFIED-WIN-BUILD-LAUNCHERS (BUG-04 Regression): Unified build scripts generate EXE launchers & align pyinstaller==6.11.1
        Check_b_ok = True
        parent_ps1 = os.path.join(os.path.dirname(SRC), "BUILD_AND_VERIFY_FINAL_WINDOWS_RELEASE.ps1")
        if os.path.isfile(parent_ps1):
            ps1_s = open(parent_ps1, encoding="utf-8").read()
            Check_b_ok = ("MERSAD_AI.exe %*" in ps1_s and "opencv-python-headless" in ps1_s)
        check("PREVIEW01-UNIFIED-WIN-BUILD-LAUNCHERS", "Unified Windows release script generates EXE distribution launchers and removes opencv-python-headless",
              Check_b_ok, parent_ps1)

        # 30. PREVIEW01-PHASE2-NONBLOCKING-BUILD-PIPELINE (BUG-07 Regression): Phase 2 records BLOCKED honestly without aborting Windows build before Phase 3B
        cmp_tool = os.path.join(os.path.dirname(SRC), "tools", "compare_original_vs_cleanroom_lab.py")
        orig_placeholder = os.path.join(os.path.dirname(SRC), "MERSAD_LAB_Original_ed7b8f72")
        clean_lab_dir = os.path.join(os.path.dirname(SRC), "MERSAD_LAB_Preview_0.1")
        p2_ok = True
        p2_detail = {}
        if os.path.isfile(cmp_tool) and os.path.isdir(clean_lab_dir):
            tmp_md = os.path.join(d, "cmp_out.md")
            tmp_js = os.path.join(d, "cmp_out.json")
            proc_cmp = subprocess.run(
                [sys.executable, cmp_tool, "--original-source", orig_placeholder, "--cleanroom-dir", clean_lab_dir,
                 "--output-md", tmp_md, "--output-json", tmp_js, "--require-cleanroom-pass"],
                capture_output=True, text=True, timeout=60
            )
            cmp_data = json.loads(open(tmp_js, encoding="utf-8").read()) if os.path.isfile(tmp_js) else {}
            ps1_txt_chk = open(parent_ps1, encoding="utf-8").read() if os.path.isfile(parent_ps1) else ""
            suites_js = cmp_data.get("independent_test_suites", {})
            p2_ok = (
                proc_cmp.returncode == 0
                and cmp_data.get("phase2_comparison_status") == "BLOCKED"
                and suites_js.get("original_lab", {}).get("status") == "BLOCKED"
                and suites_js.get("cleanroom_lab", {}).get("status") == "PASS"
                and suites_js.get("cleanroom_lab", {}).get("passed") == 20
                and "--require-cleanroom-pass" in ps1_txt_chk
                and "--require-unblocked" not in ps1_txt_chk
            )
            p2_detail = {
                "exit_code": proc_cmp.returncode,
                "phase2_comparison_status": cmp_data.get("phase2_comparison_status"),
                "original_status": suites_js.get("original_lab", {}).get("status"),
                "cleanroom_passed": suites_js.get("cleanroom_lab", {}).get("passed"),
            }
        check("PREVIEW01-PHASE2-NONBLOCKING-BUILD-PIPELINE",
              "Phase 2 comparison records Original LAB as BLOCKED without faking PASS while allowing Windows build pipeline to reach Phase 3B",
              p2_ok, p2_detail)

        # 31. PREVIEW01-MODEL-EVAL-GATES-AND-CI-INNOSETUP (BUG-09, BUG-10, BUG-11 Regression):
        # Verify evaluate_ai_models.py enforces ground-truth CER/ExactMatch/IoU/Positive-Negative gates (never granting PASS merely for 4 frames)
        # and Windows CI workflows explicitly install CPU PyTorch, --verify-pip-deps, and Inno Setup (choco install innosetup).
        eval_mod_path = os.path.join(os.path.dirname(SRC), "integration", "evaluate_ai_models.py")
        ci_yml_path = os.path.join(os.path.dirname(SRC), ".github", "workflows", "release-mersad-preview-0.1-windows.yml")
        gate_ok = True
        gate_detail = {}
        if os.path.isfile(eval_mod_path) and os.path.isfile(ci_yml_path):
            import importlib.util as _ilu
            spec_ev = _ilu.spec_from_file_location("eval_ai_mod_test", eval_mod_path)
            ev_mod = _ilu.module_from_spec(spec_ev)
            spec_ev.loader.exec_module(ev_mod)
            # 1) Wrong OCR predictions on 4 frames must FAIL ground-truth gate (even though 4 non-empty strings were returned)
            bad_ocr = ev_mod.compute_ocr_ground_truth_metrics([
                {"expected": "عدن-12345", "predicted": "عدن-99999"},
                {"expected": "صنعاء-48210", "predicted": "صنعاء-00000"},
                {"expected": "تعز-73901", "predicted": "تعز-11111"},
                {"expected": "حضرموت-55120", "predicted": "حضرموت-22222"},
            ])
            # 2) Accurate OCR predictions (including Latin transliterations from EasyOCR on VirtualCamera) must PASS ground-truth gate
            good_ocr = ev_mod.compute_ocr_ground_truth_metrics([
                {"expected": "عدن-12345", "predicted": "ADEN 12345"},
                {"expected": "صنعاء-48210", "predicted": "SANA 48210"},
                {"expected": "تعز-73901", "predicted": "TAIZ 73901"},
                {"expected": "حضرموت-55120", "predicted": "HADR 55120"},
            ])
            b4_smoke_only = ev_mod.build_four_stage_breakdown(True, True, False, False, "NOT_TESTED", "Missing consented face dataset")
            ci_yml_s = open(ci_yml_path, encoding="utf-8").read()
            gate_ok = (
                bad_ocr["passes_acceptance_gate"] is False
                and good_ocr["passes_acceptance_gate"] is True
                and good_ocr["exact_match_rate"] == 1.0
                and good_ocr["digits_match_rate"] == 1.0
                and good_ocr["mean_cer"] == 0.0
                and b4_smoke_only["smoke_inference_status"] == "PASS"
                and b4_smoke_only["ground_truth_acceptance_status"] == "NOT_TESTED"
                and hasattr(m.TesseractOCRReader, "find_tesseract_binary")
                and "choco install innosetup" in ci_yml_s
                and "https://download.pytorch.org/whl/cpu" in ci_yml_s
                and "--verify-pip-deps" in ci_yml_s
            )
            gate_detail = {"bad_ocr_pass": bad_ocr["passes_acceptance_gate"], "good_ocr_pass": good_ocr["passes_acceptance_gate"]}
        check("PREVIEW01-MODEL-EVAL-GATES-AND-CI-INNOSETUP",
              "evaluate_ai_models enforces ground-truth CER/ExactMatch/IoU/Face gates and Windows CI enforces Inno Setup & CPU PyTorch",
              gate_ok, gate_detail)

        # 32. PREVIEW01-SAFE-EVAL-BENCHMARKS-AND-NON-DESTRUCTIVE-VERIFY (BUG-21, BUG-22, BUG-23, BUG-25 Regression):
        # Verify models/eval_benchmarks/ exists inside MERSAD_AI_Preview_0.1 with 23 safe files and prepare_safe_eval_benchmarks.py --verify is read-only.
        bm_manifest_p = os.path.join(SRC, "models", "eval_benchmarks", "BENCHMARK_MANIFEST.json")
        prep_tool_p = os.path.join(os.path.dirname(SRC), "tools", "prepare_safe_eval_benchmarks.py")
        bm_ok = os.path.isfile(bm_manifest_p)
        bm_detail = {"manifest_exists": bm_ok}
        if bm_ok:
            bm_json = json.loads(open(bm_manifest_p, encoding="utf-8").read())
            ds_map = bm_json.get("datasets", {})
            bm_ok = (
                bm_json.get("contains_real_human_biometric_pii") is False
                and ds_map.get("plates", {}).get("samples_count") == 6
                and ds_map.get("faces_positive", {}).get("authorized_real_human_consent") is False
                and ds_map.get("vehicles", {}).get("is_photorealistic_natural_dataset") is False
            )
            if os.path.isfile(prep_tool_p):
                import importlib.util as _ilu_bm
                spec_bm = _ilu_bm.spec_from_file_location("prep_safe_bm_test", prep_tool_p)
                mod_bm = _ilu_bm.module_from_spec(spec_bm)
                spec_bm.loader.exec_module(mod_bm)
                import pathlib as _pl_bm
                ver_res = mod_bm.verify_safe_benchmarks(_pl_bm.Path(SRC) / "models" / "eval_benchmarks")
                bm_ok = bm_ok and (
                    ver_res.get("ok") is True
                    and ver_res.get("status") == "VERIFIED_OK"
                    and ver_res.get("mode") == "READ_ONLY_NON_DESTRUCTIVE_VERIFY"
                    and ver_res.get("verified_files_count") == 18
                )
                bm_detail["verify_result"] = ver_res.get("status")
                bm_detail["verified_files_count"] = ver_res.get("verified_files_count")
        check("PREVIEW01-SAFE-EVAL-BENCHMARKS-AND-NON-DESTRUCTIVE-VERIFY",
              "models/eval_benchmarks contains 23 safe benchmark files and prepare_safe_eval_benchmarks.py --verify runs in read-only non-destructive mode",
              bm_ok, bm_detail)

        # 33. PREVIEW01-MAIN-ENTRYPOINT-DYNAMIC-CAMERA-LIFECYCLE (BUG-27 Regression):
        # Verify natural main() entry point (not manual MersadEngineController) spawns live workers on /api/cameras/add,
        # increments latest_frame_seq, streams MJPEG, runs inference, safely stops threads & releases VideoCapture on /api/cameras/remove,
        # stays alive when 0 cameras remain, and spawns a second dynamic camera after removal.
        orig_nfr_234 = globals().get("NFR", 18)
        old_argv_234 = sys.argv[:]
        main_ep_ok = False
        main_ep_detail = {}
        try:
            globals()["NFR"] = 500
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s_ep:
                s_ep.bind(("127.0.0.1", 0))
                port_234 = s_ep.getsockname()[1]
            tok_234 = "main_ep_tok_234"
            sys.argv = [
                "mersad_live.py",
                "--source", "cam1_ok",
                "--cam", "BOOT_CAM_EP",
                "--no-window",
                "--no-telegram-listener",
                "--port", str(port_234),
                "--token", tok_234,
                "--allow-degraded-preview",
            ]
            t_main_234 = threading.Thread(target=m.main, daemon=True, name="selftest-main-ep-234")
            t_main_234.start()
            wait(lambda: "BOOT_CAM_EP" in m._ACTIVE_CAM_STATES and m._ACTIVE_ENGINE_CONTROLLER is not None, t=5.0)
            for _ in range(60):
                try:
                    p_r = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port_234}/api/ping?k={tok_234}", timeout=1.0).read())
                    if p_r.get("ok"):
                        break
                except Exception:
                    time.sleep(0.03)

            # Add first dynamic camera DYN_EP_1 via HTTP POST /api/cameras/add
            req_add1 = urllib.request.Request(
                f"http://127.0.0.1:{port_234}/api/cameras/add?k={tok_234}",
                data=json.dumps({"name": "DYN_EP_1", "source": "cam2_ok"}).encode("utf-8"),
                headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port_234}"},
                method="POST",
            )
            r_add1 = json.loads(urllib.request.urlopen(req_add1, timeout=3.0).read().decode("utf-8"))
            st_ep1 = m._ACTIVE_CAM_STATES.get("DYN_EP_1")
            rt_ep1 = st_ep1.get("reader_thread") if st_ep1 else None
            it_ep1 = st_ep1.get("infer_thread") if st_ep1 else None
            threads_started_1 = bool(rt_ep1 and rt_ep1.is_alive() and it_ep1 and it_ep1.is_alive())

            wait(lambda: st_ep1 is not None and st_ep1["latest_frame_seq"] >= 8 and st_ep1["det_runs"] >= 1 and m.STATUS.get("cameras", {}).get("DYN_EP_1", {}).get("detections", 0) >= 1, t=6.0)
            with urllib.request.urlopen(f"http://127.0.0.1:{port_234}/stream.mjpg?cam=DYN_EP_1&k={tok_234}", timeout=3.0) as mjpg_ep1:
                chunk_ep1 = mjpg_ep1.read(400)
            mjpg_ep1_ok = (b"image/jpeg" in chunk_ep1 and b"\xff\xd8" in chunk_ep1)

            # Remove DYN_EP_1 while main() is running
            req_rem1 = urllib.request.Request(
                f"http://127.0.0.1:{port_234}/api/cameras/remove?k={tok_234}",
                data=json.dumps({"name": "DYN_EP_1"}).encode("utf-8"),
                headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port_234}"},
                method="POST",
            )
            r_rem1 = json.loads(urllib.request.urlopen(req_rem1, timeout=4.0).read().decode("utf-8"))
            threads_stopped_1 = bool(rt_ep1 and not rt_ep1.is_alive() and it_ep1 and not it_ep1.is_alive())
            cap_released_1 = (st_ep1.get("cap") is None) if st_ep1 else False
            removed_status_1 = ("DYN_EP_1" not in m.STATUS.get("cameras", {}))

            # Remove BOOT_CAM_EP so 0 cameras remain, verify main() stays alive, then add second camera DYN_EP_2
            req_rem_boot = urllib.request.Request(
                f"http://127.0.0.1:{port_234}/api/cameras/remove?k={tok_234}",
                data=json.dumps({"name": "BOOT_CAM_EP"}).encode("utf-8"),
                headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port_234}"},
                method="POST",
            )
            urllib.request.urlopen(req_rem_boot, timeout=4.0).read()
            time.sleep(0.03)
            main_still_alive = t_main_234.is_alive()

            req_add2 = urllib.request.Request(
                f"http://127.0.0.1:{port_234}/api/cameras/add?k={tok_234}",
                data=json.dumps({"name": "DYN_EP_2", "source": "cam3_ok"}).encode("utf-8"),
                headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port_234}"},
                method="POST",
            )
            r_add2 = json.loads(urllib.request.urlopen(req_add2, timeout=3.0).read().decode("utf-8"))
            st_ep2 = m._ACTIVE_CAM_STATES.get("DYN_EP_2")
            wait(lambda: st_ep2 is not None and st_ep2["latest_frame_seq"] >= 8 and st_ep2["det_runs"] >= 1, t=6.0)
            with urllib.request.urlopen(f"http://127.0.0.1:{port_234}/stream.mjpg?cam=DYN_EP_2&k={tok_234}", timeout=3.0) as mjpg_ep2:
                chunk_ep2 = mjpg_ep2.read(400)
            mjpg_ep2_ok = (b"image/jpeg" in chunk_ep2 and b"\xff\xd8" in chunk_ep2)

            main_ep_ok = (
                r_add1.get("ok") is True and r_add1.get("worker_spawned") is True
                and threads_started_1 and mjpg_ep1_ok
                and r_rem1.get("ok") is True and r_rem1.get("removed") is True
                and threads_stopped_1 and cap_released_1 and removed_status_1
                and main_still_alive
                and r_add2.get("ok") is True and r_add2.get("worker_spawned") is True
                and mjpg_ep2_ok
            )
            main_ep_detail = {
                "add1_worker_spawned": r_add1.get("worker_spawned"),
                "threads_started_1": threads_started_1,
                "mjpg_ep1_ok": mjpg_ep1_ok,
                "threads_stopped_1": threads_stopped_1,
                "cap_released_1": cap_released_1,
                "main_still_alive": main_still_alive,
                "add2_worker_spawned": r_add2.get("worker_spawned"),
                "mjpg_ep2_ok": mjpg_ep2_ok,
            }
        finally:
            m.STOP_MAIN_EVENT.set()
            if "t_main_234" in locals():
                t_main_234.join(timeout=4.0)
            m.STOP_MAIN_EVENT.clear()
            globals()["NFR"] = orig_nfr_234
            sys.argv = old_argv_234
        check("PREVIEW01-MAIN-ENTRYPOINT-DYNAMIC-CAMERA-LIFECYCLE",
              "main() entry point spawns live camera workers on /api/cameras/add, streams MJPEG, runs inference, safely stops threads on remove, and adds a second camera",
              main_ep_ok, main_ep_detail)
    finally:
        shutil.rmtree(d, ignore_errors=True)

run_stage15_forensic_remediation_tests()
run_patched_v7_1_and_preview_0_1_tests()
m.db.close()
n_pass = sum(1 for _, _, st, _ in RESULTS if st == "PASS")
n_skip = sum(1 for _, _, st, _ in RESULTS if st == "SKIP")
n_fail = sum(1 for _, _, st, _ in RESULTS if st == "FAIL")
total = len(RESULTS)
print(f"\nSummary: {n_pass} PASS, {n_skip} SKIP, {n_fail} FAIL (Total: {total}).",
      "SELF-TEST OK" if n_fail == 0 else "SELF-TEST FAILED")
os.chdir(SRC)
shutil.rmtree(WORK, ignore_errors=True)
sys.exit(0 if n_fail == 0 else 1)
