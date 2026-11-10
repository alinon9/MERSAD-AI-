"""Vehicle & person registry + numbered SQLite schema migrations + re-entrant inter-process lock helper.
Faces are NOT imported: a person's face can only be enrolled live from the camera, and only if
the person's record says they consented.
Round 4 upgrades:
- P0-A: Strict person identity isolation via internal person_id (persons.id) across enrollment, consent revocation,
  status updates, deletion, and known-face loading, plus safe migration/quarantine of legacy ambiguous faces.
- P1-D: Removal of static fallback HMAC key, atomic secret/key file writing with 0600 permissions from creation,
  and explicit refusal to silently overwrite corrupt/truncated HMAC keys."""
import contextlib, csv, errno, hashlib, hmac, io, logging, os, re, secrets, shutil, sqlite3, stat, subprocess, threading, time

try:
    import fcntl
except ImportError:
    fcntl = None
try:
    import msvcrt
except ImportError:
    msvcrt = None

VSTAT = {"normal": "عادية", "watch": "مراقبة", "wanted": "مطلوبة", "stolen": "مسروقة", "expired": "منتهية الترخيص"}
KW_V = {"watch": ["مراقب", "watch"], "wanted": ["مطلوب", "wanted"], "stolen": ["مسروق", "stolen"],
        "expired": ["منتهي", "expired"], "normal": ["عادي", "normal"]}
KW_P = {"watch": ["مراقب", "watch"], "normal": ["عادي", "normal"]}
KW_T = {"truck": ["شاحن", "truck", "لوري"], "bus": ["حاف", "bus", "باص"],
        "motorcycle": ["دراج", "motor"], "car": ["سيار", "car"]}
D = {}                                               # db, lock, log, refresh, db_path (set by init)
DIG = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
AR_NORM = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي", "ـ": ""})
OCR_DIGIT_CONFUSIONS = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "|": "1", "S": "5", "s": "5", "B": "8", "Z": "2"})
hkey = lambda h: re.sub(r"[\s()_\-:/]", "", str(h or "")).lower()
_HMAC_KEY_CACHE = {}
_HMAC_KEY_CACHE_META = {}
_HMAC_KEY_LOCK = threading.RLock()
_IPC_RLOCK = threading.RLock()
_IPC_STATE = {"depth": 0, "fd": None}

# MERSAD_WINDOWS_PRIVATE_ACL_HELPERS
def _ensure_lock_byte(fd):
    """Ensure a lock file has one byte, using a raw OS file descriptor."""
    if os.lseek(fd, 0, os.SEEK_END) == 0:
        os.write(fd, b"\0")
        os.fsync(fd)
    os.lseek(fd, 0, os.SEEK_SET)


def _ensure_windows_lock_byte(fd):
    return _ensure_lock_byte(fd)


def _acquire_windows_byte_lock(fd, timeout_sec=60.0, poll_interval=0.025):
    """
    Acquire the one-byte Windows inter-process lock without msvcrt's fixed
    LK_LOCK retry limit (which raises EDEADLK after about ten attempts).
    LK_NBLCK makes one non-blocking attempt; retry only recognized lock-
    contention errors until the bounded deadline expires.
    """
    if msvcrt is None:
        return

    deadline = time.monotonic() + max(0.1, float(timeout_sec))
    contention_errnos = {
        errno.EACCES,
        errno.EAGAIN,
        errno.EDEADLK,
        getattr(errno, "EDEADLOCK", errno.EDEADLK),
    }
    contention_winerrors = {32, 33}  # ERROR_SHARING_VIOLATION / ERROR_LOCK_VIOLATION

    while True:
        # msvcrt.locking operates on the byte range beginning at the current
        # file position. Reset it before every attempt.
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return
        except OSError as exc:
            if exc.errno not in contention_errnos and getattr(exc, "winerror", None) not in contention_winerrors:
                raise

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"Timed out after {timeout_sec:.1f}s waiting for Windows database lock"
                ) from exc
            time.sleep(min(max(0.001, float(poll_interval)), remaining))



def _acquire_windows_db_mutex(db_path, timeout_sec=60.0):
    """Acquire a named Win32 mutex for the SQLite database path.

    A kernel mutex is process-safe, automatically becomes available if its
    owner crashes, and avoids CRT byte-range-lock retry/descriptor edge cases
    on Windows. WAIT_ABANDONED still grants ownership and is safe to recover.
    """
    import ctypes

    canonical_path = os.path.normcase(os.path.abspath(str(db_path))).casefold()
    digest = hashlib.sha256(canonical_path.encode("utf-8")).hexdigest()[:32]
    mutex_name = "Local\\MERSAD_DB_LOCK_" + digest

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel32.WaitForSingleObject.restype = ctypes.c_ulong
    kernel32.ReleaseMutex.argtypes = [ctypes.c_void_p]
    kernel32.ReleaseMutex.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int

    handle = kernel32.CreateMutexW(None, 0, mutex_name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())

    wait_ms = max(1, min(int(max(0.1, float(timeout_sec)) * 1000), 0xFFFFFFFE))
    result = int(kernel32.WaitForSingleObject(handle, wait_ms))
    if result in (0x00000000, 0x00000080):  # WAIT_OBJECT_0 / WAIT_ABANDONED
        return ("windows_mutex", handle, kernel32)

    error_code = ctypes.get_last_error()
    try:
        kernel32.CloseHandle(handle)
    except Exception:
        pass
    if result == 0x00000102:  # WAIT_TIMEOUT
        raise TimeoutError(
            f"Timed out after {timeout_sec:.1f}s waiting for Windows database mutex"
        )
    if result == 0xFFFFFFFF:  # WAIT_FAILED
        raise ctypes.WinError(error_code)
    raise OSError(f"Unexpected WaitForSingleObject result: 0x{result:08X}")


def _release_windows_db_mutex(lock_handle):
    """Release and close a named Win32 database mutex acquired by this thread."""
    if not (isinstance(lock_handle, tuple) and len(lock_handle) == 3
            and lock_handle[0] == "windows_mutex"):
        return
    _, handle, kernel32 = lock_handle
    try:
        if not kernel32.ReleaseMutex(handle):
            import ctypes
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel32.CloseHandle(handle)


def _is_network_filesystem_path(path):
    """Recognize Windows UNC and mapped remote-drive paths before selecting SQLite journaling."""
    raw = str(path or "")
    normalized = raw.replace("/", "\\")
    if normalized.startswith("\\\\") or normalized.lower().startswith("\\\\?\\unc\\"):
        return True
    if os.name == "nt" and raw:
        try:
            import ctypes
            drive, _ = os.path.splitdrive(os.path.abspath(raw))
            if drive:
                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel32.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
                kernel32.GetDriveTypeW.restype = ctypes.c_uint
                return int(kernel32.GetDriveTypeW(drive + "\\")) == 4  # DRIVE_REMOTE
        except Exception:
            return False
    return False


def configure_sqlite_journal_mode(db, db_path=None):
    """Prefer WAL, but fall back to DELETE if a filesystem cannot support WAL/shared-memory files."""
    path = db_path or D.get("db_path")
    if not path:
        try:
            rows = db.execute("PRAGMA database_list").fetchall()
            path = next((str(row[2]) for row in rows if str(row[1]) == "main"), "")
        except Exception:
            path = ""
    current = str(db.execute("PRAGMA journal_mode").fetchone()[0]).lower()
    if not path or path == ":memory:" or "mode=memory" in str(path).lower():
        return current

    if _is_network_filesystem_path(path):
        try:
            row = db.execute("PRAGMA journal_mode=DELETE").fetchone()
            mode = str(row[0]).lower() if row else ""
            if mode != "delete":
                raise sqlite3.OperationalError(f"SQLite refused DELETE journal mode on network path (returned {mode or 'unknown'})")
            logging.getLogger("mersad.registry").warning(
                "Network database path detected; using SQLite DELETE journal mode instead of WAL: %s", str(path)[:240]
            )
            return mode
        except sqlite3.OperationalError as exc:
            raise sqlite3.OperationalError(
                f"SQLite cannot establish DELETE journal mode on network path {path!r}; "
                "use a local disk for MERSAD_AI data. " + str(exc)
            ) from exc

    wal_error = None
    try:
        row = db.execute("PRAGMA journal_mode=WAL").fetchone()
        mode = str(row[0]).lower() if row else ""
        if mode == "wal":
            return mode
        wal_error = RuntimeError(f"SQLite returned journal mode {mode or 'unknown'} instead of WAL")
    except sqlite3.OperationalError as exc:
        wal_error = exc

    try:
        row = db.execute("PRAGMA journal_mode=DELETE").fetchone()
        mode = str(row[0]).lower() if row else ""
        if mode != "delete":
            raise sqlite3.OperationalError(f"SQLite refused DELETE journal mode (returned {mode or 'unknown'})")
        logging.getLogger("mersad.registry").warning(
            "SQLite WAL is unavailable for database path; falling back to DELETE journal mode: %s",
            str(wal_error)[:240],
        )
        return mode
    except sqlite3.OperationalError as delete_error:
        raise sqlite3.OperationalError(
            "Unable to initialize SQLite journaling: WAL failed and DELETE fallback failed. "
            f"WAL error={wal_error}; DELETE error={delete_error}"
        ) from delete_error


