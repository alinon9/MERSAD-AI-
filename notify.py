"""Telegram alerts on the phone: photo + text + tappable decision buttons (standard library only).
Env: TELEGRAM_TOKEN (from @BotFather) | TELEGRAM_CHAT_ID (operations room) | TELEGRAM_PATROL_CHAT_ID (patrol group)
     TELEGRAM_ALLOWED_USERS (optional comma-separated user IDs) | TELEGRAM_API (optional, used by self-test).
Never logs or exposes TELEGRAM_TOKEN or RTSP passwords in errors or logs.
Enforces single-owner OS lock on getUpdates listener so multiple processes never compete on the same bot token.
Records outcome metadata (ok / uncertain timeout / error) in LAST_SEND_OUTCOMES for P0-B dispatch lease recovery."""
import hashlib, json, logging, os, re, socket, threading, time, urllib.error, urllib.request, uuid

try:
    import fcntl
except ImportError:
    fcntl = None
try:
    import msvcrt
except ImportError:
    msvcrt = None

log = logging.getLogger("mersad.notify")
_SENT_LOCK = threading.Lock()
_SENT_KEYS = set()                                   # in-process idempotency cache
LAST_SEND_OUTCOMES = {}                              # key -> {"ok": bool, "uncertain": bool, "error": str, "ts": float}
TELEGRAM_STATUS = {"connected": True, "last_ok_ts": 0.0, "last_error": "", "consecutive_failures": 0}
_LISTENER_LOCK_FD = None
_LISTENER_THREAD = None
_LISTENER_DONE = threading.Event()
_LISTENER_DONE.set()


def _redact(msg):
    """Ensure TELEGRAM_TOKEN and RTSP/HTTP credentials are never leaked in exception strings or logs."""
    s = str(msg or "")
    tok = os.getenv("TELEGRAM_TOKEN", "")
    if tok:
        s = s.replace(tok, "<REDACTED_TOKEN>")
    s = re.sub(r"/bot[^/\s]+/", "/bot<REDACTED_TOKEN>/", s)
    s = re.sub(r"((?:rtsp|rtsps|http|https)://[^:/\s]+:)[^@/\s]+(@)", r"\1***\2", s, flags=re.IGNORECASE)
    return s


def _is_timeout_error(err):
    if isinstance(err, (TimeoutError, socket.timeout)):
        return True
    if isinstance(err, urllib.error.URLError) and isinstance(getattr(err, "reason", None), (TimeoutError, socket.timeout)):
        return True
    s = str(err or "").lower()
    return "timed out" in s or "timeout" in s


def multipart(fields, files=None):
    b = uuid.uuid4().hex; body = b""
    for k, v in fields.items():
        body += f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode("utf-8")
    for k, (fn, data) in (files or {}).items():
        body += (f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{fn}"\r\n'
                 f'Content-Type: image/jpeg\r\n\r\n').encode("utf-8") + data + b"\r\n"
    return body + f"--{b}--\r\n".encode("utf-8"), f"multipart/form-data; boundary={b}"


class UncertainDeliveryError(RuntimeError):
    """Raised when an HTTP POST timed out after transmission, leaving external delivery outcome uncertain (P0-B)."""
    pass


def _call(method, fields=None, files=None, timeout=15, retries=2):
    tok = os.getenv("TELEGRAM_TOKEN", "").strip()
    if not tok:
        raise RuntimeError("TELEGRAM_TOKEN is not configured")
    body, ct = multipart(fields or {}, files)
    url = f"{os.getenv('TELEGRAM_API', 'https://api.telegram.org').rstrip('/')}/bot{tok}/{method}"
    last_err = None
    timed_out = False
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, body, {"Content-Type": ct})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            res = json.loads(raw)
            if not res.get("ok", True):
                raise RuntimeError(res.get("description", "Telegram API returned ok=false"))
            TELEGRAM_STATUS["connected"] = True
            TELEGRAM_STATUS["last_ok_ts"] = time.time()
            TELEGRAM_STATUS["last_error"] = ""
            TELEGRAM_STATUS["consecutive_failures"] = 0
            return res
        except urllib.error.HTTPError as he:
            last_err = he
            if he.code == 429 and attempt < retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            break
        except Exception as e:
            last_err = e
            if _is_timeout_error(e):
                timed_out = True
                # Do not blindly re-POST on a read timeout because the server may have already processed the POST!
                break
            if attempt < retries:
                time.sleep(0.3 * (attempt + 1))
                continue
            break
    err_str = _redact(last_err)
    TELEGRAM_STATUS["connected"] = False
    TELEGRAM_STATUS["last_error"] = err_str
    TELEGRAM_STATUS["consecutive_failures"] = TELEGRAM_STATUS.get("consecutive_failures", 0) + 1
    if timed_out:
        raise UncertainDeliveryError(f"UNCERTAIN_TIMEOUT: {err_str}")
    raise RuntimeError(err_str)


