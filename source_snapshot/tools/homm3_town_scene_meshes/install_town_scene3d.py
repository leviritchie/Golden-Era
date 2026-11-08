#!/usr/bin/env python3
"""Install a built full-3D town scene candidate into the plugin source tree and the active Golden Era install.

    python tools/homm3_town_scene_meshes/install_town_scene3d.py <faction> <candidate bundle dir>
    e.g. install_town_scene3d.py inferno artifacts/homm3_inferno_full3d/candidates/t2_v1/bundle
    python tools/homm3_town_scene_meshes/install_town_scene3d.py <faction> <dir> [<faction> <dir> ...]
    ... [--game-data-root <HeroesOldenEra_Data> --camera-json <v2 extraction>] [--quick]
--quick is the test-deploy tier (docs: validators run on release or on demand): steps 2 and 5's staged validator
are skipped, replaced by cheap crash guards -- catalog.json parses with the v2 schema and this town's bundle name, its
bundleBytes/bundleSha256 match the bundle file, and every prefabKey it names (environment + layers) is an asset in
the bundle's .manifest (a missing one throws in LoadAsset). Steps 0, 1, 3, 4 and the sha256 readback still run.
--game-data-root / --camera-json (together) are forwarded to every validator run: the explicit v2 native-camera
verification of validate_town_scene3d_contract.py, for an install whose level67 no longer matches the checked-in
Golden v1 camera record (e.g. a fresh extract_city_camera_pan.py --game-data-root extraction of the active install).
Several pairs install in order, each through steps 1-4 and its readback; the staged validator (step 5's last part)
runs once after the last pair, scoped with --only to the towns this run installed (towns it did not touch were
checked when they were installed, and the build's BeforeBuild run still checks every staged town). A failure stops the batch at that
town; towns already installed stay installed with their rollback copies.

Order, fail-closed at every step:
0. the installed plugin's payload sidecar (OfflineUnlockMod.payload_abi.json, docs/plugin_payload_abi.md) must be
   current for the installed DLL and carry the TownScene version the source reader declares (PluginPayloadAbi.cs),
   so the catalog the validator checked against the source reader is read by the same contract in game;
1. refuses while any Heroes/Olden process runs;
2. `validate_town_scene3d_contract.py --catalog <candidate>/catalog.json` must pass;
3. the files now installed are copied to artifacts/town_scene_rollback/<faction>_<utc>/ (restore = copy back);
4. catalog.json, the bundle, its build report and the coverage rasters go into
   OfflineUnlockMod/homm3_town_scene_meshes/scene3d/homm3_<faction>/ and the same folder under the Golden Era plugin;
   a file the candidate lacks is removed from both, so no stale raster outlives its bundle;
5. every destination is read back by sha256, and the staged validator must pass for the installed towns.

The script commits nothing: commit the source catalog.json yourself. Proof tier on success: installed payload.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "homm3_town_scene_meshes" / "scene3d"
GE_ROOT = Path(r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\BepInEx\plugins"
               r"\OfflineUnlockMod\homm3_town_scene_meshes\scene3d")
ROLLBACK = REPO / "artifacts" / "town_scene_rollback"
sys.path.insert(0, str(REPO / "tools" / "plugin_payload_abi"))
import payload_abi  # noqa: E402
OPTIONAL = ("pan_coverage.npz", "terrain_streak.npz", "building_depth.npz",
            "sky_continuity.npz")   # building_depth: catalog buildingDepth (contact_v1); sky_continuity: catalog skyLook


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def game_running() -> list[str]:
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "Get-Process | ? { $_.Name -match 'Heroes|Olden' } | % { $_.Name + ':' + $_.Id }"],
                         capture_output=True, text=True).stdout.split()
    return out


CAMERA_ARGS: list[str] = []   # --game-data-root/--camera-json, forwarded to every validator run (see module doc)
QUICK = False                 # --quick: test-deploy tier (see module doc)


def quick_guard(faction: str, cand: Path) -> None:
    bundle = f"homm3_town_scene3d_{faction}"
    try:
        cat = json.loads((cand / "catalog.json").read_text(encoding="utf-8"))
    except ValueError as e:
        raise SystemExit(f"install: catalog.json does not parse: {e}")
    bad = []
    if cat.get("schema") != "homm3_town_scene3d_catalog.v2":
        bad.append(f"schema {cat.get('schema')!r}")
    if cat.get("bundle") != bundle:
        bad.append(f"bundle {cat.get('bundle')!r} != {bundle!r}")
    size = (cand / bundle).stat().st_size
    if cat.get("bundleBytes") != size:
        bad.append(f"bundleBytes {cat.get('bundleBytes')} != {size}")
    if cat.get("bundleSha256") != sha(cand / bundle):
        bad.append("bundleSha256 != bundle file")
    man = cand / f"{bundle}.manifest"
    keys = [(cat.get("environment") or {}).get("prefabKey")] + [r.get("prefabKey") for r in cat.get("layers") or []]
    if not man.is_file():
        bad.append(f"no {man.name} to check {len(keys)} prefab keys against")
    else:
        assets = {ln.strip()[2:].rsplit("/", 1)[-1] for ln in man.read_text(encoding="utf-8").splitlines()
                  if ln.strip().startswith("- Assets/")}
        gone = [k for k in keys if not k or f"{k.lower()}.prefab" not in {a.lower() for a in assets}]
        if gone:
            bad.append(f"prefab keys not in bundle: {gone}")
    if bad:
        raise SystemExit(f"install: quick guard failed for {faction}: {'; '.join(bad)}")
    print(f"  QUICK tier: full contract skipped (test deploy); guards OK ({len(keys)} prefabs, bundle sha matches)")


def validate(args: list[str]) -> None:
    r = subprocess.run([sys.executable, str(REPO / "tools" / "validate_town_scene3d_contract.py"), *CAMERA_ARGS, *args],
                       capture_output=True, text=True)
    tail = (r.stdout + r.stderr).strip().splitlines()[-3:]
    print("  validator:", " | ".join(tail))
    if r.returncode:
        raise SystemExit(f"install: validator failed ({' '.join(args) or 'staged'})")


def main() -> int:
    args = sys.argv[1:]
    for flag in ("--game-data-root", "--camera-json"):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                raise SystemExit(f"install: {flag} needs a path")
            CAMERA_ARGS.extend([flag, str(Path(args[i + 1]).resolve())])
            del args[i:i + 2]
    global QUICK
    if "--quick" in args:
        QUICK = True
        args.remove("--quick")
    if len(CAMERA_ARGS) not in (0, 4):
        raise SystemExit("install: --game-data-root and --camera-json must be given together")
    if not args or len(args) % 2:
        raise SystemExit(__doc__)
    pairs = [(args[i], Path(args[i + 1]).resolve()) for i in range(0, len(args), 2)]
    try:
        want = payload_abi.source_versions()["TownScene"]
        got = payload_abi.require_installed_surface("TownScene", want, GE_ROOT.parents[1])
    except payload_abi.AbiError as e:
        raise SystemExit(f"install: {e}; deploy the plugin through the established build first")
    print(f"  plugin {got['dllSha256'][:8]} serves TownScene v{want}")
    for faction, cand in pairs:
        install_one(faction, cand)
    if not QUICK:
        validate([a for faction, _ in pairs for a in ("--only", f"homm3_{faction}")])
    return 0


def install_one(faction: str, cand: Path) -> None:
    name = f"homm3_{faction}"
    bundle = f"homm3_town_scene3d_{faction}"
    need = ["catalog.json", bundle, f"{bundle}.build_report.txt"]
    missing = [n for n in need if not (cand / n).is_file()]
    if missing:
        raise SystemExit(f"install: candidate {cand} lacks {missing}")
    running = game_running()
    if running:
        raise SystemExit(f"install: game running ({running}); close it first")
    if QUICK:
        quick_guard(faction, cand)
    else:
        validate(["--catalog", str(cand / "catalog.json")])
    files = need + [n for n in OPTIONAL if (cand / n).is_file()]
    dests = [SRC_ROOT / name, GE_ROOT / name]
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    back = ROLLBACK / f"{faction}_{stamp}"
    if (SRC_ROOT / name).is_dir():
        shutil.copytree(SRC_ROOT / name, back)
        print(f"  rollback copy: {back}")
    for d in dests:
        d.mkdir(parents=True, exist_ok=True)
        for n in need + list(OPTIONAL):
            if n not in files and (d / n).exists():
                (d / n).unlink()
                print(f"  removed stale {d / n}")
        for n in files:
            shutil.copy2(cand / n, d / n)
    for n in files:
        want = sha(cand / n)
        for d in dests:
            if sha(d / n) != want:
                raise SystemExit(f"install: readback mismatch {d / n}")
    print(f"  installed {name}: bundle sha256 {sha(cand / bundle)} ({(cand / bundle).stat().st_size} bytes), "
          f"catalog sha256 {sha(cand / 'catalog.json')}")


if __name__ == "__main__":
    raise SystemExit(main())