def _windows_current_user_sid():
    if os.name != "nt":
        return None
    try:
        whoami_bin = shutil.which("whoami.exe")
        if not whoami_bin:
            sys_root = os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\Windows"
            cand_w = os.path.join(sys_root, "System32", "whoami.exe")
            whoami_bin = cand_w if os.path.isfile(cand_w) else "whoami.exe"
        proc = subprocess.run(
            [whoami_bin, "/user", "/fo", "csv", "/nh"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=10, check=False,
        )
        if proc.returncode != 0:
            raise OSError((proc.stderr or proc.stdout or "whoami failed").strip())
        match = re.search(r"\bS-1-(?:\d+-){1,}\d+\b", proc.stdout)
        if not match:
            raise OSError("Could not determine current Windows user SID")
        return match.group(0)
    except Exception as exc:
        raise OSError(f"Cannot determine Windows user SID: {exc}") from exc


def _windows_acl_script(check_only=False, is_dir=False):
    if check_only:
        return r"""
$ErrorActionPreference = 'Stop'
Import-Module Microsoft.PowerShell.Security -ErrorAction Stop
$p = $env:MERSAD_ACL_PATH
$acl = Get-Acl -LiteralPath $p
if (-not $acl.AreAccessRulesProtected) { exit 21 }
$cur = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$allowed = @($cur, 'S-1-5-18', 'S-1-5-32-544')
$rules = $acl.GetAccessRules($true, $false, [System.Security.Principal.SecurityIdentifier])
$currentAllow = $false
foreach ($r in $rules) {
    $sid = $r.IdentityReference.Value
    if ($sid -eq $cur -and $r.AccessControlType -eq [System.Security.AccessControl.AccessControlType]::Allow) { $currentAllow = $true }
    if ($r.AccessControlType -eq [System.Security.AccessControl.AccessControlType]::Allow -and $sid -notin $allowed) { exit 22 }
}
if (-not $currentAllow) { exit 23 }
exit 0
"""
    dir_flag = "$true" if is_dir else "$false"
    return r"""
$ErrorActionPreference = 'Stop'
Import-Module Microsoft.PowerShell.Security -ErrorAction Stop
$p = $env:MERSAD_ACL_PATH
$isDir = """ + dir_flag + r"""
$current = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
if ($null -eq $current) { throw 'Cannot resolve current user SID' }
$acl = Get-Acl -LiteralPath $p
$acl.SetAccessRuleProtection($true, $false)
foreach ($rule in @($acl.Access)) { [void]$acl.RemoveAccessRuleSpecific($rule) }
$acl.SetOwner($current)
$inheritance = [System.Security.AccessControl.InheritanceFlags]::None
if ($isDir) { $inheritance = [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [System.Security.AccessControl.InheritanceFlags]::ObjectInherit }
$propagation = [System.Security.AccessControl.PropagationFlags]::None
$rights = [System.Security.AccessControl.FileSystemRights]::FullControl
$allow = [System.Security.AccessControl.AccessControlType]::Allow
$principals = @($current.Value, 'S-1-5-18', 'S-1-5-32-544')
foreach ($sidText in $principals) {
  $sid = [System.Security.Principal.SecurityIdentifier]::new($sidText)
  $rule = [System.Security.AccessControl.FileSystemAccessRule]::new($sid, $rights, $inheritance, $propagation, $allow)
  [void]$acl.AddAccessRule($rule)
}
Set-Acl -LiteralPath $p -AclObject $acl
"""


def _windows_acl_call(path, script):
    env = dict(os.environ)
    env["MERSAD_ACL_PATH"] = os.path.abspath(path)
    powershell = shutil.which("pwsh.exe") or shutil.which("powershell.exe")
    if not powershell:
        sys_root = os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\Windows"
        for cand_ps in (
            os.path.join(sys_root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe"),
            os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "PowerShell", "7", "pwsh.exe"),
        ):
            if os.path.isfile(cand_ps):
                powershell = cand_ps
                break
    if not powershell:
        raise OSError("PowerShell is required to secure Windows secret-file ACLs")
    proc = subprocess.run(
        [powershell, "-NoLogo", "-NoProfile", "-NonInteractive",
         "-ExecutionPolicy", "Bypass", "-Command", script],
        env=env, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=20, check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or f"exit code {proc.returncode}").strip()
        raise OSError(f"Windows ACL operation failed for {path}: {detail[-500:]}")
    return True


def _set_windows_private_acl(path, is_dir=False):
    if os.name != "nt":
        return True
    path = os.path.abspath(path)
    if not os.path.exists(path):
        raise OSError(f"Cannot set ACL on missing path: {path}")
    cache = globals().setdefault("_WINDOWS_PRIVATE_DIRS", set())
    key = os.path.normcase(path)
    if is_dir and key in cache:
        return True
    _windows_current_user_sid()
    _windows_acl_call(path, _windows_acl_script(check_only=False, is_dir=is_dir))
    if not _windows_acl_is_private(path):
        raise OSError(f"Could not verify private Windows ACL on {path}")
    if is_dir:
        cache.add(key)
    return True


def _windows_acl_is_private(path):
    if os.name != "nt":
        return False
    try:
        return _windows_acl_call(path, _windows_acl_script(check_only=True))
    except OSError:
        return False


def atomic_write_secret_bytes(target_path, data_bytes):
    """Atomically write secret bytes with restricted owner-only permissions (0600) from creation (P1-D).
    - Creates a protected temp file via os.open(..., O_CREAT|O_EXCL|O_WRONLY, 0o600).
    - Writes all bytes, flushes, fsyncs, verifies length & permissions, then atomically replaces target_path.
    - Cleans up temp file on any error or interruption so partial/unprotected files are never left behind."""
    if not isinstance(data_bytes, (bytes, bytearray)):
        data_bytes = str(data_bytes).encode("utf-8")
    parent_dir = os.path.dirname(os.path.abspath(target_path))
    if not parent_dir or not os.path.isdir(parent_dir):
        raise OSError(f"Target directory does not exist: {parent_dir}")
    if os.path.lexists(target_path) and os.path.islink(target_path):
        raise OSError(f"Refusing to write secret to symlink path: {target_path}")
    if os.name == "nt":
        _set_windows_private_acl(parent_dir, is_dir=True)

    tmp_path = os.path.join(parent_dir, f".{os.path.basename(target_path)}.tmp.{os.getpid()}.{secrets.token_hex(6)}")
    fd = None
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        fd = os.open(tmp_path, flags, 0o600)
        if os.name == "nt":
            _set_windows_private_acl(tmp_path, is_dir=False)
        try:
            os.chmod(tmp_path, 0o600)
        except OSError:
            pass
        total_written = 0
        mv = memoryview(data_bytes)
        while total_written < len(data_bytes):
            n_w = os.write(fd, mv[total_written:])
            if n_w <= 0:
                raise OSError("Short write while saving secret file")
            total_written += n_w
        os.fsync(fd)
        os.close(fd)
        fd = None

        st_info = os.stat(tmp_path)
        if st_info.st_size != len(data_bytes):
            raise OSError(f"Incomplete secret write ({st_info.st_size} != {len(data_bytes)})")
        if os.name == "posix" and (stat.S_IMODE(st_info.st_mode) & 0o077) != 0:
            os.chmod(tmp_path, 0o600)
            st_info = os.stat(tmp_path)
            if (stat.S_IMODE(st_info.st_mode) & 0o077) != 0:
                raise OSError(f"Failed to enforce 0600 permissions on {tmp_path}")

        os.replace(tmp_path, target_path)
        if os.name == "nt":
            # os.replace preserves the protected ACL on the temporary file.
            # Re-apply and verify it on the final path rather than relying on
            # a best-effort icacls command after the atomic rename.
            _set_windows_private_acl(target_path, is_dir=False)
            if not _windows_acl_is_private(target_path):
                raise OSError(f"Failed to verify private Windows ACL on {target_path}")
    finally:
        if fd is not None:
            try: os.close(fd)
            except OSError: pass
        if os.path.lexists(tmp_path):
            try: os.remove(tmp_path)
            except OSError: pass


_HMAC_KEY_FILENAME = ".mersad_hmac.key"


def _hmac_key_stat_signature(st):
    """Stable file-identity signature used to invalidate cached HMAC keys after replacement or modification."""
    return (
        int(getattr(st, "st_dev", 0)),
        int(getattr(st, "st_ino", 0)),
        int(st.st_size),
        int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000))),
        int(getattr(st, "st_ctime_ns", int(st.st_ctime * 1_000_000_000))),
        int(getattr(st, "st_file_attributes", 0)),
    )


def _get_hmac_key():
    """Load or create the local 32-byte HMAC key and cache it after a verified read.

    Windows ACL validation invokes PowerShell/whoami. It must happen when a key
    is first loaded (or its file identity changes), not once for every audit row.
    A stat signature invalidates the in-memory key if the file is replaced or
    modified. Corrupt keys and symlinks still fail closed.
    """
    with _HMAC_KEY_LOCK:
        base_dir = os.environ.get("MERSAD_DATA_DIR") or os.getcwd()
        key_path = os.path.abspath(os.path.join(base_dir, _HMAC_KEY_FILENAME))

        if os.path.islink(key_path):
            _HMAC_KEY_CACHE.pop(key_path, None)
            _HMAC_KEY_CACHE_META.pop(key_path, None)
            raise RuntimeError(f"Security error: HMAC key file {key_path} cannot be a symbolic link")

        try:
            st_before = os.stat(key_path, follow_symlinks=False)
        except FileNotFoundError:
            st_before = None
        except OSError as e:
            _HMAC_KEY_CACHE.pop(key_path, None)
            _HMAC_KEY_CACHE_META.pop(key_path, None)
            raise RuntimeError(f"Cannot inspect HMAC key file {key_path}: {e}") from e

        if st_before is not None:
            if not stat.S_ISREG(st_before.st_mode):
                _HMAC_KEY_CACHE.pop(key_path, None)
                _HMAC_KEY_CACHE_META.pop(key_path, None)
                raise RuntimeError(f"Security error: HMAC key path {key_path} is not a regular file")

            current_signature = _hmac_key_stat_signature(st_before)
            cached_key = _HMAC_KEY_CACHE.get(key_path)
            if (
                isinstance(cached_key, bytes)
                and len(cached_key) >= 32
                and _HMAC_KEY_CACHE_META.get(key_path) == current_signature
            ):
                return cached_key

            if os.name == "nt":
                try:
                    _set_windows_private_acl(base_dir, is_dir=True)
                    _set_windows_private_acl(key_path, is_dir=False)
                except OSError as e:
                    _HMAC_KEY_CACHE.pop(key_path, None)
                    _HMAC_KEY_CACHE_META.pop(key_path, None)
                    raise RuntimeError(f"Cannot securely protect Windows HMAC key at {key_path}: {e}") from e

            try:
                with open(key_path, "rb") as f:
                    opened_stat = os.fstat(f.fileno())
                    k = f.read()
                after_stat = os.stat(key_path, follow_symlinks=False)
            except OSError as e:
                _HMAC_KEY_CACHE.pop(key_path, None)
                _HMAC_KEY_CACHE_META.pop(key_path, None)
                raise RuntimeError(f"Cannot read HMAC key file {key_path}: {e}") from e

            if os.path.islink(key_path) or (
                _hmac_key_stat_signature(opened_stat) != _hmac_key_stat_signature(after_stat)
            ):
                _HMAC_KEY_CACHE.pop(key_path, None)
                _HMAC_KEY_CACHE_META.pop(key_path, None)
                raise RuntimeError(f"Security error: HMAC key file {key_path} changed while being read")

            if len(k) < 32:
                _HMAC_KEY_CACHE.pop(key_path, None)
                _HMAC_KEY_CACHE_META.pop(key_path, None)
                raise RuntimeError(
                    f"Corrupt or truncated HMAC key file at {key_path} ({len(k)} bytes < 32). "
                    "Refusing to silently generate a replacement key to protect audit pseudonym integrity."
                )

            if os.name == "posix":
                try:
                    st_mode = stat.S_IMODE(after_stat.st_mode)
                    if (st_mode & 0o077) != 0:
                        os.chmod(key_path, 0o600)
                        after_stat = os.stat(key_path, follow_symlinks=False)
                except OSError:
                    pass

            _HMAC_KEY_CACHE[key_path] = k
            _HMAC_KEY_CACHE_META[key_path] = _hmac_key_stat_signature(after_stat)
            return k

        _HMAC_KEY_CACHE.pop(key_path, None)
        _HMAC_KEY_CACHE_META.pop(key_path, None)
        k = secrets.token_bytes(32)
        try:
            atomic_write_secret_bytes(key_path, k)
            created_stat = os.stat(key_path, follow_symlinks=False)
        except OSError as e:
            raise RuntimeError(f"Cannot securely create or persist HMAC key at {key_path}: {e}") from e
        if os.path.islink(key_path) or not stat.S_ISREG(created_stat.st_mode):
            raise RuntimeError(f"Security error: newly created HMAC key at {key_path} is not a regular file")
        _HMAC_KEY_CACHE[key_path] = k
        _HMAC_KEY_CACHE_META[key_path] = _hmac_key_stat_signature(created_stat)
        return k