def send_alert(text, photo=None, chat_env="TELEGRAM_CHAT_ID", buttons=None, sync=False, idempotency_key=None, timeout=10, retries=1, on_done=None):
    """Send Telegram message/photo.
    - If sync=True, executes synchronously and returns True ONLY if Telegram confirmed receipt (HTTP 200 ok=true).
    - Records detailed outcome in LAST_SEND_OUTCOMES[dedup_key] including 'uncertain': True if a timeout occurred.
    - Note on delivery semantics: Telegram Bot API does not support client-supplied idempotency keys, so external
      network timeouts after request transmission have uncertain outcome and are flagged as 'uncertain' rather than 'sent'."""
    chat = (os.getenv(chat_env) or "").strip()
    tok = (os.getenv("TELEGRAM_TOKEN") or "").strip()
    dedup_key = idempotency_key or hashlib.sha256(f"{chat}|{text}|{photo or ''}".encode("utf-8")).hexdigest()[:20]
    if not (tok and chat):
        outcome = {"ok": False, "uncertain": False, "error": "not_configured", "ts": time.time()}
        with _SENT_LOCK:
            LAST_SEND_OUTCOMES[dedup_key] = outcome
            LAST_SEND_OUTCOMES["__last__"] = outcome
        if on_done:
            try: on_done(False, "not_configured")
            except Exception: pass
        return False

    with _SENT_LOCK:
        if idempotency_key and dedup_key in _SENT_KEYS:
            outcome = {"ok": True, "uncertain": False, "error": "", "ts": time.time(), "deduplicated": True}
            LAST_SEND_OUTCOMES[dedup_key] = outcome
            LAST_SEND_OUTCOMES["__last__"] = outcome
            if on_done:
                try: on_done(True, "")
                except Exception: pass
            return True

    def _send_now():
        try:
            f = {"chat_id": chat}
            if buttons:
                f["reply_markup"] = json.dumps(
                    {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in buttons]},
                    ensure_ascii=False
                )
            if photo and os.path.exists(photo):
                with open(photo, "rb") as pf:
                    pdata = pf.read()
                f["caption"] = text[:1000]
                _call("sendPhoto", f, {"photo": (os.path.basename(photo), pdata)}, timeout=timeout, retries=retries)
            else:
                f["text"] = text
                _call("sendMessage", f, timeout=timeout, retries=retries)
            outcome = {"ok": True, "uncertain": False, "error": "", "ts": time.time()}
            with _SENT_LOCK:
                _SENT_KEYS.add(dedup_key)
                if len(_SENT_KEYS) > 2000:
                    _SENT_KEYS.clear()
                LAST_SEND_OUTCOMES[dedup_key] = outcome
                LAST_SEND_OUTCOMES["__last__"] = outcome
            if on_done:
                try: on_done(True, "")
                except Exception: pass
            return True
        except Exception as e:
            msg = _redact(e)
            is_uncertain = isinstance(e, UncertainDeliveryError) or _is_timeout_error(e)
            outcome = {"ok": False, "uncertain": is_uncertain, "error": msg, "ts": time.time()}
            with _SENT_LOCK:
                LAST_SEND_OUTCOMES[dedup_key] = outcome
                LAST_SEND_OUTCOMES["__last__"] = outcome
            log.warning("Telegram send failed (%s, uncertain=%s): %s", chat_env, is_uncertain, msg)
            print("Telegram failed:", msg)
            if on_done:
                try: on_done(False, msg)
                except Exception: pass
            return False

    if sync:
        return _send_now()
    threading.Thread(target=_send_now, daemon=True).start()
    return True


def _acquire_listener_lock():
    # Acquire one process-wide Telegram polling owner lock.
    global _LISTENER_LOCK_FD
    tok_hash = hashlib.sha256((os.getenv("TELEGRAM_TOKEN") or "").encode("utf-8")).hexdigest()[:16]
    if os.name == "nt":
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateSemaphoreW.argtypes = [ctypes.c_void_p, ctypes.c_long, ctypes.c_long, ctypes.c_wchar_p]
        kernel32.CreateSemaphoreW.restype = ctypes.c_void_p
        kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel32.WaitForSingleObject.restype = ctypes.c_ulong
        kernel32.ReleaseSemaphore.argtypes = [ctypes.c_void_p, ctypes.c_long, ctypes.c_void_p]
        kernel32.ReleaseSemaphore.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        name = "Local\\MERSAD_TG_LISTENER_" + tok_hash
        handle = kernel32.CreateSemaphoreW(None, 1, 1, name)
        if not handle:
            log.warning("Unable to create Telegram listener semaphore (WinError %s)", ctypes.get_last_error())
            return None
        wait_result = kernel32.WaitForSingleObject(handle, 0)
        if wait_result != 0:  # WAIT_OBJECT_0: exclusive ownership acquired
            kernel32.CloseHandle(handle)
            return None
        lock = ("windows_semaphore", handle, kernel32)
        _LISTENER_LOCK_FD = lock
        return lock

    base_dir = os.environ.get("MERSAD_DATA_DIR") or os.getcwd()
    lock_path = os.path.join(base_dir, f".tg_listener_{tok_hash[:8]}.lock")
    fd = None
    try:
        fd = open(lock_path, "a+b")
        if fcntl is not None:
            fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        elif msvcrt is not None:
            fd.seek(0, os.SEEK_END)
            if fd.tell() == 0:
                fd.write(bytes([0]))
                fd.flush()
            fd.seek(0)
            msvcrt.locking(fd.fileno(), msvcrt.LK_NBLCK, 1)
        _LISTENER_LOCK_FD = fd
        return fd
    except (OSError, IOError):
        try:
            if fd is not None:
                fd.close()
        except Exception:
            pass
        return None


