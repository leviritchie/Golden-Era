"""Contract for delivering def_retarget units in game (docs/homm3_unit_look_pipeline.md, "def_retarget delivery").

    python tools/validate_homm3_def_retarget_delivery_contract.py [--repo-root R] [--require-installed]
        [--selection NAME.json ...]

Always (source/static):
  - every selection under tools/homm3_def_retarget_delivery/*.json is well formed and pins its
    frozen inputs by sha256;
  - the lab builder routes motionAuthority "def_retarget" to BuildDefRetarget, which keeps Transform
    and blendShape curves, wraps the content in "Orientation" and bakes the VFX curves;
  - the VFX node-name contract is identical in the planner, the lab builder and the plugin runtime;
  - the plugin attaches Homm3UnitLookVfxRuntime from EnsureSkinnedBattleRuntimeCompatibility;
  - the bundle builder accepts the lane's .png albedo.
  - a row's mergeMeshes (a death shatter's *_Rubble on the body SMR, merge_rubble_glb.py) maps each node to a reason,
    names only *_Rubble nodes and never a deferMeshes node; a prepared plan records the same nodes, the lab master is
    the plan's stamped merge of the frozen retimed GLB (or of its COLOR_0 bake) and the lab mesh carries its vertices.
  - runtime record pins are refreshed only through ship_def_retarget_slice.py repin (dry run by default, fail closed;
    tests in test_ship_repin.py).
  - every existing Blender launch path uses the shared fail-closed game/disk/memory guard,
    and per-unit writer supervision retains its OS lock until the Job Object child exits.
For each selection whose output folder exists (generated artifacts, gitignored):
  - the frozen inputs still hash to the selection, the idle retime chains look-delivered -> retimed;
  - the lab report: one blendShape curve per mesh shape in every clip, weights reach the frame weight,
    clip lengths equal the GLB (Unit_Idle retimed), the master GLB is the frozen retimed GLB, the
    report was built from the current plan, every planned VFX node exists;
  - the bundle probe passed, and with --require-installed the installed bundles read back;
  - bundle_probe.json was made from the current freeze (selection + every frozen retimed GLB); a slice re-frozen
    after its probe reports "frozen; bundle probe predates this freeze", never "bundle probed" or "installed",
    and fails --require-installed.
  - a superseded selection (supersededBy) is never re-shipped: with --require-installed each bundle of its old
    readback must match a current (non-superseded) selection's readback of the installed file.
An explicit --selection limits only per-selection generated-artifact and installed-readback checks; global static and
repin checks still run. Without --selection, every selection JSON is checked (the release/full-validation default).
Fails closed; prints one line per violation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "homm3_def_retarget_delivery"))
from ship_def_retarget_slice import COLOR0_GLB, ShipError, look_spec, plan_repin, verify_frozen_stamp_pin  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent / "homm3_vfx"))
import displacement_mask_bake as dmb  # noqa: E402
import import_bindings  # noqa: E402  (tools/homm3_def_retarget_delivery)
import merge_rubble_glb  # noqa: E402  (tools/homm3_def_retarget_delivery)

PLUGIN = "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod"
NAMES = ("__homm3_vfx_billboard__", "__homm3_vfx_ground__", "__homm3_vfx_light__", "__homm3_vfx_uvatlas__")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
GOLDEN_BUNDLES = Path("V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era/BepInEx/plugins/OfflineUnlockMod/homm3_bundles")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def raw_stamp_checks(tag: str, sid: str, unit_dir: Path, frozen: dict, errors: list[str]) -> None:
    """Cheap normal-build gate for a frozen rawAccepted provenance pin; ship verifies embedded body pixels."""
    stamp_path = unit_dir / "inputs/stamp.json"
    if not stamp_path.is_file():
        if frozen.get("lookStampSha256"):
            errors.append(f"{tag}: {sid}: pinned rawAccepted stamp missing")
        return
    try:
        stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
        verify_frozen_stamp_pin(sid, stamp, stamp_path, frozen)
    except (ValueError, ShipError) as exc:
        errors.append(f"{tag}: {sid}: frozen stamp: {exc}")
        return
    if stamp.get("kind") == look_spec.RAW_ACCEPTED:
        spec_path = unit_dir / "inputs" / f"{sid}.json"
        if not spec_path.is_file():
            errors.append(f"{tag}: {sid}: frozen rawAccepted spec missing")
            return
        try:
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            errors.append(f"{tag}: {sid}: frozen rawAccepted spec unreadable: {exc}")
            return
        if look_spec.canonical_sha(spec) != frozen.get("specSha256"):
            errors.append(f"{tag}: {sid}: frozen rawAccepted spec differs from the selection")
        if not isinstance(spec.get("unit"), str) or not spec["unit"].strip():
            errors.append(f"{tag}: {sid}: frozen rawAccepted spec has no unit")
        errors += [f"{tag}: {sid}: frozen rawAccepted stamp: {e}"
                   for e in look_spec.raw_accepted_errors(stamp, spec.get("unit"))]
        if stamp.get("basecolorSha256") != frozen.get("basecolorSha256"):
            errors.append(f"{tag}: {sid}: frozen rawAccepted stamp basecolor differs from the selection")
    elif stamp.get("kind") is not None or stamp.get("basecolorFile") == look_spec.RAW_BASECOLOR:
        errors.append(f"{tag}: {sid}: unknown or unmarked frozen raw look kind")


def read(root: Path, rel: str, errors: list[str]) -> str:
    p = root / rel
    if not p.is_file():
        errors.append(f"missing source: {rel}")
        return ""
    return p.read_text(encoding="utf-8-sig", errors="replace")


def runner_guard_checks(root: Path, errors: list[str]) -> None:
    rt = "tools/homm3_def_retarget/"
    run_unit = read(root, rt + "run_unit.sh", errors)
    fleet = read(root, "tools/homm3_def_retarget_delivery/fleet_rebuild.py", errors)
    emphasis = read(root, "tools/homm3_def_retarget_emphasis/deliver.py", errors)
    gpuslot = read(root, "tools/homm3_unit_look/gpuslot.py", errors)
    guard = read(root, rt + "launch_guard.py", errors)
    memgate = read(root, rt + "memgate.py", errors)
    writer = read(root, rt + "unit_writer.py", errors)
    for name, source, anchor in (
        ("run_unit.sh", run_unit, 'python "$T/launch_guard.py"'),
        ("fleet_rebuild.py", fleet, 'launch_guard(log)'),
        ("emphasis deliver.py", emphasis, 'f"{RT}/launch_guard.py"'),
        ("look gpuslot.py", gpuslot, 'subprocess.run([sys.executable, LAUNCH_GUARD])'),
    ):
        if source and anchor not in source:
            errors.append(f"{name}: shared pre-Blender launch guard is not wired")
    if fleet and fleet.count("launch_guard(log)") < 2:
        errors.append("fleet_rebuild.py: each direct Blender launch needs its own guard")
    if guard:
        for anchor in ("HeroesOldenEra", "MIN_FREE_DISK_GB = 20.0", "memgate.check()", "if game_running():"):
            if anchor not in guard:
                errors.append(f"launch_guard.py: missing {anchor!r}")
        if guard.count("if game_running():") != 2:
            errors.append("launch_guard.py: game must be rechecked after the resource probes")
    if memgate:
        if "GlobalMemoryStatusEx" not in memgate or "if result.returncode != 0:" not in memgate:
            errors.append("memgate.py: native RAM or explicit nvidia-smi exit check missing")
        if "Get-CimInstance" in memgate or "return 99.0" in memgate:
            errors.append("memgate.py: permission-fragile or permissive probe fallback reintroduced")
    if writer:
        for anchor in ("JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE", "AssignProcessToJobObject", 'read(1) != b"1"',
                       'role="supervisor"', 'role="writer"', "JobObjectBasicAccountingInformation",
                       "validate_unit(args.unit)"):
            if anchor not in writer:
                errors.append(f"unit_writer.py: missing supervised per-unit lock contract {anchor!r}")


def static_checks(root: Path, errors: list[str]) -> None:
    runner_guard_checks(root, errors)
    lab = read(root, "tools/homm3_import/unity_editor/Homm3OwnedSkinnedLabBuild.cs", errors)
    dr = read(root, "tools/homm3_import/unity_editor/Homm3OwnedSkinnedLabBuild.DefRetarget.cs", errors)
    probe = read(root, "tools/homm3_import/unity_editor/ProbeDefRetargetDeliveryBundles.cs", errors)
    bundles = read(root, "tools/custom_prefab_pipeline/unity_editor/BuildCustomUnitBundles.cs", errors)
    runtime = read(root, f"{PLUGIN}/Homm3UnitLookVfxRuntime.cs", errors)
    visuals = read(root, f"{PLUGIN}/Homm3ImportVisuals.cs", errors)
    ship = read(root, "tools/homm3_def_retarget_delivery/ship_def_retarget_slice.py", errors)
    if lab and not re.search(r'spec\.motionAuthority == "def_retarget"\)\s*\{[^}]*BuildDefRetarget\(spec\);\s*return;', lab):
        errors.append("lab builder: motionAuthority def_retarget does not route to BuildDefRetarget before the per-clip GLB path")
    if dr:
        for anchor, why in [
            ('b.propertyName.StartsWith("blendShape.", StringComparison.Ordinal)', "blendShape curves are not kept"),
            ('private const string DefRetargetOrientationName = "Orientation";', "content is not wrapped in Orientation"),
            ('"material._MainTex_ST."', "uvAtlas ST curves are not baked"),
            ('"m_Enabled"', "flipbook/light enable curves are not baked"),
            ('"m_Intensity"', "light intensity curves are not baked"),
            ("has an unsupported curve", "unknown curve types are not refused"),
            ('ConstCurve(l.floor > 0f ? 1f : 0f)', "a clip without a light curve does not hold the light's floor (floor lights stay dark)"),
            ("LightRenderMode.ForcePixel", "effect lights are not Important (native particle lights would crowd them out of the per-object list)"),
        ]:
            if why and anchor not in dr:
                errors.append(f"lab builder def_retarget: {why} (anchor {anchor!r})")
        if "FlattenRotationTangents" in dr:
            errors.append("lab builder def_retarget must not flatten tangents (mixed STEP/LINEAR keys)")
        if "def_retarget_master.glb" not in dr:
            errors.append("lab builder def_retarget must import its master as Source/def_retarget_master.glb (the bundle builder root-adds Source/master.glb)")
    for name in NAMES:
        for label, text in (("lab builder", dr), ("plugin runtime", runtime), ("planner", ship + dr)):
            if text and name not in text:
                errors.append(f"{label}: VFX node name {name} missing (name contract drift)")
    if probe and "homm3_def_retarget_bundle_probe_spec.v1" not in probe:
        errors.append("bundle probe: spec schema anchor missing")
    if bundles and '"owned_skinned_basecolor.png"' not in bundles:
        errors.append("bundle builder: owned_skinned_basecolor.png is not accepted as the skinned albedo")
    if visuals:
        m = re.search(r"internal static bool EnsureSkinnedBattleRuntimeCompatibility\(.*?\n\t\}\n", visuals, re.S)
        if not m or "Homm3UnitLookVfxRuntime.TryAttach(instance, log);" not in m.group(0):
            errors.append("plugin: EnsureSkinnedBattleRuntimeCompatibility does not attach Homm3UnitLookVfxRuntime")
        if "attachUnitLookVfx: false" not in visuals:
            errors.append("plugin: the adventure-map idle must not attach the unit-look VFX (battle only)")
    if runtime:
        for anchor in ("ClassInjector.RegisterTypeInIl2Cpp<Homm3UnitLookVfxRuntime>()", 'Shader.Find("Sprites/Default")',
                       "_MainTex_ST", "battleSlowIdle"):
            if anchor not in runtime:
                errors.append(f"plugin runtime: anchor {anchor!r} missing")
        if re.search(r"\.parameters\b|GetParameter\(|AnimatorControllerParameterType", runtime):
            errors.append("plugin runtime: Animator.parameters / AnimatorControllerParameter break the Il2Cpp interop on this game; read floats by hash")
        if "Step(3)" not in runtime:
            errors.append("plugin runtime: the diag step must run on its own, independent of the other LateUpdate steps")
        if re.search(r"\b(?:ObjectPublic|Method_Public|Il2CppSystem\.Object\s+\w+\s*=)", runtime):
            errors.append("plugin runtime: raw generated IL2CPP names belong in GameSymbols.cs")


def probe_staleness(sel_path: Path, sel: dict, out: Path) -> str:
    """Empty when bundle_probe.json (if any) was made from the current freeze, else why not. The probe record's
    inputHashes pin the selection file and every unit's idle-retimed GLB (ship_def_retarget_slice.fingerprint)."""
    rec_p = out / "bundle_probe.json"
    if not rec_p.is_file():
        return "not probed (run prepare, lab, bundles, probe)" if (out / "installed_readback.json").is_file() else ""
    rec = json.loads(rec_p.read_text(encoding="utf-8"))
    hashes = {k.replace("\\", "/").lower(): v for k, v in rec.get("inputHashes", {}).items()}
    sel_key = str(sel_path.resolve()).replace("\\", "/").lower()
    if hashes.get(sel_key) != sha(sel_path):
        return "bundle probe predates this freeze (rerun prepare, lab, bundles, probe)"
    for row in sel["units"]:
        suffix = f"/{out.name.lower()}/{row['labSid'].lower()}/delivered_idle_retimed.glb"
        if next((v for k, v in hashes.items() if k.endswith(suffix)), None) != row["frozen"]["idleRetimedGlbSha256"]:
            return f"bundle probe predates this freeze at {row['labSid']} (rerun prepare, lab, bundles, probe)"
    return ""