def pseud(s):
    """Keyed HMAC-SHA256 pseudonym so person names/plates in audit logs cannot be brute-forced (P2-K, P1-D)."""
    key = _get_hmac_key()
    digest = hmac.new(key, str(s or "").encode("utf-8", "ignore"), hashlib.sha256).hexdigest()[:12]
    return "p-" + digest


@contextlib.contextmanager
def interprocess_db_lock(db_path=None):
    """Re-entrant thread + OS-level inter-process lock for atomic SQLite writes (P0-E).

    Lock order is always local DB lock -> process-state lock -> OS mutex.
    Some read/report paths already hold the local DB RLock before invoking a
    migration or transaction. Acquiring the process-state lock first here
    would let another thread hold it while waiting for the DB lock, creating
    a lock-order inversion and a cross-thread deadlock.
    """
    t_lock = D.get("lock")
    p = db_path or D.get("db_path") or os.path.join(os.environ.get("MERSAD_DATA_DIR") or os.getcwd(), "mersad.db")
    t_lock_acquired = False
    ipc_acquired = False
    depth_incremented = False
    try:
        if t_lock is not None:
            t_lock.acquire()
            t_lock_acquired = True

        _IPC_RLOCK.acquire()
        ipc_acquired = True

        if _IPC_STATE["depth"] == 0 and p and p != ":memory:":
            # Preserve fail-closed path validation even though the Windows
            # named mutex itself is a kernel object.
            lock_parent = os.path.dirname(os.path.abspath(p))
            if not os.path.isdir(lock_parent):
                raise OSError(f"Database lock parent directory does not exist: {lock_parent}")
            if fcntl is not None:
                lock_flags = os.O_RDWR | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0)
                lock_handle = os.open(f"{p}.ipclock", lock_flags, 0o600)
                try:
                    fcntl.flock(lock_handle, fcntl.LOCK_EX)
                except Exception:
                    os.close(lock_handle)
                    raise
            elif os.name == "nt":
                lock_handle = _acquire_windows_db_mutex(p)
            elif msvcrt is not None:
                lock_flags = os.O_RDWR | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0)
                lock_handle = os.open(f"{p}.ipclock", lock_flags, 0o600)
                try:
                    _ensure_windows_lock_byte(lock_handle)
                    _acquire_windows_byte_lock(lock_handle)
                except Exception:
                    os.close(lock_handle)
                    raise
            else:
                lock_handle = None
            _IPC_STATE["fd"] = lock_handle

        _IPC_STATE["depth"] += 1
        depth_incremented = True
        yield
    finally:
        if ipc_acquired:
            try:
                if depth_incremented:
                    _IPC_STATE["depth"] -= 1
                if _IPC_STATE["depth"] == 0 and _IPC_STATE["fd"] is not None:
                    lock_handle = _IPC_STATE["fd"]
                    _IPC_STATE["fd"] = None
                    try:
                        if isinstance(lock_handle, int):
                            try:
                                if fcntl is not None:
                                    fcntl.flock(lock_handle, fcntl.LOCK_UN)
                                elif msvcrt is not None:
                                    os.lseek(lock_handle, 0, os.SEEK_SET)
                                    msvcrt.locking(lock_handle, msvcrt.LK_UNLCK, 1)
                            except Exception:
                                pass
                            finally:
                                try:
                                    os.close(lock_handle)
                                except OSError:
                                    pass
                        elif (isinstance(lock_handle, tuple) and len(lock_handle) == 3
                              and lock_handle[0] == "windows_mutex"):
                            _release_windows_db_mutex(lock_handle)
                        else:
                            close = getattr(lock_handle, "close", None)
                            if callable(close):
                                close()
                    except Exception:
                        close = getattr(lock_handle, "close", None)
                        if callable(close):
                            try:
                                close()
                            except Exception:
                                pass
            finally:
                _IPC_RLOCK.release()
        if t_lock_acquired:
            t_lock.release()
def run_atomic_tx(db, lock, fn, db_path=None, retries=20):
    """Execute fn(db) inside BEGIN IMMEDIATE with re-entrant OS file lock and bounded retry on SQLite lock contention (P0-E)."""
    last_err = None
    for attempt in range(retries):
        try:
            with interprocess_db_lock(db_path):
                started_tx = False
                if not db.in_transaction:
                    db.execute("BEGIN IMMEDIATE")
                    started_tx = True
                try:
                    res = fn(db)
                    if started_tx:
                        db.commit()
                    return res
                except Exception:
                    if started_tx and db.in_transaction:
                        try: db.rollback()
                        except Exception: pass
                    raise
        except sqlite3.OperationalError as oe:
            last_err = oe
            if "locked" in str(oe).lower() or "busy" in str(oe).lower():
                time.sleep(0.01 * (attempt + 1))
                continue
            raise
    raise last_err


def _alias(m): return {hkey(a): k for k, v in m.items() for a in v}


AV = _alias({"plate": ["رقم اللوحة", "اللوحة", "رقم", "plate", "plate number", "number"],
             "governorate": ["المحافظة", "المدينة", "governorate", "city"],
             "model": ["اسم السيارة (الطراز)", "اسم السيارة", "السيارة", "الطراز", "model", "make", "vehicle"],
             "color": ["اللون", "color"], "vtype": ["النوع", "نوع المركبة", "type", "vehicle type"],
             "owner": ["اسم المالك", "المالك", "owner"], "status": ["الحالة", "status"],
             "notes": ["ملاحظات", "notes", "note"]})
AP = _alias({"name": ["الاسم", "اسم الشخص", "name", "full name"],
             "ref": ["الرقم المرجعي", "رقم مرجعي", "ref", "id", "reference"],
             "category": ["الفئة", "التصنيف", "category", "role"], "status": ["الحالة", "status"],
             "consent": ["موافقة (نعم/لا)", "موافقة", "consent"], "notes": ["ملاحظات", "notes", "note"]})
VH = ["رقم اللوحة", "المحافظة", "اسم السيارة (الطراز)", "اللون", "النوع", "اسم المالك", "الحالة", "ملاحظات"]
PH = ["الاسم", "الرقم المرجعي", "الفئة", "الحالة", "موافقة (نعم/لا)", "ملاحظات"]
VEX = ["00000", "عدن", "تويوتا هايلكس", "أبيض", "شاحنة", "مثال فقط", "عادية", ""]
PEX = ["مثال (احذف هذا السطر)", "V-001", "متطوع", "عادي", "نعم", ""]


def _fix_ocr_numeric_tokens(raw_str):
    """Normalize OCR lookalike characters (O->0, I/l->1, S->5, B->8, Z->2) ONLY inside tokens that contain digits."""
    tokens = re.split(r"([\s\-_/]+)", raw_str)
    out = []
    fixed = False
    for tok in tokens:
        if any(ch.isdigit() for ch in tok) and any(ch in "OoIl|SsBZ" for ch in tok):
            new_tok = tok.translate(OCR_DIGIT_CONFUSIONS)
            if new_tok != tok:
                fixed = True
            out.append(new_tok)
        else:
            out.append(tok)
    return "".join(out), fixed


_LATIN_GOV_TO_AR = {
    "ADEN": "عدن",
    "AEN": "عدن",
    "SANAA": "صنعاء",
    "SANA": "صنعاء",
    "TAIZ": "تعز",
    # Common EasyOCR omissions on narrow uppercase glyphs in small plates:
    # TAIZ -> TAZ and MARIB/MARI -> MAR. These aliases are limited to the
    # governorate-code token; they do not alter numeric-only plate matching.
    "TAZ": "تعز",
    "HADR": "حضرموت",
    "HAR": "حضرموت",
    "HADRAMOUT": "حضرموت",
    "IBB": "إب",
    "MARIB": "مأرب",
    "MARI": "مأرب",
    "MAR": "مأرب",
}


def _map_latin_gov_letters(letters: str) -> str:
    """Map standard Latin Yemeni governorate codes (ADEN, SANA, TAIZ, HADR, IBB, MARIB) to canonical Arabic."""
    up = str(letters or "").strip().upper()
    return _LATIN_GOV_TO_AR.get(up, letters)


def split_plate_ex(s):
    """Extract (core_digits, normalized_letters, ocr_confusion_fixed) from any plate string."""
    raw = str(s or "").translate(DIG).translate(AR_NORM).strip().upper()
    if not raw:
        return "", "", False
    raw_fixed, ocr_fixed = _fix_ocr_numeric_tokens(raw)
    digits = "".join(re.findall(r"\d", raw_fixed))
    letters = "".join(re.findall(r"[A-Z\u0621-\u064A]", raw_fixed))[:8]
    letters = _map_latin_gov_letters(letters)
    return digits, letters, ocr_fixed


def split_plate(s):
    """Extract (core_digits, normalized_letters) from any Arabic/Persian/English plate string."""
    digits, letters, _ = split_plate_ex(s)
    return digits, letters


def _known_governorate_plate_from_raw(raw):
    """Recover a known governorate prefix before OCR digit-confusion repair can corrupt it.

    EasyOCR can join the Latin governorate code and serial into one token (SANA48210).
    These narrow signatures are accepted only when followed solely by 3-8 serial digits.
    """
    compact = re.sub(r"[^A-Z0-9]", "", str(raw or "").upper())
    signatures = dict(_LATIN_GOV_TO_AR)
    signatures.update({
        "ADN": "عدن",
        "A05N": "عدن",   # observed EasyOCR confusion for ADEN
        "AN0": "عدن",    # observed CI read: ADEN 12345 -> AN 012345
        "T4Z": "تعز",    # observed EasyOCR confusion for TAZ/TAIZ
        "I88": "إب",
        "L88": "إب",
        "188": "إب",
    })
    for signature in sorted(signatures, key=len, reverse=True):
        if not compact.startswith(signature):
            continue
        suffix = compact[len(signature):]
        if not suffix or any(ch.isalpha() for ch in suffix):
            continue
        serial = "".join(re.findall(r"\d", suffix))
        if 3 <= len(serial) <= 8:
            return f"{signatures[signature]}-{serial}"
    return ""


