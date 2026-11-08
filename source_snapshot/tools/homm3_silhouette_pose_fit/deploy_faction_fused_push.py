#!/usr/bin/env python3
"""Faction deploy gate for fused_push skinned-mesh delivery into Golden Era.

Steps (fail-closed; does not invent missing clips):
1. ``faction_fused_push_gate.py --require-deployable``
2. Export delivery GLBs via batch ``--export-only --faction …``
3. ``validate_homm3_skinned_clip_pose_contract.py`` on the rollout clips
   (pose-units/exporter round-trip; runs even without ``--export``)
4. ``prepare_smartrig_skinned_import.py --rollout-dir <fused_push out>``
5. Print Unity lab + bundle + OfflineUnlockMod deploy commands (audio validators included)

Does not start the next faction. Mesh/smartrig quality fixes stay deferred.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
GATE = TOOL / "faction_fused_push_gate.py"
BATCH = TOOL / "run_fused_push_batch_all_units.py"
PREPARE = TOOL / "prepare_smartrig_skinned_import.py"
CLIP_POSE_VALIDATOR = ROOT / "tools/validate_homm3_skinned_clip_pose_contract.py"
OUT = ROOT / "artifacts/fused_push_skinned_rollout"
PLUGIN = (
    ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "OfflineUnlockMod.csproj"
)
GOLDEN = Path(
    r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era"
)


def _run(cmd: list[str]) -> int:
    print("+ " + " ".join(cmd), flush=True)
    return subprocess.call(cmd, cwd=str(ROOT))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--faction", required=True, help="e.g. castle")
    parser.add_argument(
        "--export",
        action="store_true",
        help="run batch --export-only after gate passes",
    )
    parser.add_argument(
        "--prepare-import",
        action="store_true",
        help="write Unity lab specs + import/manifest paths for ready units",
    )
    parser.add_argument(
        "--print-deploy",
        action="store_true",
        default=True,
        help="print Golden Era Unity/bundle/plugin deploy commands",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    faction = str(args.faction).strip()
    gate_cmd = [
        sys.executable,
        str(GATE),
        "--faction",
        faction,
        "--require-deployable",
        "--write",
    ]
    code = _run(gate_cmd)
    if code != 0:
        print(
            "faction not deployable yet (pending clips remain). "
            "Keep fused_push fitting; do not start the next faction.",
            flush=True,
        )
        return code

    if args.export:
        code = _run(
            [
                sys.executable,
                str(BATCH),
                "--faction",
                faction,
                "--export-only",
                "--export-units",
                "--resume",
            ]
        )
        if code != 0:
            return code

    # Exported clip GLBs feed the Unity lab build; verify the pose-units
    # contract on disk before any bundle work consumes them.
    code = _run([sys.executable, str(CLIP_POSE_VALIDATOR), "--rollout-dir", str(OUT)])
    if code != 0:
        return code

    deliberate = ROOT / "tools/validate_deliberate_motion_contract.py"
    deliberate_cmd = [
        sys.executable,
        str(deliberate),
        "--rollout-dir",
        str(OUT),
        "--write-reports",
    ]
    faction_units = OUT / f"{faction}_skinned_units.txt"
    if faction_units.is_file():
        deliberate_cmd.extend(["--units-file", str(faction_units)])
    code = _run(deliberate_cmd)
    if code != 0:
        return code

    if args.prepare_import:
        code = _run(
            [
                sys.executable,
                str(PREPARE),
                "--rollout-dir",
                str(OUT),
                "--require-chosen-set",
                "--write-import",
                "--write-units-manifest",
            ]
        )
        if code != 0:
            return code

    if args.print_deploy:
        plan = {
            "faction": faction,
            "proofTier": "generated-artifact until Golden Era install validators pass",
            "commands": [
                "Copy Homm3OwnedSkinnedLabBuild.cs into the Unity Editor project and run "
                f"-skinnedLabSpec {OUT / 'unity_lab_batch.json'}",
                "BuildCustomUnitBundles.BuildFromManifest for this faction's custom_units_* rows "
                "(battlePresentationLane=skinned_mesh; include sounds)",
                f"python tools/validate_homm3_unit_bundle_audio_contract.py --bundle-dir "
                f"tools/homm3_import/build_out",
                f"python tools/validate_homm3_bundle_payload_directory.py --bundle-dir "
                f"tools/homm3_import/build_out --payload-glob custom_units_* "
                f"--name-prefix custom_units_{faction if faction.startswith('homm3_') else faction}_",
                "dotnet build "
                f"\"{PLUGIN}\" -c Release "
                f"-p:GameRoot=\"{GOLDEN}\" "
                "-p:DeployHomm3Bundles=false "
                "# then deploy one validated bundle at a time with "
                "-p:DeployHomm3BundleName=custom_units_castle_h3_<unit>",
                "Confirm adventure-map Idle loop + Homm3LabClipAudioDriver via in-game smoke "
                "(user-visible gameplay; not claimed by this script)",
            ],
            "out": str(OUT),
        }
        print(json.dumps(plan, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
