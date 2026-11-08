"""Measure how vanilla Olden Era battle walks match their ground speed (the reference for stride_match_glb.py).

    python tools/homm3_def_retarget_delivery/measure_native_walk_stride.py [prefab ...]   (default: STOCK)

Reads the installed game read-only with UnityPy (same loader as tools/homm3_import/measure_native_battle_height.py):
per stock battle prefab, its `01.Walk` override clip sampled over one loop, forward kinematics in the prefab root
with the spawner's first-child scale replaced by `UnitViewConfig.scale`, and the view config's `moveSpeed`. The
contact points are the lowest foot / toe / hoof / paw / claw node of each limb that reaches the floor. The walk
state plays at 0.8 x battleSpeed (stride_gait.MOVE_STATE_SPEED), so the cycle is clip length / 0.8 game seconds.
Writes tools/homm3_def_retarget_delivery/reference/native_walk_stride.json (outside the delivery-selection glob).

Proof tier: static read of installed assets; poses are decoded clip samples, not a runtime capture. The body
translation speed = moveSpeed and the battleSpeed factor applying to both are recorded assumptions.
"""
from __future__ import annotations

import json
import re
import statistics
import sys
import zipfile
import zlib
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import stride_gait as G  # noqa: E402

sys.path.append(str(ROOT / "tools" / "homm3_idle_cadence"))
sys.path.append(str(ROOT / "tools" / "homm3_style_compare"))
sys.path.append(str(ROOT / "tools" / "homm3_import"))
from measure_native_idles import decode_streamed, eval_streamed  # noqa: E402
from extract_native import trs  # noqa: E402
from measure_native_battle_height import DEFAULT_GAME_DATA, Prefabs  # noqa: E402

OUT = HERE / "reference" / "native_walk_stride.json"
STOCK = ("humans/1prefabs/esquire", "humans/1prefabs/crossbowman", "humans/1prefabs/inquisitor",
         "humans/1prefabs/sunlight_cavalry", "nature/1prefabs/elf_tracker", "nature/1prefabs/ent",
         "neutral/1prefabs/unicorn", "neutral/1prefabs/halfling", "neutral/1prefabs/ghoul",
         "undead/1prefabs/skeleton", "dungeon/1prefabs/troglodyte", "dungeon/1prefabs/minos",
         "dungeon/1prefabs/medusa")
FOOT = re.compile(r"foot|toe|hoof|paw|claw", re.I)
SAMPLES = 240
TRANSFORM = 4


def views(core_zip: Path) -> dict:
    out = {}
    with zipfile.ZipFile(core_zip) as z:
        for n in z.namelist():
            if not (n.startswith("DB/units/units_views/") and n.endswith(".json")) or "/homm3_" in n:
                continue
            try:
                arr = json.loads(z.read(n).decode("utf-8-sig")).get("array", [])
            except (ValueError, UnicodeDecodeError):
                continue
            for v in arr:
                if isinstance(v, dict) and "mesh" in v and v.get("moveSpeed") is not None:
                    out.setdefault(str(v["mesh"]).lower(), {"id": v.get("id"), "moveSpeed": float(v["moveSpeed"]),
                                                             "scale": float(v.get("scale") or 1.0)})
    return out


def clip_curves(tt: dict, times: np.ndarray) -> tuple[dict, int]:
    """Transform curves of a generic clip at times: {pathHash: {attr: (N, k)}}; also the skipped euler count."""
    mc = tt["m_MuscleClip"]
    data = mc["m_Clip"]["data"]
    sc = data["m_StreamedClip"]; dc = data["m_DenseClip"]; cc = data["m_ConstantClip"]["data"]
    n_s = int(sc["curveCount"]); n_d = int(dc["m_CurveCount"])
    streamed = decode_streamed(sc["data"]) if sc["data"] else {}
    dense = np.asarray(dc["m_SampleArray"], dtype=np.float64)
    if n_d:
        dense = dense.reshape(int(dc["m_FrameCount"]), n_d)
        dtimes = float(dc["m_BeginTime"]) + np.arange(dense.shape[0]) / float(dc["m_SampleRate"])

    def curve(i):
        if i < n_s:
            k = streamed.get(i)
            return eval_streamed(k, times) if k else np.zeros(len(times))
        i -= n_s
        if i < n_d:
            return np.interp(times, dtimes, dense[:, i])
        return np.full(len(times), float(cc[i - n_d]))

    out, ci, euler = {}, 0, 0
    for b in tt["m_ClipBindingConstant"]["genericBindings"]:
        if b["typeID"] == TRANSFORM:
            size = 4 if b["attribute"] == 2 else 3
            if b["attribute"] in (1, 2, 3):
                out.setdefault(str(b["path"]), {})[int(b["attribute"])] = np.stack([curve(ci + k) for k in range(size)], 1)
            else:
                euler += 1
        else:
            size = 1
        ci += size
    return out, euler


