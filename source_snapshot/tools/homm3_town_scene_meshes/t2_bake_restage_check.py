#!/usr/bin/env python3
"""Restage one layer's painted-front T2 body (town_full3d_t2_paint) into a scratch STAGE, never the candidate, and
compare every written file byte for byte with the candidate's staged file (a bake refactor must not move a staged byte).

    python tools/homm3_town_scene_meshes/t2_bake_restage_check.py <faction> <candidate> <layer> <outdir>

2026-09-30 consolidation samples (all identical before and after both folds): fortress fr_t2 tbfrholy, factory
fa_v9_t2 tbfahal3, stronghold t2_v1 tavern, cove cv_t2 tbcvtave, rampart t2_v1 tbrmtvrn, dungeon t2_v1 tbdntvrn,
inferno t2_v1 tbintvrn, necropolis t2_v1 tbnctvrn, bulwark t2_v1 tbbutv01, castle t2_v1 tbcstvrn, tower tw_t2
tbtwtvrn. Results: artifacts/town_t2_bake_consolidation/ (run_all.py drives all eleven).
Exit status 1 when any file differs or the candidate lacks it. Proof tier: generated artifact."""
import hashlib, json, os, sys
from pathlib import Path
fac, cand, lid, out = sys.argv[1:5]
if fac in ("necropolis", "bulwark"):
    sys.argv = [sys.argv[0], "--faction", fac]    # town_full3d_t2_meshy reads its faction from argv at import
os.environ["TOWN_FULL3D_FACTION"] = fac
os.environ["TOWN_FULL3D_CANDIDATE"] = cand
ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools" / "homm3_town_scene_meshes"
sys.path.insert(0, str(TOOLS)); sys.path.insert(0, str(TOOLS / "t2_fortress"))
import stronghold_full3d_scene as S
real = S.STAGE
tmp = Path(out) / "stage"
tmp.mkdir(parents=True, exist_ok=True)
if fac == "fortress":
    import fortress_t2_buildings as FB
    sc = S.Scene(); S.STAGE = tmp
    b = FB.bake_layer(sc, lid)
    for name, piece, extra in ((f"Mesh_Body_{lid}", b["front"], {}), (f"Mesh_BodyM_{lid}", b["meshy"], {"max_size": 2048})):
        if piece is not None:
            sc.add_bin(S.PREFIX + lid, name, *piece, preview=False, **extra)
elif fac == "factory":
    import factory_t2_stage as FS
    sc = S.Scene(); S.STAGE = tmp
    FS.stage_layer(sc, lid)
elif fac == "stronghold":
    import stronghold_full3d_meshy as SM
    S.STAGE = tmp
    SM.build_one(lid)
elif fac == "cove":
    import cove_t2_stage as CS
    import cove_t2_buildings as CB
    seed_bins = CS.load_seed_bins(S.CAND / "work" / "seed_bodies", [lid])
    sc = S.Scene()
    allm = [l for l in CB.MESH_LAYERS if (CS.OUTD / l / "placement.json").is_file() and l not in CS.STAGE_SKIP]
    prep = {l: CS.prepare(sc, l) for l in allm}
    CS.order_cut(sc, prep, [lid])
    S.STAGE = tmp
    CS.stage_layer(sc, lid, seed_bins, prep[lid])
elif fac in ("rampart", "dungeon"):
    import numpy as np
    import rampart_t2_buildings as RB
    fr = json.loads((RB.WORK / "fits" / f"{lid}.json").read_text(encoding="utf-8"))
    zf = np.load(RB.WORK / "frame_z.npy")
    sc = S.Scene(); S.STAGE = tmp
    RB.stage_layer(sc, lid, fr, zf)
elif fac == "inferno":
    import inferno_t2_integrate as IG
    sc = S.Scene(); S.STAGE = tmp
    IG.stage_layer(sc, lid, "t2")
elif fac in ("necropolis", "bulwark"):
    import town_full3d_t2_meshy as TM
    att = json.loads((S.WORK / "stage_report.json").read_text(encoding="utf-8"))["buildings"][lid]["attempt"]
    sc = S.Scene(); S.STAGE = tmp
    TM.stage_body(sc, lid, TM.bake(lid, att, sc))
elif fac == "castle":
    import castle_t2_buildings as CB
    sc = S.Scene(); S.STAGE = tmp
    CB.stage_layer(sc, lid)
elif fac == "tower":
    import tower_t2_stage as TS
    sc = S.Scene(); S.STAGE = tmp
    TS.stage_layer(sc, lid)
else:
    raise SystemExit(fac)
res = {}
for f in sorted((tmp / (S.PREFIX + lid)).iterdir()):
    ref = real / (S.PREFIX + lid) / f.name
    a = hashlib.sha256(f.read_bytes()).hexdigest()
    b_ = hashlib.sha256(ref.read_bytes()).hexdigest() if ref.is_file() else None
    res[f.name] = {"identical": a == b_, "new": a[:12], "candidate": (b_ or "missing")[:12]}
print(json.dumps({"faction": fac, "candidate": cand, "layer": lid, "files": res}, indent=1))
(Path(out) / "result.json").write_text(json.dumps(res, indent=1))
sys.exit(0 if all(v["identical"] for v in res.values()) else 1)
