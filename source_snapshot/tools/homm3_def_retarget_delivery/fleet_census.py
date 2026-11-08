"""Readiness census of every homm3_import.json OwnedSkinned row for the DEF-retarget delivery lane.

    python tools/homm3_def_retarget_delivery/fleet_census.py [--out docs/homm3_def_retarget_fleet_census.json]

Read-only over the canonical chain (retarget build -> emphasis -> unit look; the idle retime is applied by
each slice). Per import row it reports the retarget GLB and its verify, whether the corrective-smooth
bake predates the sigma guard / Tikhonov fix, the morph extent against the slice gate, the emphasis and
look state, the idle-cadence treatment and the known-issue ledgers, then classifies the row:

  shipped             already in a tools/homm3_def_retarget_delivery/*_slice_v1.json selection
  ship_now            current bake, verify passes, morph under the gate, emphasis settled, look applied
                      on the current canonical GLB: freeze + retime + prepare/lab/bundles/probe
  rebuild_then_ship   fixable by rerunning the existing unit tools (stale bake, morph over the gate,
                      failed verify, look not applied on the current GLB, emphasis pending)
  blocked             no retarget build / inputs, or no animation (declared mesh-identity rows are listed as
                      known issues; see SOURCE_UNIT / the note below)
  out_of_scope        neutral rows (a parallel agent owns the neutral slices)

Proof tier: generated artifact census (static read of files); nothing here is built or in game.
"""
from __future__ import annotations

import argparse
import datetime
import glob
import hashlib
import json
import os
import struct
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
IMPORT = ROOT / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_import.json"
RETARGET = ROOT / "artifacts/homm3_def_retarget"
EMPH = ROOT / "artifacts/homm3_def_retarget_emphasis"
LOOK = ROOT / "artifacts/homm3_unit_look"
LOOK_SPECS = ROOT / "tools/homm3_unit_look/units"
UNIT_CFGS = ROOT / "tools/homm3_def_retarget/units"
EMPH_EXC = ROOT / "tools/homm3_def_retarget_emphasis/exceptions.json"
IDLE_EXC = ROOT / "tools/homm3_idle_cadence/idle_exceptions.json"
LEDGER = ROOT / "artifacts/homm3_mesh_repair_fleet_v1/ledger.json"
STOPGAPS = ROOT / "custom_factions/contracts/homm3_unit_presentation_stopgaps.json"
SELECTIONS = ROOT / "tools/homm3_def_retarget_delivery"
MOCAP_RUNS = ROOT / "artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/runs"
MESHY = ROOT / "artifacts/meshy_downloads"
MORPH_DELTA_MAX_HEIGHT_RATIO = 1.5            # ship_def_retarget_slice.py
# c08b4ea145 (2026-09-26 15:13:55 -0500): first bake_cs.py that bounds near-singular solves (sigma guard;
# Tikhonov a9de7da122 followed at 15:32 and the only units rebuilt between the two are the storm / pegasus
# line, which were rebuilt again on Tikhonov and are pinned in their slices). A .blend saved before this
# carries the det > 1e-6 bake. The .blend is written only by build_unit.py / bake_cs.py / emphasis install.
BAKE_FIX_EPOCH = 1790453635
# Import lab sids whose DEF retarget lives under another unit id (the import row keeps its bundle / prefab).
SOURCE_UNIT = {"toa_boar_rider": "h3_boar_rider"}
# declaredMeshIdentity rows are listed as known issues, not blocks: on 2026-09-26 the Meshy regen agent confirmed
# the source meshes of h3_centaur, h3_boar_rider and h3_paokai are correct; the installed bundles are the stale part.
TIKHONOV_EPOCH = 1790454727                   # a9de7da122
VERIFY_BONE, VERIFY_MESH = 1e-4, 2e-3         # roster_status.py tolerances


