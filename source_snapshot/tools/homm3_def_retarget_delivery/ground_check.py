"""Ground gate for a delivered owned-skinned GLB against its DEF (the stage that grounds it is ground_glb.py).

    python tools/homm3_def_retarget_delivery/ground_check.py <unit> <glb> [--json]

Per Unit_ clip, the skinned lowest vertex per key (rubble-owned vertices excluded: stride_match_glb.rubble_nodes)
relative to Unit_Idle key 0, as a
fraction of the Idle key-0 height (glTF +Y up), and the Hips height at key 0 on the same scale. Against the DEF's
bottom/top-row curve of the same clip (grounding.def_curve: alpha-255 plate vs Idle frame 0, stamped with the DEF
frames' sha1), within GROUND_TOL:
  sink    the clip's lowest vertex is not below min(0, the DEF clip's lowest bottom row) - GROUND_TOL;
  entry   key 0's lowest vertex lies in [min(0, d0), max(0, d0)] +/- GROUND_TOL (d0 the DEF's first frame);
  hips    key 0's Hips height steps from Idle's by at most GROUND_TOL + max(|d0|, |DEF first-frame top row|);
  death   Death's last key rests on the floor: |lowest vertex| <= GROUND_TOL.
Exemptions are the unit config's (grounding.exemption), stamped with their reason and still measured:
"groundContact": {"exempt": reason} records every check without failing; {"deathExempt": reason}, shrinkOut and
shatter skip only the death landing. "grounding": false is not an exemption (it only drops the capture-joint Hips
grounding in build_unit.pose_frame).
Proof tier: generated artifact (read-only measurement of built GLBs).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools/homm3_def_retarget"))
import gate_exceptions as GE  # noqa: E402
import grounding as GR  # noqa: E402
from def_wing_calibrate import Rig  # noqa: E402
from flyer_articulation import MASTER_RUNS  # noqa: E402
from stride_match_glb import Glb, rubble_nodes  # noqa: E402

GROUND_TOL = GR.GROUND_TOL


def _opaque(png: str) -> np.ndarray:
    with Image.open(png) as im:
        return np.array(im.convert("RGBA"))[:, :, 3] == 255


def def_ground_curve(unit: str) -> dict:
    p = MASTER_RUNS / unit / "linked_master/master_sequence/master_sequence.json"
    if not p.is_file():
        raise SystemExit(f"{unit}: no master sequence at {p} (the ground gate needs the DEF frames)")
    return GR.def_curve(json.loads(p.read_text(encoding="utf-8")), _opaque)


def unit_config(unit: str) -> dict:
    p = ROOT / "tools/homm3_def_retarget/units" / f"{unit}.json"
    if not p.is_file():
        raise SystemExit(f"{unit}: no unit config at {p} (the ground gate reads its grounding exemptions)")
    return json.loads(p.read_text(encoding="utf-8"))


def glb_ground(glb: Path | bytes) -> dict:
    """{"H": idle height, "clips": {suffix: {"lows": [...], "hips0": x}}} as fractions of the Idle key-0 height.
    `glb` may be the GLB's bytes (an in-memory delivery stage's output: prop_floor_glb, ground_glb)."""
    g = Glb(bytes(glb)) if isinstance(glb, (bytes, bytearray)) else Glb.load(glb)
    blob, glb = (g.raw, Path("<in-memory GLB>")) if isinstance(glb, (bytes, bytearray)) else (glb, glb)

    def samples(clip):
        anim = g.anim(clip)
        # Stride edits densify selected bones only; a key index is not a shared clip time.
        grids = []
        for ch in anim["channels"]:
            sampler = anim["samplers"][ch["sampler"]]
            interpolation = sampler.get("interpolation", "LINEAR")
            if interpolation not in {"LINEAR", "STEP"}:
                raise SystemExit(f"{glb.name} {clip}: unsupported sampler interpolation {interpolation!r}")
            t = g.read(sampler["input"])[:, 0]
            if not len(t) or not np.isfinite(t).all() or np.any(np.diff(t) <= 0):
                raise SystemExit(f"{glb.name} {clip}: invalid sampler times")
            grids.append(t)
        if not grids:
            raise SystemExit(f"{glb.name} {clip}: no animation channels to measure")
        times = np.unique(np.concatenate(grids))
        return g.world(g.sample_local(clip, times)), times

    rubble = rubble_nodes(g.names, g.parent)

    def state(rig, wm, k):
        jm = np.stack([wm[j][k] for j in rig.joints])
        rub = np.array([j in rubble for j in rig.joints])
        keep = ~(rub[rig.J] * (rig.W > 0.5)).any(1)
        V = rig.skin(jm)[keep]
        return float(V[:, 1].min()), float(V[:, 1].max()), float(jm[rig.names.index("Hips"), 1, 3])

    ri = Rig(blob, "Unit_Idle")
    idle_world, idle_times = samples("Unit_Idle")
    f0, top, h0 = state(ri, idle_world, 0)
    H = top - f0
    out = {}
    for a in ri.js["animations"]:
        c = a["name"]
        if not c.startswith("Unit_"):
            continue
        r = ri if c == "Unit_Idle" else Rig(blob, c)
        wm, times = (idle_world, idle_times) if c == "Unit_Idle" else samples(c)
        S = [state(r, wm, k) for k in range(len(times))]
        out[c[5:]] = {"lows": [round((s[0] - f0) / H, 4) for s in S], "hips0": round((S[0][2] - h0) / H, 4),
                      "times": [float(t) for t in times]}
    return {"H": H, "clips": out}


def ground_check(unit: str, glb: Path | bytes) -> tuple[list[str], dict]:
    """(faults, record). Faults are empty for a passing or fully exempt unit; the record carries every measure.
    `glb` may be the GLB's bytes (ground_glb checks its in-memory output)."""
    ex = GR.exemption(unit_config(unit))
    curve = def_ground_curve(unit)
    can = GR.canonical(curve)
    g = glb_ground(glb if isinstance(glb, (bytes, bytearray)) else Path(glb))
    bad, rec = [], {}
    for c, m in sorted(g["clips"].items()):
        seg = can.get(c)
        if seg is None:
            bad.append(f"{c}: no DEF segment to measure the ground against")
            continue
        d = GR._fill(seg["bottom"])
        top0 = GR._fill(seg["top"])[0]
        L = m["lows"]
        allow_sink = min(0.0, float(d.min())) - GROUND_TOL
        lo, hi = min(0.0, float(d[0])) - GROUND_TOL, max(0.0, float(d[0])) + GROUND_TOL
        allow_hips = GROUND_TOL + max(abs(float(d[0])), abs(float(top0)))
        r = {"min": round(min(L), 3), "first": L[0], "last": L[-1], "hips0": m["hips0"],
             "defMin": round(float(d.min()), 4), "defFirst": round(float(d[0]), 4), "defTopFirst": round(float(top0), 4)}
        f = []
        if min(L) < allow_sink:
            f.append(f"sinks to {min(L):+.3f} (DEF allows {allow_sink:+.3f})")
        if not lo <= L[0] <= hi:
            f.append(f"enters at {L[0]:+.3f} off the floor (DEF first frame {float(d[0]):+.3f}, allowed [{lo:+.3f}, {hi:+.3f}])")
        if abs(m["hips0"]) > allow_hips:
            f.append(f"Hips steps {m['hips0']:+.3f} from Idle at entry (DEF allows {allow_hips:.3f})")
        if c == "Death":
            if ex["death"]:
                r["deathExempt"] = ex["death"]
            elif abs(L[-1]) > GROUND_TOL:
                f.append(f"dead body ends {L[-1]:+.3f} {'above' if L[-1] > 0 else 'below'} the floor (tolerance {GROUND_TOL})")
        if f:
            r["faults"] = f
        rec[c] = r
        if not ex["all"]:
            bad += [f"{c} {x}" for x in f]
    bad, excused = GE.apply(unit, "ground", bad)
    return bad, {"schema": GR.SCHEMA, "tolerance": GROUND_TOL, "exempt": ex["all"], "defSource": curve["source"],
                 "H": round(g["H"], 4), "clips": rec, **({"gateExceptions": excused} if excused else {})}


