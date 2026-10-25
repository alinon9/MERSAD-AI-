#!/usr/bin/env python3
"""Patch extracted MERSAD AI sources for Windows packaging and run static syntax checks."""
from pathlib import Path
import ast
import sys

root = Path(sys.argv[1]).resolve()

def replace_once(file, old, new, label):
    p = root / file
    text = p.read_text(encoding="utf-8")
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{file}: expected one occurrence for {label}, found {count}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8", newline="")

def insert_after_once(file, anchor, insertion, marker):
    p = root / file
    text = p.read_text(encoding="utf-8")
    if marker in text:
        return
    if text.count(anchor) != 1:
        raise SystemExit(f"{file}: expected one anchor for {marker}, found {text.count(anchor)}")
    p.write_text(text.replace(anchor, anchor + insertion, 1), encoding="utf-8", newline="")

def replace_function(file, name, new_source):
    p = root / file
    text = p.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=file)
    matches = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    if len(matches) != 1:
        raise SystemExit(f"{file}: expected one function {name}, found {len(matches)}")
    node = matches[0]
    lines = text.splitlines()
    start, end = node.lineno - 1, node.end_lineno
    replacement = new_source.strip("\n").splitlines()
    p.write_text("\n".join(lines[:start] + replacement + lines[end:]) + "\n", encoding="utf-8", newline="")


def replace_between(file, start_marker, end_marker, new_source, marker):
    p = root / file
    text = p.read_text(encoding="utf-8")
    if marker in text:
        return
    if text.count(start_marker) != 1 or text.count(end_marker) != 1:
        raise SystemExit(f"{file}: expected unique boundaries for {marker}")
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    if end <= start:
        raise SystemExit(f"{file}: invalid boundary order for {marker}")
    p.write_text(text[:start] + new_source.rstrip() + "\n\n" + text[end:], encoding="utf-8", newline="")

# Use a named Windows mutex: file-region locking was not exclusive on the CI runner.
replace_function(
    "notify.py",
    "_acquire_listener_lock",
    r"""
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
""",
)
replace_function(
    "notify.py",
    "_release_listener_lock",
    r"""
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
""",
)


replace_once(
    "registry.py",
    "import contextlib, csv, hashlib, hmac, io, os, re, secrets, shutil, sqlite3, stat, threading, time\n",
    "import contextlib, csv, hashlib, hmac, io, os, re, secrets, shutil, sqlite3, stat, subprocess, threading, time\n",
    "Windows ACL subprocess support",
)

acl_helpers = r'''

# MERSAD_WINDOWS_PRIVATE_ACL_HELPERS
def _ensure_windows_lock_byte(fd):
    fd.seek(0, os.SEEK_END)
    if fd.tell() == 0:
        fd.write(bytes([0]))
        fd.flush()
    fd.seek(0)


def _windows_current_user_sid():
    if os.name != "nt":
        return None
    try:
        proc = subprocess.run(
            ["whoami.exe", "/user", "/fo", "csv", "/nh"],
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
    # Protect each parent directory once. Atomic temp files inherit its private
    # owner-only ACL; do not launch PowerShell for every config save.
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
'''
insert_after_once(
    "registry.py",
    '_IPC_STATE = {"depth": 0, "fd": None}\n',
    acl_helpers,
    "MERSAD_WINDOWS_PRIVATE_ACL_HELPERS",
)

