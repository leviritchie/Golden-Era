"""Build and install only an explicit mocap test selection, without rebuilding or copying the plugin.

The prepare/build/deploy entry points all require the same source provenance gate.
Installed bundles and the source import table are backed up and read back;
runtime appearance is not claimed.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))
from experiments.homm3_mocap_v2.delivery_style import PROFILE as STYLE_PROFILE
from experiments.homm3_mocap_v2.pipeline_contract import (
    validate_corpus_contract,
    validate_fit_report_contract,
)
from validate_homm3_mocap_delivery_contract import validate
from validate_homm3_skinned_clip_pose_contract import _accessor_f4, _read_glb
from tools.homm3_silhouette_pose_fit.prepare_smartrig_skinned_import import owned_prefab
from tools.plugin_payload_abi import payload_abi

UNITY = Path("C:/Program Files/Unity/Hub/Editor/6000.0.66f2/Editor/Unity.exe")
PROJECT = (ROOT / "oldenera_factions").resolve()
BUILD_OUT = ROOT / "tools/homm3_import/build_out"
CONTRACT = ROOT / "custom_factions/contracts/homm3_bundle_payload_contract.json"
INVENTORY = ROOT / "tools/homm3_import/homm3_units_manifest.json"
IMPORT = ROOT / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_import.json"
GOLDEN = Path("V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era")


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def dump(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_game_stopped() -> None:
    """Fail closed before deployment if the active Golden Era process is running."""
    if sys.platform != "win32":
        raise RuntimeError("deploy requires Windows tasklist process proof")
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq HeroesOldenEra.exe", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode != 0:
        raise RuntimeError(f"unable to prove HeroesOldenEra.exe is stopped: tasklist exit {result.returncode}")
    for row in csv.reader(result.stdout.splitlines()):
        if row and row[0].strip().lower() == "heroesoldenera.exe":
            raise RuntimeError("refusing deployment while HeroesOldenEra.exe is running")


PAYLOAD_SURFACE = "UnitBundle"


def validate_runtime_capability(runtime: dict) -> int:
    """The record pins the UnitBundle plugin payload version (docs/plugin_payload_abi.md), never a DLL hash; it must
    equal the version the current plugin source compiles. Returns it. The installed plugin is checked at deploy."""
    try:
        version = payload_abi.require_record_current(runtime, PAYLOAD_SURFACE, "runtime capability record")
    except payload_abi.AbiError as e:
        raise ValueError(str(e)) from e
    if "runtime behavior unproven" not in str(runtime.get("proof") or "").lower():
        raise ValueError("runtime capability proof must remain compile-only")
    return version


def run(command: list[str], log: Path, timeout: int = 3600) -> dict:
    started = time.perf_counter()
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as stream:
        subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=timeout,
                       creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
    return {"command": command, "log": str(log), "elapsedSeconds": time.perf_counter() - started}


def unity(method: str, extra: list[str], log: Path) -> dict:
    return run([str(UNITY), "-batchmode", "-quit", "-nographics", "-projectPath", str(PROJECT),
                "-executeMethod", method, "-logFile", str(log), *extra], log.with_suffix(".host.log"))


def require_scope(rows: list[dict]) -> None:
    inventory = {r["unitSid"]: r for r in load(INVENTORY)["units"]}
    entries = load(IMPORT)["entries"]
    if len({r["labSid"] for r in rows}) != len(rows) or not rows:
        raise ValueError("empty or duplicate test scope")
    for row in rows:
        item = inventory[row["labSid"]]
        if item["bundleName"] != row["bundleName"]:
            raise ValueError(f"bundle mapping drift: {row['labSid']}")
        expected = owned_prefab(row["labSid"])
        if item["battlePrefabAsset"] != expected or item["mapPrefabAsset"] != expected:
            raise ValueError(f"inventory is not already on the owned skinned lane: {row['labSid']}")
        if not any(e.get("battlePrefabAssetPath") == expected and e.get("mapPrefabAssetPath") == expected
                   and e.get("bundleName") == row["bundleName"] and row["gameSid"] in e.get("gameUnitSids", []) for e in entries):
            raise ValueError(f"missing current skinned import binding: {row['labSid']}")


def require_motion_provenance(rows: list[dict]) -> None:
    """Refuse to build/deploy a selection sourced from the silhouette lane."""
    for row in rows:
        sid = str(row.get("labSid") or "")
        fit_report_path = ROOT / str(row.get("fitReport") or "")
        if not fit_report_path.is_file():
            raise ValueError(f"{sid}: selected fit report is missing: {fit_report_path}")
        fit_report = load(fit_report_path)
        validate_fit_report_contract(fit_report, delivery=True)
        source_report = ROOT / str(row.get("sourceReport") or "")
        if not source_report.is_file():
            raise ValueError(f"{sid}: selected mocap source report is missing: {source_report}")
        validate_fit_report_contract(load(source_report), delivery=True, parent_report=fit_report)
        corpus_value = row.get("corpus")
        if corpus_value:
            corpus = ROOT / str(corpus_value)
            if corpus.is_file():
                validate_corpus_contract(load(corpus))
            elif corpus.is_dir():
                # The original Roc selection predates the skin-corpus wrapper
                # and pins a capture directory.  Its raw manifest is checked
                # by the existing delivery validator; do not reinterpret it.
                corpus_manifest = corpus / "corpus.json"
                if corpus_manifest.is_file():
                    validate_corpus_contract(load(corpus_manifest))
            else:
                raise ValueError(f"{sid}: selected mocap corpus is missing: {corpus}")


def lab_prepare_command(out: Path, selection: Path, rows: list[dict]) -> list[str]:
    return [sys.executable, str(ROOT / "tools/homm3_silhouette_pose_fit/prepare_smartrig_skinned_import.py"),
            "--rollout-dir", str(out), "--selection", str(selection.resolve()),
            "--require-chosen-set", "--lab-sids", ",".join(row["labSid"] for row in rows)]


def input_fingerprint(out: Path, selection: Path, rows: list[dict]) -> dict:
    files = [selection, ROOT / "tools/homm3_import/unity_editor/Homm3OwnedSkinnedLabBuild.cs",
             ROOT / "tools/custom_prefab_pipeline/unity_editor/BuildCustomUnitBundles.cs"]
    for row in rows:
        manifest = out / "units" / row["labSid"] / "delivery_manifest.json"
        files.append(manifest)
        data = load(manifest)
        for clip in data["clips"]:
            files.extend((Path(clip["output"]), Path(clip["rawSourceGlb"])))
            files.append(clip_motion_authority(clip))
        master = data["master"]
        files.append(Path(master["master"] if "master" in master else master["output"]))
        files.append(Path(data["skinWeights"]["path"]))
        for key in ("albedo", "normal", "metallicGloss"):
            value = data["pbr"][key]
            files.append(Path(value["output"] if isinstance(value, dict) else value))
    return {"inputHashes": {str(path.resolve()): sha(path) for path in files}}


def clip_motion_authority(clip: dict) -> Path:
    """Sample the delivered time domain, including approved slowed idle clips."""
    if "motionStyle" not in clip:
        path = Path(clip["rawSourceGlb"])
        expected = clip["rawSourceGlbSha256"]
    else:
        style = clip["motionStyle"]
        if not isinstance(style, dict) or style.get("profile") != STYLE_PROFILE:
            raise ValueError("unrecognized clip motion style")
        path = Path(style["derivedSourceGlb"])
        expected = style["derivedSourceGlbSha256"]
    if not path.is_file() or sha(path).lower() != expected.lower():
        raise ValueError("clip motion authority hash mismatch")
    return path


INSTALLED_CORE = GOLDEN / "HeroesOldenEra_Data/StreamingAssets/Core.zip"
ATTACK_CLIP_GATE = "validate_homm3_owned_skinned_attack_clip_contract.py"


def payload_gate(directory: Path, rows: list[dict], out: Path, views_core: Path = INSTALLED_CORE) -> None:
    """views_core: the Core.zip whose units_views the bundles will play against (deploy: the installed one)."""
    prefixes = [v for row in rows for v in ("--name-prefix", row["bundleName"])]
    for tool in ("validate_homm3_unit_bundle_audio_contract.py", "validate_homm3_bundle_payload_directory.py",
                 "validate_homm3_owned_skinned_facing_contract.py"):
        run([sys.executable, str(ROOT / "tools" / tool), "--bundle-dir", str(directory), *prefixes],
            out / "logs" / f"{directory.name}_{Path(tool).stem}.log", 300)
    run([sys.executable, str(ROOT / "tools" / ATTACK_CLIP_GATE), "--bundle-dir", str(directory), *prefixes,
         "--core", str(views_core)], out / "logs" / f"{directory.name}_{Path(ATTACK_CLIP_GATE).stem}.log", 300)


def raw_clip_motion_evidence(path: Path) -> tuple[bool, list[float]]:
    """Derive probe expectation/times from the immutable raw GLB animation."""
    doc, blob = _read_glb(path)
    animations = doc.get("animations") or []
    if len(animations) != 1:
        raise ValueError(f"{path}: expected exactly one raw animation")
    animation = animations[0]
    sampler_paths = {
        int(channel["sampler"]): str(channel.get("target", {}).get("path") or "")
        for channel in animation.get("channels") or []
    }
    times: set[float] = set()
    expected = False
    for sampler_index, sampler in enumerate(animation.get("samplers") or []):
        inputs = _accessor_f4(doc, blob, sampler["input"]).reshape(-1)
        times.update(float(value) for value in inputs)
        output = _accessor_f4(doc, blob, sampler["output"])
        path_name = sampler_paths.get(sampler_index, "")
        rows = output.reshape(output.shape[0], -1)
        if path_name == "rotation" and rows.shape[1] == 4:
            reference = rows[0]
            rows = rows.copy()
            for index in range(len(rows)):
                if float(np.dot(reference, rows[index])) < 0.0:
                    rows[index] *= -1.0
        if rows.size and float(np.max(np.abs(rows - rows[0]))) > 1e-5:
            expected = True
    ordered = sorted(times)
    samples = set(ordered)
    samples.update((left + right) * 0.5 for left, right in zip(ordered, ordered[1:]))
    if not samples:
        raise ValueError(f"{path}: raw animation has no sampler times")
    return expected, sorted(samples)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("lab", "bundles", "probe", "deploy"))
    parser.add_argument("--selection", type=Path, default=ROOT / "experiments/homm3_mocap_v2/stronghold_ingame_test.json")
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts/homm3_mocap_v2/stronghold_ingame_test_v1")
    parser.add_argument("--views-core", type=Path, default=INSTALLED_CORE,
                        help="Core.zip whose units_views the attack-clip gate reads before deploy; deploy always "
                             "gates on the installed Core.")
    args = parser.parse_args()
    if args.stage == "deploy" and args.views_core.resolve() != INSTALLED_CORE.resolve():
        raise ValueError("deploy gates attack clips against the installed Core.zip; --views-core is pre-deploy only")
    if not args.views_core.is_file():
        raise ValueError(f"--views-core not found: {args.views_core}")
    out = args.out.resolve()
    selection = load(args.selection)
    if (selection.get("schema") != "stronghold-current-mocap-ingame-test-selection-v1"
            or selection.get("accepted") is not False
            or selection.get("disposition") != "user_requested_ingame_test"):
        raise ValueError("not an explicit current mocap test selection")
    rows = selection["units"]
    require_motion_provenance(rows)
    errors = validate(rollout_dir=out, selection_path=args.selection.resolve())
    if errors:
        raise ValueError("mocap delivery gate failed:\n" + "\n".join(errors))
    # The lab stage is the transition boundary: it must be able to build a
    # candidate before the source import table is rewritten from billboard to
    # OwnedSkinned.  Bundle/probe/deploy stages remain binding-gated and will
    # fail closed until that rewrite has been explicitly materialized.
    if args.stage != "lab":
        require_scope(rows)
    fingerprint = input_fingerprint(out, args.selection, rows)
    if args.stage == "lab":
        result = run(lab_prepare_command(out, args.selection, rows),
                     out / "logs/prepare.log", 300)
        batch = load(out / "unity_lab_batch.json")
        if {r["labSid"] for r in batch["units"]} != {r["labSid"] for r in rows}:
            raise ValueError("prepared Unity batch differs from explicit selection")
        if any(r.get("motionAuthority") != "current_mocap_v2" for r in batch["units"]):
            raise ValueError("Unity batch lost mocap transform authority")
        for source in (ROOT / "tools/homm3_import/unity_editor/Homm3OwnedSkinnedLabBuild.cs",
                       ROOT / "tools/custom_prefab_pipeline/unity_editor/BuildCustomUnitBundles.cs"):
            shutil.copy2(source, PROJECT / "Assets/Editor" / source.name)
        result["unity"] = unity("Homm3OwnedSkinnedLabBuild.BuildFromCommandLine",
                                  ["-skinnedLabSpec", str(out / "unity_lab_batch.json")], out / "logs/unity_lab.log")
        dump(out / "lab_build.json", {**fingerprint, **result, "proof": "Unity-imported lab artifact"})
    elif args.stage == "bundles":
        lab = load(out / "lab_build.json")
        if any(lab.get(k) != v for k, v in fingerprint.items()):
            raise ValueError("delivery changed since lab build")
        unit_list = out / "bundle_unit_sids.txt"
        unit_list.write_text("\n".join(r["labSid"] for r in rows) + "\n", encoding="utf-8")
        backup = out / ("before_build_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
        backup.mkdir(exist_ok=False)
        shutil.copy2(CONTRACT, backup / CONTRACT.name)
        for row in rows:
            source = BUILD_OUT / row["bundleName"]
            if source.exists():
                shutil.copy2(source, backup / source.name)
        result = unity("OldenEra.CustomUnitBuilder.BuildCustomUnitBundles.BuildFromManifest",
                       ["-manifestPath", str(INVENTORY), "-homm3UnitListPath", str(unit_list), "-outputPath", str(BUILD_OUT)],
                       out / "logs/unity_bundles.log")
        contract = load(CONTRACT)
        changes = {}
        for row in rows:
            name = row["bundleName"]
            source = BUILD_OUT / name
            if not source.is_file() or source.stat().st_size <= 0 or name not in contract["bundles"]:
                raise ValueError(f"missing built bundle or contract row: {name}")
            new = {**contract["bundles"][name], "length": source.stat().st_size, "sha256": sha(source).upper()}
            changes[name] = {"before": contract["bundles"][name], "after": new}
            contract["bundles"][name] = new
        dump(CONTRACT, contract)
        payload_gate(BUILD_OUT, rows, out, args.views_core)
        dump(out / "bundle_build.json", {**fingerprint, **result, "backup": str(backup), "contractChanges": changes,
                                         "proof": "generated bundles validated; not installed"})
    elif args.stage == "probe":
        built = load(out / "bundle_build.json")
        if any(built.get(k) != v for k, v in fingerprint.items()):
            raise ValueError("delivery changed since bundle build")
        payload_gate(BUILD_OUT, rows, out, args.views_core)
        probe_source = ROOT / "tools/homm3_import/unity_editor/ProbeMocapDeliveryBundles.cs"
        shutil.copy2(probe_source, PROJECT / "Assets/Editor" / probe_source.name)
        probe_rows = []
        for row in rows:
            asset = f"Assets/CustomUnits/homm3_lab/{row['labSid']}/OwnedSkinned"
            delivery = load(out / "units" / row["labSid"] / "delivery_manifest.json")
            probe_clips = []
            for clip in delivery["clips"]:
                raw = clip_motion_authority(clip)
                expected, sample_times = raw_clip_motion_evidence(raw)
                probe_clips.append({"name": asset + "/Animations/" + clip["contractName"] + ".anim",
                                    "assetPath": str(raw), "expectedMotion": expected,
                                    "sampleTimes": sample_times})
            probe_rows.append({"labSid": row["labSid"], "bundlePath": str(BUILD_OUT / row["bundleName"]),
                               "prefabAssetPath": owned_prefab(row["labSid"]), "clips": probe_clips})
        spec = out / "bundle_probe_spec.json"
        report = out / "bundle_probe_report.json"
        dump(spec, {"schema": "homm3_mocap_bundle_probe_spec.v2", "sourceMotionAnalyzed": True, "units": probe_rows})
        if report.exists():
            raise ValueError("probe report already exists; preserve it before a new probe")
        result = unity("OldenEra.Homm3Import.ProbeMocapDeliveryBundles.Run",
                       ["-mocapProbeSpec", str(spec), "-mocapProbeOut", str(report)], out / "logs/unity_bundle_probe.log")
        probe = load(report)
        if {r["labSid"] for r in probe["units"]} != {r["labSid"] for r in rows} or any(not r["ok"] for r in probe["units"]):
            raise ValueError("offline bundle probe did not pass the full selection")
        dump(out / "bundle_probe.json", {**fingerprint, **result, "report": str(report), "reportSha256": sha(report),
                                         "probeSource": str(probe_source), "probeSourceSha256": sha(probe_source),
                                         "bundleHashes": {r["bundleName"]: sha(BUILD_OUT / r["bundleName"]) for r in rows}})
    else:
        require_game_stopped()
        built = load(out / "bundle_build.json")
        if any(built.get(k) != v for k, v in fingerprint.items()):
            raise ValueError("delivery changed since bundle build")
        payload_gate(BUILD_OUT, rows, out)
        probe = load(out / "bundle_probe.json")
        if any(probe.get(k) != v for k, v in fingerprint.items()) or sha(Path(probe["report"])) != probe["reportSha256"]:
            raise ValueError("offline bundle probe is stale")
        current_probe_source = ROOT / "tools/homm3_import/unity_editor/ProbeMocapDeliveryBundles.cs"
        if probe.get("probeSourceSha256", "").lower() != sha(current_probe_source).lower():
            raise ValueError("offline bundle probe code is stale")
        for row in rows:
            name = row["bundleName"]
            if sha(BUILD_OUT / name).upper() != built["contractChanges"][name]["after"]["sha256"]:
                raise ValueError(f"bundle changed since this test build: {name}")
            if sha(BUILD_OUT / name) != probe["bundleHashes"][name]:
                raise ValueError(f"bundle changed since offline loaded-bundle probe: {name}")
        target = GOLDEN / "BepInEx/plugins/OfflineUnlockMod/homm3_bundles"
        if not target.is_dir():
            raise ValueError(f"active installed bundle directory missing: {target}")
        installed_import = load(target.parent / "homm3_import.json")
        runtime = load(out / "runtime_capability_build.json")
        abi_version = validate_runtime_capability(runtime)
        installed_dll = target.parent / "OfflineUnlockMod.dll"
        try:
            installed_abi = payload_abi.require_installed_surface(PAYLOAD_SURFACE, abi_version, target.parent)
        except payload_abi.AbiError as e:
            raise ValueError(f"{e}; deploy the plugin through the established build first") from e
        source_import = load(IMPORT)
        for row in rows:
            expected = owned_prefab(row["labSid"])
            if not any(e.get("battlePrefabAssetPath") == expected and e.get("mapPrefabAssetPath") == expected
                       and e.get("bundleName") == row["bundleName"] and row["gameSid"] in e.get("gameUnitSids", [])
                       for e in installed_import["entries"]):
                raise ValueError(f"installed import binding differs: {row['labSid']}")
            # measured-stride rows (battleMoveStrideBindUnits / battleStrideMatch) are retired: the runtime no longer
            # lowers moveSpeed to them (tools/validate_unit_move_speed_normalization_contract.py forbids the fields)
            if not any(e.get("battlePrefabAssetPath") == expected and e.get("mapPrefabAssetPath") == expected
                       and e.get("bundleName") == row["bundleName"] and row["gameSid"] in e.get("gameUnitSids", [])
                       for e in source_import["entries"]):
                raise ValueError(f"source import table is missing the owned binding: {row['labSid']}")
        installed_import_path = target.parent / "homm3_import.json"
        backup = out / ("installed_backup_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
        backup.mkdir(exist_ok=False)
        shutil.copy2(installed_import_path, backup / installed_import_path.name)
        readback = []
        for row in rows:
            source, dest = BUILD_OUT / row["bundleName"], target / row["bundleName"]
            if not dest.is_file():
                raise ValueError(f"expected installed unit bundle missing: {dest}")
            shutil.copy2(dest, backup / dest.name)
        shutil.copy2(IMPORT, installed_import_path)
        if sha(installed_import_path) != sha(IMPORT):
            raise ValueError("installed import table hash differs")
        for row in rows:
            source, dest = BUILD_OUT / row["bundleName"], target / row["bundleName"]
            shutil.copy2(source, dest)
            if sha(source) != sha(dest):
                raise ValueError(f"installed readback differs: {dest}")
            readback.append({"bundle": dest.name, "sha256": sha(dest), "bytes": dest.stat().st_size})
        payload_gate(target, rows, out)
        dump(out / "installed_readback.json", {**fingerprint, "target": str(target), "backup": str(backup),
             "runtimeDll": str(installed_dll), "runtimeDllSha256": sha(installed_dll),
             payload_abi.RECORD_KEY: {"surface": PAYLOAD_SURFACE, "version": abi_version,
                                      "installedDllSha256": installed_abi["dllSha256"]},
             "importTable": str(installed_import_path), "importTableSha256": sha(installed_import_path),
             "bundles": readback, "excluded": selection.get("excluded", []),
             "proof": "installed payload validated; runtime appearance unproven"})
    print(f"{args.stage}: complete", flush=True)


if __name__ == "__main__":
    main()