def current_readbacks(root: Path) -> dict[str, dict[str, str]]:
    """{bundle: {selection: installed sha256}} from every non-superseded selection's installed_readback.json."""
    got: dict[str, dict[str, str]] = {}
    for sp in sorted((root / "tools/homm3_def_retarget_delivery").glob("*.json")):
        try:
            s = json.loads(sp.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - reported by its own selection_checks
            continue
        if not isinstance(s, dict) or s.get("supersededBy") or not s.get("out"):
            continue
        rb_p = root / s["out"] / "installed_readback.json"
        if rb_p.is_file():
            for b in json.loads(rb_p.read_text(encoding="utf-8")).get("bundles", []):
                got.setdefault(b["bundle"], {})[sp.name] = b["sha256"]
    return got


def runtime_import_checks(root: Path, tag: str, sel: dict, out: Path, require_installed: bool, errors: list[str]) -> None:
    """runtime_capability_build.json pins only its own units' homm3_import.json bindings (import_bindings.py), never the
    whole table: another unit's binding edit must not stale it, its own units' edits must."""
    rp = out / "runtime_capability_build.json"
    if not rp.is_file():
        return
    runtime = json.loads(rp.read_text(encoding="utf-8"))
    if "importTableSha256" in runtime:
        errors.append(f"{tag}: runtime record carries the retired whole-table importTableSha256 pin")
    tables = [("source", root / PLUGIN / "homm3_import.json")]
    if require_installed:
        tables.append(("installed", GOLDEN_BUNDLES.parent / "homm3_import.json"))
    for what, path in tables:
        try:
            import_bindings.check(runtime.get(import_bindings.KEY), json.loads(path.read_text(encoding="utf-8-sig")),
                                  sel["units"], f"{what} homm3_import.json")
        except (ValueError, OSError) as e:
            errors.append(f"{tag}: {e}")


def merged_master_checks(tag: str, sid: str, row: dict, plan: dict, lab: dict, errors: list[str]) -> str | None:
    """mergeMeshes: the plan names the row's nodes, the lab master is the plan's merged GLB (its stamp re-proven from
    the file) and the lab mesh carries the merged vertex count. Returns the merge's source GLB sha (which must then be
    the frozen retimed GLB or its COLOR_0 bake), or None for a row that merges nothing."""
    want = sorted(row.get("mergeMeshes") or {}) if isinstance(row.get("mergeMeshes") or {}, dict) else []
    got = sorted(m.get("node") for m in plan.get("mergedMeshes", []))
    if got != want:
        errors.append(f"{tag}: {sid}: plan merged meshes {got} differ from the selection's mergeMeshes {want}; rerun prepare")
        return None
    if not want:
        return None
    mm = plan.get("mergedMaster") or {}
    p = Path(mm.get("glb", ""))
    try:
        st = merge_rubble_glb.verify(p)
    except (merge_rubble_glb.MergeError, OSError) as e:
        errors.append(f"{tag}: {sid}: merged master {p.name}: {e}")
        return None
    if sha(p) != mm.get("sha256") or lab.get("masterGlbSha256") != mm.get("sha256") \
            or st["sourceGlbSha256"] != mm.get("sourceGlbSha256"):
        errors.append(f"{tag}: {sid}: lab master is not the plan's merged master GLB; rerun prepare and lab")
        return None
    if sorted(m["node"] for m in st["merged"]) != want or (lab.get("mesh") or {}).get("vertexCount") != st["totalVertices"] \
            or sorted(m.get("node") for m in lab.get("mergedMeshes", [])) != want:
        errors.append(f"{tag}: {sid}: lab mesh does not carry the merged vertices of {want}; rerun lab")
        return None
    return st["sourceGlbSha256"]


def repin_checks(root: Path, errors: list[str]) -> None:
    """Runtime record pins are refreshed by ship_def_retarget_slice.py repin only (never ad hoc scripts): a dry run by
    default, meshFx pins moved only to files identical in worktree / HEAD / install, bindings only added."""
    src = read(root, "tools/homm3_def_retarget_delivery/ship_def_retarget_slice.py", errors)
    for anchor in ('"deploy", "repin")', 'mode.add_argument("--write"', "repin_stage(args.selection, selection, args.write)",
                   "def plan_repin(", "def repin_stage("):
        if anchor not in src:
            errors.append(f"ship_def_retarget_slice.py: repin contract anchor {anchor!r} missing")
    if not (root / "tools/homm3_def_retarget_delivery/test_ship_repin.py").is_file():
        errors.append("test_ship_repin.py missing (repin's fail-closed tests)")
    row = {"labSid": "u", "bundleName": "b", "gameSid": "g"}
    table = {"entries": [{"bundleName": "b", "gameUnitSids": ["g"]}]}
    rec = {"meshFx": {"f": "old"}, import_bindings.KEY: import_bindings.pin(table, [row])}
    try:
        plan_repin(rec, [row], table, lambda r: "a", lambda r: "a", lambda r: "b")
        errors.append("repin: a meshFx file that differs in the install was re-pinned (must refuse)")
    except ShipError:
        pass
    try:
        plan_repin({**rec, import_bindings.KEY: import_bindings.pin(table, [row]) | {"units": {"u": "0" * 64}}},
                   [row], table, lambda r: "a", lambda r: "a", lambda r: "a")
        errors.append("repin: a changed own-unit binding was re-pinned (must refuse)")
    except ShipError:
        pass


def selection_checks(root: Path, sel_path: Path, require_installed: bool, errors: list[str]) -> str:
    try:
        sel = json.loads(sel_path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        errors.append(f"{sel_path.name}: unreadable ({e})")
        return "unreadable"
    tag = sel_path.name
    if sel.get("schema") != "homm3_def_retarget_delivery_selection.v1" or sel.get("accepted") is not False:
        errors.append(f"{tag}: schema/accepted invalid")
        return "invalid"
    for row in sel.get("units", []):
        fz = row.get("frozen", {})
        for key in ("lookDeliveredGlbSha256", "idleRetimedGlbSha256", "vfxManifestSha256", "specSha256", "basecolorSha256"):
            if not HEX64.match(str(fz.get(key, ""))):
                errors.append(f"{tag}: {row.get('labSid')}: frozen.{key} is not a sha256")
        if "lookStampSha256" in fz and not HEX64.match(str(fz["lookStampSha256"])):
            errors.append(f"{tag}: {row.get('labSid')}: frozen.lookStampSha256 is not a sha256")
        if row.get("albedo") not in ("uvAtlas", "basecolor"):
            errors.append(f"{tag}: {row.get('labSid')}: albedo mode {row.get('albedo')!r}")
        dl = row.get("deferLayers", {})
        if not isinstance(dl, dict) or any(not isinstance(v, str) or not v.strip() for v in dl.values()):
            errors.append(f"{tag}: {row.get('labSid')}: deferLayers must map each deferred layer id to a non-empty reason")
        dm = row.get("deferMeshes", {})
        if not isinstance(dm, dict) or any(not isinstance(v, str) or not v.strip() for v in dm.values()):
            errors.append(f"{tag}: {row.get('labSid')}: deferMeshes must map each deferred skinned-mesh node to a non-empty reason")
        mm = row.get("mergeMeshes", {})
        if not isinstance(mm, dict) or any(not isinstance(v, str) or not v.strip() for v in mm.values()):
            errors.append(f"{tag}: {row.get('labSid')}: mergeMeshes must map each merged skinned-mesh node to a non-empty reason")
        elif any(not n.endswith(merge_rubble_glb.RUBBLE_SUFFIX) for n in mm) or (isinstance(dm, dict) and set(dm) & set(mm)):
            errors.append(f"{tag}: {row.get('labSid')}: mergeMeshes takes only *_Rubble nodes, none of them deferred too")
    out = root / sel.get("out", "")
    if not out.is_dir():
        return "not built here"
    runtime_import_checks(root, tag, sel, out, require_installed, errors)
    state = "prepared"
    for row in sel["units"]:
        sid, fz = row["labSid"], row["frozen"]
        d = out / sid
        for rel, key in (("inputs/look_delivered.glb", "lookDeliveredGlbSha256"), ("delivered_idle_retimed.glb", "idleRetimedGlbSha256"),
                         ("inputs/vfx/vfx_manifest.json", "vfxManifestSha256"), ("inputs/basecolor.png", "basecolorSha256")):
            p = d / rel
            if not p.is_file() or sha(p) != fz[key]:
                errors.append(f"{tag}: {sid}: frozen input {rel} missing or changed")
        raw_stamp_checks(tag, sid, d, fz, errors)
        rep = d / "idle_retime_report.json"
        if rep.is_file():
            r = json.loads(rep.read_text(encoding="utf-8"))
            if r.get("srcSha256") != fz["lookDeliveredGlbSha256"] or r.get("dstSha256") != fz["idleRetimedGlbSha256"]:
                errors.append(f"{tag}: {sid}: idle retime does not chain the look-delivered GLB to the retimed GLB")
        plan_p = d / "unity/vfx_plan.json"
        lab_p = d / "lab_report.json"
        if not plan_p.is_file() or not lab_p.is_file():
            continue
        state = "lab built"
        plan = json.loads(plan_p.read_text(encoding="utf-8"))
        lab = json.loads(lab_p.read_text(encoding="utf-8"))
        merged_source = merged_master_checks(tag, sid, row, plan, lab, errors)
        if merged_source is not None:
            lab = {**lab, "masterGlbSha256": merged_source}   # the merge's source must pass the rules below
        if lab.get("masterGlbSha256") != fz["idleRetimedGlbSha256"]:
            # a bodyDisplacement unit's lab master is prepare's COLOR_0 bake of the frozen retimed GLB
            # (ship_def_retarget_slice.COLOR0_GLB, displacementMaskGlb); accepted only when its stamp re-proves the
            # bake and chains it to the frozen retimed sha -- the rule vanilla_style_fx.delivery_facts applies
            masked = d / COLOR0_GLB
            why = "lab master GLB is not the frozen retimed GLB"
            if masked.is_file():
                try:
                    st = dmb.verify(masked)
                except dmb.BakeError as ex:
                    st, why = None, f"lab master displacementMaskGlb {ex}"
                if st and st["outGlbSha256"] == lab.get("masterGlbSha256") and st["sourceGlbSha256"] == fz["idleRetimedGlbSha256"]:
                    why = None
                elif st:
                    why = "lab master GLB is neither the frozen retimed GLB nor its stamped COLOR_0 bake"
            if why:
                errors.append(f"{tag}: {sid}: {why}")
        if lab.get("vfxPlanSha256") != sha(plan_p):
            errors.append(f"{tag}: {sid}: lab was built from a different vfx plan; rerun lab")
        mesh = lab.get("mesh", {})
        shapes, fw = mesh.get("blendShapeCount", 0), mesh.get("blendShapeFrameWeight", 0)
        if shapes <= 0:
            errors.append(f"{tag}: {sid}: mesh has no blend shapes after import")
        lengths = plan.get("clipLengths", {})
        seen = set()
        for c in lab.get("clips", []):
            name = c["clip"]
            seen.add(name)
            if c.get("blendShapeCurves") != shapes:
                errors.append(f"{tag}: {sid}: {name} keeps {c.get('blendShapeCurves')} blendShape curves, mesh has {shapes}")
            if fw and abs(c.get("blendShapeMax", 0) - fw) > 0.01 * fw:
                errors.append(f"{tag}: {sid}: {name} blendShape max {c.get('blendShapeMax')} != frame weight {fw} (weight scale lost)")
            if name in lengths and abs(c.get("length", 0) - lengths[name]) > 1e-3:
                errors.append(f"{tag}: {sid}: {name} length {c.get('length')} != GLB {lengths[name]}")
            if c.get("vfxCurves", 0) <= 0 and (plan.get("quads") or plan.get("lights") or plan.get("uvAtlas")):
                errors.append(f"{tag}: {sid}: {name} carries no VFX curves")
        if seen != set(lengths):
            errors.append(f"{tag}: {sid}: lab clips {sorted(seen)} != GLB clips {sorted(lengths)}")
        dl = row.get("deferLayers", {}) if isinstance(row.get("deferLayers"), dict) else {}
        if sorted(d.get("layer") for d in plan.get("deferred", [])) != sorted(dl):
            errors.append(f"{tag}: {sid}: plan deferred layers differ from the selection's deferLayers; rerun prepare")
        dm = row.get("deferMeshes", {}) if isinstance(row.get("deferMeshes"), dict) else {}
        if sorted(d.get("node") for d in plan.get("deferredMeshes", [])) != sorted(dm):
            errors.append(f"{tag}: {sid}: plan deferred meshes differ from the selection's deferMeshes; rerun prepare")
        for light in plan.get("lights", []):
            floor = light.get("floor", 0)
            for c in light.get("clips", []):
                keys = c.get("keys", [])
                if floor > 0 and keys and (keys[0].get("t", 0) > 0 or min(k.get("intensity", 0) for k in keys) < floor):
                    errors.append(f"{tag}: {sid}: light {light.get('id')} {c.get('clip')} does not rest at its floor {floor} outside its windows")
        nodes = {n.get("name") for n in lab.get("vfxNodes", []) if n.get("name")}
        want = {q["name"] for q in plan.get("quads", [])} | {l["name"] for l in plan.get("lights", [])}
        if want - nodes:
            errors.append(f"{tag}: {sid}: planned VFX nodes missing from the lab prefab: {sorted(want - nodes)}")
        if lab.get("orientationNode") != "Orientation":
            errors.append(f"{tag}: {sid}: prefab has no Orientation node")
    # A superseded selection is never shipped again (ship refuses it); marking it edits the selection after its probe.
    stale = "" if sel.get("supersededBy") else probe_staleness(sel_path, sel, out)
    if stale:
        # The frozen inputs moved on (a re-freeze) after the last probe: the probe/readback describe an older
        # build, so the slice is not deploy-ready and must not be reported as probed or installed.
        if require_installed:
            errors.append(f"{tag}: --require-installed but {stale}")
        return f"frozen; {stale}"
    probe_p = out / "bundle_probe_report.json"
    if probe_p.is_file():
        state = "bundle probed"
        probe = json.loads(probe_p.read_text(encoding="utf-8"))
        for u in probe.get("units", []):
            if not u.get("ok"):
                errors.append(f"{tag}: bundle probe failed for {u.get('labSid')}: {u.get('errors')}")
    rb_p = out / "installed_readback.json"
    if rb_p.is_file() and sel.get("supersededBy"):
        # A superseded slice's bundles were re-installed by its successors (ship refuses to ship it again), so its
        # own readback is history. Each of its bundles must instead be what a current (non-superseded) slice's
        # readback says is installed; a bundle no current slice delivers is still a violation.
        rb = json.loads(rb_p.read_text(encoding="utf-8"))
        if require_installed:
            current = current_readbacks(root)
            for b in rb.get("bundles", []):
                p = GOLDEN_BUNDLES / b["bundle"]
                owners = [s for s, h in current.get(b["bundle"], {}).items() if p.is_file() and sha(p) == h]
                if not owners:
                    errors.append(f"{tag}: superseded, but installed bundle {b['bundle']} matches no current slice's readback")
        return f"superseded by {sel['supersededBy']}; bundles delivered by current slices"
    if rb_p.is_file():
        rb = json.loads(rb_p.read_text(encoding="utf-8"))
        if require_installed:
            for b in rb.get("bundles", []):
                p = GOLDEN_BUNDLES / b["bundle"]
                if not p.is_file() or sha(p) != b["sha256"]:
                    errors.append(f"{tag}: installed bundle {b['bundle']} differs from the slice readback")
        state = "installed"
    elif require_installed:
        errors.append(f"{tag}: --require-installed but no installed_readback.json")
    return state


def resolve_selection_scope(root: Path, requested: list[str] | None) -> tuple[list[Path], list[Path], str, list[str]]:
    selection_dir = root / "tools/homm3_def_retarget_delivery"
    available = sorted(selection_dir.glob("*.json"))
    errors: list[str] = []
    if not available:
        errors.append(f"no delivery selection JSON files found in {selection_dir}")

    if requested is None:
        return available, available, f"all ({len(available)}/{len(available)})", errors

    by_name = {path.name: path for path in available}
    unknown = list(dict.fromkeys(name for name in requested if name not in by_name))
    if unknown:
        errors.append(f"unknown delivery selection(s): {', '.join(unknown)}")
        return [], available, f"invalid (unknown: {', '.join(unknown)})", errors

    requested_names = set(requested)
    selected = [path for path in available if path.name in requested_names]
    names = ", ".join(path.name for path in selected)
    return selected, available, f"selected ({len(selected)}/{len(available)}: {names})", errors


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    ap.add_argument("--require-installed", action="store_true")
    ap.add_argument(
        "--selection",
        action="append",
        default=None,
        metavar="NAME.json",
        help=(
            "Limit per-selection generated-artifact/readback checks to this exact JSON basename; repeatable. "
            "Global static and repin checks still run. Omitting it checks all selections."
        ),
    )
    args = ap.parse_args()
    root = Path(args.repo_root).resolve()
    errors: list[str] = []
    selections, _all_selections, scope, scope_errors = resolve_selection_scope(root, args.selection)
    static_checks(root, errors)
    repin_checks(root, errors)
    errors.extend(scope_errors)
    states = {}
    if not scope_errors:
        for sel in selections:
            states[sel.name] = selection_checks(root, sel, args.require_installed, errors)
    for e in errors:
        print("FAIL " + e)
    print(
        f"homm3 def_retarget delivery contract: {len(states)} selection(s) {states}, "
        f"{len(errors)} violation(s), scope={scope}"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