def norm_plate(s, governorate=""):
    """Canonical plate representation; preserve known governorate prefixes before OCR digit repair."""
    raw = str(s or "").translate(DIG).translate(AR_NORM).strip().upper()
    if not raw:
        return ""
    known_prefix_plate = _known_governorate_plate_from_raw(raw)
    if known_prefix_plate:
        return known_prefix_plate
    digits, letters = split_plate(raw)
    if not digits:
        return ""
    eff_letters = letters or _norm_letters_only(governorate)
    if not eff_letters:
        # EasyOCR may mistake the IBB prefix for "188" on small plate crops.
        # Recover only explicit, known governorate signatures; leave ordinary
        # numeric-only plates untouched.
        compact = re.sub(r"[^A-Z0-9]", "", raw)
        signatures = (
            ("IBB", "إب"), ("I88", "إب"), ("L88", "إب"), ("188", "إب"),
            ("ADEN", "عدن"), ("ADN", "عدن"),
            ("SANAA", "صنعاء"), ("SANA", "صنعاء"),
            ("TAIZ", "تعز"), ("TAZ", "تعز"),
            ("HADRAMOUT", "حضرموت"), ("HADR", "حضرموت"),
            ("MARIB", "مأرب"), ("MARI", "مأرب"), ("MAR", "مأرب"),
        )
        for signature, canonical in signatures:
            if compact.startswith(signature):
                eff_letters = canonical
                if canonical == "إب" and len(digits) > 5 and digits.startswith("188"):
                    digits = digits[3:]
                break
    return f"{eff_letters}-{digits}" if eff_letters else digits

def _norm_letters_only(s):
    raw = str(s or "").translate(DIG).translate(AR_NORM).strip().upper()
    return "".join(re.findall(r"[A-Z\u0621-\u064A]", raw))[:8]


