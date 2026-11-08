#!/usr/bin/env python3
"""Override-only attack-slot remap + exact rebundle for older owned skinned units (regression lane).

For units with no frozen DEF selection, the 2026-09-27 attack-slot change (shot on animationIndex 1 ->
15.Skill_1 -> Unit_ShootFront; melee/counter on 0 -> 14.Attack -> Unit_AttackFront) is applied by rewriting only
those two stock slots of each unit's existing override controller. No LabBuild, master GLB import, look bake or
re-freeze runs; every other file under the unit's OwnedSkinned root is hash-pinned before and after.

Stages (run in order, one cohort at a time; every Unity stage goes through unitylock and the launch guard):
  plan     derive the desired slots from the candidate Core view (desired_slots -> required_slots), pin inputs
  remap    back up the AOCs, rewrite the two slots in Unity, verify only m_OverrideClip lines changed
  bundles  build the exact manifest bundles into build_out, update the payload contract rows, run the payload,
           audio, facing and candidate-Core attack-clip gates, and require every serialized object except the AOC
           and bundle table to be byte-identical to the installed bundle
  probe    load each rebuilt bundle in the Editor: non-null stock base, every override pair as remapped

Cohorts: tools/homm3_import/attack_slot_remap_cohorts.json (game SIDs), or --units for a pilot. Never deploys.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools/homm3_import"))
from plan_owned_skinned_attack_remap import desired_slots  # noqa: E402
from validate_homm3_owned_skinned_attack_clip_contract import load_views  # noqa: E402
from validate_homm3_stock_controller_identity import check as stock_identity_check  # noqa: E402

UNITY = Path("C:/Program Files/Unity/Hub/Editor/6000.0.66f2/Editor/Unity.exe")
PROJECT = Path("V:/homm3_unity_work")
BUILD_OUT = ROOT / "tools/homm3_import/build_out"
CONTRACT = ROOT / "custom_factions/contracts/homm3_bundle_payload_contract.json"
MANIFEST = ROOT / "tools/homm3_import/homm3_units_manifest.json"
IMPORT = ROOT / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_import.json"
COHORTS = ROOT / "tools/homm3_import/attack_slot_remap_cohorts.json"
OUT_ROOT = ROOT / "artifacts/claude_takeover_20260927/regression/remap"
EDITOR_SCRIPTS = (
    ROOT / "tools/homm3_import/unity_editor/Homm3OwnedSkinnedAttackSlotRemap.cs",
    ROOT / "tools/homm3_import/unity_editor/Homm3StockControllerIdentityAudit.cs",
)
BUILDER_SCRIPT = ROOT / "tools/custom_prefab_pipeline/unity_editor/BuildCustomUnitBundles.cs"
GATES = ("validate_homm3_unit_bundle_audio_contract.py", "validate_homm3_bundle_payload_directory.py",
         "validate_homm3_owned_skinned_facing_contract.py")
ATTACK_CLIP_GATE = "validate_homm3_owned_skinned_attack_clip_contract.py"
INSTALLED_BUNDLES = Path("V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era/"
                         "BepInEx/plugins/OfflineUnlockMod/homm3_bundles")
# Object types a remap-only rebundle may change relative to the installed bundle.
PARITY_MAY_DIFFER = {"AssetBundle", "AnimatorOverrideController"}


def installed_parity(built: Path, installed: Path) -> dict:
    """Every serialized object except the AOC and the bundle table must be byte-identical to the installed bundle:
    the rebuild changes the two attack slots and nothing about mesh, clips, textures, materials or prefab."""
    import UnityPy
    from collections import Counter

    def objects(path: Path) -> Counter:
        env = UnityPy.load(str(path))
        return Counter((o.type.name, hashlib.sha256(o.get_raw_data()).hexdigest()) for o in env.objects)
    if not installed.is_file():
        raise RemapError(f"no installed bundle to compare: {installed}")
    a, b = objects(installed), objects(built)
    gone, new = a - b, b - a
    bad = sorted({t for t, _ in (gone + new).elements() if t not in PARITY_MAY_DIFFER})
    if bad or sum(gone.values()) != sum(new.values()) or sum(new.values()) > 2:
        raise RemapError(f"{built.name}: rebuilt bundle differs from installed beyond the AOC: types {bad}, "
                         f"{sum(gone.values())} object(s) gone, {sum(new.values())} new")
    return {"objects": sum(b.values()), "changedTypes": sorted({t for t, _ in new})}


class RemapError(RuntimeError):
    pass


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def dump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def run(command: list, log: Path, timeout: int = 5400) -> dict:
    started = time.perf_counter()
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as stream:
        rc = subprocess.run([str(c) for c in command], stdout=stream, stderr=subprocess.STDOUT, timeout=timeout).returncode
    if rc != 0:
        raise RemapError(f"command failed rc={rc}; see {log}")
    return {"command": [str(c) for c in command], "log": str(log), "elapsedSeconds": round(time.perf_counter() - started, 1)}


# --unity-direct (main) is the explicit, loudly logged opt-out of the Unity queue.
UNITY_DIRECT = False


def unity(method: str, extra: list, log: Path, output_dir: Path | None = None) -> dict:
    """One Unity batch job through the Unity queue (tools/unity_queue, docs/unity_queue_runner.md); the runner's
    preflight covers the launch guard, memgate and the one-Unity-per-project rule. Raises on failure."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("unity_queue", ROOT / "tools/unity_queue/unity_queue.py")
    uq = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(uq)
    started = time.perf_counter()
    extra = [str(c) for c in extra]
    res = uq.launch(kind="attack_slot_remap", method=method, args=extra, project=PROJECT, log=log,
                    inputs=[x for x in extra if Path(x).is_file()], output_dir=output_dir, unity=UNITY,
                    requester=f"remap_owned_attack_slots {method}", direct=UNITY_DIRECT)
    if res["status"] != "ok":
        raise RemapError(f"Unity job {res.get('id', 'direct')} {method} failed: {res.get('error') or res.get('exitCode')}; "
                         f"see {log}")
    return {"command": [method, *extra], "log": str(log), "elapsedSeconds": round(time.perf_counter() - started, 1),
            **({"unityQueueJob": res["id"], "unityQueueLaunch": res.get("launchId")} if "id" in res else {"unityDirect": True})}


