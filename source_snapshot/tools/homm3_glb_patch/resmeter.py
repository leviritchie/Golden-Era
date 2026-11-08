"""Measure one command's wall time, peak RAM and bytes written (the whole process tree).

    python tools/homm3_glb_patch/resmeter.py [--json OUT] -- <cmd> [args...]

Samples every 50 ms with psutil: peak summed working set (RSS) of the child and all its descendants, and
io_counters().write_bytes summed over every process seen (a process's last reading is kept after it exits).
Prints one "RESMETER {...}" JSON line and exits with the child's code. Used to profile the full chain against the
patch lane (docs/homm3_glb_patch_lane.md); nothing here is a gate.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time

import psutil


def measure(cmd: list[str], poll: float = 0.05) -> dict:
    t0 = time.perf_counter()
    p = subprocess.Popen(cmd)
    root = psutil.Process(p.pid)
    peak, writes, reads = 0, {}, {}
    while True:
        try:
            procs = [root] + root.children(recursive=True)
        except psutil.NoSuchProcess:
            procs = []
        rss = 0
        for q in procs:
            try:
                rss += q.memory_info().rss
                io = q.io_counters()
                writes[q.pid], reads[q.pid] = io.write_bytes, io.read_bytes
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        peak = max(peak, rss)
        if p.poll() is not None:
            break
        time.sleep(poll)
    return {"cmd": cmd, "rc": p.returncode, "wallSeconds": round(time.perf_counter() - t0, 2),
            "peakRssMB": round(peak / 2**20, 1), "writtenMB": round(sum(writes.values()) / 2**20, 2),
            "readMB": round(sum(reads.values()) / 2**20, 2), "processes": len(writes)}


def main(argv: list[str]) -> int:
    out = None
    if argv[:1] == ["--json"]:
        out, argv = argv[1], argv[2:]
    if argv[:1] != ["--"] or len(argv) < 2:
        raise SystemExit(__doc__)
    rec = measure(argv[1:])
    print("RESMETER " + json.dumps(rec))
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    return rec["rc"]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