def _letter_similarity(a, b):
    """Compute character overlap / subsequence similarity in [0.0, 1.0] between two normalized letter strings."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return max(0.55, 0.85 * (min(len(a), len(b)) / max(len(a), len(b))))
    common = sum(1 for ch in set(a) if ch in set(b))
    return common / max(len(set(a)), len(set(b)))


def _edit_distance_1(a, b):
    """Return True if strings a and b have Levenshtein edit distance == 1 (and lengths >= 4)."""
    if not a or not b or min(len(a), len(b)) < 4 or abs(len(a) - len(b)) > 1:
        return False
    if a == b:
        return False
    if len(a) == len(b):
        return sum(1 for x, y in zip(a, b) if x != y) == 1
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    i = j = diffs = 0
    while i < len(shorter) and j < len(longer):
        if shorter[i] == longer[j]:
            i += 1; j += 1
        else:
            diffs += 1
            j += 1
            if diffs > 1:
                return False
    return True


def migrate_legacy_faces(db):
    """Safely migrate or quarantine legacy face rows that lack a valid unambiguous person_id (P0-A item 7):
    - Never guesses randomly when multiple persons share the same name: quarantines ambiguous rows (quarantined=1).
    - Never grants automatic consent to faces whose person has consent=0: quarantines them.
    - Assigns person_id ONLY when exactly 1 person record exists with that name AND has active consent=1."""
    cols_f = {r[1] for r in db.execute("PRAGMA table_info(faces)").fetchall()}
    if "quarantined" not in cols_f:
        try: db.execute("ALTER TABLE faces ADD COLUMN quarantined INTEGER DEFAULT 0")
        except sqlite3.OperationalError: pass
    if "quarantine_reason" not in cols_f:
        try: db.execute("ALTER TABLE faces ADD COLUMN quarantine_reason TEXT DEFAULT ''")
        except sqlite3.OperationalError: pass
    if "person_id" not in cols_f:
        try: db.execute("ALTER TABLE faces ADD COLUMN person_id INTEGER DEFAULT 0")
        except sqlite3.OperationalError: pass

    unassigned = db.execute(
        "SELECT rowid, COALESCE(name,''), COALESCE(person_id,0) FROM faces "
        "WHERE COALESCE(quarantined, 0) = 0 AND ("
        "  COALESCE(person_id, 0) <= 0 "
        "  OR NOT EXISTS (SELECT 1 FROM persons p WHERE p.id = faces.person_id)"
        ")"
    ).fetchall()
    if not unassigned:
        return 0

    quarantined_cnt = 0
    for f_rowid, f_name, f_pid in unassigned:
        if f_pid > 0:
            # Had a person_id that no longer exists in persons -> quarantine orphan
            db.execute(
                "UPDATE faces SET person_id=0, quarantined=1, quarantine_reason='orphan_person_id_not_found' WHERE rowid=?",
                (f_rowid,)
            )
            quarantined_cnt += 1
            continue
        p_rows = db.execute(
            "SELECT id, COALESCE(consent,0), COALESCE(status,'normal') FROM persons WHERE name=?",
            (f_name,)
        ).fetchall()
        if len(p_rows) == 1 and int(p_rows[0][1]) == 1:
            pid, _, p_st = p_rows[0]
            db.execute(
                "UPDATE faces SET person_id=?, watch=?, quarantined=0, quarantine_reason='' WHERE rowid=?",
                (pid, int(p_st == "watch"), f_rowid)
            )
        elif len(p_rows) > 1:
            db.execute(
                "UPDATE faces SET person_id=0, quarantined=1, quarantine_reason='ambiguous_legacy_name_multiple_persons' WHERE rowid=?",
                (f_rowid,)
            )
            quarantined_cnt += 1
        elif len(p_rows) == 1 and int(p_rows[0][1]) == 0:
            db.execute(
                "UPDATE faces SET person_id=?, quarantined=1, quarantine_reason='legacy_face_without_consent' WHERE rowid=?",
                (p_rows[0][0], f_rowid)
            )
            quarantined_cnt += 1
        else:
            db.execute(
                "UPDATE faces SET person_id=0, quarantined=1, quarantine_reason='orphan_legacy_face_no_person' WHERE rowid=?",
                (f_rowid,)
            )
            quarantined_cnt += 1
    return quarantined_cnt


_CRITICAL_DB_ERR_TOKENS = (
    "database or disk is full",
    "disk is full",
    "no space left",
    "readonly",
    "read-only",
    "attempt to write a readonly database",
    "permission denied",
    "access is denied",
    "unable to open database file",
    "not a database",
    "database disk image is malformed",
)


def _is_critical_storage_error(exc):
    msg = str(exc or "").strip().lower()
    return any(tok in msg for tok in _CRITICAL_DB_ERR_TOKENS)


def _is_in_memory_db(db, db_path=None):
    if db_path == ":memory:":
        return True
    if db_path:
        return False
    try:
        db_list = db.execute("PRAGMA database_list").fetchall()
        if db_list and all(not str(r[2] or "").strip() for r in db_list):
            return True
    except Exception:
        pass
    return False


def _ensure_calibration_and_eval_schema(db):
    """Idempotently ensure extended camera_links columns, field_calibrations table, and plate_eval_runs table exist (Stage 11)."""
    db.execute(
        "CREATE TABLE IF NOT EXISTS camera_links("
        "from_cam TEXT, to_cam TEXT, min_sec REAL DEFAULT 90, expected_sec REAL DEFAULT 300, "
        "source TEXT DEFAULT 'user_calibrated', via TEXT DEFAULT '', "
        "max_sec REAL DEFAULT 0, distance_m REAL DEFAULT 0, observations_count INTEGER DEFAULT 0, "
        "calibration_date TEXT DEFAULT '', traffic_condition TEXT DEFAULT 'normal', "
        "measurement_source TEXT DEFAULT 'manual', notes TEXT DEFAULT '', "
        "updated_ts REAL DEFAULT 0, updated_by TEXT DEFAULT '', "
        "PRIMARY KEY(from_cam, to_cam))"
    )
    cols_cl = {r[1] for r in db.execute("PRAGMA table_info(camera_links)").fetchall()}
    for col_name, col_ddl in (
        ("via", "ALTER TABLE camera_links ADD COLUMN via TEXT DEFAULT ''"),
        ("max_sec", "ALTER TABLE camera_links ADD COLUMN max_sec REAL DEFAULT 0"),
        ("distance_m", "ALTER TABLE camera_links ADD COLUMN distance_m REAL DEFAULT 0"),
        ("observations_count", "ALTER TABLE camera_links ADD COLUMN observations_count INTEGER DEFAULT 0"),
        ("calibration_date", "ALTER TABLE camera_links ADD COLUMN calibration_date TEXT DEFAULT ''"),
        ("traffic_condition", "ALTER TABLE camera_links ADD COLUMN traffic_condition TEXT DEFAULT 'normal'"),
        ("measurement_source", "ALTER TABLE camera_links ADD COLUMN measurement_source TEXT DEFAULT 'manual'"),
        ("notes", "ALTER TABLE camera_links ADD COLUMN notes TEXT DEFAULT ''"),
        ("updated_ts", "ALTER TABLE camera_links ADD COLUMN updated_ts REAL DEFAULT 0"),
        ("updated_by", "ALTER TABLE camera_links ADD COLUMN updated_by TEXT DEFAULT ''"),
    ):
        if col_name not in cols_cl:
            try:
                db.execute(col_ddl)
            except sqlite3.OperationalError:
                pass

    db.execute("""CREATE TABLE IF NOT EXISTS field_calibrations(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entry_type TEXT DEFAULT 'manual_unverified',
        verification_status TEXT DEFAULT 'manual_unverified',
        from_cam TEXT DEFAULT '',
        to_cam TEXT DEFAULT '',
        transit_sec REAL DEFAULT 0,
        measured_plate_accuracy REAL,
        samples_count INTEGER DEFAULT 0,
        correct_reads INTEGER DEFAULT 0,
        incorrect_reads INTEGER DEFAULT 0,
        source_description TEXT DEFAULT '',
        measurement_date TEXT DEFAULT '',
        model_used TEXT DEFAULT '',
        operator_name TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        created_ts REAL DEFAULT 0,
        updated_ts REAL DEFAULT 0
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS plate_eval_runs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL NOT NULL,
        eval_date TEXT DEFAULT '',
        dataset_path TEXT DEFAULT '',
        plate_model TEXT DEFAULT '',
        detector_mode TEXT DEFAULT '',
        vehicle_stage_enabled INTEGER DEFAULT 0,
        total_samples INTEGER DEFAULT 0,
        valid_files INTEGER DEFAULT 0,
        invalid_files INTEGER DEFAULT 0,
        detected_count INTEGER DEFAULT 0,
        failed_detection_count INTEGER DEFAULT 0,
        failed_ocr_count INTEGER DEFAULT 0,
        detection_recall REAL DEFAULT 0,
        detection_precision REAL DEFAULT 0,
        detection_f1 REAL DEFAULT 0,
        mean_iou REAL,
        exact_match_rate REAL DEFAULT 0,
        end_to_end_exact_match_rate REAL DEFAULT 0,
        cropped_ocr_exact_match_rate REAL DEFAULT 0,
        digits_match_rate REAL DEFAULT 0,
        char_accuracy_rate REAL DEFAULT 0,
        cer REAL DEFAULT 0,
        mean_latency_ms REAL DEFAULT 0,
        status TEXT DEFAULT 'completed',
        report_json TEXT DEFAULT '{}'
    )""")
    cols_pe = {r[1] for r in db.execute("PRAGMA table_info(plate_eval_runs)").fetchall()}
    for col_name, col_ddl in (
        ("detection_f1", "ALTER TABLE plate_eval_runs ADD COLUMN detection_f1 REAL DEFAULT 0"),
        ("end_to_end_exact_match_rate", "ALTER TABLE plate_eval_runs ADD COLUMN end_to_end_exact_match_rate REAL DEFAULT 0"),
        ("cropped_ocr_exact_match_rate", "ALTER TABLE plate_eval_runs ADD COLUMN cropped_ocr_exact_match_rate REAL DEFAULT 0"),
    ):
        if col_name not in cols_pe:
            try:
                db.execute(col_ddl)
            except sqlite3.OperationalError:
                pass


def migrate_db(db, lock, db_path=None):
    """Apply numbered, non-destructive schema migrations (v1..v6) with automatic backup of existing database files.
    GAP-02: Strictly separates WAL/mmap filesystem incompatibility from critical storage failures (disk full / read-only),
    rolls back cleanly before switching to DELETE mode, verifies journal_mode == 'delete'/'truncate', and forbids MEMORY/OFF."""
    eff_path = db_path or D.get("db_path")
    if eff_path is None and _is_in_memory_db(db, None):
        eff_path = ":memory:"
    is_mem = (eff_path == ":memory:")
    with interprocess_db_lock(eff_path):
        was_in_tx = db.in_transaction
        if not was_in_tx:
            need_delete_fallback = False
            wal_err = None
            try:
                mode_row = db.execute("PRAGMA journal_mode=WAL").fetchone()
                cur_mode = str(mode_row[0]).strip().lower() if (mode_row and mode_row[0] is not None) else ""
                if not is_mem and cur_mode != "wal":
                    need_delete_fallback = True
                else:
                    db.execute("PRAGMA busy_timeout=15000")
                    db.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_ts REAL, description TEXT)")
            except Exception as exc:
                if _is_critical_storage_error(exc) or isinstance(exc, PermissionError):
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    raise sqlite3.OperationalError(
                        f"Critical database storage failure during initialization ({eff_path or 'db'}): {exc}"
                    ) from exc
                if isinstance(exc, sqlite3.OperationalError):
                    need_delete_fallback = True
                    wal_err = exc
                else:
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    raise

            if need_delete_fallback:
                try:
                    db.rollback()
                except Exception:
                    pass
                try:
                    res_mode = db.execute("PRAGMA journal_mode=DELETE").fetchone()
                except Exception as del_exc:
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    raise sqlite3.OperationalError(
                        f"Failed to switch SQLite journal_mode from WAL to DELETE for {eff_path or 'db'}: {del_exc}"
                    ) from (wal_err or del_exc)
                actual_mode = str(res_mode[0]).strip().lower() if (res_mode and res_mode[0] is not None) else ""
                if not is_mem:
                    if actual_mode in ("memory", "off"):
                        raise sqlite3.OperationalError(
                            f"Unsafe SQLite journal_mode '{actual_mode}' is strictly forbidden for operational database {eff_path or 'db'}"
                        )
                    if actual_mode not in ("delete", "truncate"):
                        raise sqlite3.OperationalError(
                            f"SQLite WAL fallback failed: expected journal_mode 'delete'/'truncate', got '{actual_mode}'"
                        )
                try:
                    db.execute("PRAGMA busy_timeout=15000")
                    db.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_ts REAL, description TEXT)")
                except Exception as create_exc:
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    raise sqlite3.OperationalError(
                        f"Database schema_migrations initialization failed after DELETE fallback ({eff_path or 'db'}): {create_exc}"
                    ) from create_exc
        else:
            try:
                db.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_ts REAL, description TEXT)")
            except Exception as tx_exc:
                if _is_critical_storage_error(tx_exc):
                    raise sqlite3.OperationalError(
                        f"Critical database storage failure during migration ({eff_path or 'db'}): {tx_exc}"
                    ) from tx_exc
                raise
        cur_ver = db.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()[0]
        if cur_ver >= 6:
            # Idempotent check: ensure camera_links extended columns, field_calibrations, plate_eval_runs, and vehicle indexes exist
            db.execute("CREATE INDEX IF NOT EXISTS idx_vehicles_digits ON vehicles(plate_digits)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_vehicles_status ON vehicles(status)")
            _ensure_calibration_and_eval_schema(db)
            if not was_in_tx:
                db.commit()
            return
        has_legacy = bool(db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sightings'").fetchone())
        if has_legacy and cur_ver < 6 and db_path and os.path.exists(db_path) and os.path.getsize(db_path) > 0:
            bak = f"{db_path}.bak.v{cur_ver}"
            if not os.path.exists(bak):
                try: shutil.copy2(db_path, bak)
                except OSError: pass

        if cur_ver < 1:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS vehicles(plate TEXT PRIMARY KEY, governorate TEXT, model TEXT, color TEXT,
              vtype TEXT DEFAULT 'car', owner TEXT, status TEXT DEFAULT 'normal', notes TEXT, updated REAL,
              plate_digits TEXT DEFAULT '', plate_letters TEXT DEFAULT '');
            CREATE TABLE IF NOT EXISTS persons(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, ref TEXT DEFAULT '',
              category TEXT, status TEXT DEFAULT 'normal', consent INTEGER DEFAULT 0, notes TEXT, updated REAL, UNIQUE(name, ref));
            CREATE TABLE IF NOT EXISTS faces(name TEXT, emb BLOB, watch INTEGER DEFAULT 0, person_id INTEGER DEFAULT 0,
              quarantined INTEGER DEFAULT 0, quarantine_reason TEXT DEFAULT '');
            CREATE TABLE IF NOT EXISTS sightings(ts REAL, cam TEXT, plate TEXT, conf REAL, vclass TEXT,
              src TEXT DEFAULT 'live', direction TEXT DEFAULT '', raw_text TEXT DEFAULT '', session_id TEXT DEFAULT '');
            CREATE TABLE IF NOT EXISTS audit(i INTEGER PRIMARY KEY, ts REAL, action TEXT, ref TEXT, prev TEXT, hash TEXT);
            """)
            db.execute("INSERT INTO schema_migrations VALUES(1, ?, 'Base tables')", (time.time(),))

        if cur_ver < 2:
            cols_s = {r[1] for r in db.execute("PRAGMA table_info(sightings)").fetchall()}
            for col, ddl in (
                ("vclass", "ALTER TABLE sightings ADD COLUMN vclass TEXT"),
                ("src", "ALTER TABLE sightings ADD COLUMN src TEXT DEFAULT 'live'"),
                ("direction", "ALTER TABLE sightings ADD COLUMN direction TEXT DEFAULT ''"),
                ("raw_text", "ALTER TABLE sightings ADD COLUMN raw_text TEXT DEFAULT ''"),
            ):
                if col not in cols_s:
                    try: db.execute(ddl)
                    except sqlite3.OperationalError: pass
            cols_f = {r[1] for r in db.execute("PRAGMA table_info(faces)").fetchall()}
            if "watch" not in cols_f:
                try: db.execute("ALTER TABLE faces ADD COLUMN watch INTEGER DEFAULT 0")
                except sqlite3.OperationalError: pass
            db.execute("UPDATE sightings SET src='live' WHERE src IS NULL OR src=''")
            db.execute("INSERT INTO schema_migrations VALUES(2, ?, 'Upgrade sightings & faces columns')", (time.time(),))

        if cur_ver < 3:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS alerts(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts REAL,
              ts_str TEXT,
              msg TEXT,
              subject TEXT,
              ref TEXT,
              detail TEXT,
              cam TEXT,
              img TEXT,
              status TEXT DEFAULT 'pending',
              decided_by TEXT DEFAULT '',
              decided_ts REAL DEFAULT 0,
              dispatched INTEGER DEFAULT 0,
              dispatch_status TEXT DEFAULT 'not_required',
              dispatch_attempts INTEGER DEFAULT 0,
              next_retry_ts REAL DEFAULT 0,
              last_error TEXT DEFAULT '',
              dispatch_started_ts REAL DEFAULT 0,
              dispatch_owner TEXT DEFAULT '',
              repeat_count INTEGER DEFAULT 1,
              last_seen_ts REAL DEFAULT 0,
              notify_status TEXT DEFAULT 'pending',
              notify_attempts INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS camera_links(
              from_cam TEXT,
              to_cam TEXT,
              min_sec REAL DEFAULT 90,
              expected_sec REAL DEFAULT 300,
              source TEXT DEFAULT 'user_calibrated',
              PRIMARY KEY(from_cam, to_cam)
            );
            CREATE INDEX IF NOT EXISTS idx_sightings_plate_ts ON sightings(plate, ts);
            CREATE INDEX IF NOT EXISTS idx_sightings_ts ON sightings(ts);
            CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);
            CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit(ts);
            """)
            db.execute("INSERT INTO schema_migrations VALUES(3, ?, 'Add alerts, camera_links, and indexes')", (time.time(),))

        if cur_ver < 4:
            cols_v = {r[1] for r in db.execute("PRAGMA table_info(vehicles)").fetchall()}
            for col, ddl in (
                ("plate_digits", "ALTER TABLE vehicles ADD COLUMN plate_digits TEXT DEFAULT ''"),
                ("plate_letters", "ALTER TABLE vehicles ADD COLUMN plate_letters TEXT DEFAULT ''"),
            ):
                if col not in cols_v:
                    try: db.execute(ddl)
                    except sqlite3.OperationalError: pass
            db.execute("CREATE INDEX IF NOT EXISTS idx_vehicles_digits ON vehicles(plate_digits)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_vehicles_status ON vehicles(status)")

            cols_a = {r[1] for r in db.execute("PRAGMA table_info(alerts)").fetchall()}
            for col, ddl in (
                ("dispatch_status", "ALTER TABLE alerts ADD COLUMN dispatch_status TEXT DEFAULT 'not_required'"),
                ("dispatch_attempts", "ALTER TABLE alerts ADD COLUMN dispatch_attempts INTEGER DEFAULT 0"),
                ("next_retry_ts", "ALTER TABLE alerts ADD COLUMN next_retry_ts REAL DEFAULT 0"),
                ("last_error", "ALTER TABLE alerts ADD COLUMN last_error TEXT DEFAULT ''"),
            ):
                if col not in cols_a:
                    try: db.execute(ddl)
                    except sqlite3.OperationalError: pass
            cols_s = {r[1] for r in db.execute("PRAGMA table_info(sightings)").fetchall()}
            if "session_id" not in cols_s:
                try: db.execute("ALTER TABLE sightings ADD COLUMN session_id TEXT DEFAULT ''")
                except sqlite3.OperationalError: pass
            db.execute("INSERT INTO schema_migrations VALUES(4, ?, 'Add plate_digits/letters, alert dispatch_status, and session_id')", (time.time(),))

        if cur_ver < 5:
            cols_a = {r[1] for r in db.execute("PRAGMA table_info(alerts)").fetchall()}
            for col, ddl in (
                ("dispatch_started_ts", "ALTER TABLE alerts ADD COLUMN dispatch_started_ts REAL DEFAULT 0"),
                ("repeat_count", "ALTER TABLE alerts ADD COLUMN repeat_count INTEGER DEFAULT 1"),
                ("last_seen_ts", "ALTER TABLE alerts ADD COLUMN last_seen_ts REAL DEFAULT 0"),
                ("notify_status", "ALTER TABLE alerts ADD COLUMN notify_status TEXT DEFAULT 'pending'"),
                ("notify_attempts", "ALTER TABLE alerts ADD COLUMN notify_attempts INTEGER DEFAULT 0"),
            ):
                if col not in cols_a:
                    try: db.execute(ddl)
                    except sqlite3.OperationalError: pass

            cols_p = {r[1] for r in db.execute("PRAGMA table_info(persons)").fetchall()}
            if "id" not in cols_p:
                db.executescript("""
                CREATE TABLE IF NOT EXISTS persons_v5(
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT,
                  ref TEXT DEFAULT '',
                  category TEXT,
                  status TEXT DEFAULT 'normal',
                  consent INTEGER DEFAULT 0,
                  notes TEXT,
                  updated REAL,
                  UNIQUE(name, ref)
                );
                INSERT OR IGNORE INTO persons_v5(name, ref, category, status, consent, notes, updated)
                  SELECT name, COALESCE(ref,''), category, status, consent, notes, updated FROM persons;
                DROP TABLE persons;
                ALTER TABLE persons_v5 RENAME TO persons;
                """)
            cols_f = {r[1] for r in db.execute("PRAGMA table_info(faces)").fetchall()}
            if "person_id" not in cols_f:
                try: db.execute("ALTER TABLE faces ADD COLUMN person_id INTEGER DEFAULT 0")
                except sqlite3.OperationalError: pass

            v_rows = db.execute("SELECT plate, COALESCE(governorate,'') FROM vehicles").fetchall()
            for pl, gov in v_rows:
                dg, lt_str = split_plate(pl)
                eff_lt = lt_str or _norm_letters_only(gov)
                canon_pl = f"{eff_lt}-{dg}" if (eff_lt and dg) else pl
                if canon_pl != pl:
                    exists_canon = db.execute("SELECT 1 FROM vehicles WHERE plate=?", (canon_pl,)).fetchone()
                    if not exists_canon:
                        db.execute("UPDATE vehicles SET plate=?, plate_digits=?, plate_letters=? WHERE plate=?",
                                   (canon_pl, dg, eff_lt, pl))
                    else:
                        db.execute("UPDATE vehicles SET plate_digits=?, plate_letters=? WHERE plate=?",
                                   (dg, eff_lt, pl))
                else:
                    db.execute("UPDATE vehicles SET plate_digits=?, plate_letters=? WHERE plate=?",
                               (dg, eff_lt, pl))

            db.execute("INSERT INTO schema_migrations VALUES(5, ?, 'Canonical letters-digits PK, persons internal ID, alert lease & repeat_count')", (time.time(),))

        if cur_ver < 6:
            cols_f = {r[1] for r in db.execute("PRAGMA table_info(faces)").fetchall()}
            for col, ddl in (
                ("person_id", "ALTER TABLE faces ADD COLUMN person_id INTEGER DEFAULT 0"),
                ("quarantined", "ALTER TABLE faces ADD COLUMN quarantined INTEGER DEFAULT 0"),
                ("quarantine_reason", "ALTER TABLE faces ADD COLUMN quarantine_reason TEXT DEFAULT ''"),
            ):
                if col not in cols_f:
                    try: db.execute(ddl)
                    except sqlite3.OperationalError: pass
            db.execute("CREATE INDEX IF NOT EXISTS idx_faces_person_id ON faces(person_id)")

            cols_a = {r[1] for r in db.execute("PRAGMA table_info(alerts)").fetchall()}
            if "dispatch_owner" not in cols_a:
                try: db.execute("ALTER TABLE alerts ADD COLUMN dispatch_owner TEXT DEFAULT ''")
                except sqlite3.OperationalError: pass

            db.executescript("""
            CREATE TABLE IF NOT EXISTS evidence_archive_ops(
              orig_rel TEXT PRIMARY KEY,
              arch_rel TEXT,
              sha256 TEXT,
              alert_id INTEGER DEFAULT 0,
              started_ts REAL,
              completed_ts REAL DEFAULT 0,
              who TEXT DEFAULT '',
              status TEXT DEFAULT 'in_progress'
            );
            CREATE TABLE IF NOT EXISTS camera_links(
              from_cam TEXT,
              to_cam TEXT,
              min_sec REAL DEFAULT 90,
              expected_sec REAL DEFAULT 300,
              source TEXT DEFAULT 'user_calibrated',
              via TEXT DEFAULT '',
              PRIMARY KEY(from_cam, to_cam)
            );
            """)
            cols_cl = {r[1] for r in db.execute("PRAGMA table_info(camera_links)").fetchall()}
            if "via" not in cols_cl:
                try:
                    db.execute("ALTER TABLE camera_links ADD COLUMN via TEXT DEFAULT ''")
                except sqlite3.OperationalError:
                    pass
            _ensure_calibration_and_eval_schema(db)
            migrate_legacy_faces(db)
            db.execute(
                "INSERT INTO schema_migrations VALUES(6, ?, 'v6_camera_links_via_and_constraints: Strict person_id face isolation, quarantine legacy faces, dispatch_owner, archive ops journal, camera_links.via')",
                (time.time(),)
            )

        if not was_in_tx:
            db.commit()


def init(db, lock, log, refresh, db_path=None):
    eff_path = db_path if db_path is not None else (":memory:" if _is_in_memory_db(db, None) else None)
    D.update(db=db, lock=lock, log=log, refresh=refresh, db_path=eff_path)
    migrate_db(db, lock, db_path=eff_path)


def pick(v, kw, default):
    v = str(v or "").strip().lower()
    if not v: return default
    for code, ks in kw.items():
        if v == code or any(k in v for k in ks): return code
    return None


def cell(v):
    if v is None: return ""
    if isinstance(v, float) and v.is_integer(): return str(int(v))
    return str(v).strip()


def clean_vehicle(d):
    """Validate and canonicalize a vehicle record.
    P0-C: The canonical primary key is 'letters-digits' whenever plate letters or governorate exist."""
    raw_plate = d.get("plate")
    digits_only, letters_only = split_plate(raw_plate)
    if not (3 <= len(digits_only) <= 8):
        return None, "رقم اللوحة غير صالح (يجب أن يتضمن 3 إلى 8 أرقام)"
    st = pick(d.get("status"), KW_V, "normal")
    if st is None:
        return None, f"حالة غير معروفة: {d.get('status')}"
    g = lambda k, n=60: str(d.get(k) or "").strip()[:n]
    gov = g("governorate", 30)
    eff_letters = letters_only or _norm_letters_only(gov)
    canon_plate = f"{eff_letters}-{digits_only}" if eff_letters else digits_only
    if len(canon_plate) > 20:
        return None, "رقم اللوحة طويل جداً"
    return dict(
        plate=canon_plate, plate_digits=digits_only, plate_letters=eff_letters,
        governorate=gov, model=g("model"), color=g("color", 30),
        vtype=pick(d.get("vtype"), KW_T, "car") or "other",
        owner=g("owner"), status=st, notes=g("notes", 200)
    ), None


def clean_person(d):
    n = str(d.get("name") or "").strip()[:40]
    if not n: return None, "الاسم مطلوب"
    st = pick(d.get("status"), KW_P, "normal")
    if st is None: return None, f"حالة غير معروفة: {d.get('status')}"
    c = d.get("consent"); c = c is True or str(c).strip().lower() in ("1", "true", "yes", "y", "نعم", "موافق")
    g = lambda k, m: str(d.get(k) or "").strip()[:m]
    raw_id = d.get("id") if d.get("id") is not None else d.get("person_id")
    pid = int(raw_id) if str(raw_id or "").isdigit() and int(raw_id) > 0 else None
    return dict(id=pid, name=n, ref=g("ref", 30), category=g("category", 30) or "متطوع", status=st, consent=int(c), notes=g("notes", 200)), None


def _up_vehicle(c, allow_downgrade=True):
    db = D["db"]
    ex = db.execute("SELECT status FROM vehicles WHERE plate=?", (c["plate"],)).fetchone()
    if ex and not allow_downgrade and ex[0] in ("wanted", "stolen") and c["status"] not in ("wanted", "stolen"):
        return "protected_skip"
    db.execute("""INSERT INTO vehicles(plate,plate_digits,plate_letters,governorate,model,color,vtype,owner,status,notes,updated)
      VALUES(:plate,:plate_digits,:plate_letters,:governorate,:model,:color,:vtype,:owner,:status,:notes,:u)
      ON CONFLICT(plate) DO UPDATE SET plate_digits=:plate_digits, plate_letters=:plate_letters,
      governorate=:governorate, model=:model, color=:color, vtype=:vtype,
      owner=:owner, status=:status, notes=:notes, updated=:u""", {**c, "u": time.time()})
    return "updated" if ex else "added"


def _up_person(c):
    """Insert or update a person record and update/delete ONLY that person's face embeddings via person_id (P0-A)."""
    db = D["db"]
    migrate_legacy_faces(db)
    pid = c.get("id")
    ex = None
    if pid:
        row = db.execute("SELECT id, name, COALESCE(ref,'') FROM persons WHERE id=?", (pid,)).fetchone()
        if row:
            ex = row
    if not ex and c["ref"]:
        row = db.execute("SELECT id, name, COALESCE(ref,'') FROM persons WHERE name=? AND COALESCE(ref,'')=?", (c["name"], c["ref"])).fetchone()
        if row:
            ex = row
            pid = row[0]
    if not ex and not c["ref"]:
        ex_any = db.execute("SELECT id, name, COALESCE(ref,'') FROM persons WHERE name=?", (c["name"],)).fetchall()
        if len(ex_any) == 1:
            ex = ex_any[0]
            pid = ex[0]
            c = {**c, "ref": ex[2]}
        elif len(ex_any) > 1:
            raise ValueError("يوجد أكثر من شخص بنفس الاسم في السجل؛ يرجى تحديد الرقم المرجعي (ref) أو المعرّف (id) لمنع خلط الهويات")

    now_u = time.time()
    if ex and pid:
        db.execute(
            "UPDATE persons SET name=?, ref=?, category=?, status=?, consent=?, notes=?, updated=? WHERE id=?",
            (c["name"], c["ref"], c["category"], c["status"], c["consent"], c["notes"], now_u, pid)
        )
        action = "updated"
    else:
        cur = db.execute(
            "INSERT INTO persons(name,ref,category,status,consent,notes,updated) VALUES(?,?,?,?,?,?,?)",
            (c["name"], c["ref"], c["category"], c["status"], c["consent"], c["notes"], now_u)
        )
        pid = int(cur.lastrowid)
        action = "added"

    # P0-A: Strictly scope consent revocation and watchlist updates to person_id == pid ONLY!
    if not c["consent"]:
        db.execute("DELETE FROM faces WHERE person_id=?", (pid,))
    else:
        db.execute(
            "UPDATE faces SET watch=?, name=? WHERE person_id=? AND COALESCE(quarantined, 0)=0",
            (int(c["status"] == "watch"), c["name"], pid)
        )
    return action, pid