def resolve_units(game_sids: list[str]) -> list[dict]:
    """game SIDs -> one row per lab unit, with every game SID its import row serves."""
    pending = set(load(COHORTS).get("pendingFleetBuild", []))
    blocked = sorted(set(game_sids) & pending)
    if blocked:
        raise RemapError(f"{blocked} wait for the fleet DEF-retarget build; they are not remapped")
    manifest = {r["bundleName"]: r for r in load(MANIFEST)["units"]}
    entries = load(IMPORT)["entries"]
    units: dict[str, dict] = {}
    for gsid in game_sids:
        rows = [e for e in entries if gsid in (e.get("gameUnitSids") or [])]
        if len(rows) != 1:
            raise RemapError(f"{gsid}: expected one import row, found {len(rows)}")
        row = rows[0]
        inv = manifest.get(row["bundleName"])
        prefab = row.get("battlePrefabAssetPath")
        if not inv or inv.get("battlePrefabAsset") != prefab or not str(prefab).endswith("/OwnedSkinned/owned_skinned.prefab"):
            raise RemapError(f"{gsid}: import row is not an owned skinned manifest unit ({row['bundleName']})")
        units.setdefault(inv["unitSid"], {"labSid": inv["unitSid"], "bundleName": row["bundleName"],
                                          "gameUnitSids": sorted(set(row["gameUnitSids"])), "prefab": prefab})
    return list(units.values())


