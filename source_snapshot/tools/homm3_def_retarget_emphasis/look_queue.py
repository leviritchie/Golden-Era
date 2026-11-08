"""Re-apply the unit look to every emphasised GLB (chain: build -> emphasis -> idle retime -> look).

  python tools/homm3_def_retarget_emphasis/look_queue.py [--workers 1] [--follow]

A unit is due when its emphasis stamp is "emphasised", the canonical GLB is still the emphasised export
(emphasisedGlbSha256), it has a unit-look spec, and the look stamp was not made from that GLB. Each due
unit runs `python tools/homm3_unit_look/look.py <unit> --force` after memgate, never while another
process has the unit open (Win32_Process command lines). With --follow, keeps polling while a
`deliver.py --roster` batch is running and until nothing is due. Results: artifacts/homm3_def_retarget_emphasis/look_queue.jsonl.
"""
import argparse, datetime, json, os, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import deliver as D  # noqa: E402
import emphasis as E  # noqa: E402


def is_due(u):
    st = D.load_json(f"{D.wdir(u)}/stamp.json")
    if not st or st.get("decision") != "emphasised":
        return False
    if not os.path.exists(f"{E.ROOT}/tools/homm3_unit_look/units/{u}.json"):
        return False
    lst = D.load_json(f"{E.ROOT}/artifacts/homm3_unit_look/{u}/stamp.json") or {}
    if lst.get("sourceGlbSha256") == st["emphasisedGlbSha256"]:
        return False
    g = D.canon(u)["glb"]
    if D.fstat(g) != st.get("glbStat") and E.sha256_file(g) != st["emphasisedGlbSha256"]:
        return False                      # GLB replaced since (a rebuild, or look already ran on it)
    return True


def due():
    return [u for u in D.roster() if is_due(u)]


def roster_running():
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | ForEach-Object { $_.CommandLine }"],
                         capture_output=True, text=True).stdout
    return any("deliver.py" in l and "--roster" in l for l in out.splitlines())


def run(u):
    if not is_due(u):                     # the list is built once per pass; another queue may have done it since
        return {"unit": u, "result": "done-elsewhere"}
    if D.building(u):
        return {"unit": u, "result": "busy"}
    D.gate()
    t0 = time.time()
    r = subprocess.run([sys.executable, f"{E.ROOT}/tools/homm3_unit_look/look.py", u, "--force"], cwd=E.ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    res = {"unit": u, "result": "ok" if r.returncode == 0 else f"exit {r.returncode}", "seconds": round(time.time() - t0),
           "tail": (r.stdout + r.stderr).strip().splitlines()[-3:]}
    with open(f"{E.OUT}/look_queue.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(dict(res, at=datetime.datetime.now().isoformat(timespec="seconds"))) + "\n")
    D.log(u, "look", res["result"], res["seconds"], "s")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--follow", action="store_true")
    ap.add_argument("--reverse", action="store_true", help="walk the roster backwards (a second queue process)")
    a = ap.parse_args()
    failed = set()
    while True:
        q = [u for u in due() if u not in failed]
        if a.reverse:
            q.reverse()
        if q:
            with ThreadPoolExecutor(max(1, min(2, a.workers))) as ex:
                res = list(ex.map(run, q))
            failed |= {r["unit"] for r in res if r["result"] not in ("ok", "busy", "done-elsewhere")}
            if any(r["result"] != "busy" for r in res):
                continue
        elif not a.follow or not roster_running():
            break
        time.sleep(60)
    D.log("look queue done; failed:", sorted(failed))


if __name__ == "__main__":
    main()