DEBT = ROOT / "tools/homm3_owned_skinned_ground_debt.json"


def fault_key(f: str) -> str:
    """'<clip> <check word> ...' -> '<clip>:<check word>' (sinks / enters / Hips / dead / config), the debt's unit."""
    w = f.split()
    return f"{w[0]}:{w[1]}"


def debt_entry(selection: str, lab: str) -> dict | None:
    return next((d for d in json.loads(DEBT.read_text(encoding="utf-8"))["entries"]
                 if d["selection"] == selection and d["labSid"] == lab), None)


def debt_uncovered(entry: dict | None, sha: str, bad: list[str]) -> list[str]:
    """Faults the debt entry does not cover (all of them without an entry or when its frozen sha differs)."""
    if not bad:
        return []
    if not entry or entry.get("idleRetimedGlbSha256") != sha:
        return list(bad)
    return [b for b in bad if fault_key(b) not in set(entry["faults"])]


CACHE = ROOT / "artifacts/homm3_def_retarget_delivery/_ground/ground_check_cache.json"


def ground_cache_key(unit: str, glb: Path) -> str | None:
    """Cache key over everything ground_check reads: the GLB bytes, the DEF frame bytes, the unit config and this
    gate's own code (including the GLB sampler and quaternion interpolator). None when an input is missing."""
    import hashlib
    h = hashlib.sha256()
    for p in (Path(glb), ROOT / "tools/homm3_def_retarget/units" / f"{unit}.json", Path(__file__),
              Path(GR.__file__), Path(GE.__file__), HERE / "def_wing_calibrate.py", HERE / "stride_match_glb.py",
              HERE / "stride_gait.py", HERE / "reference/native_walk_stride.json"):
        if not p.is_file():
            return None
        h.update(p.read_bytes())
    msp = MASTER_RUNS / unit / "linked_master/master_sequence/master_sequence.json"
    if not msp.is_file():
        return None
    h.update(msp.read_bytes())
    for f in json.loads(msp.read_text(encoding="utf-8"))["frames"]:
        h.update(Path(f["sourcePng"]).read_bytes())
    return f"{unit}:{h.hexdigest()}"