def plan_unit(unit: dict, views: dict) -> dict:
    root = unit["prefab"].rsplit("/", 1)[0]
    desired = desired_slots(views, unit["gameUnitSids"])
    required = [unit["prefab"], root + "/owned_skinned.overrideController"]
    required += [f"{root}/Animations/{d['clip']}.anim" for d in desired]
    for rel in required:
        if not (PROJECT / rel).is_file():
            raise RemapError(f"{unit['labSid']}: required source asset missing: {rel} "
                             "(a missing clip cannot be substituted; the unit needs a source rebuild)")
    root_dir = PROJECT / root
    inputs = [{"path": p.relative_to(PROJECT).as_posix(), "sha256": sha(p)}
              for p in sorted(root_dir.rglob("*")) if p.is_file()]
    return {"labSid": unit["labSid"], "bundleName": unit["bundleName"], "gameUnitSids": unit["gameUnitSids"],
            "sourcePrefabAsset": unit["prefab"], "sourceControllerAsset": root + "/owned_skinned.overrideController",
            "desired": desired, "inputAssets": inputs}


def identity_gate(lab_sids: list[str], out: Path) -> None:
    errors, summary = stock_identity_check(PROJECT, MANIFEST, set(lab_sids))
    dump(out / "stock_identity_gate.json", {"errors": errors, **summary})
    if errors:
        raise RemapError("stock controller identity gate failed:\n" + "\n".join(errors[:20]))


def check_pins(plan: dict, may_change: dict[str, str]) -> None:
    """may_change: AOC path -> the hash it must now have."""
    for unit in plan["units"]:
        for pin in unit["inputAssets"]:
            want = may_change.get(pin["path"], pin["sha256"])
            if sha(PROJECT / pin["path"]) != want:
                raise RemapError(f"{unit['labSid']}: source asset changed outside the remap: {pin['path']}")