# HMAC keys and secrets are stored under a private ACL on Windows. POSIX mode
# checks remain unchanged and still enforce 0600.
replace_once(
    "registry.py",
    '    if os.path.lexists(target_path) and os.path.islink(target_path):\n'
    '        raise OSError(f"Refusing to write secret to symlink path: {target_path}")\n\n',
    '    if os.path.lexists(target_path) and os.path.islink(target_path):\n'
    '        raise OSError(f"Refusing to write secret to symlink path: {target_path}")\n'
    '    if os.name == "nt":\n'
    '        _set_windows_private_acl(parent_dir, is_dir=True)\n\n',
    "secure secrets parent",
)
replace_once(
    "registry.py",
    '        fd = os.open(tmp_path, flags, 0o600)\n        try:\n            os.chmod(tmp_path, 0o600)\n',
    '        fd = os.open(tmp_path, flags, 0o600)\n'
    '        if os.name == "nt":\n'
    '            _set_windows_private_acl(tmp_path, is_dir=False)\n'
    '        try:\n            os.chmod(tmp_path, 0o600)\n',
    "secure temporary secret file before writing",
)
replace_once(
    "registry.py",
    '    if os.path.lexists(key_path):\n'
    '        if os.path.islink(key_path):\n'
    '            _HMAC_KEY_CACHE.pop(key_path, None)\n'
    '            raise RuntimeError(f"Security error: HMAC key file {key_path} cannot be a symbolic link")\n',
    '    if os.path.lexists(key_path):\n'
    '        if os.path.islink(key_path):\n'
    '            _HMAC_KEY_CACHE.pop(key_path, None)\n'
    '            raise RuntimeError(f"Security error: HMAC key file {key_path} cannot be a symbolic link")\n'
    '        if os.name == "nt":\n'
    '            try:\n'
    '                _set_windows_private_acl(base_dir, is_dir=True)\n'
    '                _set_windows_private_acl(key_path, is_dir=False)\n'
    '            except OSError as e:\n'
    '                _HMAC_KEY_CACHE.pop(key_path, None)\n'
    '                raise RuntimeError(f"Cannot securely protect Windows HMAC key at {key_path}: {e}") from e\n',
    "secure existing HMAC key",
)
replace_once(
    "registry.py",
    '            elif msvcrt is not None:\n                fd.seek(0)\n                msvcrt.locking(fd.fileno(), msvcrt.LK_LOCK, 1)\n',
    '            elif msvcrt is not None:\n                _ensure_windows_lock_byte(fd)\n                msvcrt.locking(fd.fileno(), msvcrt.LK_LOCK, 1)\n',
    "SQLite Windows IPC lock byte-range",
)

# If a secrets file already exists, verify/restrict the Windows ACL before reading.
replace_once(
    "mersad_live.py",
    'def _load_secrets_file():\n    """Load .mersad_secrets.json safely, rejecting symlinks and enforcing 0600 on POSIX (P1-D)."""\n',
    'def _load_secrets_file():\n    """Load secrets safely, enforcing POSIX modes or restricted Windows ACLs (P1-D)."""\n',
    "document platform-specific secrets protection",
)
replace_once(
    "mersad_live.py",
    '    if os.path.islink(_SECRETS_FILE):\n'
    '        logger.error("Security error: %s is a symbolic link; refusing to load secrets", _SECRETS_FILE)\n'
    '        return {}\n'
    '    if os.name == "posix":\n',
    '    if os.path.islink(_SECRETS_FILE):\n'
    '        logger.error("Security error: %s is a symbolic link; refusing to load secrets", _SECRETS_FILE)\n'
    '        return {}\n'
    '    if os.name == "nt":\n'
    '        try:\n'
    '            R._set_windows_private_acl(os.getcwd(), is_dir=True)\n'
    '            R._set_windows_private_acl(_SECRETS_FILE, is_dir=False)\n'
    '        except OSError as e:\n'
    '            logger.error("Security error: cannot protect Windows secrets ACL: %s", redact_url(e))\n'
    '            return {}\n'
    '    if os.name == "posix":\n',
    "secure existing Windows secrets file",
)

# Validate real OS-level secret protection, not POSIX mode bits on Windows.
replace_once("selftest.py",
    '        key_mode = stat_mod.S_IMODE(os.stat(key_file).st_mode)\n',
    '        key_mode = stat_mod.S_IMODE(os.stat(key_file).st_mode)\n'
    '        key_secure = (key_mode == 0o600) if os.name == "posix" else reg_mod._windows_acl_is_private(key_file)\n',
    "measure HMAC key protection")
replace_once("selftest.py",
    '              p_first == p_after_restart and key_mode == 0o600 and corrupt_raised and still_corrupt_len == 11 and unwritable_raised,\n',
    '              p_first == p_after_restart and key_secure and corrupt_raised and still_corrupt_len == 11 and unwritable_raised,\n',
    "assert HMAC protection")
replace_once("selftest.py",
    '              (p_first, p_after_restart, oct(key_mode), corrupt_raised, still_corrupt_len, unwritable_raised))\n',
    '              (p_first, p_after_restart, (oct(key_mode) if os.name == "posix" else "windows_acl=" + str(key_secure)), corrupt_raised, still_corrupt_len, unwritable_raised))\n',
    "report HMAC protection")
replace_once("selftest.py",
    '    sec_mode_before = stat_mod.S_IMODE(os.stat(m._SECRETS_FILE).st_mode)\n',
    '    sec_mode_before = stat_mod.S_IMODE(os.stat(m._SECRETS_FILE).st_mode)\n'
    '    sec_secure_before = (sec_mode_before == 0o600) if os.name == "posix" else reg_mod._windows_acl_is_private(m._SECRETS_FILE)\n',
    "measure secrets protection before save")
