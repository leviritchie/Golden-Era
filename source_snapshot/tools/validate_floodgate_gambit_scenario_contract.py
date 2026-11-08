#!/usr/bin/env python3
"""Validate The Floodgate Gambit generated-artifact contract."""
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path
MAP_SID="h3_floodgate_gambit"; SCHEMA="homm3.olden_floodgate_gambit.v1"; ROOT=Path("artifacts")/"campaign_port_poc"/"floodgate_gambit"
def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--repo-root",type=Path,default=Path(__file__).resolve().parents[1]); ap.add_argument("--skip-generate",action="store_true"); args=ap.parse_args(); repo=args.repo_root.resolve(); errors=[]
    builder=repo/"experiments/campaign_port_poc/build_floodgate_gambit_scenario.py"; installer=repo/"tools/install_floodgate_gambit_scenario.py"; profile=repo/"scenarios/floodgate_gambit/scenario.profile.json"
    for path in (builder,installer,profile):
        if not path.is_file(): errors.append(f"missing {path}")
    if not args.skip_generate:
        result=subprocess.run([sys.executable,str(builder),"--out-root",str(repo/ROOT)],check=False)
        if result.returncode: errors.append("builder failed")
    try:
        sys.path.insert(0,str(repo/"experiments/campaign_port_poc")); import port_homecoming_poc as poc
        container=poc.read_olden_map_container(repo/ROOT/"maps"/f"{MAP_SID}.map"); chunks=list(container.chunks); meta,data,_,quest=chunks
        if len(chunks)!=4: errors.append(f"map needs four chunks, got {len(chunks)}")
        if data.get("sizeX_")!=64 or data.get("sizeZ_")!=64: errors.append("map dimensions must be 64x64")
        for required in ("cliffRandomSeed","generatorChecksum","settings"):
            if required not in data: errors.append(f"schema field missing: {required}")
        if len(data.get("tilesMap") or [])!=4096: errors.append("terrain length mismatch")
        if (meta.get("spawns") or {}).get("playersCount")!=2: errors.append("map needs player plus AI spawn")
        entities={x.get("sid") for x in (data.get("objectsProperties") or {}).get("propEntities",[]) if isinstance(x,dict)}
        if "floodgate_gambit_floodgate_citadel" not in entities: errors.append("citadel entity missing")
        blob=json.dumps(quest)
        for token in ("ObjectInteractionAfter","ObjectCaptureEntity","GameVictory","BeforeIamVsHero","SquadKill","CounterEqualityInDays"):
            if token not in blob: errors.append(f"quest missing {token}")
        if not any(x.get("sid")=="Zone 1x1" for x in (data.get("markers") or [])): errors.append("Zone 1x1 markers missing")
        mains=[q for q in quest.get("quests",[]) if q.get("main")]
        if len(mains)!=1 or len(mains[0].get("subQuests",[]))<5: errors.append("main quest needs one quest with at least five objectives")
    except Exception as exc: errors.append(f"artifact inspection failed: {type(exc).__name__}: {exc}")
    overlay=repo/ROOT/"core_overlay"; dialog_dir=overlay/"DB/dialogs/dialogs/custom_maps/FloodgateGambit"; squad=overlay/"DB/squads/squads_custom_maps/FloodgateGambit/floodgate_gambit_griffin_x5.json"
    if len(list(dialog_dir.glob("*.json")))<7: errors.append("expected seven dialog files")
    if not squad.is_file(): errors.append("guard squad overlay missing")
    if errors:
        print("floodgate gambit contract FAIL",file=sys.stderr); print("\n".join(f"- {e}" for e in errors),file=sys.stderr); return 1
    print(json.dumps({"ok":True,"mapSid":MAP_SID,"schema":SCHEMA},indent=2)); return 0
if __name__=="__main__": raise SystemExit(main())