def save_vehicle(d, ip):
    c, e = clean_vehicle(d)
    if e: return {"ok": False, "error": e}
    allow_down = bool(d.get("force", True))
    with interprocess_db_lock():
        try:
            a = _up_vehicle(c, allow_downgrade=allow_down)
            D["db"].commit()
        except Exception as ex:
            D["db"].rollback(); return {"ok": False, "error": str(ex)}
    D["log"](f"registry vehicle {a}", f"{c['plate']} status={c['status']} by {ip}")
    return {"ok": True, "action": a, "plate": c["plate"]}


def save_person(d, ip):
    c, e = clean_person(d)
    if e: return {"ok": False, "error": e}
    with interprocess_db_lock():
        try:
            a, pid = _up_person(c); D["db"].commit()
        except Exception as ex:
            D["db"].rollback(); return {"ok": False, "error": str(ex)}
    p_tag = pseud(f"{pid}:{c['name']}")
    D["log"](f"registry person {a}", f"{p_tag} id={pid} ref={c['ref']} status={c['status']} consent={c['consent']} by {ip}")
    D["refresh"]()
    return {"ok": True, "action": a, "id": pid, "person_id": pid}


def delete(kind, key, ip):
    """Delete a vehicle or person record safely (P0-A item 5):
    - Deleting a person by id, ref, or unambiguous name deletes ONLY that person's face embeddings (person_id=pid),
      never wiping embeddings of homonymous persons."""
    db = D["db"]
    with interprocess_db_lock():
        try:
            if kind == "vehicles":
                ref = norm_plate(key)
                n = db.execute("DELETE FROM vehicles WHERE plate=? OR plate_digits=?", (ref, key)).rowcount
            else:
                migrate_legacy_faces(db)
                s_key = str(key or "").strip()
                target_pid = None
                if s_key.startswith("id:") and s_key[3:].isdigit():
                    target_pid = int(s_key[3:])
                elif s_key.isdigit():
                    row_by_id = db.execute("SELECT id FROM persons WHERE id=?", (int(s_key),)).fetchone()
                    if row_by_id:
                        target_pid = int(row_by_id[0])

                if target_pid is not None:
                    row = db.execute("SELECT id, name, COALESCE(ref,'') FROM persons WHERE id=?", (target_pid,)).fetchone()
                    if not row:
                        n = 0
                        ref = pseud(s_key)
                    else:
                        n = db.execute("DELETE FROM persons WHERE id=?", (target_pid,)).rowcount
                        # P0-A: Delete ONLY faces belonging to this exact person_id!
                        db.execute("DELETE FROM faces WHERE person_id=?", (target_pid,))
                        ref = f"{pseud(f'{target_pid}:{row[1]}')} id={target_pid}"
                else:
                    # Check if key matches a unique ref first, else check name
                    by_ref = db.execute("SELECT id, name, COALESCE(ref,'') FROM persons WHERE ref=? AND COALESCE(ref,'')!=''", (s_key,)).fetchall()
                    if len(by_ref) == 1:
                        target_pid, nm, _ = by_ref[0]
                        n = db.execute("DELETE FROM persons WHERE id=?", (target_pid,)).rowcount
                        db.execute("DELETE FROM faces WHERE person_id=?", (target_pid,))
                        ref = f"{pseud(f'{target_pid}:{nm}')} id={target_pid}"
                    else:
                        by_name = db.execute("SELECT id, name, COALESCE(ref,'') FROM persons WHERE name=?", (s_key,)).fetchall()
                        if len(by_name) > 1:
                            db.rollback()
                            return {
                                "ok": False,
                                "error": "يوجد أكثر من شخص بنفس الاسم؛ يجب الحذف باستخدام المعرّف الداخلي (id) أو الرقم المرجعي (ref) لمنع حذف سجلات شخص آخر"
                            }
                        elif len(by_name) == 1:
                            target_pid, nm, _ = by_name[0]
                            n = db.execute("DELETE FROM persons WHERE id=?", (target_pid,)).rowcount
                            db.execute("DELETE FROM faces WHERE person_id=?", (target_pid,))
                            ref = f"{pseud(f'{target_pid}:{nm}')} id={target_pid}"
                        else:
                            n = 0
                            ref = pseud(s_key)
            db.commit()
        except Exception:
            db.rollback(); raise
    if n:
        D["log"](f"registry {kind} deleted", f"{ref} by {ip}")
    if kind == "persons":
        D["refresh"]()
    return {"ok": bool(n)}