def _release_listener_lock(fd):
    # Release the named mutex or POSIX/CRT file lock.
    global _LISTENER_LOCK_FD
    if fd is None:
        return
    if isinstance(fd, tuple) and len(fd) == 3 and fd[0] == "windows_semaphore":
        _, handle, kernel32 = fd
        try:
            import ctypes
            kernel32.ReleaseSemaphore(handle, 1, None)
        except Exception:
            pass
        try:
            kernel32.CloseHandle(handle)
        except Exception:
            pass
        if _LISTENER_LOCK_FD is fd:
            _LISTENER_LOCK_FD = None
        return
    try:
        if fcntl is not None:
            fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
        elif msvcrt is not None:
            fd.seek(0)
            msvcrt.locking(fd.fileno(), msvcrt.LK_UNLCK, 1)
    except Exception:
        pass
    try:
        fd.close()
    except Exception:
        pass
    if _LISTENER_LOCK_FD is fd:
        _LISTENER_LOCK_FD = None


def start_listener(on_press, stop_event=None):
    """Listen for button presses; only the lock owner polls getUpdates."""
    global _LISTENER_THREAD
    chat = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    tok = (os.getenv("TELEGRAM_TOKEN") or "").strip()
    if not (tok and chat):
        return False

    lock_fd = _acquire_listener_lock()
    if lock_fd is None:
        log.info("Telegram listener is already owned by another running process; skipping duplicate getUpdates polling.")
        return False

    def loop():
        off = 0
        try:
            while not (stop_event and stop_event.is_set()):
                try:
                    r = _call(
                        "getUpdates",
                        {"offset": off, "timeout": 15, "allowed_updates": json.dumps(["callback_query"])},
                        timeout=20,
                        retries=0
                    )
                    allowed_users = {
                        u.strip() for u in (os.getenv("TELEGRAM_ALLOWED_USERS") or "").split(",") if u.strip()
                    }
                    for u in r.get("result", []):
                        off = u["update_id"] + 1
                        cb = u.get("callback_query")
                        if not cb:
                            continue
                        msg = cb.get("message") or {}
                        uid = str((cb.get("from") or {}).get("id", ""))
                        if str(msg.get("chat", {}).get("id")) != str(chat) or (allowed_users and uid not in allowed_users):
                            try: _call("answerCallbackQuery", {"callback_query_id": cb["id"], "text": "غير مصرّح لك بالقرار"}, timeout=5, retries=0)
                            except Exception: pass
                            continue
                        reply = on_press(cb.get("data", ""), "tg:" + uid)
                        try:
                            _call("answerCallbackQuery", {"callback_query_id": cb["id"], "text": reply}, timeout=5, retries=0)
                        except Exception as e:
                            log.debug("answerCallbackQuery failed: %s", _redact(e))
                        if msg.get("message_id") is not None:
                            try:
                                _call(
                                    "editMessageReplyMarkup",
                                    {"chat_id": chat, "message_id": msg["message_id"], "reply_markup": json.dumps({"inline_keyboard": []})},
                                    timeout=5,
                                    retries=0
                                )
                            except Exception as e:
                                log.debug("editMessageReplyMarkup failed: %s", _redact(e))
                except Exception as e:
                    log.debug("Listener poll error: %s", _redact(e))
                    time.sleep(2)
        finally:
            _release_listener_lock(lock_fd)
            _LISTENER_DONE.set()

    _LISTENER_DONE.clear()
    _LISTENER_THREAD = threading.Thread(target=loop, daemon=True, name="mersad_telegram_listener")
    _LISTENER_THREAD.start()
    return True


def wait_listener_stopped(timeout=3.0):
    """Wait for the Telegram polling worker to observe shutdown and release its OS lock."""
    thread = _LISTENER_THREAD
    if thread is None or thread is threading.current_thread():
        return True
    thread.join(timeout=max(0.0, float(timeout)))
    return not thread.is_alive()