def measure_prefab(P: Prefabs, key: str, view: dict) -> dict:
    ra = P.ra
    nodes: dict[int, dict] = {}

    def visit(pid, parent):
        tt = ra.objects[pid].read_typetree()
        go = ra.objects[tt["m_GameObject"]["m_PathID"]].read_typetree()
        vec = lambda k: [tt[k][c] for c in ("x", "y", "z", "w") if c in tt[k]]  # noqa: E731
        nodes[pid] = {"name": go["m_Name"], "t": vec("m_LocalPosition"), "q": vec("m_LocalRotation"),
                      "s": vec("m_LocalScale"), "parent": parent, "go": go,
                      "children": [c["m_PathID"] for c in tt["m_Children"]]}
        for c in tt["m_Children"]:
            visit(c["m_PathID"], pid)

    root_tt = ra.objects[P.container["units/" + key]].read_typetree()
    root = next(c for c in P.comps(root_tt) if c.type.name in ("Transform", "RectTransform")).path_id
    visit(root, None)
    first = nodes[root]["children"][0]
    nodes[first]["s"] = [float(np.copysign(view["scale"], x)) for x in nodes[first]["s"]]

    def path_of(pid, stop):
        parts = []
        while pid is not None and pid != stop:
            parts.append(nodes[pid]["name"]); pid = nodes[pid]["parent"]
        return "/".join(reversed(parts))

    for pid, n in nodes.items():
        for c in P.comps(n["go"]):
            if c.type.name != "Animator":
                continue
            ctrl = ra.objects.get(c.read_typetree()["m_Controller"]["m_PathID"])
            if ctrl is None or ctrl.type.name != "AnimatorOverrideController":
                continue
            for cl in ctrl.read_typetree()["m_Clips"]:
                orig = ra.objects.get(cl["m_OriginalClip"]["m_PathID"])
                ov = ra.objects.get(cl["m_OverrideClip"]["m_PathID"])
                if orig is not None and ov is not None and orig.peek_name() == "01.Walk":
                    return _walk(nodes, pid, ov, path_of, view)
    raise ValueError("no AnimatorOverrideController mapping 01.Walk")


def _walk(nodes, anim_pid, clip_obj, path_of, view) -> dict:
    tt = clip_obj.read_typetree()
    mc = tt["m_MuscleClip"]
    start, stop = float(mc["m_StartTime"]), float(mc["m_StopTime"])
    length = stop - start
    times = start + np.arange(SAMPLES) * length / SAMPLES
    curves, euler = clip_curves(tt, times)
    byhash, stack = {}, [anim_pid]
    while stack:
        p = stack.pop(); stack += nodes[p]["children"]
        if p != anim_pid:
            byhash[str(zlib.crc32(path_of(p, anim_pid).encode()))] = p
    n = len(times)
    loc = {pid: [np.tile(nd["t"], (n, 1)), np.tile(nd["q"], (n, 1)), np.tile(nd["s"], (n, 1))] for pid, nd in nodes.items()}
    posed = 0
    for h, attrs in curves.items():
        if h not in byhash:
            continue
        p = byhash[h]
        if 1 in attrs:
            loc[p][0] = attrs[1]
        if 2 in attrs:
            loc[p][1] = G.qnorm(attrs[2])
        if 3 in attrs:
            loc[p][2] = attrs[3]
        posed += 1
    mats = {}

    def wm(pid):
        if pid not in mats:
            t, q, s = loc[pid]
            m = np.zeros((n, 4, 4))
            m[:, :3, :3] = G.qmat(q) * s[:, None, :]
            m[:, :3, 3] = t; m[:, 3, 3] = 1
            par = nodes[pid]["parent"]
            mats[pid] = m if par is None else wm(par) @ m
        return mats[pid]

    under, stack = [], [anim_pid]
    while stack:
        p = stack.pop(); under.append(p); stack += nodes[p]["children"]
    pos = {p: wm(p)[:, :3, 3] for p in under}
    allp = np.stack([pos[p][0] for p in under])
    height = float(np.ptp(allp[:, 1]))
    cand = [p for p in under if FOOT.search(nodes[p]["name"])]
    # limbs: candidates joined through candidate ancestry; each limb contributes its lowest node
    limb_of = {}
    for p in cand:
        a, top = nodes[p]["parent"], p
        while a is not None and a in cand:
            top, a = a, nodes[a]["parent"]
        limb_of.setdefault(top, []).append(p)
    contacts = {}
    for top, members in limb_of.items():
        best = min(members, key=lambda p: float(pos[p][:, 1].min()))
        contacts[nodes[best]["name"] + f"#{best}"] = pos[best]
    if not contacts:
        raise ValueError("no foot/toe/hoof node under the Animator")
    floor = min(float(v[:, 1].min()) for v in contacts.values())
    grounded = {k: v for k, v in contacts.items() if v[:, 1].min() <= floor + 0.06 * height}
    # root travel over the loop: a clip that walks off and snaps back would show here
    hips = min(under, key=lambda p: len(path_of(p, anim_pid)) if FOOT.search(nodes[p]["name"]) is None and p != anim_pid else 1e9)
    res = G.analyze(grounded, length, height, 1.0, view["moveSpeed"], forward=None)
    res.update({"viewId": view["id"], "viewScale": view["scale"], "clip": clip_obj.peek_name(),
                "clipLength": round(length, 4), "bodyHeight": round(height, 4), "posedCurves": posed,
                "eulerCurvesSkipped": euler, "contacts": sorted(grounded),
                "strideRequiredOverHeight": round(res["strideRequired"] / height, 3),
                "strideActualOverHeight": round(res["strideActual"] / height, 3),
                "firstBoneLoopTravel": round(float(np.linalg.norm(pos[hips][-1] - pos[hips][0])), 4)})
    res["_replay"] = (grounded, length, height, view["moveSpeed"])
    return res