def aoc_diff_is_override_only(before: Path, after: Path) -> list[str]:
    a = before.read_text(encoding="utf-8").splitlines()
    b = after.read_text(encoding="utf-8").splitlines()
    bad = [line for line in difflib.unified_diff(a, b, lineterm="", n=0)
           if line[:1] in "+-" and not line.startswith(("+++", "---"))
           and "m_OverrideClip:" not in line]
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("stage", choices=("plan", "remap", "bundles", "probe"))
    ap.add_argument("--cohort", required=True, help="cohort name in attack_slot_remap_cohorts.json, or a pilot name with --units")
    ap.add_argument("--units", nargs="+", help="explicit game SIDs (pilot)")
    ap.add_argument("--views-core", type=Path, required=True, help="candidate Core.zip whose units_views drive the slots")
    ap.add_argument("--unity-direct", action="store_true",
                    help="explicit opt-out: launch Unity directly instead of submitting to the Unity queue")
    args = ap.parse_args()
    global UNITY_DIRECT
    UNITY_DIRECT = args.unity_direct
    if not all(ch.isalnum() or ch == "_" for ch in args.cohort):
        raise RemapError("cohort name must be [A-Za-z0-9_]")
    out = OUT_ROOT / args.cohort
    game_sids = args.units or load(COHORTS)["cohorts"].get(args.cohort)
    if not game_sids:
        raise RemapError(f"unknown cohort {args.cohort}")
    core = args.views_core.resolve()
    core_sha = sha(core)
    plan_path = out / "plan.json"

    if args.stage == "plan":
        units = resolve_units(game_sids)
        identity_gate([u["labSid"] for u in units], out)
        views = load_views(core)
        plan = {"schema": "homm3_owned_attack_slot_remap_batch.v1", "cohort": args.cohort,
                "proof": "source-static plan; nothing edited", "gameUnitSids": sorted(game_sids),
                "corePath": str(core), "coreSha256": core_sha, "projectPath": str(PROJECT),
                "importSha256": sha(IMPORT), "manifestSha256": sha(MANIFEST),
                "units": [plan_unit(u, views) for u in units]}
        if plan_path.exists() and (out / "remap_report.json").exists():
            raise RemapError(f"{args.cohort} was already remapped; its plan is the record, not a draft")
        dump(plan_path, plan)
        for u in plan["units"]:
            print(f"{u['labSid']}: " + ", ".join(f"{d['slot']} -> {d['clip']}" for d in u["desired"])
                  + f" ({len(u['inputAssets'])} pinned)")
        return 0

    plan = load(plan_path)
    if plan["coreSha256"] != core_sha or sha(IMPORT) != plan["importSha256"] or sha(MANIFEST) != plan["manifestSha256"]:
        raise RemapError("candidate Core, import table or manifest changed since plan; re-plan")
    report_path = out / "remap_report.json"

    if args.stage == "remap":
        if report_path.exists():
            raise RemapError(f"{report_path} exists; this cohort was already remapped")
        check_pins(plan, {})
        identity_gate([u["labSid"] for u in plan["units"]], out)
        backup = out / "aoc_backup"
        for u in plan["units"]:
            dst = backup / u["labSid"] / "owned_skinned.overrideController"
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                # A refused launch (guard/lock) leaves backups of untouched AOCs; reuse only a byte-identical one.
                if sha(dst) != sha(PROJECT / u["sourceControllerAsset"]):
                    raise RemapError(f"backup {dst} differs from the current AOC; refusing to overwrite it")
                continue
            shutil.copy2(PROJECT / u["sourceControllerAsset"], dst)
        for src in EDITOR_SCRIPTS:
            shutil.copy2(src, PROJECT / "Assets/Editor" / src.name)
        result = unity("Homm3OwnedSkinnedAttackSlotRemap.RunFromCommandLine",
                       ["-attackSlotRemapPlan", plan_path, "-attackSlotRemapPlanSha256", sha(plan_path),
                        "-attackSlotRemapReport", report_path], out / "logs/unity_remap.log")
        report = load(report_path)
        after = {}
        for r in report["units"]:
            u = next(x for x in plan["units"] if x["labSid"] == r["labSid"])
            aoc = PROJECT / u["sourceControllerAsset"]
            if sha(aoc) != r["controllerSha256After"]:
                raise RemapError(f"{r['labSid']}: AOC hash differs from the Unity report")
            bad = aoc_diff_is_override_only(backup / r["labSid"] / "owned_skinned.overrideController", aoc)
            if bad:
                raise RemapError(f"{r['labSid']}: AOC changed beyond m_OverrideClip lines: {bad[:4]}")
            after[u["sourceControllerAsset"]] = r["controllerSha256After"]
            got = {p["slot"]: p["clip"] for p in r["after"]}
            for d in u["desired"]:
                if got.get(d["slot"]) != d["clip"]:
                    raise RemapError(f"{r['labSid']}: {d['slot']} is {got.get(d['slot'])}, planned {d['clip']}")
        check_pins(plan, after)
        dump(out / "remap.json", {**result, "reportSha256": sha(report_path), "aocAfter": after,
                                  "proof": "Unity Editor in-place override remap; source pins verified"})
        return 0

    report = load(report_path)
    after = load(out / "remap.json")["aocAfter"]
    check_pins(plan, after)
    rows = plan["units"]

    if args.stage == "bundles":
        identity_gate([u["labSid"] for u in rows], out)
        unit_list = out / "bundle_unit_sids.txt"
        unit_list.write_text("\n".join(u["labSid"] for u in rows) + "\n", encoding="utf-8")
        backup = out / ("before_build_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
        backup.mkdir(parents=True)
        shutil.copy2(CONTRACT, backup / CONTRACT.name)
        for u in rows:
            if (BUILD_OUT / u["bundleName"]).exists():
                shutil.copy2(BUILD_OUT / u["bundleName"], backup / u["bundleName"])
        shutil.copy2(BUILDER_SCRIPT, PROJECT / "Assets/Editor" / BUILDER_SCRIPT.name)
        result = unity("OldenEra.CustomUnitBuilder.BuildCustomUnitBundles.BuildFromManifest",
                       ["-manifestPath", MANIFEST, "-homm3UnitListPath", unit_list, "-outputPath", BUILD_OUT],
                       out / "logs/unity_bundles.log", output_dir=BUILD_OUT)
        contract = load(CONTRACT)
        changes = {}
        for u in rows:
            name, src = u["bundleName"], BUILD_OUT / u["bundleName"]
            if not src.is_file() or src.stat().st_size <= 0 or name not in contract["bundles"]:
                raise RemapError(f"missing built bundle or payload contract row: {name}")
            new = {**contract["bundles"][name], "length": src.stat().st_size, "sha256": sha(src).upper()}
            changes[name] = {"before": contract["bundles"][name], "after": new}
            contract["bundles"][name] = new
        dump(CONTRACT, contract)
        prefixes = [v for u in rows for v in ("--name-prefix", u["bundleName"])]
        # The shared gates match --name-prefix by startswith (custom_units_h3_mage also selects
        # custom_units_h3_mage_upg_alt), so they read an exact copy of this cohort's bundles instead.
        gate_dir = out / "gate_bundles"
        if gate_dir.exists():
            shutil.rmtree(gate_dir)
        gate_dir.mkdir()
        for u in rows:
            for suffix in ("", ".manifest"):
                src = BUILD_OUT / (u["bundleName"] + suffix)
                if src.is_file():
                    shutil.copy2(src, gate_dir / src.name)
        for tool in GATES:
            run([sys.executable, ROOT / "tools" / tool, "--bundle-dir", gate_dir, *prefixes],
                out / "logs" / f"{Path(tool).stem}.log", 600)
        run([sys.executable, ROOT / "tools" / ATTACK_CLIP_GATE, "--bundle-dir", BUILD_OUT, *prefixes, "--core", core],
            out / "logs" / f"{Path(ATTACK_CLIP_GATE).stem}.log", 600)
        parity = {u["bundleName"]: installed_parity(BUILD_OUT / u["bundleName"], INSTALLED_BUNDLES / u["bundleName"])
                  for u in rows}
        dump(out / "bundle_build.json", {**result, "installedParity": parity, "backup": str(backup), "contractChanges": changes,
                                         "attackClipViewsCore": str(core), "attackClipViewsCoreSha256": core_sha,
                                         "bundleHashes": {u["bundleName"]: sha(BUILD_OUT / u["bundleName"]) for u in rows},
                                         "proof": "generated bundles validated; not installed"})
        return 0

    if args.stage == "probe":
        built = load(out / "bundle_build.json")
        for u in rows:
            if sha(BUILD_OUT / u["bundleName"]) != built["bundleHashes"][u["bundleName"]]:
                raise RemapError(f"{u['bundleName']} changed since the bundle stage")
        by_sid = {r["labSid"]: r for r in report["units"]}
        spec = {"schema": "homm3_owned_attack_slot_remap_probe_spec.v1", "units": [
            {"labSid": u["labSid"], "bundlePath": str(BUILD_OUT / u["bundleName"]),
             "prefabAssetPath": u["sourcePrefabAsset"].lower(), "expected": by_sid[u["labSid"]]["after"]} for u in rows]}
        spec_path, probe_out = out / "probe_spec.json", out / "probe_report.json"
        dump(spec_path, spec)
        if probe_out.exists():
            probe_out.rename(probe_out.with_name(f"probe_report_{datetime.now():%Y%m%d_%H%M%S}.json"))
        for src in EDITOR_SCRIPTS:
            shutil.copy2(src, PROJECT / "Assets/Editor" / src.name)
        result = unity("Homm3OwnedSkinnedAttackSlotRemap.ProbeFromCommandLine",
                       ["-attackSlotProbeSpec", spec_path, "-attackSlotProbeOut", probe_out], out / "logs/unity_probe.log")
        probe = load(probe_out)
        if {p["labSid"] for p in probe["units"]} != {u["labSid"] for u in rows} or any(not p["ok"] for p in probe["units"]):
            raise RemapError("attack-slot bundle probe failed: " + json.dumps([p for p in probe["units"] if not p["ok"]])[:2000])
        dump(out / "bundle_probe.json", {**result, "report": str(probe_out), "reportSha256": sha(probe_out),
                                         "bundleHashes": built["bundleHashes"]})
        return 0
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RemapError as exc:
        print(f"REMAP ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