replace_once("selftest.py",
    '    sec_mode_after = stat_mod.S_IMODE(os.stat(m._SECRETS_FILE).st_mode)\n',
    '    sec_mode_after = stat_mod.S_IMODE(os.stat(m._SECRETS_FILE).st_mode)\n'
    '    sec_secure_after = (sec_mode_after == 0o600) if os.name == "posix" else reg_mod._windows_acl_is_private(m._SECRETS_FILE)\n',
    "measure secrets protection after save")
replace_once("selftest.py",
    '          and not leftover_tmps and sec_mode_before == 0o600 and sec_mode_after == 0o600,\n',
    '          and not leftover_tmps and sec_secure_before and sec_secure_after,\n',
    "assert secrets protection")
replace_once("selftest.py",
    '          (interrupted_raised, sec_after_crash, leftover_tmps, oct(sec_mode_before), oct(sec_mode_after)))\n',
    '          (interrupted_raised, sec_after_crash, leftover_tmps, (oct(sec_mode_before) if os.name == "posix" else "windows_acl=" + str(sec_secure_before)), (oct(sec_mode_after) if os.name == "posix" else "windows_acl=" + str(sec_secure_after))))\n',
    "report secrets protection")

# Windows chmod(0555) does not revoke NTFS write rights. Use a real deny ACL in
# the test, then remove that deny ACE in finally so cleanup always works.
replace_once(
    "selftest.py",
    '        os.chmod(ro_install, 0o555)\n        try:\n',
    '        ro_sid = None\n'
    '        if os.name == "nt":\n'
    '            ro_sid = reg_mod._windows_current_user_sid()\n'
    '            icacls = shutil.which("icacls.exe") or os.path.join(os.environ.get("SystemRoot", r"C:\\Windows"), "System32", "icacls.exe")\n'
    '            deny = subprocess.run([icacls, ro_install, "/deny", f"*{ro_sid}:(WD,AD,WA,WEA)"], capture_output=True, text=True, timeout=10)\n'
    '            if deny.returncode != 0:\n'
    '                raise RuntimeError("Unable to create a real read-only install directory for Windows test: " + (deny.stderr or deny.stdout)[-300:])\n'
    '        else:\n'
    '            os.chmod(ro_install, 0o555)\n'
    '        try:\n',
    "use real Windows read-only ACL")
replace_once(
    "selftest.py",
    '        finally:\n            os.chmod(ro_install, 0o755)\n',
    '        finally:\n'
    '            if os.name == "nt" and ro_sid:\n'
    '                icacls = shutil.which("icacls.exe") or os.path.join(os.environ.get("SystemRoot", r"C:\\Windows"), "System32", "icacls.exe")\n'
    '                subprocess.run([icacls, ro_install, "/remove:d", f"*{ro_sid}"], capture_output=True, text=True, timeout=10)\n'
    '            else:\n'
    '                os.chmod(ro_install, 0o755)\n',
    "restore Windows read-only ACL after test")

