"""Full-roster status for the DEF retarget: every faction's 7 unit lines x 3 variants (21 units).

Usage: python tools/homm3_def_retarget/roster_status.py [faction ...]   (default: all homm3_*.json)

Each roster slot (unitLines[i].names[v], variant "", "_upg", "_upg_alt") is resolved to the unit id
used by the pipeline: prefix+snake(name) (e.g. h3_glaivier), else baseSid+variant (e.g.
h3_kobold_upg_alt). Status, strongest first:
  done       GLB exported after the current bake and glb_verify.json within tolerance (review not checked)
  stale      verified, but the GLB predates the current corrective-smooth bake (rebuild)
  built      a .blend exists but no passing verify
  config     units/<id>.json exists, not built
  ready      mesh and capture exist, no config yet
  hand       mesh exists, capture only under remaining_forced_* (hand-keyed route)
  no-mesh / no-capture / no-inputs
"""
import glob, json, os, re, sys

ROOT = r"V:/games/Olden Era Playtest Tweak"
RUNS = os.path.join(ROOT, "artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/runs")
ART = os.path.join(ROOT, "artifacts/homm3_def_retarget")
UNITS = os.path.join(ROOT, "tools/homm3_def_retarget/units")
MESH = os.path.join(ROOT, "artifacts/meshy_downloads")
VARIANTS = ["", "_upg", "_upg_alt"]
snake = lambda s: re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")

KNOWN = set(os.listdir(RUNS)) | {f[:-len("_smartrigged.glb")] for f in os.listdir(MESH) if f.endswith("_smartrigged.glb") and not f.startswith("_")}         | {f[:-5] for f in os.listdir(UNITS) if f.endswith(".json")} | set(os.listdir(ART))
RANK = ["done", "stale", "built", "config", "ready", "hand", "no-mesh", "no-capture", "no-inputs"]
BAKE_EPOCH = 1790272687     # commit a952dea52b: last change to the corrective-smooth bake

def candidates(line, v, name):
    base = line["baseSid"]; first = snake(line["names"][0])
    prefix = base[: -len(first)] if base.endswith(first) else base.rsplit("_", 1)[0] + "_"
    sn = snake(name)
    out = [prefix + sn]
    # HotA/other-mod units live under their own prefixes (hota_cove_*, hota_bulwark_*, toa_*, temple_*)
    out += sorted(k for k in KNOWN if re.fullmatch(r"(hota_[a-z]+|toa|temple)_" + re.escape(sn), k))
    out += [base + VARIANTS[v]]
    if prefix != "h3_":
        out.append("h3_" + snake(line["names"][0]) + VARIANTS[v])
    return list(dict.fromkeys(out))

def status(uid):
    vj = os.path.join(ART, uid, "glb_verify.json")
    if os.path.exists(vj):
        r = json.load(open(vj))
        ok = r and all(not x.get("missing") and x.get("maxBoneErr", 1) <= 1e-4 and x.get("maxMeshErr", 0) <= 2e-3 for x in r.values())
        glb = os.path.join(ART, uid, f"{uid}_def_retarget.glb")
        if ok and os.path.exists(glb):
            return "done" if os.path.getmtime(glb) >= BAKE_EPOCH else "stale"
    if os.path.exists(os.path.join(ART, uid, f"{uid}_def_retarget.blend")):
        return "built"
    if os.path.exists(os.path.join(UNITS, uid + ".json")):
        return "config"
    mesh = os.path.exists(os.path.join(MESH, uid + "_smartrigged.glb"))
    cap = os.path.exists(os.path.join(RUNS, uid, "linked_master", "capture", "capture", "raw_capture.npz"))
    forced = bool(glob.glob(os.path.join(RUNS, uid, "remaining_forced_*")))
    if mesh and cap:
        return "ready"
    if mesh and forced:
        return "hand"
    return "no-mesh" if cap or forced else ("no-capture" if mesh else "no-inputs")

def exists_any(uid):
    return any(os.path.exists(p) for p in (os.path.join(ART, uid), os.path.join(UNITS, uid + ".json"),
               os.path.join(MESH, uid + "_smartrigged.glb"), os.path.join(RUNS, uid)))

files = [os.path.join(ROOT, "custom_factions", f"homm3_{f}.json") for f in sys.argv[1:]] or \
        sorted(glob.glob(os.path.join(ROOT, "custom_factions", "homm3_*.json")))
total = {}
for fp in files:
    d = json.load(open(fp)); fac = os.path.basename(fp)[6:-5]
    rows = []
    for line in d.get("unitLines", []):
        for v, name in enumerate(line["names"]):
            cands = [c for c in candidates(line, v, name) if exists_any(c)] or candidates(line, v, name)[:1]
            uid = min(cands, key=lambda c: RANK.index(status(c)))     # the id with the most progress
            rows.append((line["tier"], VARIANTS[v] or "base", name, uid, status(uid)))
    if not rows:
        continue
    counts = {}
    for r in rows:
        counts[r[4]] = counts.get(r[4], 0) + 1
    total[fac] = counts
    print(f"\n== {fac}: {len(rows)} units — " + ", ".join(f"{k} {n}" for k, n in sorted(counts.items(), key=lambda kv: -kv[1])))
    for t, var, name, uid, st in rows:
        print(f"  T{t} {var:8s} {name:22s} {uid:34s} {st}")
if len(total) > 1:
    agg = {}
    for c in total.values():
        for k, n in c.items():
            agg[k] = agg.get(k, 0) + n
    print("\nALL: " + ", ".join(f"{k} {n}" for k, n in sorted(agg.items(), key=lambda kv: -kv[1])) + f" (of {sum(agg.values())})")
