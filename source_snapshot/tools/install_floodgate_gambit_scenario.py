#!/usr/bin/env python3
"""Install The Floodgate Gambit map and its Core overlay."""
from __future__ import annotations
import argparse, json, shutil, subprocess, sys, zipfile
from datetime import datetime
from pathlib import Path
MAP_SID="h3_floodgate_gambit"
GAME=Path(r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era")
ROOT=Path("artifacts")/"campaign_port_poc"/"floodgate_gambit"
MAPS=Path("HeroesOldenEra_Data")/"StreamingAssets"/"maps"
CORE=Path("HeroesOldenEra_Data")/"StreamingAssets"/"Core.zip"
def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--repo-root",type=Path,default=Path(__file__).resolve().parents[1]); ap.add_argument("--game-root",type=Path,default=GAME); ap.add_argument("--skip-validate",action="store_true"); args=ap.parse_args(); repo=args.repo_root.resolve(); game=args.game_root.resolve()
    if not args.skip_validate:
        result=subprocess.run([sys.executable,str(repo/"tools"/"validate_floodgate_gambit_scenario_contract.py"),"--repo-root",str(repo)],check=False)
        if result.returncode: raise SystemExit("floodgate gambit validation failed")
    if not game.is_dir(): raise SystemExit(f"game root missing: {game}")
    root=repo/ROOT; mp=root/"maps"/f"{MAP_SID}.map"; side=root/"maps"/f"{MAP_SID}.json"; ov=root/"core_overlay"; dest=game/MAPS; dest.mkdir(parents=True,exist_ok=True); suffix=f".floodgate_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    for src in (mp,side):
        if not src.is_file(): raise SystemExit(f"missing artifact: {src}")
        target=dest/src.name
        if target.exists(): shutil.copy2(target,target.with_name(target.name+suffix))
        shutil.copy2(src,target)
    core=game/CORE
    if not core.is_file(): raise SystemExit(f"missing Core.zip: {core}")
    tmp=core.with_suffix(".zip.tmp_floodgate")
    if tmp.exists(): tmp.unlink()
    members=[p.relative_to(ov).as_posix() for p in ov.rglob("*") if p.is_file()]
    with zipfile.ZipFile(core) as src, zipfile.ZipFile(tmp,"w",compression=zipfile.ZIP_DEFLATED) as dst:
        skip=set(members)
        for info in src.infolist():
            if info.filename not in skip: dst.writestr(info,src.read(info.filename))
        for name in members: dst.writestr(name,(ov/name).read_bytes())
    shutil.copy2(core,core.with_name(core.name+suffix)); tmp.replace(core)
    print(json.dumps({"ok":True,"mapSid":MAP_SID,"mapsDir":str(dest),"overlayMembers":len(members)},indent=2)); return 0
if __name__=="__main__": raise SystemExit(main())
