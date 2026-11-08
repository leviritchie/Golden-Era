"""Exclusive lock for Unity batch runs on the shared oldenera_factions project.

Unity refuses to open one project in two instances at once, and several agents share it.
Every Unity launch goes through this wrapper:

    python tools/homm3_vfx/unitylock.py run [--wait MINUTES] -- <command ...>

It takes the lock (an atomic mkdir), runs memgate, runs the command, and releases the lock on
exit, including after a failure. Exit codes: the command's own; 3 if the lock was not free within
--wait (default 30) minutes; 4 if memgate was full. The owner PID is this wrapper itself, so a lock
whose owner PID is gone is stale and is broken at once, unless a Unity.exe is still running on the
lock's -projectPath (an orphaned child of a killed wrapper); then it waits like any held lock. `python tools/homm3_vfx/unitylock.py status` shows the holder.
"""
import ctypes
import errno
import json, os, shutil, subprocess, sys, time, random
import math
import shlex

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOCK = os.path.join(ROOT, "artifacts", "homm3_vfx_experiments", "_unity.lock")
MEMGATE = os.path.join(ROOT, "tools", "homm3_def_retarget", "memgate.py")
LOCK_OWNER_GRACE_S = 5.0
sys.path.insert(0, os.path.join(ROOT, "tools"))
from resource_lock_guard import advisory_guard

class ProcessProbeError(RuntimeError):
    pass


class LockMetadataError(RuntimeError):
    pass


def normalize_project_path(path):
    return os.path.normcase(os.path.normpath(str(path).strip().strip('"')))


def project_path_from_args(args):
    for index, token in enumerate(args[:-1]):
        if str(token).lower() == "-projectpath":
            value = str(args[index + 1]).strip().strip('"')
            return value or None
    return None


def project_path_from_commandline(command_line):
    try:
        tokens = shlex.split(command_line, posix=False)
    except ValueError as exc:
        raise ProcessProbeError(f"could not parse Unity command line: {exc}") from exc
    for index, token in enumerate(tokens[:-1]):
        if token.strip('"').lower() != "-projectpath":
            continue
        value = tokens[index + 1].strip().strip('"')
        if not value:
            raise ProcessProbeError("Unity command line has an empty -projectPath")
        if index + 2 < len(tokens) and not tokens[index + 2].startswith("-"):
            raise ProcessProbeError("Unity command line has an ambiguous unquoted -projectPath")
        return value
    if any(token.strip('"').lower() == "-projectpath" for token in tokens):
        raise ProcessProbeError("Unity command line has a missing -projectPath value")
    return None


