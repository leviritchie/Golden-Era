#!/usr/bin/env python3
"""Unity queue runner: agents submit Unity batch jobs; one runner batches them into one Unity launch per project.

    python tools/unity_queue/unity_queue.py submit --kind K --project P --method Type.Method [--input F ...]
           [--output-dir D] [--log L] [--build-target T] [--graphics] [--requester R] [--wait] [--timeout S] -- <args>
    python tools/unity_queue/unity_queue.py run [--once] [--gather S] [--max-batch N] [--poll S]
    python tools/unity_queue/unity_queue.py status [--recent N]
    python tools/unity_queue/unity_queue.py warmup --project P [--wait]      (cold/incomplete Library: the only job allowed)
    python tools/unity_queue/unity_queue.py library-check --project P       (dry: is the Library cold? launches nothing)

Python callers use launch() (one call: submit, drain/wait, copy the job's log slice to the caller's log path).
Contract and usage: docs/unity_queue_runner.md. Agents must submit, not launch.

Queue: V:/olden_port_work/unity_queue/{pending,running,done,failed} (UNITY_QUEUE_ROOT overrides it, for tests).
A job is <id>.json; a finished job also has <id>.result.json and <id>.log (its slice of the launch log) beside it.

Batching: a drain takes the shared Unity lock (tools/homm3_vfx/unitylock.py's lock dir, so the queue and the
remaining unitylock callers never run two editors), claims every pending job (atomic rename into running/), groups
them by (Unity.exe, project, buildTarget, graphics) and runs one launch per group through
UnityQueueDispatcher.RunBatch (tools/unity_queue/unity/UnityQueueDispatcher.cs, staged into the project). Identical
jobs (same dedupe key: kind, executeMethod, args, launch fields, input content hashes) are run once: submit returns
the queued/running job's id, and a duplicate that raced in is resolved from its twin's result.

Fail closed: a job whose method throws (or calls UnityQueueExit(nonzero)) is failed with its log excerpt and the
batch continues; a Unity crash, compile failure or timeout fails every job that launch did not report, naming the
launch exit code; a refused preflight (game running, memgate/launch_guard, a Unity already on the project, inputs
changed since submit) fails the job with that reason. There is no fallback to a direct launch: --unity-direct on a
caller is the explicit, loudly logged opt-out.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import importlib.util
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QUEUE_ROOT = Path(os.environ.get("UNITY_QUEUE_ROOT", "").strip() or "V:/olden_port_work/unity_queue")
STATES = ("pending", "running", "done", "failed")
DEFAULT_UNITY = Path("C:/Program Files/Unity/Hub/Editor/6000.0.66f2/Editor/Unity.exe")
DISPATCHER_SRC = Path(__file__).resolve().parent / "unity" / "UnityQueueDispatcher.cs"
DISPATCHER_REL = Path("Assets/Editor/UnityQueue/UnityQueueDispatcher.cs")
DISPATCH_METHOD = "UnityQueueDispatcher.RunBatch"
MEMGATE = ROOT / "tools/homm3_def_retarget/memgate.py"
LAUNCH_GUARD = ROOT / "tools/homm3_def_retarget/launch_guard.py"
JOB_SCHEMA = "unity_queue_job.v1"
RESULT_SCHEMA = "unity_queue_result.v1"
# launch-level flags belong to the job's fields, never to its args
RESERVED_ARGS = {"-batchmode", "-quit", "-nographics", "-projectPath", "-executeMethod", "-logFile", "-buildTarget",
                 "-unityQueueBatch"}
HASH_LIMIT = 512 * 2 ** 20  # inputs larger than this are keyed by size + mtime instead of content
MEMORY_WAIT_MIN = 6
ORPHAN_RECOVERY_INTERVAL_S = 15.0
_last_orphan_recovery = 0.0
# Cold/incomplete Library guard (2026-10-08: a wiped Library silently reimported inside a lab job and filled V: twice).
# A wipe of <project>/Library must create <project>/.library_wiped; a successful warm-up job removes it.
LIBRARY_WIPED_MARKER = ".library_wiped"
WARMUP_KIND = "library_warmup"
WARMUP_METHOD = "UnityQueue.LibraryWarmup"  # sentinel: a warm-up launches -batchmode -quit with no -executeMethod
WARMUP_TIMEOUT_S = 6 * 3600
INITIAL_REFRESH_END = "Application.AssetDatabase Initial Refresh End"  # Unity 6000.0 prints it once a refresh completes
COLD_LOG_MARKERS = ("Rebuilding Library because the asset database could not be found",
                    "Failed to write the asset file")
WARMUP_MIN_FREE_GB = float(os.environ.get("UNITY_QUEUE_WARMUP_MIN_FREE_GB", "").strip() or 40)
LOW_DISK_WARN_GB = float(os.environ.get("UNITY_QUEUE_LOW_DISK_GB", "").strip() or 10)
DISK_WATCH_INTERVAL_S = 30.0
LOW_DISK_FLAG = "LOW_DISK.flag"

_ul_spec = importlib.util.spec_from_file_location("unity_queue_unitylock", ROOT / "tools/homm3_vfx/unitylock.py")
unitylock = importlib.util.module_from_spec(_ul_spec)
_ul_spec.loader.exec_module(unitylock)
_mg_spec = importlib.util.spec_from_file_location("unity_queue_memgate", MEMGATE)
memgate = importlib.util.module_from_spec(_mg_spec)
_mg_spec.loader.exec_module(memgate)


class QueueError(RuntimeError):
    pass


@dataclass(frozen=True)
class CapacityWaitResult:
    refusal: str | None = None
    aborted: bool = False
    probe_failed: bool = False


# ------------------------------------------------------------------------------------------------ paths / io
def qdir(state: str) -> Path:
    d = QUEUE_ROOT / state
    d.mkdir(parents=True, exist_ok=True)
    return d


def now() -> float:
    return time.time()


def stamp(t: float | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now() if t is None else t))


def load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def dump(p: Path, value) -> None:
    tmp = p.with_name(p.name + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(value, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def norm_project(p) -> str:
    return os.path.normcase(os.path.realpath(str(p)))


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fingerprint_input(path: str) -> dict:
    p = Path(path)
    if p.is_file():
        st = p.stat()
        if st.st_size <= HASH_LIMIT:
            return {"path": str(p), "sha256": sha256_file(p)}
        return {"path": str(p), "size": st.st_size, "mtimeNs": st.st_mtime_ns}
    if p.is_dir():
        h = hashlib.sha256()
        for f in sorted(x for x in p.rglob("*") if x.is_file()):
            st = f.stat()
            h.update(f"{f.relative_to(p).as_posix()}\0{st.st_size}\0{st.st_mtime_ns}\n".encode())
        return {"path": str(p), "dirListingSha256": h.hexdigest()}
    raise QueueError(f"input does not exist: {p}")


def pid_alive(pid: int) -> bool:
    return unitylock.pid_alive(pid)


# ------------------------------------------------------------------------------------------------ submit
def make_job(*, kind: str, execute_method: str, args: list, project, unity=DEFAULT_UNITY, inputs=(), output_dir=None,
             requester=None, build_target=None, graphics=False, log=None, timeout_s=5400) -> dict:
    args = [str(a) for a in args]
    if (kind == WARMUP_KIND) != (execute_method == WARMUP_METHOD) or (kind == WARMUP_KIND and args):
        raise QueueError(f"a warm-up job is kind {WARMUP_KIND} with method {WARMUP_METHOD} and no args "
                         f"(`unity_queue.py warmup --project P`)")
    bad = sorted(set(args) & RESERVED_ARGS)
    if bad:
        raise QueueError(f"job args may not carry launch-level flags {bad}; they are job fields")
    if not re.fullmatch(r"[A-Za-z0-9_.]+\.[A-Za-z0-9_]+", execute_method):
        raise QueueError(f"executeMethod must be Namespace.Type.Method: {execute_method!r}")
    if not Path(unity).is_file():
        raise QueueError(f"Unity.exe not found: {unity}")
    if not (Path(project) / "Assets").is_dir():
        raise QueueError(f"not a Unity project (no Assets/): {project}")
    fps = [fingerprint_input(str(i)) for i in inputs]
    launch = {"unity": str(Path(unity)), "project": norm_project(project), "buildTarget": build_target or None,
              "graphics": bool(graphics)}
    key = hashlib.sha256(json.dumps({"kind": kind, "executeMethod": execute_method, "args": args, **launch,
                                     "inputs": fps}, sort_keys=True).encode()).hexdigest()
    safe_kind = re.sub(r"[^A-Za-z0-9_-]+", "_", kind)[:40]
    jid = f"{time.strftime('%Y%m%dT%H%M%S')}_{safe_kind}_{key[:10]}_{random.randrange(16 ** 4):04x}"
    return {"schema": JOB_SCHEMA, "id": jid, "key": key, "kind": kind, "executeMethod": execute_method, "args": args,
            "inputs": fps, "outputDir": str(output_dir) if output_dir else None,
            "requester": requester or f"{Path(sys.argv[0]).name} pid {os.getpid()}", **launch,
            "projectPathAsGiven": str(project), "log": str(log) if log else None, "timeoutSeconds": int(timeout_s),
            "submittedAt": now()}


def find_live_twin(key: str) -> str | None:
    for state in ("pending", "running"):
        for f in qdir(state).glob("*.json"):
            try:
                if load(f).get("key") == key:
                    return f.stem
            except (OSError, ValueError):
                continue
    return None


def submit(job: dict) -> tuple[str, bool]:
    """Queue the job; returns (id, deduped). An identical pending/running job is reused, not queued twice."""
    twin = find_live_twin(job["key"])
    if twin:
        return twin, True
    dump(qdir("pending") / f"{job['id']}.json", job)
    return job["id"], False


def result_path(jid: str) -> Path | None:
    for state in ("done", "failed"):
        p = QUEUE_ROOT / state / f"{jid}.result.json"
        if p.is_file():
            return p
    return None


def result(jid: str) -> dict | None:
    p = result_path(jid)
    return load(p) if p else None


def wait_for(jid: str, timeout_s: float, drain: bool = True) -> dict:
    """Block until the job has a result. While it is pending and no other drain holds the lock, this process drains
    the queue itself (one launch for everything pending, the job included): no daemon is required."""
    if not math.isfinite(timeout_s) or timeout_s < 0:
        raise QueueError(f"invalid wait timeout: {timeout_s!r}")
    deadline = time.monotonic() + timeout_s
    while True:
        r = result(jid)
        if r:
            return r
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise QueueError(f"timed out after {timeout_s:.0f}s waiting for job {jid} (it remains in its current "
                             f"queue state; "
                             f"`unity_queue.py status`)")
        pending_path = QUEUE_ROOT / "pending" / f"{jid}.json"
        if drain and pending_path.is_file():
            def abort_wait() -> bool:
                return result_path(jid) is not None or not pending_path.is_file()

            drain_once(abort=abort_wait, lock_wait_s=remaining, capacity_wait_s=remaining)
            if result_path(jid):
                continue
            if time.monotonic() >= deadline:
                raise QueueError(f"timed out after {timeout_s:.0f}s waiting for job {jid} (it remains in its current "
                                 f"queue state; "
                                 f"`unity_queue.py status`)")
            continue
        recover_orphans()
        if not any((QUEUE_ROOT / s / f"{jid}.json").is_file() for s in ("pending", "running", "done", "failed")):
            raise QueueError(f"job {jid} is in no queue state; was the queue dir cleaned?")
        time.sleep(min(5, max(0, deadline - time.monotonic())))


# ------------------------------------------------------------------------------------------------ lock
def unity_processes() -> list[dict]:
    return unitylock.list_unity_processes()


def unity_on_project(project: str, given: str) -> list[int]:
    """PIDs of Unity editors open on the project (by command line, either spelling), plus a held Temp/UnityLockfile."""
    keys = {unitylock.normalize_project_path(project), unitylock.normalize_project_path(given)}
    pids = []
    unknown_pids = []
    for row in unity_processes():
        command_line = row.get("CommandLine") or ""
        if not command_line:
            unknown_pids.append(int(row["ProcessId"]))
            continue
        try:
            editor_project = unitylock.project_path_from_commandline(command_line)
        except unitylock.ProcessProbeError:
            unknown_pids.append(int(row["ProcessId"]))
            continue
        if not editor_project:
            unknown_pids.append(int(row["ProcessId"]))
            continue
        if unitylock.normalize_project_path(editor_project) in keys:
            pids.append(int(row["ProcessId"]))
    lockfile = Path(project) / "Temp" / "UnityLockfile"
    if lockfile.exists():
        try:
            with open(lockfile, "a"):
                pass
        except PermissionError:
            pids.append(-1)  # the editor holds its project lockfile open: running, PID unknown
    pids.extend(unknown_pids)
    return pids


def acquire_unity_lock(note: str, wait_s: float, abort=None) -> bool:
    """The shared unitylock lock dir (one Unity on this machine at a time). False if aborted or not free in time."""
    if not math.isfinite(wait_s) or wait_s < 0:
        raise QueueError(f"invalid Unity lock wait timeout: {wait_s!r}")
    lock = Path(unitylock.LOCK)
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + max(0.0, wait_s)
    while True:
        try:
            os.mkdir(lock)
            try:
                owner_path = lock / "owner.json"
                temporary_path = lock / f"owner.json.tmp-{os.getpid()}"
                temporary_path.write_text(
                    json.dumps({"pid": os.getpid(), "since": now(), "cmd": note[:300]}), encoding="utf-8")
                os.replace(temporary_path, owner_path)
            except BaseException:
                shutil.rmtree(lock, ignore_errors=True)
                raise
            return True
        except FileExistsError:
            try:
                h = unitylock.holder()
            except unitylock.LockMetadataError as e:
                raise QueueError(f"Unity lock metadata is invalid: {e}") from e
            missing_owner_remaining = None
            if h is None and lock.is_dir():
                try:
                    age = time.time() - lock.stat().st_mtime
                except FileNotFoundError:
                    age = None
                except OSError as e:
                    raise QueueError(f"cannot inspect Unity lock directory {lock}: {e}; lock preserved") from e
                if age is not None:
                    if age >= unitylock.LOCK_OWNER_GRACE_S:
                        raise QueueError(
                            f"Unity lock at {lock} has no owner.json after {unitylock.LOCK_OWNER_GRACE_S:g}s; "
                            "lock preserved. Inspect the owner and repair/remove the lock only after confirming "
                            "its process is stopped."
                        )
                    missing_owner_remaining = unitylock.LOCK_OWNER_GRACE_S - age
            owner_pid = None
            if h:
                raw_owner_pid = h.get("pid")
                try:
                    if isinstance(raw_owner_pid, bool):
                        raise ValueError("PID must be an integer")
                    owner_pid = int(raw_owner_pid)
                    if owner_pid <= 0:
                        raise ValueError("PID must be positive")
                except (TypeError, ValueError, OverflowError) as e:
                    raise QueueError(
                        f"Unity lock at {lock} has an invalid owner PID {raw_owner_pid!r}; lock preserved"
                    ) from e
                try:
                    alive = pid_alive(owner_pid)
                except unitylock.ProcessProbeError as e:
                    raise QueueError(
                        f"Unity process probe failed for lock owner PID {owner_pid} at {lock}: {e}; lock preserved"
                    ) from e
            else:
                alive = True
            if h and not alive:
                try:
                    removed = unitylock.remove_stale_lock(h)
                except unitylock.ProcessProbeError as e:
                    raise QueueError(f"Unity process probe failed while checking stale lock {h}: {e}") from e
                if removed:
                    print(f"UNITY_QUEUE breaking stale unity lock {h}", flush=True)
                    continue
            if abort and abort():
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                print(f"UNITY_QUEUE unity lock busy, held by {h}", flush=True)
                return False
            delay = min(10 + random.uniform(0, 5), remaining)
            if missing_owner_remaining is not None:
                delay = min(delay, missing_owner_remaining)
            time.sleep(delay)


def set_lock_note(note: str, project_path: str | None = None) -> None:
    owner_path = Path(unitylock.LOCK) / "owner.json"
    temporary_path = owner_path.with_name(f"owner.json.tmp-{os.getpid()}")
    try:
        temporary_path.write_text(json.dumps({"pid": os.getpid(), "since": now(),
                                               "cmd": note[:300], "projectPath": project_path}), encoding="utf-8")
        os.replace(temporary_path, owner_path)
    except OSError:
        try:
            temporary_path.unlink()
        except OSError:
            pass
        pass


def release_unity_lock() -> None:
    unitylock.release_owned_lock()


# ------------------------------------------------------------------------------------------------ run
def finish(job: dict, state: str, res: dict, log_text: str) -> dict:
    jid = job["id"]
    dest = qdir(state)
    (dest / f"{jid}.log").write_text(log_text, encoding="utf-8")
    full = {"schema": RESULT_SCHEMA, "id": jid, "key": job["key"], "kind": job["kind"],
            "executeMethod": job["executeMethod"], "requester": job["requester"], "finishedAt": stamp(),
            "jobLog": str(dest / f"{jid}.log"), **res}
    dump(dest / f"{jid}.result.json", full)
    src = QUEUE_ROOT / "running" / f"{jid}.json"
    if src.is_file():
        os.replace(src, dest / f"{jid}.json")
    else:
        dump(dest / f"{jid}.json", job)
    print(f"UNITY_QUEUE {full['status'].upper()} {jid} {job['executeMethod']}"
          + (f" -- {res.get('error')}" if res.get("error") else ""), flush=True)
    return full


def recover_orphans(*, force: bool = False) -> int:
    """Fail dead runner jobs, probing each distinct PID at most once per scan."""
    global _last_orphan_recovery
    tick = time.monotonic()
    if not force and tick - _last_orphan_recovery < ORPHAN_RECOVERY_INTERVAL_S:
        return 0
    running = []
    for f in qdir("running").glob("*.json"):
        try:
            job = load(f)
        except (OSError, ValueError) as exc:
            raise QueueError(f"cannot inspect running job {f}: {exc}; no orphan recovery was performed") from exc
        if not isinstance(job, dict):
            raise QueueError(f"running job {f} is not a JSON object; no orphan recovery was performed")
        claim = job.get("claim")
        if not isinstance(claim, dict):
            raise QueueError(f"running job {f} has no valid claim metadata; no orphan recovery was performed")
        raw_pid = claim.get("pid")
        try:
            if isinstance(raw_pid, bool):
                raise ValueError("PID must be an integer")
            pid = int(raw_pid)
            if pid <= 0:
                raise ValueError("PID must be positive")
        except (TypeError, ValueError, OverflowError) as exc:
            raise QueueError(
                f"running job {f} has an invalid runner PID {raw_pid!r}; no orphan recovery was performed"
            ) from exc
        if pid != os.getpid():
            running.append((pid, job))
    try:
        liveness = {pid: pid_alive(pid) for pid in sorted({pid for pid, _ in running})}
    except unitylock.ProcessProbeError as exc:
        raise QueueError(f"Unity queue runner process probe failed; no orphan recovery was performed: {exc}") from exc
    recovered = 0
    for pid, job in running:
        if not liveness[pid]:
            finish(job, "failed", {"status": "failed", "exitCode": None,
                                   "error": f"runner pid {pid} died while the job was running; no result was recorded "
                                            f"(the Unity launch it owned was killed or crashed); resubmit",
                                   "logExcerpt": [], "outputs": {}}, "")
            recovered += 1
    _last_orphan_recovery = tick
    return recovered


def claim_pending() -> list[dict]:
    jobs = []
    for f in sorted(qdir("pending").glob("*.json"), key=lambda p: p.name):  # ids start with the submit time
        dst = qdir("running") / f.name
        try:
            os.rename(f, dst)
        except (FileNotFoundError, FileExistsError, PermissionError):
            continue  # another drain claimed it
        try:
            job = load(dst)
        except (OSError, ValueError) as e:
            os.replace(dst, qdir("failed") / f.name)
            print(f"UNITY_QUEUE unreadable job file {f.name}: {e}", flush=True)
            continue
        job["claim"] = {"pid": os.getpid(), "at": now()}
        dump(dst, job)
        jobs.append(job)
    return jobs


def excerpt(text: str, tail: int = 60) -> list[str]:
    lines = text.splitlines()
    errs = [l for l in lines[:-tail] if re.search(r"error|exception|failed", l, re.I)][-20:]
    return ([*errs, "..."] if errs else []) + lines[-tail:]


def outputs_since(output_dir: str | None, since: float) -> dict:
    if not output_dir or not Path(output_dir).is_dir():
        return {}
    out = {}
    for f in sorted(Path(output_dir).rglob("*")):
        if f.is_file() and f.stat().st_mtime >= since - 1:
            out[str(f.relative_to(output_dir).as_posix())] = sha256_file(f)
            if len(out) >= 500:
                break
    return out


def stage_dispatcher(project) -> None:
    dst = Path(project) / DISPATCHER_REL
    if dst.is_file() and dst.read_bytes() == DISPATCHER_SRC.read_bytes():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DISPATCHER_SRC, dst)


def wait_for_capacity(abort=None, timeout_s: float | None = None) -> CapacityWaitResult:
    """Wait for generic launch capacity without holding the Unity execution lock."""
    internal_limit = MEMORY_WAIT_MIN * 60
    try:
        requested = internal_limit if timeout_s is None else float(timeout_s)
    except (TypeError, ValueError):
        return CapacityWaitResult("invalid capacity wait timeout", probe_failed=True)
    if not math.isfinite(requested) or requested < 0:
        return CapacityWaitResult("invalid capacity wait timeout", probe_failed=True)
    caller_limited = timeout_s is not None
    deadline = time.monotonic() + min(internal_limit, requested)
    last_capacity = None
    while True:
        if abort and abort():
            return CapacityWaitResult(aborted=True)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            if caller_limited:
                return CapacityWaitResult(aborted=True)
            if last_capacity is None:
                return CapacityWaitResult(refusal="memgate capacity wait expired before a probe completed")
            free_ram, free_vram = last_capacity
            refusal = (f"memgate refused after {MEMORY_WAIT_MIN} min: free RAM {free_ram:.1f} GB "
                       f"(need {memgate.MIN_RAM_GB:.1f}), free VRAM {free_vram:.1f} GB "
                       f"(need {memgate.MIN_VRAM_GB:.1f})")
            return CapacityWaitResult(refusal=refusal)
        try:
            ok, free_ram, free_vram = memgate.check(timeout_s=min(15.0, remaining))
        except memgate.ProbeError as e:
            if caller_limited and time.monotonic() >= deadline:
                return CapacityWaitResult(aborted=True)
            return CapacityWaitResult(f"memgate refused (probe failed): {e}", probe_failed=True)
        last_capacity = (free_ram, free_vram)
        if caller_limited and time.monotonic() >= deadline:
            return CapacityWaitResult(aborted=True)
        if ok:
            return CapacityWaitResult()
        if abort and abort():
            return CapacityWaitResult(aborted=True)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            if caller_limited:
                return CapacityWaitResult(aborted=True)
            refusal = (f"memgate refused after {MEMORY_WAIT_MIN} min: free RAM {free_ram:.1f} GB "
                       f"(need {memgate.MIN_RAM_GB:.1f}), free VRAM {free_vram:.1f} GB "
                       f"(need {memgate.MIN_VRAM_GB:.1f})")
            return CapacityWaitResult(refusal=refusal)
        time.sleep(min(30 + random.uniform(0, 15), remaining))


def free_gb(path) -> float:
    return shutil.disk_usage(path).free / 1024 ** 3


def log_project(log: Path) -> str | None:
    """The -projectPath a Unity log was started with (Unity echoes its command line at the top of the log)."""
    try:
        with open(log, "r", encoding="utf-8", errors="replace") as f:
            head = [f.readline().strip() for _ in range(60)]
    except OSError:
        return None
    return head[head.index("-projectPath") + 1] if "-projectPath" in head[:-1] else None


def latest_project_log(project: str) -> Path | None:
    """The project's most recent queue launch unity.log (launch ids start with their start time)."""
    launches = QUEUE_ROOT / "launches"
    if not launches.is_dir():
        return None
    key = norm_project(project)
    for d in sorted((p for p in launches.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True):
        log = d / "unity.log"
        if log.is_file() and (given := log_project(log)) and norm_project(given) == key:
            return log
    return None


def library_cold(project: str) -> str | None:
    """Why the project's Library is cold/incomplete (a launch would silently reimport it), or None when warm."""
    lib = Path(project) / "Library"
    if (Path(project) / LIBRARY_WIPED_MARKER).exists():
        return f"wipe marker {Path(project) / LIBRARY_WIPED_MARKER} present"
    missing = [n for n in ("ArtifactDB", "SourceAssetDB") if not (lib / n).exists()]
    if missing:
        return f"{lib} has no {' / '.join(missing)}"
    log = latest_project_log(project)
    if log:
        try:
            data = log.read_bytes()
        except OSError as e:
            return f"cannot read the last launch log {log}: {e}"
        hits = [m for m in COLD_LOG_MARKERS if m.encode() in data]
        if hits and INITIAL_REFRESH_END.encode() not in data:
            return f"the last launch log {log} has {hits[0]!r} and no completed refresh ({INITIAL_REFRESH_END!r})"
    return None


def library_refusal(project: str, given: str, warmup: bool) -> str | None:
    """Cold Library: refuse everything but the warm-up. The warm-up itself needs WARMUP_MIN_FREE_GB free."""
    free = free_gb(project)
    if warmup:
        if free < WARMUP_MIN_FREE_GB:
            return (f"Library warm-up needs {WARMUP_MIN_FREE_GB:.0f} GB free on {Path(project).anchor or project} "
                    f"(has {free:.1f}); a full rebuild of the unit project grew Library to ~100 GB")
        return None
    why = library_cold(project)
    if why:
        return (f"Library cold/incomplete ({why}): run the warm-up job (needs ~{WARMUP_MIN_FREE_GB:.0f} GB free, "
                f"{free:.1f} GB free now): python tools/unity_queue/unity_queue.py warmup --project \"{given}\" --wait")
    return None


def watch_disk(project: str, ldir: Path, launch_id: str, last_warn: float | None) -> float | None:
    """In-flight free-space watch: below LOW_DISK_WARN_GB, warn loudly and write a flag file. Never kills Unity."""
    try:
        free = free_gb(project)
    except OSError:
        return last_warn
    if free >= LOW_DISK_WARN_GB or (last_warn is not None and time.monotonic() - last_warn < 300):
        return last_warn
    msg = (f"UNITY_QUEUE LOW DISK: {free:.1f} GB free on {Path(project).anchor or project} (warn below "
           f"{LOW_DISK_WARN_GB:.0f} GB) during launch {launch_id}; Unity is NOT killed - the user decides")
    print("!" * 100 + "\n" + msg + "\n" + "!" * 100, file=sys.stderr, flush=True)
    flag = {"launchId": launch_id, "project": project, "freeGb": round(free, 2), "thresholdGb": LOW_DISK_WARN_GB,
            "at": stamp(), "message": msg}
    for p in (ldir / LOW_DISK_FLAG, QUEUE_ROOT / LOW_DISK_FLAG):
        try:
            dump(p, flag)
        except OSError:
            pass
    return time.monotonic()


def preflight(project: str, given: str, warmup: bool = False) -> str | None:
    """Zero-wait recheck after the Unity lock; a failed race refuses before any editor launch."""
    try:
        p = subprocess.run([sys.executable, str(LAUNCH_GUARD)], capture_output=True, text=True, cwd=ROOT)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"launch_guard failed: {e}"
    if p.returncode != 0:
        return f"launch_guard refused (rc {p.returncode}): {(p.stdout + p.stderr).strip()[-400:]}"
    try:
        refusal = library_refusal(project, given, warmup)
    except OSError as e:
        return f"Library/free-space check failed: {e}"
    if refusal:
        return refusal
    try:
        busy = unity_on_project(project, given)
    except unitylock.ProcessProbeError as e:
        return f"Unity process probe failed: {e}"
    if busy:
        return f"a Unity editor is already running on {project} (pids {busy}); one editor per project"
    return None


def run_launch(group: list[dict], capacity_wait: CapacityWaitResult | None = None) -> list[dict]:
    """One Unity launch for jobs that share (unity, project, buildTarget, graphics). Returns the results."""
    head = group[0]
    warmup = head["kind"] == WARMUP_KIND
    canon, twins = {}, {}
    for j in group:
        if j["key"] in canon:
            twins[j["id"]] = canon[j["key"]]["id"]
        else:
            canon[j["key"]] = j
    jobs = list(canon.values())
    by_id = {j["id"]: j for j in group}
    results = {}

    def fail_all(js, reason, log_text=""):
        for j in js:
            results[j["id"]] = finish(j, "failed", {"status": "failed", "exitCode": None, "error": reason,
                                                    "logExcerpt": excerpt(log_text), "outputs": {}}, log_text)

    stale = []
    for j in jobs:
        try:
            now_fps = [fingerprint_input(i["path"]) for i in j["inputs"]]
        except QueueError as e:
            now_fps = [{"error": str(e)}]
        if now_fps != j["inputs"]:
            stale.append(j)
    fail_all(stale, "inputs changed since submit (the dedupe key no longer describes them); resubmit")
    jobs = [j for j in jobs if j not in stale]
    if jobs:
        if capacity_wait and capacity_wait.probe_failed:
            reason = capacity_wait.refusal or "memgate probe failed"
        else:
            reason = preflight(head["project"], head["projectPathAsGiven"], warmup=warmup)
        if reason:
            fail_all(jobs, "launch refused: " + reason)
            jobs = []
    if jobs:
        launch_id = time.strftime("%Y%m%dT%H%M%S") + f"_{os.getpid()}_{random.randrange(16 ** 4):04x}"
        ldir = qdir("launches") / launch_id
        ldir.mkdir(parents=True)
        log, results_path = ldir / "unity.log", ldir / "results.jsonl"
        dump(ldir / "batch.json", {"launchId": launch_id, "resultsPath": str(results_path), "warmup": warmup,
                                   "jobs": [{"id": j["id"], "executeMethod": j["executeMethod"], "args": j["args"]}
                                            for j in jobs]})
        stage_dispatcher(head["projectPathAsGiven"])
        cmd = [head["unity"], "-batchmode", "-quit", *([] if head["graphics"] else ["-nographics"]),
               "-projectPath", head["projectPathAsGiven"],
               *(["-buildTarget", head["buildTarget"]] if head["buildTarget"] else []),
               *([] if warmup else ["-executeMethod", DISPATCH_METHOD, "-unityQueueBatch", str(ldir / "batch.json")]),
               "-logFile", str(log)]
        set_lock_note(f"unity_queue launch {launch_id} -projectPath {head['projectPathAsGiven']}",
                      project_path=head["projectPathAsGiven"])
        for j in jobs:
            j["launchId"] = launch_id
            dump(QUEUE_ROOT / "running" / f"{j['id']}.json", j)
        print(f"UNITY_QUEUE LAUNCH {launch_id}: {len(jobs)} job(s) on {head['projectPathAsGiven']}", flush=True)
        t0 = now()
        timeout = sum(j["timeoutSeconds"] for j in jobs) + 600
        timed_out = False
        low_disk = None
        with open(ldir / "host.log", "w", encoding="utf-8") as host:
            proc = subprocess.Popen(cmd, stdout=host, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + timeout
            while True:
                try:
                    rc = proc.wait(timeout=max(0.1, min(DISK_WATCH_INTERVAL_S, deadline - time.monotonic())))
                    break
                except subprocess.TimeoutExpired:
                    if time.monotonic() < deadline:
                        low_disk = watch_disk(head["projectPathAsGiven"], ldir, launch_id, low_disk)
                        continue
                    timed_out = True
                    proc.kill()  # our own Unity child only; never the game
                    rc = proc.wait()
                    break
        wall = round(now() - t0, 1)
        text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
        lines = text.splitlines()
        reported = {}
        if results_path.is_file():
            for l in results_path.read_text(encoding="utf-8").splitlines():
                if l.strip():
                    r = json.loads(l)
                    reported[r["id"]] = r
        dump(ldir / "launch.json", {"launchId": launch_id, "cmd": cmd, "jobs": [j["id"] for j in jobs],
                                    "unityExitCode": rc, "timedOut": timed_out, "wallSeconds": wall,
                                    "startedAt": stamp(t0), "reported": len(reported), "warmup": warmup,
                                    "lowDiskWarned": low_disk is not None})
        refreshed = INITIAL_REFRESH_END in text
        if warmup and rc == 0 and refreshed and not timed_out:
            (Path(head["projectPathAsGiven"]) / LIBRARY_WIPED_MARKER).unlink(missing_ok=True)
        for j in jobs:
            if warmup:
                ok = rc == 0 and refreshed and not timed_out
                why = None if ok else (f"Library warm-up {'timed out' if timed_out else f'exited {rc}'}"
                                       f"{'' if refreshed else ' without a completed refresh'}; see {log}")
                tail = "\n".join(lines[-2000:]) + "\n"
                results[j["id"]] = finish(j, "done" if ok else "failed", {
                    "launchId": launch_id, "launchLog": str(log), "launchExitCode": rc, "launchWallSeconds": wall,
                    "launchJobs": len(jobs), "outputs": {}, "status": "ok" if ok else "failed", "exitCode": rc,
                    "elapsedSeconds": wall, "error": why, "logExcerpt": excerpt(tail)}, tail)
                continue
            b = next((i for i, l in enumerate(lines) if l.startswith(f"UNITY_QUEUE_JOB_BEGIN {j['id']}")), None)
            e = next((i for i, l in enumerate(lines) if l.startswith(f"UNITY_QUEUE_JOB_END {j['id']}")), None)
            slice_text = "\n".join(lines[b:(e + 1 if e is not None else None)]) + "\n" if b is not None else ""
            base = {"launchId": launch_id, "launchLog": str(log), "launchExitCode": rc, "launchWallSeconds": wall,
                    "launchJobs": len(jobs), "outputs": outputs_since(j["outputDir"], t0)}
            r = reported.get(j["id"])
            if r:
                state = "done" if r["status"] == "ok" else "failed"
                results[j["id"]] = finish(j, state, {**base, "status": r["status"], "exitCode": r["exitCode"],
                                                     "elapsedSeconds": r["elapsedSeconds"], "error": r["error"],
                                                     "logExcerpt": excerpt(slice_text)}, slice_text)
            else:
                why = (f"Unity launch timed out after {timeout}s and was killed" if timed_out else
                       f"Unity launch ended with exit code {rc} before this job reported a result "
                       f"({'it started and did not finish: crash' if b is not None else 'it never started: compile error, crash or dispatcher failure'}); "
                       f"see {log}")
                ctx = slice_text or text
                results[j["id"]] = finish(j, "failed", {**base, "status": "failed", "exitCode": None, "error": why,
                                                        "logExcerpt": excerpt(ctx)}, ctx)
    for tid, cid in twins.items():
        c = results[cid]
        results[tid] = finish(by_id[tid], "done" if c["status"] == "ok" else "failed",
                              {k: v for k, v in c.items() if k not in ("schema", "id", "key", "kind", "executeMethod",
                                                                      "requester", "finishedAt", "jobLog")}
                              | {"dedupedInto": cid},
                              Path(c["jobLog"]).read_text(encoding="utf-8") if Path(c["jobLog"]).is_file() else "")
    return [results[j["id"]] for j in group]


def drain_once(max_batch: int = 16, gather_s: float = 0.0, lock_wait_s: float = 4 * 3600, abort=None,
               capacity_wait_s: float | None = None) -> int:
    """Wait for capacity, then take the Unity lock, claim, group, and launch. Returns launches run."""
    pending_at_start = {path.name for path in qdir("pending").glob("*.json")}
    if not pending_at_start:
        return 0

    def should_abort() -> bool:
        if abort and abort():
            return True
        pending_dir = qdir("pending")
        return not any((pending_dir / name).is_file() for name in pending_at_start)

    caller_deadline = None
    if capacity_wait_s is not None:
        try:
            wait_budget = float(capacity_wait_s)
        except (TypeError, ValueError) as e:
            raise QueueError(f"invalid capacity wait timeout: {capacity_wait_s!r}") from e
        if not math.isfinite(wait_budget) or wait_budget < 0:
            raise QueueError(f"invalid capacity wait timeout: {capacity_wait_s!r}")
        caller_deadline = time.monotonic() + wait_budget
    if not math.isfinite(lock_wait_s) or lock_wait_s < 0:
        raise QueueError(f"invalid Unity lock wait timeout: {lock_wait_s!r}")
    capacity_wait = wait_for_capacity(abort=should_abort, timeout_s=capacity_wait_s)
    if capacity_wait.probe_failed:
        raise QueueError(capacity_wait.refusal or "memgate probe failed; refusing to reserve Unity resources")
    if capacity_wait.aborted or should_abort():
        return 0
    if caller_deadline is not None and time.monotonic() >= caller_deadline:
        return 0
    if not any(qdir("pending").glob("*.json")):
        return 0
    lock_wait = lock_wait_s
    if caller_deadline is not None:
        lock_wait = min(lock_wait, max(0.0, caller_deadline - time.monotonic()))
    if not acquire_unity_lock(f"unity_queue drain pid {os.getpid()}", lock_wait, should_abort):
        return 0
    launches = 0
    try:
        if should_abort() or (caller_deadline is not None and time.monotonic() >= caller_deadline):
            return 0
        recover_orphans(force=True)
        if caller_deadline is not None and time.monotonic() >= caller_deadline:
            return 0
        if gather_s > 0:
            gather_wait = gather_s if caller_deadline is None else min(gather_s, caller_deadline - time.monotonic())
            if gather_wait > 0:
                time.sleep(gather_wait)
            if caller_deadline is not None and time.monotonic() >= caller_deadline:
                return 0
        jobs = claim_pending()
        groups: dict[tuple, list[dict]] = {}
        for j in jobs:
            groups.setdefault((j["unity"], j["project"], j["buildTarget"], j["graphics"], j["kind"] == WARMUP_KIND),
                              []).append(j)
        for _, g in sorted(groups.items(), key=lambda kv: not kv[0][-1]):  # warm-ups first, then the jobs behind them
            for i in range(0, len(g), max_batch):
                run_launch(g[i:i + max_batch], capacity_wait=capacity_wait)
                launches += 1
    finally:
        release_unity_lock()
    return launches


# ------------------------------------------------------------------------------------------------ caller API
def launch(*, kind: str, method: str, args: list, project, log=None, inputs=(), output_dir=None, graphics=False,
           build_target=None, unity=DEFAULT_UNITY, requester=None, direct=False, timeout_s=5400,
           wait_s=12 * 3600) -> dict:
    """The one Unity entry point for switched callers. Queue (default): submit, drain/wait, copy the job's log slice to
    `log`, return the result dict (status "ok" or "failed"). direct=True is the explicit --unity-direct opt-out: a
    single launch through unitylock, logged loudly, returning {"status", "exitCode", "direct": True}."""
    if direct:
        refusal = library_refusal(str(project), str(project), kind == WARMUP_KIND)
        if refusal:
            print(f"UNITY_QUEUE direct launch refused: {refusal}", file=sys.stderr, flush=True)
            return {"status": "failed", "exitCode": None, "direct": True, "error": refusal}
        banner = (f"UNITY_QUEUE BYPASS: --unity-direct launches {method} on {project} outside the queue "
                  f"(no batching, no dedupe, no queue result); docs/unity_queue_runner.md")
        print("!" * 100 + "\n" + banner + "\n" + "!" * 100, file=sys.stderr, flush=True)
        stage_dispatcher(project)  # the shimmed builders compile against nothing, but keep the project uniform
        cmd = [sys.executable, str(ROOT / "tools/homm3_vfx/unitylock.py"), "run", "--wait", "60", "--", str(unity),
               "-batchmode", "-quit", *([] if graphics else ["-nographics"]), "-projectPath", str(project),
               *(["-buildTarget", build_target] if build_target else []),
               *(["-executeMethod", method] if kind != WARMUP_KIND else []),
               *[str(a) for a in args], *(["-logFile", str(log)] if log else [])]
        rc = subprocess.run(cmd).returncode
        return {"status": "ok" if rc == 0 else "failed", "exitCode": rc, "direct": True}
    job = make_job(kind=kind, execute_method=method, args=args, project=project, unity=unity, inputs=inputs,
                   output_dir=output_dir, requester=requester, build_target=build_target, graphics=graphics, log=log,
                   timeout_s=timeout_s)
    jid, deduped = submit(job)
    print(f"UNITY_QUEUE SUBMITTED {jid} {method}" + (" (deduped onto an identical queued job)" if deduped else ""),
          flush=True)
    res = wait_for(jid, wait_s)
    if log:
        Path(log).parent.mkdir(parents=True, exist_ok=True)
        src = Path(res["jobLog"])
        Path(log).write_text(src.read_text(encoding="utf-8") if src.is_file() else "", encoding="utf-8")
    if res["status"] != "ok":
        print(f"UNITY_QUEUE job {jid} FAILED: {res.get('error')}\n  " + "\n  ".join(res.get("logExcerpt", [])[-25:]),
              file=sys.stderr, flush=True)
    return res


def take_direct_flag(argv: list | None = None) -> bool:
    """Remove `--unity-direct` from sys.argv (call at import, before argparse) and return whether it was given. The
    one explicit opt-out for callers switched with run_cmd(); launch() logs the bypass loudly."""
    argv = sys.argv if argv is None else argv
    if "--unity-direct" in argv:
        argv.remove("--unity-direct")
        return True
    return False


class QueuedRun:
    """subprocess.CompletedProcess look-alike for callers that read .returncode."""

    def __init__(self, res: dict):
        self.result = res
        self.returncode = 0 if res["status"] == "ok" else (res.get("exitCode") or 1)
        self.args = res.get("id")
        jl = Path(res["jobLog"]) if res.get("jobLog") else None
        self.stdout = jl.read_text(encoding="utf-8", errors="replace") if jl and jl.is_file() else ""
        self.stderr = "" if res["status"] == "ok" else f"UNITY_QUEUE job {res.get('id')} failed: {res.get('error')}\n"


def parse_unity_cmd(cmd: list) -> dict:
    """A classic `[python unitylock.py run ... --] Unity.exe -batchmode ... -executeMethod M ...` command -> launch() kwargs."""
    toks = [str(c) for c in cmd]
    if len(toks) > 2 and toks[1].replace("\\", "/").endswith("unitylock.py") and "--" in toks:
        toks = toks[toks.index("--") + 1:]
    if not toks or not toks[0].lower().endswith("unity.exe"):
        raise QueueError(f"not a Unity command line: {toks[:3]}")
    kw = {"unity": toks[0], "graphics": True, "build_target": None, "log": None, "args": []}
    i = 1
    while i < len(toks):
        t = toks[i]
        if t in ("-batchmode", "-quit"):
            pass
        elif t == "-nographics":
            kw["graphics"] = False
        elif t in ("-projectPath", "-buildTarget", "-executeMethod", "-logFile"):
            if i + 1 >= len(toks):
                raise QueueError(f"{t} without a value")
            kw[{"-projectPath": "project", "-buildTarget": "build_target", "-executeMethod": "method",
                "-logFile": "log"}[t]] = toks[i + 1]
            i += 1
        else:
            kw["args"].append(t)
        i += 1
    for k in ("project", "method"):
        if k not in kw:
            raise QueueError(f"Unity command line has no -{'projectPath' if k == 'project' else 'executeMethod'}")
    return kw


def run_cmd(cmd: list, *, kind: str, inputs=None, output_dir=None, direct: bool = False, requester=None,
            timeout_s: int = 5400) -> QueuedRun:
    """Switch point for callers that built a Unity command line: the same command becomes one queued job. Inputs
    default to the job args that are existing files. Returns an object with .returncode (0 ok, else nonzero)."""
    kw = parse_unity_cmd(cmd)
    if inputs is None:
        inputs = [a for a in kw["args"] if not a.startswith("-") and Path(a).is_file()]
    res = launch(kind=kind, inputs=inputs, output_dir=output_dir, direct=direct, timeout_s=timeout_s,
                 requester=requester or f"{Path(sys.argv[0]).name} {kind}", **kw)
    return QueuedRun(res)


# ------------------------------------------------------------------------------------------------ CLI
def status(recent: int) -> dict:
    out = {"queueRoot": str(QUEUE_ROOT), "unityLock": unitylock.holder() or "free"}
    for s in ("pending", "running"):
        out[s] = []
        for f in sorted(qdir(s).glob("*.json")):
            try:
                j = load(f)
                out[s].append({"id": j["id"], "kind": j["kind"], "method": j["executeMethod"],
                               "requester": j["requester"], "launchId": j.get("launchId")})
            except (OSError, ValueError):
                out[s].append({"id": f.stem, "error": "unreadable"})
    for s in ("done", "failed"):
        rs = sorted(qdir(s).glob("*.result.json"), key=lambda p: p.stat().st_mtime)[-recent:]
        out[s] = []
        for f in rs:
            r = load(f)
            out[s].append({k: r.get(k) for k in ("id", "kind", "status", "error", "launchId", "elapsedSeconds",
                                                 "launchWallSeconds", "dedupedInto")})
    return out


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    tail = []
    if "--" in argv:
        tail, argv = argv[argv.index("--") + 1:], argv[:argv.index("--")]
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("submit")
    s.add_argument("--kind", required=True)
    s.add_argument("--method", required=True, help="executeMethod, Namespace.Type.Method")
    s.add_argument("--project", required=True)
    s.add_argument("--unity", default=str(DEFAULT_UNITY))
    s.add_argument("--input", action="append", default=[])
    s.add_argument("--output-dir")
    s.add_argument("--log", help="caller log path (the job's slice of the launch log is copied there with --wait)")
    s.add_argument("--build-target")
    s.add_argument("--graphics", action="store_true", help="launch without -nographics")
    s.add_argument("--requester")
    s.add_argument("--wait", action="store_true")
    s.add_argument("--timeout", type=float, default=5400, help="job timeout (s) inside the launch")
    s.add_argument("--wait-timeout", type=float, default=12 * 3600)
    r = sub.add_parser("run")
    r.add_argument("--once", action="store_true", help="drain what is pending and exit")
    r.add_argument("--gather", type=float, default=0.0, help="seconds to wait after taking the lock before claiming")
    r.add_argument("--max-batch", type=int, default=16)
    r.add_argument("--poll", type=float, default=15.0)
    w = sub.add_parser("warmup", help=f"queue a Library warm-up: -batchmode -quit, no -executeMethod "
                                      f"(needs {WARMUP_MIN_FREE_GB:.0f} GB free)")
    w.add_argument("--project", required=True)
    w.add_argument("--unity", default=str(DEFAULT_UNITY))
    w.add_argument("--build-target")
    w.add_argument("--graphics", action="store_true")
    w.add_argument("--requester")
    w.add_argument("--wait", action="store_true")
    w.add_argument("--timeout", type=float, default=WARMUP_TIMEOUT_S)
    w.add_argument("--wait-timeout", type=float, default=12 * 3600)
    lc = sub.add_parser("library-check")
    lc.add_argument("--project", required=True)
    st = sub.add_parser("status")
    st.add_argument("--recent", type=int, default=10)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "library-check":
            why = library_cold(a.project)
            print(json.dumps({"project": a.project, "resolved": norm_project(a.project), "cold": why is not None,
                              "reason": why, "lastLaunchLog": str(latest_project_log(a.project) or ""),
                              "freeGb": round(free_gb(a.project), 1), "warmupMinFreeGb": WARMUP_MIN_FREE_GB},
                             indent=1))
            return 1 if why else 0
        if a.cmd in ("submit", "warmup"):
            warm = a.cmd == "warmup"
            job = make_job(kind=WARMUP_KIND if warm else a.kind, execute_method=WARMUP_METHOD if warm else a.method,
                           args=[] if warm else tail, project=a.project, unity=a.unity,
                           inputs=[] if warm else a.input, output_dir=None if warm else a.output_dir,
                           requester=a.requester, build_target=a.build_target, graphics=a.graphics,
                           log=None if warm else a.log, timeout_s=a.timeout)
            jid, deduped = submit(job)
            print(json.dumps({"id": jid, "deduped": deduped}))
            if not a.wait:
                return 0
            res = wait_for(jid, a.wait_timeout)
            if getattr(a, "log", None):
                src = Path(res["jobLog"])
                Path(a.log).write_text(src.read_text(encoding="utf-8") if src.is_file() else "", encoding="utf-8")
            print(json.dumps(res, indent=1))
            return 0 if res["status"] == "ok" else 1
        if a.cmd == "run":
            while True:
                n = drain_once(max_batch=a.max_batch, gather_s=a.gather)
                if a.once:
                    print(f"UNITY_QUEUE drained: {n} launch(es)")
                    return 0
                time.sleep(a.poll)
        print(json.dumps(status(a.recent), indent=1))
        return 0
    except QueueError as e:
        print(f"UNITY_QUEUE ERROR {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