def load_ground_cache() -> dict:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def store_ground_cache(fresh: dict) -> None:
    """Merge freshly measured {key: {"bad", "rec"}} into the cache, dropping older keys for the same units.
    Single writer: parallel callers measure with persist=False and hand their entries to one store."""
    if not fresh:
        return
    units = {k.split(":", 1)[0] + ":" for k in fresh}
    cache = {k: v for k, v in load_ground_cache().items() if not any(k.startswith(u) for u in units)}
    cache.update(fresh)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache), encoding="utf-8")


def ground_check_cached(unit: str, glb: Path, persist: bool = True) -> tuple[list[str], dict, dict]:
    """ground_check, memoised on ground_cache_key. Any input change re-measures. Returns (bad, rec, fresh) where
    fresh is the new cache entry ({} on a hit); persist=False leaves writing it to the caller."""
    key = ground_cache_key(unit, glb)
    if key is None:
        bad, rec = ground_check(unit, glb)
        return bad, rec, {}
    hit = load_ground_cache().get(key)
    if hit:
        return hit["bad"], hit["rec"], {}
    bad, rec = ground_check(unit, glb)
    fresh = {key: {"bad": bad, "rec": rec}}
    if persist:
        store_ground_cache(fresh)
    return bad, rec, fresh


def main() -> int:
    unit, glb = sys.argv[1], Path(sys.argv[2])
    bad, rec = ground_check(unit, glb)
    if "--json" in sys.argv:
        print(json.dumps(rec, indent=1))
    else:
        for c, r in rec["clips"].items():
            print(f"  {c:12s} " + " ".join(f"{k}={v}" for k, v in r.items() if k != "faults"))
    for b in bad:
        print("FAIL " + b)
    if rec["exempt"]:
        print(f"exempt ({rec['exempt']}): measured, not gated")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