def list_rows(kind, q=""):
    q_s = q.strip()
    q_digits, _ = split_plate(q_s)
    like = f"%{q_s}%"
    like_d = f"%{q_digits}%" if q_digits else like
    db = D["db"]
    with D["lock"]:
        if kind == "vehicles":
            cur = db.execute("""SELECT plate, governorate, model, color, vtype, owner, status, notes FROM vehicles
              WHERE plate LIKE ? OR plate_digits LIKE ? OR model LIKE ? OR owner LIKE ? OR governorate LIKE ?
              ORDER BY updated DESC LIMIT 500""", (like, like_d, like, like, like))
        else:
            migrate_legacy_faces(db)
            cur = db.execute("""SELECT p.id, p.name, p.ref, p.category, p.status, p.consent, p.notes,
              (SELECT COUNT(*) FROM faces f WHERE f.person_id = p.id AND COALESCE(f.quarantined, 0) = 0) AS face_samples FROM persons p
              WHERE p.name LIKE ? OR p.ref LIKE ? OR p.category LIKE ? ORDER BY p.updated DESC LIMIT 500""", (like,) * 3)
        cols = [c[0] for c in cur.description]; rows = cur.fetchall()
    return [dict(zip(cols, r)) for r in rows]


LAST_LOOKUP_STATS = {"approx_rows_scanned": 0, "legacy_rows_scanned": 0, "elapsed_ms": 0.0}