def main(argv=None) -> int:
    keys = (argv if argv is not None else sys.argv[1:]) or list(STOCK)
    P = Prefabs(DEFAULT_GAME_DATA)
    vs = views(DEFAULT_GAME_DATA / "StreamingAssets" / "Core.zip")
    rows, skipped = {}, {}
    for key in keys:
        if key not in vs or "units/" + key not in P.container:
            skipped[key] = "no view config or prefab"
            continue
        try:
            rows[key] = measure_prefab(P, key, vs[key])
        except (ValueError, KeyError, StopIteration) as ex:
            skipped[key] = f"{type(ex).__name__}: {ex}"
            continue
        r = rows[key]
        print(f"{key}: moveSpeed {r['moveSpeed']} cycle {r['cycleGameSeconds']}s stride req {r['strideRequired']} "
              f"({r['strideRequiredOverHeight']} H) actual {r['strideActual']} ratio {r['requiredOverActual']} "
              f"slip {r['slipRatio']}", flush=True)
    ratios = [r["requiredOverActual"] for r in rows.values() if r.get("requiredOverActual")]
    calib = statistics.median(ratios)
    for r in rows.values():
        grounded, length, height, speed = r.pop("_replay")
        c = G.analyze(grounded, length, height, 1.0, speed, forward=None, playback=G.MOVE_STATE_SPEED * calib)
        r["calibrated"] = {"slipRatio": c["slipRatio"], "requiredOverActual": c["requiredOverActual"],
                           "cycleGameSeconds": c["cycleGameSeconds"], "strideRequiredOverHeight": round(c["strideRequired"] / height, 3)}
    doc = {"schema": "native_walk_stride.v1",
           "rule": "01.Walk sampled over one loop; world = prefab root with UnitViewConfig.scale on the first child; "
                   "cycle = clip length / 0.8 (move state speed x battleSpeed 1); slip against moveSpeed",
           "assumptions": ["ground translation speed = UnitViewConfig.moveSpeed world units / s (docs: live worldSpeed "
                           "matched the field)", "battleSpeed scales clip playback and translation alike"],
           "medianRequiredOverActual": round(calib, 3),
           "effectiveBattleSpeed": round(calib, 3),
           "effectiveBattleSpeedNote": "the vanilla walks need their clips played this much faster than 0.8 (or the body "
                                       "moved this much slower than moveSpeed) for their kinematic stride to match; "
                                       "stride_match_glb.py plays owned walks under the same factor",
           "calibratedMedianSlipRatio": round(statistics.median(r["calibrated"]["slipRatio"] for r in rows.values()), 3),
           "calibratedP75SlipRatio": round(float(np.percentile([r["calibrated"]["slipRatio"] for r in rows.values()], 75)), 3),
           "medianSlipRatio": round(statistics.median(r["slipRatio"] for r in rows.values()), 3) if rows else None,
           "units": rows, "skipped": skipped,
           "proof": "static read of the installed assets (UnityPy); not a runtime capture"}
    OUT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"median required/actual {doc['medianRequiredOverActual']} slip {doc['medianSlipRatio']} -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
