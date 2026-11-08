#!/usr/bin/env python3
"""Contract: delivery/runtime records pin a plugin payload version, never the plugin DLL hash (docs/plugin_payload_abi.md).

    python tools/validate_plugin_payload_abi_contract.py [--require-installed] [--plugin-dir D] [--strict-readers]

Always (source/static and generated records):
  - tools/plugin_payload_abi/surfaces.json is well formed; PluginPayloadAbi.cs declares exactly one const per surface;
    every surface reader exists;
  - the version-bump guard runs and prints its warnings (a reader changed since its acknowledgement); with
    --strict-readers a warning fails;
  - the ship lanes (def_retarget slices, mocap candidates) pin the payload surface and never copy or hash-pin a
    plugin DLL; the town installer checks the installed TownScene version; the csproj emits and deploys the sidecar;
  - every runtime_capability_build.json under artifacts/homm3_def_retarget_delivery and artifacts/homm3_mocap_v2
    pins {pluginPayloadAbi: {surface: UnitBundle, version}} equal to the source const and carries no retired
    dll / dllSha256 / sources pin.
With --require-installed (read-only against the Golden Era plugin folder):
  - the installed OfflineUnlockMod.payload_abi.json exists and was generated for the installed DLL (sha256);
  - its surface versions equal the source consts, so every record above validates against the installed plugin.
Fails closed; one line per violation.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "plugin_payload_abi"))
import payload_abi as abi  # noqa: E402

PLUGIN = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
RECORD_LANES = (ROOT / "artifacts" / "homm3_def_retarget_delivery", ROOT / "artifacts" / "homm3_mocap_v2")
SHIP_LANES = (ROOT / "tools" / "homm3_def_retarget_delivery" / "ship_def_retarget_slice.py",
              ROOT / "experiments" / "homm3_mocap_v2" / "ship_ingame_candidates.py")
TOWN_INSTALLER = ROOT / "tools" / "homm3_town_scene_meshes" / "install_town_scene3d.py"
CSPROJ = PLUGIN / "OfflineUnlockMod.csproj"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--require-installed", action="store_true")
    ap.add_argument("--plugin-dir", type=Path, default=abi.GOLDEN_PLUGIN)
    ap.add_argument("--strict-readers", action="store_true")
    args = ap.parse_args()
    errors: list[str] = []

    try:
        manifest = abi.load_surfaces()
        versions = abi.source_versions(manifest)
    except (abi.AbiError, OSError, ValueError) as e:
        print(f"FAIL plugin payload abi: {e}")
        return 1
    for name, s in manifest["surfaces"].items():
        if not s.get("readers") or not s.get("dependsOn"):
            errors.append(f"surfaces.json: {name} needs readers and dependsOn")
        for rel in s.get("readers", []):
            if not (ROOT / rel).is_file():
                errors.append(f"surfaces.json: {name} reader missing: {rel}")
    warnings = abi.guard(manifest)
    for w in warnings:
        print(f"WARNING {w}")
    if warnings and args.strict_readers:
        errors.append(f"version-bump guard: {len(warnings)} warning(s) under --strict-readers")

    for lane in SHIP_LANES:
        text = lane.read_text(encoding="utf-8")
        rel = lane.relative_to(ROOT).as_posix()
        if "payload_abi.require_record_current" not in text or "payload_abi.require_installed_surface" not in text:
            errors.append(f"{rel}: must pin and check the UnitBundle payload version through payload_abi")
        for needle in ('runtime["dll"]', "runtime_dll", 'runtime["dllSha256"]', "RUNTIME_SOURCES"):
            if needle in text:
                errors.append(f"{rel}: retired plugin DLL pin/copy {needle!r} is back")
    town = TOWN_INSTALLER.read_text(encoding="utf-8")
    if 'require_installed_surface("TownScene"' not in town:
        errors.append("install_town_scene3d.py: must check the installed plugin's TownScene version before installing")
    csproj = CSPROJ.read_text(encoding="utf-8")
    for needle in ("plugin_payload_abi\\payload_abi.py", abi.SIDECAR_NAME):
        if needle not in csproj:
            errors.append(f"OfflineUnlockMod.csproj: sidecar emit/deploy wiring missing {needle!r}")

    records = [f for lane in RECORD_LANES if lane.is_dir() for f in sorted(lane.glob("*/runtime_capability_build.json"))]
    for f in records:
        where = f.relative_to(ROOT).as_posix()
        try:
            abi.require_record_current(json.loads(f.read_text(encoding="utf-8-sig")), "UnitBundle", where)
        except (abi.AbiError, ValueError) as e:
            errors.append(str(e))

    installed = ""
    if args.require_installed:
        try:
            data = abi.read_installed(args.plugin_dir)
            if data["surfaces"] != versions:
                errors.append(f"installed sidecar surfaces {data['surfaces']} differ from source {versions}")
            installed = f" installed dll {data['dllSha256'][:8]} surfaces {data['surfaces']}"
        except abi.AbiError as e:
            errors.append(str(e))

    for e in errors:
        print(f"FAIL {e}")
    if errors:
        return 1
    print(f"OK plugin payload abi: source {versions}, {len(records)} runtime record(s) pin their surface version, "
          f"{len(warnings)} guard warning(s){installed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