replace_between(
    "selftest.py",
    "        # P1-4 & P1-F: Uncalibrated route conflict",
    "        # Consent revocation immediately removes face samples and stops matching",
    r"""
        # P1-4 & P1-F: Isolated uncalibrated route-notice test (avoid stale sightings/topology).
        uncal_plate = str(90000 + (os.getpid() % 10000))
        saved_links = m.db.execute("SELECT from_cam, to_cam, min_sec, expected_sec, source FROM camera_links").fetchall()
        try:
            with m.DBL:
                m.db.execute("DELETE FROM sightings WHERE plate=?", (uncal_plate,))
                m.db.execute("DELETE FROM camera_links")
                m.db.commit()
            if m.INS:
                m.INS.configure_topology()
                m.INS.M["last_cam"].pop(uncal_plate, None)
            msg_uncal, _ = m.register(uncal_plate, 0.91, "CAM1", "car", session_id="s_cam1")
            time.sleep(0.05)
            msg_uncal2, _ = m.register(uncal_plate, 0.91, "CAM2", "car", session_id="s_cam2")
            aid_uncal = m.raise_alert(msg_uncal2, uncal_plate, "CAM2", np.zeros((100, 100, 3), np.uint8))
            wait(lambda: any(uncal_plate in f.get("caption", "") for f in calls("sendPhoto")), t=3.0)
            uncal_photo = next(f for f in calls("sendPhoto") if uncal_plate in f.get("caption", ""))
            check("P1-4", "uncalibrated route conflict raises 'ROUTE NOTICE (uncalibrated)' (🔵 للعلم) with NO patrol dispatch buttons",
                  msg_uncal2 == "ROUTE NOTICE (uncalibrated)" and "🔵 للعلم" in uncal_photo["caption"]
                  and "reply_markup" not in uncal_photo, uncal_photo)
            res_conf_info = post("/api/decision", {"id": aid_uncal, "action": "confirm"})
            check("P1-F", "server rejects decide('confirm') on INFO_ONLY / uncalibrated route notice alert",
                  res_conf_info.get("ok") is False and db_q("select status from alerts where id=?", aid_uncal)[0][0] == "pending", res_conf_info)
            post("/api/decision", {"id": aid_uncal, "action": "ack"})
        finally:
            with m.DBL:
                m.db.execute("DELETE FROM sightings WHERE plate=?", (uncal_plate,))
                m.db.execute("DELETE FROM camera_links")
                m.db.executemany(
                    "INSERT INTO camera_links(from_cam, to_cam, min_sec, expected_sec, source) VALUES(?,?,?,?,?)",
                    saved_links
                )
                m.db.commit()
            if m.INS:
                m.INS.configure_topology()
                m.INS.M["last_cam"].pop(uncal_plate, None)

""",
    "MERSAD_ISOLATED_UNCALIBRATED_ROUTE_NOTICE_TEST",
)

replace_once(
    "selftest.py",
    '        o1, e1 = p1.communicate(timeout=30)\n        o2, e2 = p2.communicate(timeout=30)\n',
    '        o1, e1 = p1.communicate(timeout=30)\n        o2, e2 = p2.communicate(timeout=30)\n        mp_exit_codes = (p1.returncode, p2.returncode)\n',
    "capture P0-E child process exit codes",
)
replace_once(
    "selftest.py",
    '            "listener_owned = m.start_listener(lambda d, w: \'ok\', stop_event=stop_ev)\\n"\n            "m.log(\'session start\', cam)\\n"',
    '            "listener_owned = m.start_listener(lambda d, w: \'ok\', stop_event=stop_ev)\\n"\n            "# Hold ownership briefly so the peer definitely attempts acquisition while this process is alive.\\n"\n            "time.sleep(5.0)\\n"\n            "m.log(\'session start\', cam)\\n"',
    "synchronize real overlap in multi-process listener test",
)

replace_once(
    "selftest.py",
    '              (o1.strip(), o2.strip(), tot_alerts, tot_audit, v_p.stdout.strip(), e1[-200:], e2[-200:]))\n',
    '              (o1.strip(), o2.strip(), tot_alerts, tot_audit, v_p.stdout.strip(), e1[-200:], e2[-200:], mp_exit_codes))\n',
    "report P0-E child process exit codes",
)

for name in ("notify.py", "registry.py", "mersad_live.py", "selftest.py"):
    ast.parse((root / name).read_text(encoding="utf-8"), filename=name)

# Emit targeted source context in CI logs so remaining Windows failures can be fixed from evidence.
for file_name, line_ranges in {
    "notify.py": [(1, 250)],
    "selftest.py": [(650, 720), (850, 970), (1330, 1375)],
    "mersad_live.py": [(1900, 1965)],
}.items():
    source_lines = (root / file_name).read_text(encoding="utf-8").splitlines()
    print(f"\\n===== WINDOWS-DIAG {file_name} =====", flush=True)
    if file_name == "notify.py":
        for idx, line in enumerate(source_lines, 1):
            if any(token in line.lower() for token in ("listener", "msvcrt.locking", "telegram")):
                lo, hi = max(1, idx - 5), min(len(source_lines), idx + 11)
                print(f"--- {file_name}:{lo}-{hi} ---", flush=True)
                for n in range(lo, hi + 1):
                    print(f"{n}: {source_lines[n-1]}", flush=True)
    else:
        for lo, hi in line_ranges:
            lo, hi = min(lo, len(source_lines)), min(hi, len(source_lines))
            print(f"--- {file_name}:{lo}-{hi} ---", flush=True)
            for n in range(lo, hi + 1):
                print(f"{n}: {source_lines[n-1]}", flush=True)

print("Patched Windows listener mutex, inherited private ACLs, and isolated Windows integration fixtures.")