def pid_alive(pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ProcessProbeError(f"invalid process PID {pid!r}: {exc}") from exc
    if pid <= 0:
        raise ProcessProbeError(f"invalid process PID {pid!r}: PID must be positive")
    if pid > 0xFFFFFFFF:
        raise ProcessProbeError(f"invalid process PID {pid}: exceeds the Win32 DWORD range")
    if os.name == "nt":
        handle = None
        kernel32 = None
        probe_failed = False
        try:
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            try:
                handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            except Exception as exc:
                raise ProcessProbeError(f"OpenProcess failed for PID {pid}: {exc}") from exc
            if not handle:
                try:
                    error = ctypes.get_last_error()
                except Exception as exc:
                    raise ProcessProbeError(
                        f"OpenProcess failed for PID {pid}; could not read Win32 error: {exc}"
                    ) from exc
                if error == 87:                              # ERROR_INVALID_PARAMETER: no such PID
                    return False
                if error == 5:                               # ERROR_ACCESS_DENIED: may be live
                    return True
                raise ProcessProbeError(f"OpenProcess failed for PID {pid}: WinError {error}")
            code = wintypes.DWORD()
            try:
                exit_ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            except Exception as exc:
                raise ProcessProbeError(f"GetExitCodeProcess failed for PID {pid}: {exc}") from exc
            if not exit_ok:
                try:
                    error = ctypes.get_last_error()
                except Exception as exc:
                    raise ProcessProbeError(
                        f"GetExitCodeProcess failed for PID {pid}; could not read Win32 error: {exc}"
                    ) from exc
                raise ProcessProbeError(f"GetExitCodeProcess failed for PID {pid}: WinError {error}")
            return code.value == 259                  # STILL_ACTIVE
        except ProcessProbeError:
            probe_failed = True
            raise
        except Exception as exc:
            probe_failed = True
            raise ProcessProbeError(f"Windows PID probe failed for PID {pid}: {exc}") from exc
        except BaseException:
            probe_failed = True
            raise
        finally:
            if handle:
                try:
                    close_ok = kernel32.CloseHandle(handle)
                except Exception as exc:
                    if not probe_failed:
                        raise ProcessProbeError(f"CloseHandle failed for PID {pid}: {exc}") from exc
                else:
                    if not close_ok and not probe_failed:
                        try:
                            error = ctypes.get_last_error()
                        except Exception as exc:
                            raise ProcessProbeError(
                                f"CloseHandle failed for PID {pid}; could not read Win32 error: {exc}"
                            ) from exc
                        raise ProcessProbeError(f"CloseHandle failed for PID {pid}: WinError {error}")
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return False
        if exc.errno == errno.EPERM:
            return True
        raise ProcessProbeError(f"os.kill liveness probe failed for PID {pid}: {exc}") from exc
    except Exception as exc:
        raise ProcessProbeError(f"process liveness probe failed for PID {pid}: {exc}") from exc
    return True


def list_unity_processes():
    if os.name != "nt":
        raise ProcessProbeError("Unity process inventory requires Windows CIM")
    command = (
        "$ErrorActionPreference = 'Stop'; "
        "try { $rows = @(Get-CimInstance -ClassName Win32_Process -Filter \"Name='Unity.exe'\" "
        "-ErrorAction Stop | Select-Object ProcessId,CommandLine); "
        "ConvertTo-Json -InputObject $rows -Compress -Depth 3 } "
        "catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProcessProbeError(f"Unity CIM process inventory failed: {exc}") from exc
    if result.returncode != 0:
        raise ProcessProbeError(
            f"Unity CIM process inventory exited {result.returncode}: {result.stderr.strip() or result.stdout.strip()}"
        )
    output = result.stdout.strip()
    if not output:
        raise ProcessProbeError("Unity CIM process inventory returned no JSON")
    try:
        rows = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ProcessProbeError(f"Unity CIM process inventory returned invalid JSON: {exc}") from exc
    if rows is None:
        raise ProcessProbeError("Unity CIM process inventory returned JSON null instead of an array")
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        raise ProcessProbeError("Unity CIM process inventory returned an unexpected JSON shape")
    normalized = []
    for row in rows:
        if not isinstance(row, dict):
            raise ProcessProbeError("Unity CIM process inventory included a malformed row")
        try:
            pid = int(row["ProcessId"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ProcessProbeError("Unity CIM process inventory included a row without a valid PID") from exc
        if pid <= 0:
            raise ProcessProbeError("Unity CIM process inventory included a nonpositive PID")
        normalized.append({"ProcessId": pid, "CommandLine": row.get("CommandLine")})
    return normalized

def unity_running_on(cmd, project_path=None):
    """True if Unity is on the exact project; ambiguous process data fails closed."""
    if project_path is None:
        try:
            project_path = project_path_from_commandline(cmd)
        except ProcessProbeError:
            return True
    rows = list_unity_processes()
    if not project_path:
        return bool(rows)
    target = normalize_project_path(project_path)
    for row in rows:
        command_line = row.get("CommandLine") or ""
        if not command_line:
            return True
        try:
            running_project = project_path_from_commandline(command_line)
        except ProcessProbeError:
            return True
        if not running_project or normalize_project_path(running_project) == target:
            return True
    return False

def holder(lock_path=None):
    """Read complete lock metadata; absence is distinct from corrupt or unreadable ownership."""
    lock_path = LOCK if lock_path is None else lock_path
    owner_path = os.path.join(lock_path, "owner.json")
    try:
        with open(owner_path, encoding="utf-8") as f:
            value = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LockMetadataError(
            f"cannot read Unity lock metadata at {owner_path}: {exc}; lock preserved. "
            "Inspect the owner and repair/remove the lock only after confirming its process is stopped."
        ) from exc
    if not isinstance(value, dict):
        raise LockMetadataError(
            f"invalid Unity lock metadata at {owner_path}: expected a JSON object; lock preserved. "
            "Inspect the owner and repair/remove the lock only after confirming its process is stopped."
        )
    try:
        raw_pid = value["pid"]
        if isinstance(raw_pid, bool) or not isinstance(raw_pid, (int, str)):
            raise TypeError("pid must be an integer")
        pid = int(raw_pid)
    except (KeyError, TypeError, ValueError) as exc:
        raise LockMetadataError(
            f"invalid Unity lock metadata at {owner_path}: missing or invalid pid; lock preserved. "
            "Inspect the owner and repair/remove the lock only after confirming its process is stopped."
        ) from exc
    if pid <= 0:
        raise LockMetadataError(
            f"invalid Unity lock metadata at {owner_path}: pid must be positive; lock preserved. "
            "Inspect the owner and repair/remove the lock only after confirming its process is stopped."
        )
    return value


def remove_stale_lock(expected_holder, lock_path=None):
    """Remove an unchanged dead-owner lock only while holding its nonblocking mutation guard."""
    lock_path = LOCK if lock_path is None else lock_path
    guard_path = str(lock_path) + ".reap.lock"
    with advisory_guard(guard_path) as acquired:
        if not acquired or holder(lock_path) != expected_holder:
            return False
        try:
            pid = int(expected_holder["pid"])
        except (KeyError, TypeError, ValueError):
            return False
        if pid_alive(pid):
            return False
        if unity_running_on(expected_holder.get("cmd", ""), expected_holder.get("projectPath")):
            return False
        shutil.rmtree(lock_path, ignore_errors=True)
        return not os.path.exists(lock_path)


def release_owned_lock(pid=None, lock_path=None):
    """Release this process's unchanged lock owner without deleting a replacement."""
    lock_path = LOCK if lock_path is None else lock_path
    self_pid = os.getpid() if pid is None else int(pid)
    expected = holder(lock_path)
    if not expected or expected.get("pid") != self_pid:
        return False
    with advisory_guard(str(lock_path) + ".reap.lock") as acquired:
        if acquired and holder(lock_path) == expected:
            shutil.rmtree(lock_path, ignore_errors=True)
            return not os.path.exists(lock_path)
    return False

def acquire(wait_min, cmd):
    try:
        wait_min = float(wait_min)
    except (TypeError, ValueError):
        print(f"UNITYLOCK invalid wait timeout {wait_min!r}", flush=True)
        return False
    if not math.isfinite(wait_min) or wait_min < 0:
        print(f"UNITYLOCK invalid wait timeout {wait_min!r}", flush=True)
        return False
    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
    deadline = time.monotonic() + wait_min * 60
    while True:
        try:
            os.mkdir(LOCK)
            try:
                owner_path = os.path.join(LOCK, "owner.json")
                temporary_path = owner_path + f".tmp-{os.getpid()}"
                with open(temporary_path, "x", encoding="utf-8") as f:
                    json.dump({"pid": os.getpid(), "since": time.time(), "cmd": " ".join(cmd)[:300],
                               "projectPath": project_path_from_args(cmd)}, f)
                os.replace(temporary_path, owner_path)
            except BaseException:
                shutil.rmtree(LOCK, ignore_errors=True)
                raise
            return True
        except FileExistsError:
            try:
                h = holder()
                missing_owner_remaining = None
                if h is None and os.path.isdir(LOCK):
                    try:
                        age = time.time() - os.path.getmtime(LOCK)
                    except FileNotFoundError:
                        age = None
                    except OSError as exc:
                        raise LockMetadataError(
                            f"cannot inspect Unity lock directory {LOCK}: {exc}; lock preserved"
                        ) from exc
                    if age is not None:
                        if age >= LOCK_OWNER_GRACE_S:
                            raise LockMetadataError(
                                f"Unity lock at {LOCK} has no owner.json after {LOCK_OWNER_GRACE_S:g}s; lock preserved. "
                                "Inspect the owner and repair/remove the lock only after confirming its process is stopped."
                            )
                        missing_owner_remaining = LOCK_OWNER_GRACE_S - age
            except LockMetadataError as exc:
                print(f"UNITYLOCK metadata invalid: {exc}", flush=True)
                return False
            try:
                alive = pid_alive(h["pid"]) if h else True
            except ProcessProbeError as exc:
                print(f"UNITYLOCK process probe failed; keeping lock at {LOCK} for {h}: {exc}", flush=True)
                return False
            if h and not alive:
                try:
                    removed = remove_stale_lock(h)
                except ProcessProbeError as exc:
                    print(f"UNITYLOCK process probe failed; keeping lock {h}: {exc}", flush=True)
                    return False
                if removed:
                    print(f"UNITYLOCK breaking stale lock {h}", flush=True)
                    continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                print(f"UNITYLOCK BUSY held by {h}"); return False
            delay = min(20 + random.uniform(0, 10), remaining)
            if missing_owner_remaining is not None:
                delay = min(delay, missing_owner_remaining)
            time.sleep(delay)

def main(argv=None):
    a = sys.argv[1:] if argv is None else argv
    if a[:1] == ["status"]:
        try:
            current_holder = holder()
            if current_holder is not None:
                print(current_holder)
                return 0
            if not os.path.isdir(LOCK):
                print("UNITYLOCK free")
                return 0
            try:
                age = time.time() - os.path.getmtime(LOCK)
            except FileNotFoundError:
                print("UNITYLOCK free")
                return 0
            except OSError as exc:
                raise LockMetadataError(f"cannot inspect Unity lock directory {LOCK}: {exc}; lock preserved") from exc
            if age < LOCK_OWNER_GRACE_S:
                remaining = max(0.0, LOCK_OWNER_GRACE_S - age)
                print(f"UNITYLOCK owner metadata pending at {LOCK} (creation grace {remaining:.1f}s remaining)")
                return 3
            raise LockMetadataError(
                f"Unity lock at {LOCK} has no owner.json after {LOCK_OWNER_GRACE_S:g}s; lock preserved. "
                "Inspect the owner and repair/remove the lock only after confirming its process is stopped."
            )
        except LockMetadataError as exc:
            print(f"UNITYLOCK metadata invalid: {exc}", file=sys.stderr, flush=True)
            return 5
    if a[:1] != ["run"] or "--" not in a:
        print(__doc__); return 2
    try:
        wait = float(a[a.index("--wait") + 1]) if "--wait" in a[:a.index("--")] else 30.0
    except (IndexError, ValueError):
        print("UNITYLOCK invalid --wait value", file=sys.stderr)
        return 2
    if not math.isfinite(wait) or wait < 0:
        print("UNITYLOCK invalid --wait value", file=sys.stderr)
        return 2
    cmd = a[a.index("--") + 1:]
    if subprocess.run([sys.executable, MEMGATE, "--wait", "6"]).returncode != 0:
        print("UNITYLOCK memgate full; not launching")
        return 4
    if not acquire(wait, cmd):
        return 3
    try:
        if subprocess.run([sys.executable, MEMGATE]).returncode != 0:
            print("UNITYLOCK memgate full; not launching"); return 4
        return subprocess.run(cmd).returncode
    finally:
        release_owned_lock()

if __name__ == "__main__":
    sys.exit(main())