def lookup_vehicle(plate):
    """Look up a vehicle using core digits + secondary letters/governorate (P0-A, P0-B, P0-C, GAP-13).
    GAP-13 optimization:
    - Uses idx_vehicles_digits / PRIMARY KEY for exact digit or canonical plate lookup.
    - Scans only legacy rows with empty plate_digits if any exist.
    - Restricts approximate edit-distance-1 candidate fetch strictly to status IN ('wanted', 'stolen')
      with LENGTH(plate_digits) BETWEEN len(q_digits)-1 AND len(q_digits)+1 via idx_vehicles_status."""
    t0 = time.perf_counter()
    q_digits, q_letters, ocr_fixed = split_plate_ex(plate)
    if not q_digits:
        LAST_LOOKUP_STATS.update(approx_rows_scanned=0, legacy_rows_scanned=0, elapsed_ms=(time.perf_counter() - t0) * 1000.0)
        return None
    with D["lock"]:
        cur = D["db"].execute(
            "SELECT plate, COALESCE(plate_digits,''), COALESCE(plate_letters,''), governorate, model, color, vtype, owner, status, notes "
            "FROM vehicles WHERE plate_digits=? OR plate=?",
            (q_digits, norm_plate(plate))
        )
        rows = cur.fetchall()
    if not rows:
        # Check only legacy rows where plate_digits was not populated (0 rows on migrated databases)
        with D["lock"]:
            cur_leg = D["db"].execute(
                "SELECT plate, COALESCE(plate_digits,''), COALESCE(plate_letters,''), governorate, model, color, vtype, owner, status, notes "
                "FROM vehicles WHERE COALESCE(plate_digits, '') = ''"
            )
            leg_v = cur_leg.fetchall()
        rows = [r for r in leg_v if split_plate(r[0])[0] == q_digits]

        if not rows:
            min_len = max(1, len(q_digits) - 1)
            max_len = len(q_digits) + 1
            with D["lock"]:
                cur_approx = D["db"].execute(
                    "SELECT plate, COALESCE(plate_digits,''), COALESCE(plate_letters,''), governorate, model, color, vtype, owner, status, notes "
                    "FROM vehicles WHERE status IN ('wanted', 'stolen') "
                    "AND (LENGTH(COALESCE(plate_digits, '')) BETWEEN ? AND ? OR COALESCE(plate_digits, '') = '')",
                    (min_len, max_len)
                )
                wanted_v = cur_approx.fetchall()
            LAST_LOOKUP_STATS.update(
                approx_rows_scanned=len(wanted_v),
                legacy_rows_scanned=len(leg_v),
                elapsed_ms=(time.perf_counter() - t0) * 1000.0,
            )
            approx = []
            for r in wanted_v:
                r_dg = r[1] or split_plate(r[0])[0]
                if _edit_distance_1(q_digits, r_dg):
                    approx.append(r)
            if approx:
                pl, pdg, plt, gov, mod, col, vt, own, st, nt = approx[0]
                dg, lt_from_pl = split_plate(pl)
                eff_lt = plt or lt_from_pl or _norm_letters_only(gov)
                return {
                    "plate": pl, "plate_digits": dg, "plate_letters": eff_lt,
                    "governorate": gov or "", "model": mod or "", "color": col or "",
                    "vtype": vt or "car", "owner": own or "", "status": st or "normal", "notes": nt or "",
                    "match_type": "approximate",
                    "match_note": "تطابق تقريبي (مسافة تحرير 1) — تطابق محتمل يتطلب تحققاً بصرياً",
                    "conf_factor": 0.75,
                    "ambiguous": False,
                    "contradictory_letters": False,
                    "visual_check_only": True
                }
            return None
    LAST_LOOKUP_STATS.update(approx_rows_scanned=0, legacy_rows_scanned=0, elapsed_ms=(time.perf_counter() - t0) * 1000.0)

    candidates = []
    for pl, pdg, plt, gov, mod, col, vt, own, st, nt in rows:
        dg, lt_from_pl = split_plate(pl)
        eff_lt = plt or lt_from_pl or _norm_letters_only(gov)
        candidates.append({
            "plate": pl, "plate_digits": dg, "plate_letters": eff_lt,
            "governorate": gov or "", "model": mod or "", "color": col or "",
            "vtype": vt or "car", "owner": own or "", "status": st or "normal", "notes": nt or ""
        })

    def _finalize_ocr_fixed(res_dict):
        if not ocr_fixed or not res_dict:
            return res_dict
        out = dict(res_dict)
        out["match_type"] = "approximate"
        out["match_note"] = "تطابق تقريبي (تصحيح التباس محارف OCR مثل O/0 أو I/1) — تحقق بصري"
        out["conf_factor"] = min(float(out.get("conf_factor", 0.80)), 0.80)
        out["visual_check_only"] = True
        return out

    if len(candidates) == 1:
        c = candidates[0]
        rec_lt = c["plate_letters"]
        if (not q_letters and not rec_lt) or (q_letters and rec_lt and q_letters == rec_lt):
            return _finalize_ocr_fixed({
                **c, "match_type": "exact", "match_note": "مطابقة كاملة",
                "conf_factor": 1.0, "ambiguous": False, "contradictory_letters": False, "visual_check_only": False
            })
        if not q_letters or not rec_lt:
            return _finalize_ocr_fixed({
                **c, "match_type": "digits_only",
                "match_note": "تطابق بالأرقام فقط، الأحرف غير مؤكدة",
                "conf_factor": 0.85, "ambiguous": False, "contradictory_letters": False, "visual_check_only": False
            })
        sim = _letter_similarity(q_letters, rec_lt)
        if sim >= 0.5:
            return _finalize_ocr_fixed({
                **c, "match_type": "digits_only",
                "match_note": "تطابق بالأرقام فقط، الأحرف غير مؤكدة (تشابه جزئي للأحرف)",
                "conf_factor": 0.85, "ambiguous": False, "contradictory_letters": False, "visual_check_only": False
            })
        return _finalize_ocr_fixed({
            **c, "match_type": "digits_only",
            "match_note": f"تطابق محتمل — تحقق بصري (تطابق بالأرقام فقط مع تعارض الأحرف/المحافظة: المقروء «{q_letters}» مقابل المسجل «{rec_lt}»)",
            "conf_factor": 0.60, "ambiguous": False, "contradictory_letters": True, "visual_check_only": True
        })

    prio = {"wanted": 5, "stolen": 4, "watch": 3, "expired": 2, "normal": 1}
    if q_letters:
        scored = sorted(
            ((_letter_similarity(q_letters, c["plate_letters"]), prio.get(c["status"], 0), c) for c in candidates),
            key=lambda x: (x[0], x[1]),
            reverse=True
        )
        best_sim, _, best_c = scored[0]
        second_sim = scored[1][0] if len(scored) > 1 else 0.0
        if best_sim == 1.0 and best_sim > second_sim:
            return _finalize_ocr_fixed({
                **best_c, "match_type": "exact", "match_note": "مطابقة كاملة (أرقام + أحرف)",
                "conf_factor": 1.0, "ambiguous": False, "contradictory_letters": False, "visual_check_only": False
            })
        if best_sim >= 0.5 and best_sim > second_sim:
            return _finalize_ocr_fixed({
                **best_c, "match_type": "digits_only",
                "match_note": "تطابق بالأرقام فقط، الأحرف غير مؤكدة (تم اختيار الأقرب بالأحرف)",
                "conf_factor": 0.85, "ambiguous": False, "contradictory_letters": False, "visual_check_only": False
            })

    candidates.sort(key=lambda c: -prio.get(c["status"], 0))
    chosen = dict(candidates[0])
    all_plates = " / ".join(c["plate"] for c in candidates)
    chosen.update(
        match_type="ambiguous",
        ambiguous=True,
        contradictory_letters=bool(q_letters),
        visual_check_only=True,
        candidates=[c["plate"] for c in candidates],
        match_note=f"تطابق محتمل — تحقق بصري (تطابق بالأرقام فقط مع تعدد سجلات بنفس الأرقام: {all_plates})",
        conf_factor=0.65
    )
    return _finalize_ocr_fixed(chosen)


def get_person(name="", ref="", person_id=None):
    """Resolve a person record unambiguously by internal person_id, (name, ref), or unique name (P0-A).
    Returns None if multiple records share the given name and neither person_id nor ref was provided."""
    s_name = str(name or "").strip()
    if person_id is None and s_name.startswith("id:") and s_name[3:].isdigit():
        person_id = int(s_name[3:])
        s_name = ""
    if person_id is not None and str(person_id).isdigit():
        pid = int(person_id)
        with D["lock"]:
            r = D["db"].execute(
                "SELECT id, name, COALESCE(ref,''), category, status, consent, notes FROM persons WHERE id=?",
                (pid,)
            ).fetchone()
        if r:
            return dict(zip(("id", "name", "ref", "category", "status", "consent", "notes"), r))
        return None
    s_ref = str(ref or "").strip()
    rows = list_rows("persons", s_name or s_ref)
    if s_ref:
        matches = [x for x in rows if (not s_name or x["name"] == s_name) and x.get("ref") == s_ref]
        if len(matches) == 1:
            return matches[0]
        return None
    if s_name:
        matches = [x for x in rows if x["name"] == s_name]
        if len(matches) == 1:
            return matches[0]
    return None


def parse_file(fn, data):
    f = fn.lower()
    if f.endswith((".xlsx", ".xlsm")):
        try: from openpyxl import load_workbook
        except ImportError: raise ValueError("لقراءة Excel ثبّت: pip install openpyxl (أو احفظ الملف بصيغة CSV)")
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        try:
            ws = wb.active
            return [[cell(c) for c in r] for _, r in zip(range(10001), ws.iter_rows(values_only=True))]
        finally:
            try: wb.close()
            except Exception: pass
    if f.endswith((".csv", ".txt")):
        try: txt = data.decode("utf-8-sig")
        except UnicodeDecodeError: txt = data.decode("cp1256", "replace")
        try: dia = csv.Sniffer().sniff(txt[:2000], delimiters=",;\t")
        except csv.Error: dia = csv.excel
        return [[cell(c) for c in r] for r in csv.reader(io.StringIO(txt), dia)]
    raise ValueError("صيغة غير مدعومة: استخدم ملف .xlsx أو .csv")


def import_file(kind, filename, data, ip, force_overwrite=False):
    veh = kind == "vehicles"
    try: rows = [r for r in parse_file(filename, data) if any(r)]
    except Exception as e: return {"ok": False, "error": str(e)}
    if not rows: return {"ok": False, "error": "الملف فارغ"}
    alias, clean, need = (AV, clean_vehicle, "plate") if veh else (AP, clean_person, "name")
    hdr = [alias.get(hkey(h)) for h in rows[0]]
    if need not in hdr:
        return {"ok": False, "error": "لم أجد عمود " + ("رقم اللوحة" if veh else "الاسم") + " في السطر الأول. حمّل القالب واستخدم عناوينه."}
    add = upd = 0; errs = []; warnings = []
    seen_in_file = {}
    with interprocess_db_lock():
        try:
            for i, r in enumerate(rows[1:], start=2):
                d = {k: r[j] for j, k in enumerate(hdr) if k and j < len(r)}
                if (veh and split_plate(d.get("plate"))[0] == "00000") or (not veh and str(d.get("name", "")).startswith("مثال")):
                    continue
                c, e = clean(d)
                if e:
                    errs.append(f"السطر {i}: {e}"); continue
                rec_key = c["plate"] if veh else f"{c['name']}|{c.get('ref','')}"
                if rec_key in seen_in_file:
                    warnings.append(f"السطر {i}: تكرار المفتاح «{rec_key}» داخل نفس الملف (سبقه السطر {seen_in_file[rec_key]})")
                seen_in_file[rec_key] = i
                if veh:
                    a = _up_vehicle(c, allow_downgrade=force_overwrite)
                    if a == "protected_skip":
                        warnings.append(f"السطر {i}: لم يُستبدل السجل الأمني الحرج للوحة «{c['plate']}» بحالة أقل دون تأكيد صريح")
                        continue
                else:
                    try:
                        a, _ = _up_person(c)
                    except ValueError as ve:
                        errs.append(f"السطر {i}: {ve}"); continue
                add += a == "added"; upd += a == "updated"
            D["db"].commit()
        except Exception as ex:
            D["db"].rollback()
            return {"ok": False, "error": f"فشل حفظ البيانات: {ex}"}
    D["log"](f"registry import {kind}", f"+{add} ~{upd} !{len(errs)} w={len(warnings)} sha256={hashlib.sha256(data).hexdigest()[:16]} by {ip}")
    if not veh:
        D["refresh"]()
    return {"ok": True, "added": add, "updated": upd, "skipped": len(errs), "errors": errs[:10], "warnings": warnings[:10]}


def template(kind):
    heads, ex = (VH, VEX) if kind == "vehicles" else (PH, PEX)
    try:
        from openpyxl import Workbook
        wb = Workbook()
        try:
            ws = wb.active; ws.sheet_view.rightToLeft = True
            ws.append(heads); ws.append(ex); buf = io.BytesIO(); wb.save(buf)
            return buf.getvalue(), f"mersad_{kind}_template.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        finally:
            try: wb.close()
            except Exception: pass
    except ImportError:
        s = io.StringIO(); w = csv.writer(s); w.writerow(heads); w.writerow(ex)
        return s.getvalue().encode("utf-8-sig"), f"mersad_{kind}_template.csv", "text/csv; charset=utf-8"