def load(p: Path, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return default


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def morph_extent(path: Path) -> dict:
    """Largest morph-target offset / rest height (same measure as ship_def_retarget_slice.morph_extent)."""
    b = path.read_bytes()
    jl = struct.unpack("<I", b[12:16])[0]
    js = json.loads(b[20:20 + jl])
    bin0 = 20 + jl + 8

    def vec3(i):
        acc = js["accessors"][i]
        n = acc["count"]
        if "bufferView" in acc:
            bv = js["bufferViews"][acc["bufferView"]]
            o = bin0 + bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
            stride = bv.get("byteStride", 12)
            if stride == 12:
                out = np.frombuffer(b, np.float32, 3 * n, o).reshape(n, 3).copy()
            else:
                out = np.stack([np.frombuffer(b, np.float32, 3, o + k * stride) for k in range(n)])
        else:
            out = np.zeros((n, 3), np.float32)
        sp = acc.get("sparse")
        if sp:
            m = sp["count"]
            dt = {5121: np.uint8, 5123: np.uint16, 5125: np.uint32}[sp["indices"]["componentType"]]
            iv, vv = js["bufferViews"][sp["indices"]["bufferView"]], js["bufferViews"][sp["values"]["bufferView"]]
            idx = np.frombuffer(b, dt, m, bin0 + iv.get("byteOffset", 0) + sp["indices"].get("byteOffset", 0))
            val = np.frombuffer(b, np.float32, 3 * m, bin0 + vv.get("byteOffset", 0) + sp["values"].get("byteOffset", 0)).reshape(m, 3)
            out[idx.astype(np.int64)] = val
        return out

    worst, worst_name, height, targets = 0.0, None, 0.0, 0
    for m in js.get("meshes", []):
        names = m.get("extras", {}).get("targetNames", [])
        for p in m["primitives"]:
            ys = vec3(p["attributes"]["POSITION"])[:, 1]
            height = max(height, float(ys.max() - ys.min()))
            for t, tg in enumerate(p.get("targets", [])):
                if "POSITION" not in tg:
                    continue
                targets += 1
                d = float(np.sqrt((vec3(tg["POSITION"]).astype(np.float64) ** 2).sum(1)).max())
                if d > worst:
                    worst, worst_name = d, (names[t] if t < len(names) else str(t))
    clips = sorted(a["name"] for a in js.get("animations", []) if a["name"].startswith("Unit_"))
    return {"worstDelta": round(worst, 4), "worstTarget": worst_name, "restHeight": round(height, 4),
            "ratio": round(worst / height, 4) if height > 0 else None, "morphTargets": targets, "clips": clips}


def verify_status(u: str) -> dict:
    v = load(RETARGET / u / "glb_verify.json")
    if not v:
        return {"status": "missing"}
    bad = sorted(k for k, x in v.items() if x.get("missing") or x.get("maxBoneErr", 1) > VERIFY_BONE or x.get("maxMeshErr", 0) > VERIFY_MESH)
    idle = v.get("Unit_Idle", {})
    return {"status": "fail" if bad else "ok", "failedClips": bad,
            "worstMeshErr": round(max((x.get("maxMeshErr", 0) or 0) for x in v.values()), 6),
            "idleLoopClosed": abs(idle.get("lastMinusFirst", 1.0)) < 1e-6 if idle else None}


def iso(t: float | None) -> str | None:
    return datetime.datetime.fromtimestamp(t).isoformat(timespec="seconds") if t else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=ROOT / "docs/homm3_def_retarget_fleet_census.json")
    ap.add_argument("--no-morph", action="store_true", help="skip the GLB morph read (fast)")
    args = ap.parse_args()

    table = load(IMPORT)
    emph_exc = load(EMPH_EXC)["exceptions"]
    idle_exc = load(IDLE_EXC)["units"]
    ledger = {r["unitSid"]: r for r in load(LEDGER)["rows"]}
    stop = load(STOPGAPS)
    stopgaps, declared = stop["stopgaps"], stop["declaredMeshIdentity"]
    shipped = {}
    for sp in sorted(SELECTIONS.glob("*.json")):
        s = load(sp)
        if s.get("schema") != "homm3_def_retarget_delivery_selection.v1" or s.get("supersededBy"):
            continue
        for r in s["units"]:
            shipped[r["labSid"]] = {"selection": sp.name, "idleRetimedGlbSha256": r["frozen"]["idleRetimedGlbSha256"]}

    rows = []
    for e in table["entries"]:
        prefab = e["battlePrefabAssetPath"]
        lab = prefab.split("/")[3]
        src = SOURCE_UNIT.get(lab, lab)     # the retarget/look unit id this lab sid is built from
        faction = e["battleResPath"].split("/")[2]
        game = e.get("gameUnitSids", [])
        C = RETARGET / src
        glb, blend = C / f"{src}_def_retarget.glb", C / f"{src}_def_retarget.blend"
        r = {"labSid": lab, "sourceUnit": src, "gameSids": game, "faction": faction, "bundleName": e["bundleName"],
             "unitConfig": (UNIT_CFGS / f"{src}.json").is_file(),
             "mesh": (MESHY / f"{src}_smartrigged.glb").is_file(),
             "capture": (MOCAP_RUNS / src / "linked_master/capture/capture/raw_capture.npz").is_file(),
             "handKeyed": bool(glob.glob(str(ROOT / "tools/homm3_def_retarget/handoffs/**" / f"*{src.replace('h3_', '')}*keys*.py"), recursive=True))}
        r["retargetGlb"] = glb.is_file()
        r["blend"] = blend.is_file()
        r["verify"] = verify_status(src) if glb.is_file() else {"status": "missing"}
        bt = blend.stat().st_mtime if blend.is_file() else None
        r["bakeSavedAt"] = iso(bt)
        r["bake"] = None if bt is None else ("tikhonov" if bt >= TIKHONOV_EPOCH else "sigma_guard" if bt >= BAKE_FIX_EPOCH else "stale_det_rule")
        if r["unitConfig"] and (load(UNIT_CFGS / f"{src}.json") or {}).get("correctiveSmooth", {}) is False:
            r["bake"] = "disabled"            # the unit config turns the corrective-smooth bake off: no morphs
        r["morph"] = morph_extent(glb) if glb.is_file() and not args.no_morph else None
        st = load(EMPH / src / "stamp.json")
        exc = emph_exc.get(src)
        r["emphasis"] = {"exception": exc["kind"] if exc else None,
                         "decision": st.get("decision") if st else None,
                         "appliedAt": st.get("appliedAt") if st else None,
                         "emphasisedGlbSha256": st.get("emphasisedGlbSha256") if st else None}
        ls = load(LOOK / src / "stamp.json")
        look = {"spec": (LOOK_SPECS / f"{src}.json").is_file(), "stamp": ls is not None}
        if ls:
            look["appliedAt"] = ls.get("appliedAt")
            look["mode"] = ls.get("mode")
            ok_stat = glb.is_file() and ls.get("deliveredGlbStat") == {"size": glb.stat().st_size, "mtimeNs": glb.stat().st_mtime_ns}
            look["onCurrentGlb"] = bool(ok_stat or (glb.is_file() and sha(glb) == ls.get("deliveredGlbSha256")))
            es = r["emphasis"]["emphasisedGlbSha256"]
            look["afterEmphasis"] = (ls.get("sourceGlbSha256") == es) if (st and st.get("decision") == "emphasised") else None
            look["floorLights"] = ls.get("floorLights", [])
            look["vfxLayers"] = sorted((load(LOOK / src / "vfx/vfx_manifest.json") or {}).get("layers", {}))
        r["look"] = look
        ie = idle_exc.get(src)
        r["idle"] = {"treatment": ie["treatment"] if ie else "rule", "flags": ie.get("flags") if ie else []}
        lr = ledger.get(lab) or next((ledger[g] for g in game if g in ledger), None)
        r["meshRepairLedger"] = {"identity": lr["identity"]["status"], "processingState": lr["repair"]["processingState"]} if lr else None
        issues = []
        for g in [lab, *game]:
            if g in declared:
                issues.append(f"declaredMeshIdentity[{g}]: {declared[g]['evidence'][:160]}")
            if g in stopgaps:
                issues.append(f"stopgap[{g}] {stopgaps[g]['class']}: {', '.join(stopgaps[g]['issues'])}")
        r["knownIssues"] = sorted(set(issues))
        r["shipped"] = shipped.get(lab)

        # ---- classification
        why = []
        if faction == "neutral":
            cls = "out_of_scope"
            why.append("neutral: parallel agent owns neutral slices")
        elif r["shipped"]:
            cls = "shipped"
            why.append(f"in {r['shipped']['selection']}")
        else:
            block = []
            if not r["retargetGlb"] and not r["unitConfig"]:
                block.append("no retarget build and no unit config")
            elif not r["retargetGlb"]:
                block.append("no retarget GLB (config only)")
            if r["retargetGlb"] and r["morph"] and not r["morph"]["clips"]:
                block.append("no Unit_ clips")
            if block:
                cls = "blocked"
                why += block
            else:
                fix = []
                if r["verify"]["status"] != "ok":
                    fix.append(f"verify {r['verify']['status']} {r['verify'].get('failedClips', '')}")
                if r["bake"] not in ("tikhonov", "disabled"):
                    fix.append(f"bake {r['bake']} (blend {r['bakeSavedAt']})")
                if r["morph"] and (r["morph"]["ratio"] is None or r["morph"]["ratio"] > MORPH_DELTA_MAX_HEIGHT_RATIO):
                    fix.append(f"morph ratio {r['morph']['ratio']} > {MORPH_DELTA_MAX_HEIGHT_RATIO}")
                if exc and exc["kind"] == "pendingRebuild":
                    fix.append("emphasis pendingRebuild")
                elif not exc and not st:
                    fix.append("emphasis not run")
                if not look["stamp"]:
                    fix.append("no look stamp")
                elif not look.get("onCurrentGlb"):
                    fix.append("look not applied on the current canonical GLB")
                elif look.get("afterEmphasis") is False:
                    fix.append("look source is not the emphasised GLB")
                cls = "rebuild_then_ship" if fix else "ship_now"
                why += fix
        r["class"], r["why"] = cls, why
        rows.append(r)
        print(f"{lab:32s} {faction:10s} {cls:18s} {'; '.join(why)[:140]}", flush=True)

    counts = {}
    for r in rows:
        counts[r["class"]] = counts.get(r["class"], 0) + 1
    by_fac = {}
    for r in rows:
        by_fac.setdefault(r["faction"], {}).setdefault(r["class"], 0)
        by_fac[r["faction"]][r["class"]] += 1
    out = {"schema": "homm3_def_retarget_fleet_census.v1", "generatedAt": datetime.datetime.now().isoformat(timespec="seconds"),
           "generator": "tools/homm3_def_retarget_delivery/fleet_census.py",
           "proof": "generated-artifact census (static read of the canonical chain); nothing built, installed or in game",
           "gates": {"morphDeltaMaxHeightRatio": MORPH_DELTA_MAX_HEIGHT_RATIO, "bakeFixEpoch": iso(BAKE_FIX_EPOCH),
                     "tikhonovEpoch": iso(TIKHONOV_EPOCH), "verifyTolerance": {"maxBoneErr": VERIFY_BONE, "maxMeshErr": VERIFY_MESH},
                     "defLaneConform": "e5010f6abd -60 Orientation bind is applied by the lab builder at slice time, so every slice built now carries it"},
           "counts": counts, "byFaction": by_fac, "rows": rows}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(counts), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
