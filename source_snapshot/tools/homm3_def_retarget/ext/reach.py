"""Reach check for units with a "propExtend" block: reach.py <unit> [--json]

For every propExtend clip, skins the canonical GLB and measures the mesh's forward (+Z, GLB frame)
extent per sample against Unit_Idle t0, in Idle body lengths (Z extent). The DEF's own peak is the
entry's "defPeakL" (front edge vs DEF Idle f0 in body lengths, measured from the DEF plates); the
check fails (exit 1) when the GLB peak is below 0.8 x defPeakL, or when an entry has no defPeakL.
Not an ext hook (defines no stage functions); lives beside prop_extend.py so a gate can call it.
Proof tier: generated artifact.
"""
import sys, json
import numpy as np
from pathlib import Path
R = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(R / "tools/homm3_def_retarget_delivery"))
from stride_match_glb import Glb

RATIO = 0.8


def measure(g, clip, n=41):
    js = g.json
    skin = js["skins"][0]; joints = skin["joints"]
    ibm = g.read(skin["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1)
    prims = []
    for nd in js["nodes"]:
        if "mesh" in nd and "skin" in nd:
            for p in js["meshes"][nd["mesh"]]["primitives"]:
                a = p["attributes"]; V = g.read(a["POSITION"])
                prims.append((V, g.read(a["JOINTS_0"]).astype(int), g.read(a["WEIGHTS_0"])))

    def pts(c, t):
        mats = g.world(g.sample_local(c, np.array([t]))); M = np.stack([mats[j][0] for j in joints]) @ ibm
        out = []
        for V, J, W in prims:
            h = np.c_[V, np.ones(len(V))]
            out.append(sum(W[:, k:k + 1] * np.einsum("nij,nj->ni", M[J[:, k]], h)[:, :3] for k in range(4)))
        return np.concatenate(out)
    I = pts("Unit_Idle", 0.0)
    # vertices collapsed to ~0 scale (hidden sections, rubble) sit on their bone head: ignore
    z0 = I[:, 2].max(); L = float(np.ptp(I[:, 2]))
    e = g.clip_end(clip); ts = np.linspace(0, e, n)
    f = [(pts(clip, t)[:, 2].max() - z0) / L for t in ts]
    i = int(np.argmax(f))
    return {"idleLenZ": round(L, 3), "peakFront": round(float(f[i]), 3), "atT": round(float(ts[i] / e), 2),
            "curve": [round(float(x), 3) for x in f]}


def main():
    u = sys.argv[1]
    cfg = json.load(open(R / f"tools/homm3_def_retarget/units/{u}.json", encoding="utf-8"))
    g = Glb.load(R / f"artifacts/homm3_def_retarget/{u}/{u}_def_retarget.glb")
    ok = True; rep = {"unit": u, "entries": []}
    for s in cfg.get("propExtend", []):
        for clip in s["clips"]:
            m = measure(g, "Unit_" + clip)
            dp = s.get("defPeakL")
            m.update({"name": s["name"], "clip": clip, "defPeakL": dp,
                      "pass": dp is not None and m["peakFront"] >= RATIO * dp})
            ok &= m["pass"]; rep["entries"].append(m)
    rep["ok"] = ok
    print(json.dumps(rep if "--json" in sys.argv else {k: v for k, v in rep.items()}))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
