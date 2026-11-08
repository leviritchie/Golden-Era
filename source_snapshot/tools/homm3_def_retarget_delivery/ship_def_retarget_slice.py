"""Ship an explicit selection of def_retarget units into the game through the native owned-skinned lane.

    python tools/homm3_def_retarget_delivery/ship_def_retarget_slice.py <stage> [--selection S]

Stages (each one re-checks the frozen inputs first; every Unity step is a job submitted to the Unity queue,
tools/unity_queue, whose runner preflights memgate/launch guard and batches jobs per project):

  prepare  verify the frozen inputs (look-delivered GLB, idle-retimed GLB, vfx manifest + assets,
           spec) against the selection, write the delivery textures, one ``vfx_plan.json`` per unit
           and ``unity_lab_batch.json`` (motionAuthority ``def_retarget``)
  lab      copy the editor scripts into the Unity project and run
           Homm3OwnedSkinnedLabBuild.BuildFromCommandLine (the existing lab builder; def_retarget
           keeps Transform + blendShape curves and bakes the VFX plan into the clips)
  bundles  the existing BuildCustomUnitBundles.BuildFromManifest for exactly these units, contract
           rows updated, payload validators run
  probe    load the built bundles in the editor (ProbeDefRetargetDeliveryBundles) and check the
           prefab, clips, blend-shape curves and VFX nodes survive the bundle
  deploy   game stopped; require the installed plugin's payload sidecar to carry the record's UnitBundle
           version (docs/plugin_payload_abi.md; the slice never copies a plugin DLL), back up, copy the
           bundles and (when the runtime record pins it) homm3_import.json, read back
  repin    refresh the runtime record's data pins (dry run unless --write): meshFx pins move only to files
           byte-identical in the worktree, at HEAD and in the install (no plugin-data change ships); a selection
           unit with no importBindings pin gets import_bindings.unit_digest; anything else refuses with the reasons

Vanilla-style rows (``vfxAuthority: vanilla_style``, docs/olden_era_vanilla_vfx_style.md 8.3): the unit-look
layers the row's ``vanillaStyleSpec`` supersedes (uvAtlas glow, defFlipbook sheets, effect lights, volumetric
fire, event hideMesh/missile) are left out of the plan, the albedo is the delivery basecolor, and the effects ride the plugin folder
(``homm3_mesh_fx`` catalog + emission PNGs) instead of the bundle; deploy copies those files as pinned by the
runtime record's ``meshFx`` map. ``--mesh-fx-source REL=PATH`` (deploy only) takes one pinned file from PATH instead
of the shared worktree plugin folder, so a slice can ship the committed catalog while other agents still compile
into the worktree copy; it is refused unless PATH's sha equals both the record's pin and the blob committed at HEAD,
and the readback records the source. A selection marked ``supersededBy`` is refused.

displacementMaskGlb (a vanilla-style spec's ``bodyDisplacement`` layer, lane battle_body_displacement): Hex/Lit FLAG
displacement reads the body mesh's COLOR_0.r, which a delivered GLB does not carry. prepare bakes the layer's mask
into ``<unit>/delivered_idle_retimed.color0.glb`` with tools/homm3_vfx/displacement_mask_bake.py (stamped, refused
unless the stamp's source is the frozen idle-retimed GLB and its rule is the spec's mask) and hands the lab builder
that GLB as the master; the lab builder refuses a master whose hash is not the plan's or whose mesh imported without
a colour stream. bundles and deploy require the unit's compiled vanilla-style record to pin the same mask sha
(``displacementBake``), so the catalog row describes the mesh that ships; probe reads the colour stream back out of
the built bundle (ProbeDisplacementMaskBundles.cs: vertex count and mask mean/max against the bake stamp) and deploy
refuses a displacement row without that readback. Proof tier of the whole chain: generated/installed payload; the wave in game is unproven.

mergeMeshes (a selection row's ``{"<unit>_Rubble": reason}``, written by freeze_slice.py or moved from deferMeshes by
``merge_rubble_glb.py rows``): a death shatter's rubble mesh ships appended to the body primitive. prepare runs
merge_rubble_glb.merge on the lab master (the frozen retimed GLB, or its displacement bake) into
``<unit>/unity/merged_master.glb`` (stamped, lossless: check_equivalent) and records ``mergedMaster`` / ``mergedMeshes``
(vertex ranges) in the plan; the lab builder refuses a master whose one SMR does not carry the plan's merged vertex
count; probe reads the bundle's mesh vertex count and bakes the skin at Unit_Death keys: the rubble range is collapsed
before the break and spread after it, and collapsed in Unit_Idle (rubble_probe_checks). One body SMR and one
material, so the runtime needs no change. A node in both deferMeshes and mergeMeshes refuses.

The plan is Unity-agnostic data. Time mapping: the idle retime (docs/homm3_idle_cadence.md)
maps every idle key time t to t0 + (t - t0) * factor with t0 = the idle's first key (1/12 s),
so VFX windows of Unit_Idle are mapped the same way. Other clips are untouched.
Unity root space of a Blender world point (x, y, z) is (-x, z, -y) (Blender -> glTF Y-up ->
glTFast X mirror); the builder turns it into anchor-bone space by sampling the clip.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import struct
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/homm3_unit_look"))
import spec as look_spec  # noqa: E402
from glbpatch import Glb, sha256_bytes  # noqa: E402
sys.path.insert(0, str(ROOT / "tools/plugin_payload_abi"))
import payload_abi  # noqa: E402
import import_bindings  # noqa: E402  (same directory)
import merge_rubble_glb  # noqa: E402  (same directory)

UNITY = Path("C:/Program Files/Unity/Hub/Editor/6000.0.66f2/Editor/Unity.exe")
PROJECT = (ROOT / "oldenera_factions").resolve()
BUILD_OUT = ROOT / "tools/homm3_import/build_out"
CONTRACT = ROOT / "custom_factions/contracts/homm3_bundle_payload_contract.json"
INVENTORY = ROOT / "tools/homm3_import/homm3_units_manifest.json"
IMPORT = ROOT / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_import.json"
GOLDEN = Path("V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era")
MEMGATE = ROOT / "tools/homm3_def_retarget/memgate.py"
UNITYLOCK = ROOT / "tools/homm3_vfx/unitylock.py"
DEFAULT_SELECTION = ROOT / "tools/homm3_def_retarget_delivery/cove_slice_v1.json"
EDITOR_SCRIPTS = (
    ROOT / "tools/homm3_import/unity_editor/Homm3OwnedSkinnedLabBuild.cs",
    ROOT / "tools/homm3_import/unity_editor/Homm3OwnedSkinnedLabBuild.DefRetarget.cs",
    ROOT / "tools/custom_prefab_pipeline/unity_editor/BuildCustomUnitBundles.cs",
)
PROBE_SCRIPT = ROOT / "tools/homm3_import/unity_editor/ProbeDefRetargetDeliveryBundles.cs"
# displacementMaskGlb rows only: reads the body mesh's colour stream back out of the built bundle
DISPLACEMENT_PROBE_SCRIPT = ROOT / "tools/homm3_import/unity_editor/ProbeDisplacementMaskBundles.cs"
DISPLACEMENT_MASK_TOLERANCE = 0.01  # |bundle mean(COLOR.r) - stamp mean| (8-bit quantised both sides)
# The plugin surface these bundles need (UnitBundleContractVersion in PluginPayloadAbi.cs); its reader files are
# listed in tools/plugin_payload_abi/surfaces.json. The runtime record pins this version, not a DLL hash.
PAYLOAD_SURFACE = "UnitBundle"
PLUGIN_DIR = ROOT / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod"
# vfxAuthority vanilla_style: the unit-look layers of these types are superseded by
# tools/homm3_vfx/vanilla_style/units/<unit>.json (emission map + vanilla particles in the plugin catalog)
SUPERSEDED_TYPES = ("uvAtlas", "defFlipbook", "effectLight", "volumetricFire", "event")

FPS = 12.0
IDLE = "Unit_Idle"
# lifecycle role per clip (owns loopTime in the lab builder); the stock map is the builder's
ROLES = {
    "Unit_Idle": "cycle", "Unit_Move": "cycle", "Unit_Mouseover": "cycle", "Unit_Defence": "cycle",
    "Unit_MoveStart": "entry", "Unit_MoveEnd": "exit", "Unit_AttackFront": "one_shot",
    "Unit_ShootFront": "one_shot", "Unit_Hitted": "one_shot", "Unit_Death": "terminal",
}
QUAD_PREFIX = {"billboard": "__homm3_vfx_billboard__", "groundPlane": "__homm3_vfx_ground__"}
LIGHT_PREFIX = "__homm3_vfx_light__"
NEUTRAL_NORMAL = (128, 128, 255, 255)
NEUTRAL_METALLIC_GLOSS = (0, 0, 0, 89)       # metallic 0, smoothness 0.35 (the runtime's own constant)
# Largest corrective morph offset allowed, as a multiple of the rest mesh height. bake_cs.py solves each
# offset through the vertex's blended bone rotation; a near-singular blend passes its det > 1e-6 guard and
# explodes (h3_storm_elemental 320 units on a 1.7-unit body, h3_pegasus 18 on 1.78). Unity sizes the
# SkinnedMeshRenderer's dirty AABB from the morph extents, the battle fit reads that AABB, and the unit
# ships at 1/250 of its size (2026-09-26 in game: storm elemental invisible). Measured sound units reach 0.73.
MORPH_DELTA_MAX_HEIGHT_RATIO = 1.5


class ShipError(Exception):
    pass


BACKUPS_KEPT = 3


def prune_backups(out, prefix, keep=BACKUPS_KEPT):
    """Keep the newest `keep` rollback snapshots of one kind; every ship makes one (~400 MB each)."""
    for old in sorted(out.glob(prefix + "_*"))[:-keep]:
        if old.is_dir():
            shutil.rmtree(old)


def load(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def dump(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def canonical_sha(obj) -> str:
    sys.path.insert(0, str(ROOT / "tools/homm3_unit_look"))
    import spec as look_spec  # noqa: E402
    return look_spec.canonical_sha(obj)


# ---------------------------------------------------------------- GLB reading (no numpy needed)
def read_glb(path: Path):
    b = path.read_bytes()
    if b[:4] != b"glTF":
        raise ShipError(f"{path}: not a GLB")
    jl = struct.unpack("<I", b[12:16])[0]
    js = json.loads(b[20:20 + jl])
    bin0 = 20 + jl + 8
    return js, b, bin0


def accessor_floats(js, b, bin0, index) -> list[float]:
    acc = js["accessors"][index]
    if acc["componentType"] != 5126:
        raise ShipError("non-float accessor")
    bv = js["bufferViews"][acc["bufferView"]]
    width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[acc["type"]]
    o = bin0 + bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = bv.get("byteStride", 4 * width)
    out = []
    for i in range(acc["count"]):
        out.extend(struct.unpack_from("<" + "f" * width, b, o + i * stride))
    return out


def accessor_vec3(js, b, bin0, index) -> list[tuple]:
    """A float VEC3 accessor as tuples, sparse accessors (glTF morph targets) included."""
    acc = js["accessors"][index]
    if acc["componentType"] != 5126 or acc["type"] != "VEC3":
        raise ShipError("expected a float VEC3 accessor")
    count = acc["count"]
    if "bufferView" in acc:
        flat = accessor_floats(js, b, bin0, index)
        out = [tuple(flat[i:i + 3]) for i in range(0, 3 * count, 3)]
    else:
        out = [(0.0, 0.0, 0.0)] * count
    sp = acc.get("sparse")
    if sp:
        n = sp["count"]
        fmt = {5121: "B", 5123: "H", 5125: "I"}[sp["indices"]["componentType"]]
        iv, vv = js["bufferViews"][sp["indices"]["bufferView"]], js["bufferViews"][sp["values"]["bufferView"]]
        idx = struct.unpack_from("<" + fmt * n, b, bin0 + iv.get("byteOffset", 0) + sp["indices"].get("byteOffset", 0))
        val = struct.unpack_from("<" + "f" * (3 * n), b, bin0 + vv.get("byteOffset", 0) + sp["values"].get("byteOffset", 0))
        for k, i in enumerate(idx):
            out[i] = val[3 * k:3 * k + 3]
    return out


def morph_extent(js, b, bin0) -> dict:
    """Largest morph-target offset against the rest height, per GLB (see MORPH_DELTA_MAX_HEIGHT_RATIO)."""
    worst, worst_name, height = 0.0, None, 0.0
    for m in js.get("meshes", []):
        names = m.get("extras", {}).get("targetNames", [])
        for p in m["primitives"]:
            ys = [v[1] for v in accessor_vec3(js, b, bin0, p["attributes"]["POSITION"])]
            height = max(height, max(ys) - min(ys))
            for t, target in enumerate(p.get("targets", [])):
                if "POSITION" not in target:
                    continue
                d = max((x * x + y * y + z * z) ** 0.5 for x, y, z in accessor_vec3(js, b, bin0, target["POSITION"]))
                if d > worst:
                    worst, worst_name = d, (names[t] if t < len(names) else str(t))
    return {"worstDelta": round(worst, 4), "worstTarget": worst_name, "restHeight": round(height, 4),
            "ratio": round(worst / height, 4) if height > 0 else None}


def glb_facts(path: Path) -> dict:
    js, b, bin0 = read_glb(path)
    clips = {}
    for an in js.get("animations", []):
        times = set()
        for s in an["samplers"]:
            times.update(accessor_floats(js, b, bin0, s["input"]))
        clips[an["name"]] = {"first": min(times), "last": max(times)}
    meshes = js.get("meshes", [])
    targets = [len(p.get("targets", [])) for m in meshes for p in m["primitives"]]
    names = [n.get("name") for n in js.get("nodes", [])]
    return {"clips": clips, "morphTargets": targets, "morphExtent": morph_extent(js, b, bin0), "nodes": names,
            "skins": len(js.get("skins", [])), "joints": [names[j] for j in js["skins"][0]["joints"]] if js.get("skins") else []}


# ---------------------------------------------------------------- selection and freeze
def unit_dir(out: Path, sid: str) -> Path:
    return out / sid


VS_COMPILED_DIR = ROOT / "tools/homm3_vfx/vanilla_style/compiled"
COLOR0_GLB = "delivered_idle_retimed.color0.glb"


def displacement_layer(row: dict) -> dict | None:
    """The vanilla-style spec's bodyDisplacement layer for a vanilla_style row (at most one), else None."""
    if row.get("vfxAuthority") != "vanilla_style":
        return None
    spec = load(ROOT / row["vanillaStyleSpec"])
    layers = [l for l in spec.get("layers", []) if l.get("type") == "bodyDisplacement"]
    if len(layers) > 1:
        raise ShipError(f"{row['labSid']}: more than one bodyDisplacement layer")
    return layers[0] if layers else None


def displacement_mask_glb(row: dict, out: Path, *, bake: bool) -> dict | None:
    """displacementMaskGlb: bake (prepare) or re-verify (later stages) the COLOR_0.r mask GLB the lab builds from.
    Refused unless the stamp's source is the frozen idle-retimed GLB and its rule is the spec layer's mask."""
    layer = displacement_layer(row)
    if layer is None:
        return None
    sys.path.insert(0, str(ROOT / "tools/homm3_vfx"))
    import displacement_mask_bake as dmb  # noqa: E402
    sid = row["labSid"]
    d = unit_dir(out, sid)
    src, dst = d / "delivered_idle_retimed.glb", d / COLOR0_GLB
    try:
        stamp = dmb.bake(src, dst, layer["mask"]) if bake else dmb.verify(dst)
    except dmb.BakeError as exc:
        raise ShipError(f"{sid}: displacementMaskGlb {exc}") from exc
    if stamp["sourceGlbSha256"] != row["frozen"]["idleRetimedGlbSha256"]:
        raise ShipError(f"{sid}: displacementMaskGlb was not baked from the frozen idle-retimed GLB")
    if stamp["rule"] != layer["mask"]:
        raise ShipError(f"{sid}: displacementMaskGlb rule is not the spec's {layer['id']} mask; rerun prepare")
    return {"layer": layer["id"], "glb": str(dst.resolve()), "sha256": stamp["outGlbSha256"],
            "sourceGlbSha256": stamp["sourceGlbSha256"], "stampSha256": sha(Path(str(dst) + ".stamp.json"))}


def displacement_probe(rows: list[dict], out: Path) -> dict | None:
    """Editor-load each displacementMaskGlb row's built bundle and read COLOR.r back; compare with the bake stamp."""
    need = [(r, displacement_mask_glb(r, out, bake=False)) for r in rows]
    need = [(r, dm) for r, dm in need if dm]
    if not need:
        return None
    shutil.copy2(DISPLACEMENT_PROBE_SCRIPT, PROJECT / "Assets/Editor" / DISPLACEMENT_PROBE_SCRIPT.name)
    spec = {"schema": "homm3_displacement_mask_bundle_probe_spec.v1",
            "units": [{"labSid": r["labSid"], "bundlePath": str(BUILD_OUT / r["bundleName"]),
                       "prefabAssetPath": f"Assets/CustomUnits/homm3_lab/{r['labSid']}/OwnedSkinned/owned_skinned.prefab"}
                      for r, _ in need]}
    spec_path, report = out / "displacement_probe_spec.json", out / "displacement_probe_report.json"
    dump(spec_path, spec)
    if report.exists():
        report.unlink()
    result = unity("OldenEra.Homm3Import.ProbeDisplacementMaskBundles.Run",
                   ["-displacementProbeSpec", spec_path, "-displacementProbeOut", report], out / "logs/unity_displacement_probe.log")
    got = {u["labSid"]: u for u in load(report)["units"]}
    for r, dm in need:
        u = got.get(r["labSid"])
        if not u or not u["ok"] or not u["vertexColors"]:
            raise ShipError(f"{r['labSid']}: displacement bundle probe failed: {u and u.get('errors')}")
        # the bundle keeps one body SMR (a deferred / dropped skinned mesh is baked too, with its own primitive):
        # exactly one baked primitive must be that body, and its mask must survive the bundle
        stamp = load(Path(dm["glb"] + ".stamp.json"))
        plan = load(unit_dir(out, r["labSid"]) / "unity/vfx_plan.json")
        mm = verify_merged_master(plan, dm["sha256"])
        if mm:
            # mergeMeshes: the body SMR is the body primitive with the merged ones appended, so the expected
            # mask is their vertex-weighted mean and their max
            meshes = [mm["bodySourceMesh"]] + [m["sourceMesh"] for m in plan["mergedMeshes"]]
            parts = [p for p in stamp["primitives"] if p["mesh"] in meshes]
            n = sum(p["vertices"] for p in parts)
            body = ([{"vertices": n, "maskMean": sum(p["maskMean"] * p["vertices"] for p in parts) / n,
                      "maskMax": max(p["maskMax"] for p in parts)}]
                    if len(parts) == len(meshes) and n == u["vertexCount"] else [])
        else:
            body = [p for p in stamp["primitives"] if p["vertices"] == u["vertexCount"]]
        if len(body) != 1 or abs(u["maskMean"] - body[0]["maskMean"]) > DISPLACEMENT_MASK_TOLERANCE                 or abs(u["maskMax"] - body[0]["maskMax"]) > DISPLACEMENT_MASK_TOLERANCE:
            raise ShipError(f"{r['labSid']}: bundle mask (vertices {u['vertexCount']}, mean {u['maskMean']:.4f}, max "
                            f"{u['maskMax']:.4f}) is not one baked primitive's ({stamp['primitives']})")
    return {**result, "report": str(report), "reportSha256": sha(report),
            "probeSourceSha256": sha(DISPLACEMENT_PROBE_SCRIPT),
            "units": {r["labSid"]: dm["sha256"] for r, dm in need}}


def require_displacement_compiled(rows: list[dict], out: Path) -> None:
    """The catalog row (vanilla_style_fx compile, displacementBake) must describe the mask GLB this slice ships."""
    for row in rows:
        dm = displacement_mask_glb(row, out, bake=False)
        if dm is None:
            continue
        sid = row["labSid"]
        plan = load(unit_dir(out, sid) / "unity/vfx_plan.json")
        if (plan.get("displacementMaskGlb") or {}).get("sha256") != dm["sha256"]:
            raise ShipError(f"{sid}: vfx_plan displacementMaskGlb is not the verified bake; rerun prepare")
        report = load(unit_dir(out, sid) / "lab_report.json")
        mm = verify_merged_master(plan, dm["sha256"])
        if report.get("masterGlbSha256") != (mm["sha256"] if mm else dm["sha256"]):
            raise ShipError(f"{sid}: lab report was not built from the displacement mask GLB"
                            f"{' (merged)' if mm else ''}; rerun lab")
        rec_path = VS_COMPILED_DIR / f"{sid}.json"
        bake = (load(rec_path).get("displacementBake") or {}).get(dm["layer"]) if rec_path.is_file() else None
        if not bake or bake.get("outGlbSha256") != dm["sha256"]:
            raise ShipError(f"{sid}: compiled vanilla-style record does not pin displacementMaskGlb {dm['sha256'][:12]}; "
                            "run vanilla_style_fx.py compile --unit after the lab stage")


def verify_frozen_look_kind(sid: str, source_unit: str, stamp: dict, look_glb: Path,
                            basecolor_sha: str, manifest: dict) -> None:
    """The frozen copy must retain rawAccepted evidence, not just its four content hash fields."""
    kind = stamp.get("kind")
    if kind is None:
        if stamp.get("basecolorFile") == look_spec.RAW_BASECOLOR:
            raise ShipError(f"{sid}: raw basecolor stamp has no rawAccepted kind")
        return
    if kind != look_spec.RAW_ACCEPTED:
        raise ShipError(f"{sid}: unknown frozen look stamp kind {kind!r}")
    bad = look_spec.raw_accepted_errors(stamp, source_unit)
    if bad:
        raise ShipError(f"{sid}: frozen rawAccepted stamp refused: {'; '.join(bad)}")
    if any(ly.get("type") == "uvAtlas" for ly in manifest.get("layers", {}).values()):
        raise ShipError(f"{sid}: rawAccepted ships the raw body image, not a uvAtlas albedo")
    try:
        glb = Glb.load(look_glb)
        embedded_sha = sha256_bytes(glb.image_bytes(glb.body_base_color_image()))
    except (KeyError, IndexError, ValueError) as exc:
        raise ShipError(f"{sid}: cannot verify frozen rawAccepted GLB body image: {exc}") from exc
    if embedded_sha != basecolor_sha:
        raise ShipError(f"{sid}: frozen rawAccepted basecolor is not the GLB's embedded body image")


def verify_frozen_stamp_pin(sid: str, stamp: dict, stamp_path: Path, frozen: dict) -> None:
    pin = frozen.get("lookStampSha256")
    if pin is None and stamp.get("kind") != look_spec.RAW_ACCEPTED:
        return  # older applied-look rows have no whole-stamp pin
    if stamp.get("kind") != look_spec.RAW_ACCEPTED or not pin or sha(stamp_path) != pin:
        raise ShipError(f"{sid}: rawAccepted stamp is missing, changed, or no longer pinned by the selection")


def verify_freeze(selection: dict, out: Path, *, pins_only: bool = False) -> dict:
    """Every frozen input must still hash to the selection's pins. Returns per-unit facts unless pins_only."""
    facts = {}
    for row in selection["units"]:
        sid, fz = row["labSid"], row["frozen"]
        d = unit_dir(out, sid)
        inp = d / "inputs"
        checks = {
            inp / "look_delivered.glb": fz["lookDeliveredGlbSha256"],
            d / "delivered_idle_retimed.glb": fz["idleRetimedGlbSha256"],
            inp / "vfx/vfx_manifest.json": fz["vfxManifestSha256"],
            inp / "basecolor.png": fz["basecolorSha256"],
        }
        for p, want in checks.items():
            if not p.is_file():
                raise ShipError(f"{sid}: frozen input missing: {p}")
            got = sha(p)
            if got != want:
                raise ShipError(f"{sid}: frozen input changed: {p.name} {got[:12]} != {want[:12]}")
        stamp = load(inp / "stamp.json")
        verify_frozen_stamp_pin(sid, stamp, inp / "stamp.json", fz)
        if stamp.get("deliveredGlbSha256") != fz["lookDeliveredGlbSha256"] or stamp.get("vfxManifestSha256") != fz["vfxManifestSha256"] \
                or stamp.get("specSha256") != fz["specSha256"] or stamp.get("basecolorSha256") != fz["basecolorSha256"]:
            raise ShipError(f"{sid}: frozen stamp disagrees with the selection")
        spec = load(inp / f"{sid}.json")
        if canonical_sha(spec) != fz["specSha256"]:
            raise ShipError(f"{sid}: frozen spec canonical sha differs from the stamp")
        report = load(d / "idle_retime_report.json")
        if report.get("srcSha256") != fz["lookDeliveredGlbSha256"] or report.get("dstSha256") != fz["idleRetimedGlbSha256"]:
            raise ShipError(f"{sid}: idle retime report does not chain look-delivered -> retimed")
        factor = float(report["treatment"]["factor"])
        manifest = load(inp / "vfx/vfx_manifest.json")
        verify_frozen_look_kind(sid, spec["unit"], stamp, inp / "look_delivered.glb", fz["basecolorSha256"], manifest)
        for name, want in manifest.get("assets", {}).items():
            p = inp / "vfx" / name
            if not p.is_file() or sha(p) != want:
                raise ShipError(f"{sid}: vfx asset {name} missing or changed")
        if pins_only:
            continue
        glb = glb_facts(d / "delivered_idle_retimed.glb")
        extent = glb["morphExtent"]
        if extent["ratio"] is None or extent["ratio"] > MORPH_DELTA_MAX_HEIGHT_RATIO:
            raise ShipError(f"{sid}: corrective morph '{extent['worstTarget']}' moves a vertex {extent['worstDelta']} "
                            f"on a {extent['restHeight']}-tall body (ratio {extent['ratio']} > {MORPH_DELTA_MAX_HEIGHT_RATIO}); "
                            "the bake_cs solve blew up and the runtime would fit the unit to a speck")
        facts[sid] = {"spec": spec, "manifest": manifest, "idleFactor": factor, "stamp": stamp,
                      "glb": glb,
                      "lookGlb": glb_facts(inp / "look_delivered.glb")}
    return facts


def verify_source_mesh(selection: dict, out: Path, facts: dict) -> None:
    """Every frozen GLB must still be built from the unit's reviewed source mesh (source_mesh_identity.attest, the
    rule freeze_slice applied); a row that recorded sourceMeshSha256 / identityReview must still agree."""
    from source_mesh_identity import IdentityError, attest, load_legacy, load_reviews
    reviews, legacy = load_reviews(), load_legacy()
    for row in selection["units"]:
        sid = row["labSid"]
        try:
            got = attest(facts[sid]["spec"]["unit"], unit_dir(out, sid) / "inputs/look_delivered.glb", reviews, legacy)
        except IdentityError as exc:
            raise ShipError(f"{sid}: source mesh identity: {exc}; re-freeze after the rebuild") from exc
        for k, v in got.items():
            if k in row and row[k] != v:
                raise ShipError(f"{sid}: frozen {k} {str(row[k])[:12]} is no longer {str(v)[:12]}; re-freeze")


# ---------------------------------------------------------------- plan
def make_time_map(sid: str, fact: dict):
    look_idle = fact["lookGlb"]["clips"][IDLE]
    t0 = look_idle["first"]
    factor = fact["idleFactor"]
    got = fact["glb"]["clips"][IDLE]
    want_last = t0 + (look_idle["last"] - t0) * factor
    if abs(got["first"] - t0) > 1e-4 or abs(got["last"] - want_last) > 1e-3:
        raise ShipError(f"{sid}: retimed idle spans {got}, expected first {t0} last {want_last}")

    def tmap(clip: str, t: float) -> float:
        # key 0's window opens half a frame before key 0, which maps below 0 on the idle: clamp
        return max(0.0, t0 + (t - t0) * factor) if clip == IDLE else t
    return tmap, {"clip": IDLE, "t0": t0, "factor": factor}


def cell_st(tiles_x: int, tiles_y: int, cell: int) -> list[float]:
    r, c = divmod(cell, tiles_x)
    return [1.0 / tiles_x, 1.0 / tiles_y, c / tiles_x, 1.0 - (r + 1) / tiles_y]


def step_keys(keys: list[dict], length: float) -> list[dict]:
    """Stepped keys as the lab builder bakes them: a later key at the same time wins (key 0's window
    clamps onto the leading t=0 key on the retimed idle), and keys at or past the clip end are dropped
    (the last DEF window closes half a frame after it; a key there would stretch the clip)."""
    by_t: dict[float, dict] = {}
    for k in keys:
        by_t[k["t"]] = k
    return [by_t[t] for t in sorted(by_t) if t < length - 1e-6]


def vanilla_style_superseded(row: dict, manifest: dict) -> dict:
    """{layer id: reason} the row's vanilla-style spec supersedes; {} for a unit_look row."""
    authority = row.get("vfxAuthority", "unit_look")
    if authority == "unit_look":
        if row.get("vanillaStyleSpec"):
            raise ShipError(f"{row['labSid']}: vanillaStyleSpec without vfxAuthority vanilla_style")
        return {}
    if authority != "vanilla_style":
        raise ShipError(f"{row['labSid']}: unknown vfxAuthority {authority!r}")
    if row.get("albedo") != "basecolor" or row.get("deferLayers"):
        raise ShipError(f"{row['labSid']}: a vanilla-style row ships the basecolor albedo and defers nothing")
    spec_path = ROOT / (row.get("vanillaStyleSpec") or "")
    if not spec_path.is_file():
        raise ShipError(f"{row['labSid']}: vanillaStyleSpec {row.get('vanillaStyleSpec')!r} missing")
    spec = load(spec_path)
    if spec.get("unit") != row["labSid"]:
        raise ShipError(f"{row['labSid']}: vanillaStyleSpec is for {spec.get('unit')}")
    sup = spec["supersedes"]["lookLayers"]
    need = sorted(l for l, v in manifest["layers"].items() if v["type"] in SUPERSEDED_TYPES)
    if sorted(sup) != need:
        raise ShipError(f"{row['labSid']}: vanilla-style spec supersedes {sorted(sup)}, the look manifest has {need}")
    return dict(sup)


def build_plan(sid: str, fact: dict, out: Path, deferred: dict | None = None, deferred_meshes: dict | None = None,
               superseded: dict | None = None, merged_meshes: dict | None = None) -> dict:
    deferred = deferred or {}
    deferred_meshes = deferred_meshes or {}
    merged_meshes = merged_meshes or {}
    superseded = superseded or {}
    both = sorted(set(deferred_meshes) & set(merged_meshes))
    if both:
        raise ShipError(f"{sid}: {both} both deferred and merged")
    if any(not isinstance(r, str) or not r.strip() for r in merged_meshes.values()):
        raise ShipError(f"{sid}: mergeMeshes must map each node to a non-empty reason")
    odd = sorted(n for n in merged_meshes if not n.endswith(merge_rubble_glb.RUBBLE_SUFFIX))
    if odd:
        raise ShipError(f"{sid}: mergeMeshes only takes a death shatter's *{merge_rubble_glb.RUBBLE_SUFFIX} mesh, not {odd}")
    manifest, spec = fact["manifest"], fact["spec"]
    if manifest.get("fps") != FPS:
        raise ShipError(f"{sid}: manifest fps {manifest.get('fps')} != 12")
    tmap, idle_map = make_time_map(sid, fact)
    clips = fact["glb"]["clips"]
    unit_clips = sorted(c for c in clips if c.startswith("Unit_"))
    joints = set(fact["glb"]["joints"])
    spec_layers = {l["id"]: l for l in spec["vfx"]["layers"]}
    vfx_dir = unit_dir(out, sid) / "inputs/vfx"
    plan = {"schema": "homm3_def_retarget_vfx_plan.v1", "unit": sid, "idleTimeMap": idle_map,
            "clipLengths": {c: clips[c]["last"] for c in unit_clips},
            "clipLengthList": [{"clip": c, "length": clips[c]["last"]} for c in unit_clips], "uvAtlas": None, "quads": [], "lights": [],
            "unsupported": [], "deferred": [],
            # layers the unit's vanilla-style spec replaces (vfxAuthority vanilla_style): never baked
            "superseded": [{"layer": l, "reason": r} for l, r in sorted(superseded.items())],
            # skinned meshes besides the body that the lab builder leaves out (selection "deferMeshes")
            "deferredMeshes": [{"node": n, "reason": r} for n, r in sorted(deferred_meshes.items())],
            # skinned meshes appended to the body primitive at prepare (selection "mergeMeshes"); prepare adds the
            # vertex ranges and the merged master's pins (merge_master)
            "mergedMeshes": [{"node": n, "reason": r} for n, r in sorted(merged_meshes.items())]}
    for lid, layer in manifest["layers"].items():
        typ = layer["type"]
        if lid in superseded:
            continue
        if typ == "uvAtlas":
            if plan["uvAtlas"] is not None:
                raise ShipError(f"{sid}: more than one uvAtlas layer")
            cells = layer["cellST"]
            steps = []
            for clip, keys in layer["clips"].items():
                if clip not in clips:
                    raise ShipError(f"{sid}: uvAtlas clip {clip} not in the GLB")
                seq = [{"t": 0.0, "cell": keys[0]["cell"]}]
                seq += [{"t": round(tmap(clip, k["window"][0]), 6), "cell": k["cell"]} for k in keys]
                seq = step_keys(seq, clips[clip]["last"])
                steps.append({"clip": clip, "keys": seq})
            plan["uvAtlas"] = {"id": lid, "atlas": str((vfx_dir / layer["atlas"]).resolve()),
                               "atlasSha256": sha(vfx_dir / layer["atlas"]), "cells": [{"st": c} for c in cells],
                               "clips": steps, "restCell": 0}
        elif typ == "defFlipbook":
            for clip, e in layer["clips"].items():
                if not e.get("sheet"):
                    continue
                render = e.get("render", "billboard")
                if render not in QUAD_PREFIX:
                    plan["unsupported"].append(f"{lid}/{clip}: render {render}")
                    continue
                if e.get("anchorPoint") != "head":
                    raise ShipError(f"{sid}: {lid}/{clip}: anchorPoint {e.get('anchorPoint')} not supported")
                if e["anchorBone"] not in joints:
                    raise ShipError(f"{sid}: {lid}/{clip}: anchor bone {e['anchorBone']} is not a joint")
                if clip not in clips:
                    raise ShipError(f"{sid}: {lid}: clip {clip} not in the GLB")
                tx, ty = int(e["tilesX"]), int(e["tilesY"])
                keys = [{"t": 0.0, "cell": -1}]
                for k in e["keys"]:
                    if k["cell"] >= tx * ty:
                        raise ShipError(f"{sid}: {lid}/{clip}: cell {k['cell']} outside {tx}x{ty}")
                    keys.append({"t": round(tmap(clip, k["window"][0]), 6), "cell": int(k["cell"])})
                keys.append({"t": round(tmap(clip, e["keys"][-1]["window"][1]), 6), "cell": -1})
                # the last DEF window closes half a frame past the clip end; a key there would stretch
                # the Unity clip by 1/24 s, so the last cell holds to the end instead
                keys = step_keys(keys, clips[clip]["last"])
                used = sorted({k["cell"] for k in keys if k["cell"] >= 0})
                sheet = vfx_dir / e["sheet"]
                plan["quads"].append({
                    "name": f"{QUAD_PREFIX[render]}{lid}__{clip}", "layer": lid, "clip": clip, "render": render,
                    "anchorBone": e["anchorBone"], "sheet": str(sheet.resolve()), "sheetSha256": sha(sheet),
                    "tilesX": tx, "tilesY": ty, "sizeUnits": [float(e["sizeUnits"][0]), float(e["sizeUnits"][1])],
                    "cells": [{"index": c, "uvRect": cell_st(tx, ty, c)} for c in used], "keys": keys})
        elif typ == "effectLight":
            sl = spec_layers.get(lid)
            if not sl:
                raise ShipError(f"{sid}: effectLight {lid} missing from the frozen spec")
            bone = sl["anchor"]["bone"]
            if bone not in joints:
                raise ShipError(f"{sid}: light {lid} anchor {bone} is not a joint")
            floor = layer.get("floor", 0.0)
            if not isinstance(floor, (int, float)) or floor < 0:
                # a per-clip floor ({clip: number}) is valid in the look spec but this builder holds one
                # scalar in every clip; refuse rather than deliver a floor the spec did not author
                raise ShipError(f"{sid}: light {lid} floor {floor!r} is not a scalar >= 0")
            floor = float(floor)
            clip_rows = []
            for clip, keys in layer["clips"].items():
                if clip not in clips:
                    raise ShipError(f"{sid}: light {lid} clip {clip} not in the GLB")
                if floor > 0 and all(k.get("source") == "floor" and float(k["intensity"]) == floor for k in keys):
                    # a floor-only clip (the look's vfx stage writes positions only where it baked a view):
                    # no curve; the builder's curve-less path holds the floor for the whole clip
                    continue
                known = [i for i, k in enumerate(keys) if k.get("positionWorld") is not None]
                if not known:
                    raise ShipError(f"{sid}: light {lid} clip {clip} has no key with a position")
                rows = []
                for i, k in enumerate(keys):
                    # an unbaked key's position is its nearest baked key's (the light rides its anchor bone)
                    x, y, z = keys[min(known, key=lambda j: (abs(j - i), j))]["positionWorld"]
                    rows.append({"t": round(tmap(clip, k["window"][0]), 6),
                                 "tPose": round(tmap(clip, (k["defFrame"] + 1) / FPS), 6),
                                 "intensity": float(k["intensity"]), "rootPosition": [-x, z, -y]})
                # outside its DEF windows a light rests at its floor (docs "Floors"), before the first
                # window as after the last one
                if floor > 0 and rows[0]["t"] > 0:
                    rows.insert(0, {"t": 0.0, "tPose": rows[0]["tPose"], "intensity": floor,
                                    "rootPosition": rows[0]["rootPosition"]})
                rows.append({"t": round(tmap(clip, keys[-1]["window"][1]), 6), "tPose": rows[-1]["tPose"],
                             "intensity": floor, "rootPosition": rows[-1]["rootPosition"]})
                rows = step_keys(rows, clips[clip]["last"])
                clip_rows.append({"clip": clip, "keys": rows})
            plan["lights"].append({"name": LIGHT_PREFIX + lid, "id": lid, "anchorBone": bone, "rgb": layer["rgb"],
                                   "range": float(layer["range"]), "floor": floor,
                                   "clips": clip_rows})
        elif lid in deferred:
            # an explicit, reasoned per-selection deferral (selection "deferLayers"); recorded in the
            # plan and the report, never silent. Every other unsupported layer still refuses.
            plan["deferred"].append({"layer": lid, "type": typ, "reason": deferred[lid]})
        else:
            plan["unsupported"].append(f"{lid}: type {typ}")
    delivered = sorted(l for l in deferred if l in manifest["layers"]
                       and manifest["layers"][l]["type"] in ("uvAtlas", "defFlipbook", "effectLight"))
    if delivered:
        raise ShipError(f"{sid}: deferLayers names layers this slice delivers: {delivered}")
    missing = sorted(set(deferred) - set(manifest["layers"]))
    if missing:
        raise ShipError(f"{sid}: deferLayers names layers the manifest does not have: {missing}")
    if plan["unsupported"]:
        raise ShipError(f"{sid}: layers this slice cannot deliver: {plan['unsupported']}")
    held = {l["id"] for l in plan["lights"] if l["floor"] > 0}
    # a superseded floor light is replaced by the vanilla-style emission map (steady glow is emission)
    unheld = sorted(set(fact["stamp"].get("floorLights", [])) - held - set(superseded))
    if unheld:
        raise ShipError(f"{sid}: the base colour is graded under floor lights {unheld} that this plan does not hold")
    return plan


def glb_morph_peak(path: Path) -> dict:
    """Per animation, the key times and the largest morph weight at each key (LINEAR samplers)."""
    js, b, bin0 = read_glb(path)
    out = {}
    for an in js.get("animations", []):
        for ch in an["channels"]:
            if ch["target"]["path"] != "weights":
                continue
            s = an["samplers"][ch["sampler"]]
            if s.get("interpolation", "LINEAR") != "LINEAR":
                raise ShipError(f"{path.name}: {an['name']} morph weights are not LINEAR")
            times = accessor_floats(js, b, bin0, s["input"])
            w = accessor_floats(js, b, bin0, s["output"])
            n = len(w) // len(times)
            out[an["name"]] = (times, [w[k * n:(k + 1) * n] for k in range(len(times))])
    return out


DENSIFY_STAMP = "homm3DefRetargetDeliveryDensify"   # densify_clip_glb.STAMP


def glb_densify_record(path: Path, unit: str) -> dict:
    """The densify step's record in a delivered GLB: {clip: keysPerSpan} for every densified clip, {} for none.

    densify_clip_glb.py resamples a clip onto keysPerSpan intervals per original key interval and keeps every
    original key, so a densified track's DEF step keys are its keys 0, per, 2*per, ... and the in-between keys
    hold spline-blended morph weights that are not steps. Fails closed when the unit config asks for
    deliveryDensify and the GLB carries no record, or the record names clips the config does not."""
    js, _b, _bin0 = read_glb(path)
    st = js.get("asset", {}).get("extras", {}).get(DENSIFY_STAMP)
    cfg = load(ROOT / "tools/homm3_def_retarget/units" / f"{unit}.json").get("deliveryDensify")
    want = sorted(f"Unit_{c}" for c in cfg["clips"]) if cfg else []
    got = sorted(st["clips"]) if st else []
    if want != got:
        raise ShipError(f"{unit}: deliveryDensify clips in the unit config {want} != the delivered GLB's densify record {got}")
    if not st:
        return {}
    per = int(st["keysPerSpan"])
    if per < 2:
        raise ShipError(f"{unit}: densify record keysPerSpan {per} < 2")
    return {c: {"keysPerSpan": per, "keysBefore": list(r["keysBefore"]), "keysAfter": list(r["keysAfter"])}
            for c, r in st["clips"].items()}


def peak_at(track, t: float) -> float:
    times, rows = track
    if t <= times[0]:
        return max(rows[0])
    for k in range(1, len(times)):
        if t <= times[k] + 1e-9:
            f = (t - times[k - 1]) / (times[k] - times[k - 1])
            return max(a + (c - a) * f for a, c in zip(rows[k - 1], rows[k]))
    return max(rows[-1])


def probe_frame_times(plan: dict, peaks: dict, densify: dict) -> dict:
    """Per clip, the times the probe reads a step key, taken from the delivered GLB's own weight track.

    The idle clip keeps its (i+1)/FPS grid mapped through idleTimeMap: retime_idle.py inserts in-between
    keys there, so not every idle key is a step. Every other clip samples each of its own weight-track keys
    up to the clip length: stride_match_glb.py speeds Unit_Move up by its cadence (up to 1.6), which moves
    those keys off the 1/FPS grid, and the GLB is the one record of where they landed. Either way every
    sample must sit on a key of the track or after its last key (the weights hold there); a time between
    two keys refuses. A clip the densify step resampled (densify: glb_densify_record) probes only its DEF step
    keys, every keysPerSpan-th key of the track; a track whose key count is not what the record says refuses."""
    unit = plan["unit"]
    missing = sorted(set(densify) - set(plan["clipLengths"]))
    if missing:
        raise ShipError(f"{unit}: densify record names clips the plan does not have: {missing}")
    im = plan["idleTimeMap"]
    out = {}
    for clip, length in plan["clipLengths"].items():
        if clip not in peaks:
            raise ShipError(f"{unit}: delivered GLB has no morph-weight track for {clip}")
        keys = peaks[clip][0]
        if clip == im["clip"]:
            src_len = (length - im["t0"]) / im["factor"] + im["t0"]
            times, i = [], 0
            while (i + 1) / FPS <= src_len + 1e-4:
                times.append(im["t0"] + ((i + 1) / FPS - im["t0"]) * im["factor"])
                i += 1
        elif clip in densify:
            d = densify[clip]
            per, n = d["keysPerSpan"], len(keys)
            if clip == im["clip"]:
                raise ShipError(f"{unit}: {clip} is both idle-retimed and densified")
            if (n - 1) % per or (n - 1) // per + 1 not in d["keysBefore"] or n not in d["keysAfter"]:
                raise ShipError(f"{unit}: {clip} weight track has {n} keys, not a densified track of the record "
                                f"(keysPerSpan {per}, keysBefore {d['keysBefore']}, keysAfter {d['keysAfter']})")
            times = [t for t in keys[::per] if t <= length + 1e-4]
        else:
            times = [t for t in keys if t <= length + 1e-4]
        if not times:
            raise ShipError(f"{unit}: {clip} has no step key to probe")
        for t in times:
            if t < keys[-1] - 1e-4 and min(abs(t - k) for k in keys) > 1e-4:
                raise ShipError(f"{unit}: {clip}@{t:.4f} is not a key of the delivered GLB weight track")
        out[clip] = times
    return out


def probe_checks(plan: dict, peaks: dict, densify: dict) -> list[dict]:
    """Sample points for the editor bundle probe: each reads a step key of the delivered GLB (probe_frame_times).

    bake_cs.py adds no corrective shape for a frame whose correction is under 1e-4 (a frame at the
    rest pose), so the delivered GLB keys every shape to 0 there. Each frame check therefore expects
    what the GLB itself holds at that key: one shape at the frame weight (blendOneHot) or none
    (blendNone). A GLB weight that is neither refuses the probe instead of guessing. The Unity probe
    samples the same list of times (ProbeDefRetargetDeliveryBundles.cs reads c.t)."""
    eps = 0.02                                   # well inside a >= 1/12 s window
    unit = plan["unit"]
    lengths = plan["clipLengths"]
    checks = []
    for clip, times in probe_frame_times(plan, peaks, densify).items():
        for t in times:
            peak = peak_at(peaks[clip], t)
            if peak <= 0.01:
                kind = "blendNone"
            elif peak >= 0.99:
                kind = "blendOneHot"
            else:
                raise ShipError(f"{unit}: {clip}@{t:.3f}: delivered GLB morph peak {peak:.3f} is neither one shape nor none")
            checks.append({"clip": clip, "t": round(t, 6), "kind": kind, "path": "", "values": []})
    atlas = plan.get("uvAtlas")
    if atlas:
        by_clip = {c["clip"]: c["keys"] for c in atlas["clips"]}
        for clip in lengths:
            keys = by_clip.get(clip, [{"t": 0.0, "cell": atlas["restCell"]}])
            for k in keys:
                checks.append({"clip": clip, "t": round(k["t"] + eps, 6), "kind": "st", "path": "",
                               "values": atlas["cells"][k["cell"]]["st"]})
    for q in plan["quads"]:
        for k in q["keys"]:
            if k["t"] + eps < lengths[q["clip"]]:
                checks.append({"clip": q["clip"], "t": round(k["t"] + eps, 6), "kind": "enabled", "path": q["name"], "values": [k["cell"]]})
        other = next(c for c in sorted(lengths) if c != q["clip"])
        checks.append({"clip": other, "t": 0.1, "kind": "enabled", "path": q["name"], "values": [-1]})
    for light in plan["lights"]:
        lit = {c["clip"] for c in light["clips"]}
        for c in light["clips"]:
            for k in c["keys"]:
                if k["t"] + eps < lengths[c["clip"]]:
                    checks.append({"clip": c["clip"], "t": round(k["t"] + eps, 6), "kind": "light", "path": light["name"], "values": [k["intensity"]]})
        for other in sorted(c for c in lengths if c not in lit):
            checks.append({"clip": other, "t": 0.1, "kind": "light", "path": light["name"], "values": [light["floor"]]})
    return checks


MERGED_GLB = "merged_master.glb"


def merge_master(plan: dict, master: Path, dst: Path) -> Path:
    """mergeMeshes: append the plan's merged nodes to the body primitive of ``master`` (merge_rubble_glb); the plan
    records the merged master's pins and each node's vertex range. Returns the GLB the lab builds from."""
    try:
        rec = merge_rubble_glb.merge(master, dst, [m["node"] for m in plan["mergedMeshes"]])
    except merge_rubble_glb.MergeError as exc:
        raise ShipError(f"{plan['unit']}: mergeMeshes: {exc}") from exc
    if rec["sourceGlbSha256"] != sha(master):
        raise ShipError(f"{plan['unit']}: merged master was not built from {master.name}")
    reasons = {m["node"]: m["reason"] for m in plan["mergedMeshes"]}
    plan["mergedMeshes"] = [{"node": m["node"], "reason": reasons[m["node"]], "firstVertex": m["firstVertex"],
                             "vertices": m["vertices"], "sourceMesh": m["sourceMesh"]} for m in rec["merged"]]
    plan["mergedMaster"] = {"glb": rec["glb"], "sha256": rec["sha256"], "sourceGlbSha256": rec["sourceGlbSha256"],
                            "bodyVertices": rec["bodyVertices"], "bodySourceMesh": rec["bodySourceMesh"],
                            "totalVertices": rec["totalVertices"]}
    return dst


def verify_merged_master(plan: dict, source_sha: str) -> dict | None:
    """Later stages: the plan's merged master must still be the stamped merge of ``source_sha``. None when the plan
    merges nothing."""
    mm = plan.get("mergedMaster")
    if not plan.get("mergedMeshes"):
        if mm:
            raise ShipError(f"{plan['unit']}: plan has a merged master but no merged meshes; rerun prepare")
        return None
    if not mm or "firstVertex" not in plan["mergedMeshes"][0]:
        raise ShipError(f"{plan['unit']}: plan merges {[m['node'] for m in plan['mergedMeshes']]} but prepare did not "
                        "record the merge; rerun prepare")
    p = Path(mm["glb"])
    try:
        st = merge_rubble_glb.verify(p)
    except (merge_rubble_glb.MergeError, OSError) as exc:
        raise ShipError(f"{plan['unit']}: merged master: {exc}; rerun prepare") from exc
    if sha(p) != mm["sha256"] or st["sourceGlbSha256"] != source_sha or mm["sourceGlbSha256"] != source_sha:
        raise ShipError(f"{plan['unit']}: merged master is not the plan's merge of the lab source GLB; rerun prepare")
    return mm


RUBBLE_ROOT = "RubbleRoot"            # build_unit.py shatter: parent of every Chunk_NN bone
RUBBLE_COLLAPSED_MAX = 0.01           # rubble range bbox diagonal / body rest height while held at 1e-4 scale
RUBBLE_SPREAD_MIN = 0.1               # ... once the chunks have burst (they settle into a heap about the body's size)


def rubble_probe_checks(plan: dict, glb: Path) -> list[dict]:
    """Bundle probe checks for each merged rubble range (ProbeDefRetargetDeliveryBundles "meshRange"): the baked skin
    extent of the range over the body's rest height must be collapsed at the last Unit_Death key before RubbleRoot
    grows and in Unit_Idle, and spread at the last Unit_Death key. Times are keys of the delivered GLB's own
    RubbleRoot scale track (merge_rubble_glb keeps every animation byte-identical)."""
    if not plan.get("mergedMeshes"):
        return []
    js, b, bin0 = read_glb(glb)
    names = [n.get("name") for n in js["nodes"]]
    if names.count(RUBBLE_ROOT) != 1:
        raise ShipError(f"{plan['unit']}: merged rubble but the GLB has no single {RUBBLE_ROOT} node")
    rr = names.index(RUBBLE_ROOT)

    def scale_keys(clip):
        an = next((a for a in js.get("animations", []) if a.get("name") == clip), None)
        ch = next((c for c in (an or {}).get("channels", [])
                   if c["target"].get("node") == rr and c["target"]["path"] == "scale"), None)
        if ch is None:
            raise ShipError(f"{plan['unit']}: {clip} does not key {RUBBLE_ROOT} scale; the rubble would keep whatever "
                            "pose the last clip left")
        s = an["samplers"][ch["sampler"]]
        t, v = accessor_floats(js, b, bin0, s["input"]), accessor_floats(js, b, bin0, s["output"])
        return [(t[i], max(v[3 * i:3 * i + 3])) for i in range(len(t))]

    death = scale_keys("Unit_Death")
    live = [i for i, (_, k) in enumerate(death) if k > 0.5]
    if not live or live[0] == 0 or death[live[0] - 1][1] > 1e-3 or death[-1][1] < 0.5:
        raise ShipError(f"{plan['unit']}: Unit_Death {RUBBLE_ROOT} scale is not held collapsed, then grown and kept: {death}")
    idle = scale_keys(IDLE)
    if max(k for _, k in idle) > 1e-3:
        raise ShipError(f"{plan['unit']}: Unit_Idle shows the rubble ({RUBBLE_ROOT} scale {idle})")
    checks = []
    for m in plan["mergedMeshes"]:
        rng = [m["firstVertex"], m["vertices"]]
        checks += [{"clip": "Unit_Death", "t": round(death[live[0] - 1][0], 6), "kind": "meshRange", "path": m["node"],
                    "values": rng + [0.0, RUBBLE_COLLAPSED_MAX]},
                   {"clip": "Unit_Death", "t": round(death[-1][0], 6), "kind": "meshRange", "path": m["node"],
                    "values": rng + [RUBBLE_SPREAD_MIN, 1e6]},
                   {"clip": IDLE, "t": round(idle[0][0], 6), "kind": "meshRange", "path": m["node"],
                    "values": rng + [0.0, RUBBLE_COLLAPSED_MAX]}]
    return checks


def write_png(path: Path, rgba: tuple, size: int = 4) -> None:
    from PIL import Image
    Image.new("RGBA", (size, size), rgba).save(path)


def prepare(selection: dict, out: Path, facts: dict) -> None:
    units = []
    for row in selection["units"]:
        sid = row["labSid"]
        fact = facts[sid]
        d = unit_dir(out, sid)
        unity_dir = d / "unity"
        unity_dir.mkdir(parents=True, exist_ok=True)
        plan = build_plan(sid, fact, out, row.get("deferLayers"), row.get("deferMeshes"),
                          vanilla_style_superseded(row, fact["manifest"]), row.get("mergeMeshes"))
        if row.get("vfxAuthority") == "vanilla_style" and (plan["uvAtlas"] or plan["quads"] or plan["lights"]):
            raise ShipError(f"{sid}: a vanilla-style plan must carry no uvAtlas, quads or lights")
        if row["albedo"] == "uvAtlas":
            if not plan["uvAtlas"]:
                raise ShipError(f"{sid}: albedo uvAtlas but no uvAtlas layer")
            albedo = Path(plan["uvAtlas"]["atlas"])
        elif row["albedo"] == "basecolor":
            if plan["uvAtlas"]:
                raise ShipError(f"{sid}: a uvAtlas unit must ship the atlas as its albedo")
            albedo = d / "inputs/basecolor.png"
        else:
            raise ShipError(f"{sid}: unknown albedo mode {row['albedo']}")
        dm = displacement_mask_glb(row, out, bake=True)
        if dm:
            plan["displacementMaskGlb"] = dm
        master = Path(dm["glb"]) if dm else d / "delivered_idle_retimed.glb"
        if plan["mergedMeshes"]:
            master = merge_master(plan, master, unity_dir / MERGED_GLB)
        normal = unity_dir / "neutral_normal.png"
        metallic = unity_dir / "neutral_metallicgloss.png"
        write_png(normal, NEUTRAL_NORMAL)
        write_png(metallic, NEUTRAL_METALLIC_GLOSS)
        dump(unity_dir / "vfx_plan.json", plan)
        clips = []
        for clip in sorted(plan["clipLengths"]):
            if clip not in ROLES:
                raise ShipError(f"{sid}: clip {clip} has no lifecycle role")
            clips.append({"contractName": clip, "sourcePath": "", "sourceAnimation": clip,
                          "lifecycleRole": ROLES[clip], "fps": FPS})
        units.append({"labSid": sid, "clipPrefix": "Unit", "masterGlb": str(master.resolve()),
                      "albedo": str(albedo.resolve()), "normal": str(normal.resolve()), "metallicGloss": str(metallic.resolve()),
                      "motionAuthority": "def_retarget", "vfxPlan": str((unity_dir / "vfx_plan.json").resolve()),
                      "placeholderIdleOnly": False, "clips": clips})
    dump(out / "unity_lab_batch.json", {"units": units})


# ---------------------------------------------------------------- stage plumbing
def require_game_stopped() -> None:
    result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq HeroesOldenEra.exe", "/FO", "CSV", "/NH"],
                            capture_output=True, text=True, check=False, timeout=15)
    if result.returncode != 0:
        raise ShipError(f"unable to prove HeroesOldenEra.exe is stopped: tasklist exit {result.returncode}")
    for r in csv.reader(result.stdout.splitlines()):
        if r and r[0].strip().lower() == "heroesoldenera.exe":
            raise ShipError("refusing deployment while HeroesOldenEra.exe is running")


def run(command: list, log: Path, timeout: int = 5400) -> dict:
    started = time.perf_counter()
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as stream:
        rc = subprocess.run([str(c) for c in command], stdout=stream, stderr=subprocess.STDOUT, check=False, timeout=timeout).returncode
    if rc != 0:
        raise ShipError(f"command failed rc={rc}; see {log}")
    return {"command": [str(c) for c in command], "log": str(log), "elapsedSeconds": round(time.perf_counter() - started, 1)}


# --unity-direct (main) is the explicit, loudly logged opt-out of the Unity queue.
UNITY_DIRECT = False


def unity(method: str, extra: list, log: Path, output_dir: Path | None = None) -> dict:
    """One Unity batch job through the Unity queue (tools/unity_queue, docs/unity_queue_runner.md): batched with other
    queued jobs on this project, preflighted (game, V: space, memgate, launch guard) by the runner. Raises on failure."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("unity_queue", ROOT / "tools/unity_queue/unity_queue.py")
    uq = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("unity_queue", uq)   # its @dataclass resolves annotations through sys.modules
    spec.loader.exec_module(uq)
    started = time.perf_counter()
    extra = [str(c) for c in extra]
    res = uq.launch(kind="def_retarget_ship", method=method, args=extra, project=PROJECT, log=log,
                    inputs=[x for x in extra if Path(x).is_file()], output_dir=output_dir, unity=UNITY,
                    requester=f"ship_def_retarget_slice {method}", direct=UNITY_DIRECT)
    if res["status"] != "ok":
        raise ShipError(f"Unity job {res.get('id', 'direct')} {method} failed: {res.get('error') or res.get('exitCode')}; "
                        f"see {log}")
    return {"command": [method, *extra], "log": str(log), "elapsedSeconds": round(time.perf_counter() - started, 1),
            **({"unityQueueJob": res["id"], "unityQueueLaunch": res.get("launchId")} if "id" in res else {"unityDirect": True})}


def fingerprint(out: Path, selection_path: Path, selection: dict) -> dict:
    files = [selection_path, *EDITOR_SCRIPTS, out / "unity_lab_batch.json"]
    for row in selection["units"]:
        d = unit_dir(out, row["labSid"])
        files += [d / "delivered_idle_retimed.glb", d / "unity/vfx_plan.json"]
        if displacement_layer(row) is not None:
            files += [d / COLOR0_GLB, d / (COLOR0_GLB + ".stamp.json")]
        if row.get("mergeMeshes"):
            files.append(d / "unity" / MERGED_GLB)
    missing = [str(p) for p in files if not p.is_file()]
    if missing:
        raise ShipError(f"{len(missing)} stage input(s) missing (first: {missing[0]}); the slice was frozen but not "
                        "prepared - run prepare, lab, bundles, probe")
    return {"inputHashes": {str(p.resolve()): sha(p) for p in files}}


def freeze_mismatch(record: dict, selection_path: Path, selection: dict) -> list[str]:
    """Why a stage record (prepare/lab/bundle/probe .json) was not made from the current freeze: the selection file
    and every unit's frozen idle-retimed GLB must hash as the record's inputHashes say. Keys are matched by path
    suffix so a drive-letter case change is not a mismatch. Empty list = current."""
    hashes = {k.replace("\\", "/").lower(): v for k, v in record.get("inputHashes", {}).items()}
    why = []
    sel_key = str(selection_path.resolve()).replace("\\", "/").lower()
    if hashes.get(sel_key) != sha(selection_path):
        why.append(f"selection {selection_path.name} changed (re-frozen)")
    out_name = Path(selection["out"]).name.lower()
    for row in selection["units"]:
        suffix = f"/{out_name}/{row['labSid'].lower()}/delivered_idle_retimed.glb"
        got = next((v for k, v in hashes.items() if k.endswith(suffix)), None)
        if got != row["frozen"]["idleRetimedGlbSha256"]:
            why.append(f"{row['labSid']}: {'not in the record' if got is None else 'frozen GLB differs'}")
    return why


def require_current(record_path: Path, selection_path: Path, selection: dict) -> dict:
    if not record_path.is_file():
        raise ShipError(f"{record_path.name} missing; run the stages in order: prepare, lab, bundles, probe")
    record = load(record_path)
    why = freeze_mismatch(record, selection_path, selection)
    if why:
        raise ShipError(f"{record_path.name} predates the current freeze of {selection_path.name} "
                        f"({len(why)} difference(s), first: {why[0]}); rerun prepare, lab, bundles, probe")
    return record


INSTALLED_CORE = GOLDEN / "HeroesOldenEra_Data/StreamingAssets/Core.zip"
ATTACK_CLIP_GATE = "validate_homm3_owned_skinned_attack_clip_contract.py"


def payload_gate(directory: Path, rows: list, out: Path, views_core: Path = INSTALLED_CORE) -> None:
    """views_core: the Core.zip whose units_views the bundles will play against. The attack-clip gate
    checks every attack slot the view names against the bundle's AOC; deploy always uses the installed Core."""
    prefixes = [v for r in rows for v in ("--name-prefix", r["bundleName"])]
    for tool in ("validate_homm3_unit_bundle_audio_contract.py", "validate_homm3_bundle_payload_directory.py",
                 "validate_homm3_owned_skinned_facing_contract.py"):
        run([sys.executable, ROOT / "tools" / tool, "--bundle-dir", directory, *prefixes],
            out / "logs" / f"{directory.name}_{Path(tool).stem}.log", 300)
    run([sys.executable, ROOT / "tools" / ATTACK_CLIP_GATE, "--bundle-dir", directory, *prefixes,
         "--core", views_core], out / "logs" / f"{directory.name}_{Path(ATTACK_CLIP_GATE).stem}.log", 300)


def require_scope(rows: list) -> None:
    inventory = {r["unitSid"]: r for r in load(INVENTORY)["units"]}
    entries = load(IMPORT)["entries"]
    for row in rows:
        prefab = f"Assets/CustomUnits/homm3_lab/{row['labSid']}/OwnedSkinned/owned_skinned.prefab"
        item = inventory.get(row["labSid"])
        if not item or item.get("bundleName") != row["bundleName"] or item.get("battlePrefabAsset") != prefab:
            raise ShipError(f"{row['labSid']}: inventory row is not on the owned skinned lane / bundle")
        if not any(e.get("battlePrefabAssetPath") == prefab and e.get("bundleName") == row["bundleName"]
                   and row["gameSid"] in e.get("gameUnitSids", []) for e in entries):
            raise ShipError(f"{row['labSid']}: source import table has no binding for {row['gameSid']}")


def validate_runtime_capability(runtime: dict, rows: list) -> int:
    """The record pins the UnitBundle payload version (docs/plugin_payload_abi.md), which must equal the version the
    current plugin source compiles, and the import-table bindings of its own units. Returns the version. The installed
    plugin and table are checked separately at deploy."""
    try:
        version = payload_abi.require_record_current(runtime, PAYLOAD_SURFACE, "runtime capability record")
    except payload_abi.AbiError as e:
        raise ShipError(str(e)) from e
    # The plugin reads homm3_import.json beside the DLL (battleWorldHeightPerHex, bindings). The record pins only its
    # own units' bindings (import_bindings.py), so another unit's binding edit does not stale it.
    if "importTableSha256" in runtime:
        raise ShipError("runtime record carries the retired whole-table importTableSha256 pin; pin importBindings")
    try:
        import_bindings.check(runtime.get(import_bindings.KEY), load(IMPORT), rows, "source homm3_import.json")
    except ValueError as e:
        raise ShipError(str(e)) from e
    return version


RUNTIME_RECORD = "runtime_capability_build.json"
INSTALLED_PLUGIN_DIR = GOLDEN / "BepInEx/plugins/OfflineUnlockMod"


def _short(h: str | None) -> str:
    return h[:12] if h else "missing"


def head_blob_sha(path: Path) -> str | None:
    """sha256 of the blob committed at HEAD for a repo path (None when HEAD has no such blob)."""
    r = subprocess.run(["git", "show", f"HEAD:{path.resolve().relative_to(ROOT.resolve()).as_posix()}"],
                       cwd=ROOT, capture_output=True)
    return hashlib.sha256(r.stdout).hexdigest() if r.returncode == 0 else None


def plan_repin(record: dict, rows: list, table: dict, worktree_sha, head_sha, installed_sha) -> dict:
    """The refresh of a runtime record's data pins, or ShipError (fail closed, every problem listed).

    meshFx: a pin moves only to a file that is byte-identical in the worktree, at HEAD and in the install, so the
    deploy that follows ships no plugin-data change; any divergence refuses the whole repin. importBindings: a
    selection unit with no pin gets import_bindings.unit_digest of the source table; a pin outside the selection, or
    an own unit whose binding changed since it was pinned, refuses (repin never drops or rewrites a pin).
    *_sha: callables rel -> sha256 or None. Returns {"meshFx": {rel: (old, new)}, "importBindings": {labSid: digest}}."""
    problems, fx = [], {}
    for rel, pinned in sorted((record.get("meshFx") or {}).items()):
        w, h, i = worktree_sha(rel), head_sha(rel), installed_sha(rel)
        if w is None or not (w == h == i):
            problems.append(f"meshFx {rel}: worktree {_short(w)}, HEAD {_short(h)}, installed {_short(i)} differ; "
                            "commit and install the plugin data through its owning ship first")
        elif w != pinned:
            fx[rel] = (pinned, w)
    pin = record.get(import_bindings.KEY)
    if not isinstance(pin, dict) or pin.get("schema") != import_bindings.SCHEMA or not isinstance(pin.get("units"), dict):
        problems.append(f"runtime record has no {import_bindings.KEY} {import_bindings.SCHEMA} pin to extend")
        pin = {"units": {}}
    want = {r["labSid"]: r for r in rows}
    extra = sorted(set(pin["units"]) - set(want))
    if extra:
        problems.append(f"{import_bindings.KEY} pins {extra}, which the selection does not ship")
    add = {}
    for sid, row in sorted(want.items()):
        try:
            digest = import_bindings.unit_digest(table, row)
        except ValueError as e:
            problems.append(str(e))
            continue
        if sid not in pin["units"]:
            add[sid] = digest
        elif pin["units"][sid] != digest:
            problems.append(f"{import_bindings.KEY} {sid}: its bindings changed since the record pinned them "
                            "(a real binding change needs a new runtime build record, not a repin)")
    if problems:
        raise ShipError("repin refused:\n  " + "\n  ".join(problems))
    return {"meshFx": fx, "importBindings": add}


def apply_repin(record: dict, plan: dict, slice_name: str, head: str, when: str) -> dict:
    """A copy of the record with the plan applied and its provenance notes."""
    new = json.loads(json.dumps(record))
    for rel, (_, now) in plan["meshFx"].items():
        new["meshFx"][rel] = now
    new[import_bindings.KEY]["units"].update(plan["importBindings"])
    if plan["meshFx"]:
        new["meshFxNote"] = (f"{slice_name} repin {when}: meshFx re-pinned ({len(plan['meshFx'])} of "
                             f"{len(new['meshFx'])} pins) to the worktree homm3_mesh_fx == HEAD {head} == installed; "
                             "no plugin-data change ships with this slice")
    if plan["importBindings"]:
        new["importBindingsNote"] = (f"{slice_name} repin {when}: added {sorted(plan['importBindings'])} (new to the "
                                     f"selection) via import_bindings.unit_digest of the source homm3_import.json at "
                                     f"HEAD {head}; other pins unchanged")
    new["refreshedAt"] = when
    return new


def repin_stage(selection_path: Path, selection: dict, write: bool, *, plugin_dir: Path = PLUGIN_DIR,
                installed_dir: Path = INSTALLED_PLUGIN_DIR, table_path: Path = IMPORT, head_sha=None) -> dict:
    """repin: print the planned pin diff of the selection's runtime record; write it only with write=True (the record
    is backed up beside itself first and re-checked after). Default is a dry run that writes nothing."""
    rp = (ROOT / selection["out"]).resolve() / RUNTIME_RECORD
    if not rp.is_file():
        raise ShipError(f"{rp} missing: repin refreshes an existing runtime record, it never creates one")
    record = load(rp)
    table = load(table_path)
    head_sha = head_sha or (lambda rel: head_blob_sha(plugin_dir / rel))
    plan = plan_repin(record, selection["units"], table,
                      lambda rel: sha(plugin_dir / rel) if (plugin_dir / rel).is_file() else None, head_sha,
                      lambda rel: sha(installed_dir / rel) if (installed_dir / rel).is_file() else None)
    name = selection_path.stem
    for rel, (old, now) in plan["meshFx"].items():
        print(f"repin {name}: meshFx {rel}: {_short(old)} -> {_short(now)}")
    for sid, digest in plan["importBindings"].items():
        print(f"repin {name}: {import_bindings.KEY} + {sid}: {_short(digest)}")
    if not plan["meshFx"] and not plan["importBindings"]:
        print(f"repin {name}: record current, nothing to repin")
        return plan
    if not write:
        print(f"repin {name}: dry run, {len(plan['meshFx'])} meshFx pin(s) and {len(plan['importBindings'])} "
              f"binding(s) would change; nothing written (--write to apply)")
        return plan
    head = subprocess.run(["git", "rev-parse", "--short=10", "HEAD"], cwd=ROOT, capture_output=True,
                          text=True).stdout.strip()
    when = datetime.now().isoformat(timespec="seconds")
    new = apply_repin(record, plan, name, head, when)
    try:
        import_bindings.check(new[import_bindings.KEY], table, selection["units"], "source homm3_import.json")
    except ValueError as e:
        raise ShipError(f"repin result fails its own check: {e}") from e
    shutil.copy2(rp, rp.with_name(f"runtime_capability_build.prerepin_{datetime.now():%Y%m%d_%H%M%S}.json"))
    tmp = rp.with_name(rp.name + ".tmp")
    dump(tmp, new)
    tmp.replace(rp)
    print(f"repin {name}: wrote {rp}")
    return plan


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=("prepare", "lab", "bundles", "probe", "deploy", "repin"))
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                      help="repin only (its default): print the pin diff, write nothing")
    mode.add_argument("--write", action="store_true",
                      help="repin only: write the refreshed runtime record (backed up beside itself first)")
    ap.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    ap.add_argument("--views-core", type=Path, default=INSTALLED_CORE,
                    help="Core.zip whose units_views the attack-clip gate reads (default: installed GE Core). "
                         "Use a candidate overlay Core only before deploy; deploy always gates on the installed Core.")
    ap.add_argument("--mesh-fx-source", action="append", default=[], metavar="REL=PATH",
                    help="deploy only: take the pinned meshFx file REL (e.g. homm3_mesh_fx/catalog.json) from PATH; "
                         "PATH must hash to the runtime record's pin and to the blob committed at HEAD")
    ap.add_argument("--unity-direct", action="store_true",
                    help="launch Unity directly instead of submitting to the Unity queue (explicit, logged opt-out; "
                         "docs/unity_queue_runner.md)")
    args = ap.parse_args()
    global UNITY_DIRECT
    UNITY_DIRECT = args.unity_direct
    if args.mesh_fx_source and args.stage != "deploy":
        raise ShipError("--mesh-fx-source is a deploy-stage option")
    if args.stage == "deploy" and args.views_core.resolve() != INSTALLED_CORE.resolve():
        raise ShipError("deploy gates attack clips against the installed Core.zip; --views-core is for pre-deploy stages")
    if not args.views_core.is_file():
        raise ShipError(f"--views-core not found: {args.views_core}")
    selection = load(args.selection)
    if selection.get("schema") != "homm3_def_retarget_delivery_selection.v1" or selection.get("accepted") is not False \
            or selection.get("disposition") != "user_requested_ingame_test":
        raise ShipError("not an explicit def_retarget test selection")
    if selection.get("supersededBy"):
        raise ShipError(f"selection is superseded by {selection['supersededBy']}; ship that one")
    if (args.dry_run or args.write) and args.stage != "repin":
        raise ShipError("--dry-run / --write are repin options")
    if args.stage == "repin":
        repin_stage(args.selection, selection, args.write)
        return 0
    out = (ROOT / selection["out"]).resolve()
    rows = selection["units"]
    facts = verify_freeze(selection, out)
    verify_source_mesh(selection, out, facts)
    require_scope(rows)
    if args.stage == "prepare":
        prepare(selection, out, facts)
        dump(out / "prepare.json", {**fingerprint(out, args.selection, selection), "proof": "generated plan; nothing built"})
    elif args.stage == "lab":
        require_current(out / "prepare.json", args.selection, selection)
        fp = fingerprint(out, args.selection, selection)
        prep = load(out / "prepare.json")
        if prep.get("inputHashes") != fp["inputHashes"]:
            raise ShipError("inputs changed since prepare; rerun prepare")
        for src in EDITOR_SCRIPTS:
            shutil.copy2(src, PROJECT / "Assets/Editor" / src.name)
        result = unity("Homm3OwnedSkinnedLabBuild.BuildFromCommandLine",
                       ["-skinnedLabSpec", out / "unity_lab_batch.json"], out / "logs/unity_lab.log")
        reports = {}
        for row in rows:
            rp = PROJECT / f"Assets/CustomUnits/homm3_lab/{row['labSid']}/OwnedSkinned/owned_skinned_def_retarget_report.json"
            if not rp.is_file():
                raise ShipError(f"{row['labSid']}: lab builder wrote no def_retarget report")
            shutil.copy2(rp, unit_dir(out, row["labSid"]) / "lab_report.json")
            reports[row["labSid"]] = sha(rp)
        dump(out / "lab_build.json", {**fp, **result, "labReports": reports, "proof": "Unity-imported lab artifact"})
    elif args.stage == "bundles":
        require_current(out / "lab_build.json", args.selection, selection)
        fp = fingerprint(out, args.selection, selection)
        lab = load(out / "lab_build.json")
        if lab.get("inputHashes") != fp["inputHashes"]:
            raise ShipError("delivery changed since lab build")
        require_displacement_compiled(rows, out)
        # A duplicated stock-controller GUID loads every AOC with a null base: the bundle would ship no animation.
        run([sys.executable, ROOT / "tools/validate_homm3_stock_controller_identity.py", "--project", PROJECT,
             *[v for r in rows for v in ("--unit", r["labSid"])]],
            out / "logs/stock_controller_identity.log", 300)
        unit_list = out / "bundle_unit_sids.txt"
        unit_list.write_text("\n".join(r["labSid"] for r in rows) + "\n", encoding="utf-8")
        backup = out / ("before_build_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
        backup.mkdir(exist_ok=False)
        prune_backups(out, "before_build")
        shutil.copy2(CONTRACT, backup / CONTRACT.name)
        for r in rows:
            src = BUILD_OUT / r["bundleName"]
            if src.exists():
                shutil.copy2(src, backup / src.name)
        result = unity("OldenEra.CustomUnitBuilder.BuildCustomUnitBundles.BuildFromManifest",
                       ["-manifestPath", INVENTORY, "-homm3UnitListPath", unit_list, "-outputPath", BUILD_OUT],
                       out / "logs/unity_bundles.log", output_dir=BUILD_OUT)
        contract = load(CONTRACT)
        changes = {}
        for r in rows:
            name = r["bundleName"]
            src = BUILD_OUT / name
            if not src.is_file() or src.stat().st_size <= 0 or name not in contract["bundles"]:
                raise ShipError(f"missing built bundle or contract row: {name}")
            new = {**contract["bundles"][name], "length": src.stat().st_size, "sha256": sha(src).upper()}
            changes[name] = {"before": contract["bundles"][name], "after": new}
            contract["bundles"][name] = new
        dump(CONTRACT, contract)
        payload_gate(BUILD_OUT, rows, out, args.views_core)
        dump(out / "bundle_build.json", {**fp, **result, "backup": str(backup), "contractChanges": changes,
                                         "attackClipViewsCore": str(args.views_core.resolve()),
                                         "attackClipViewsCoreSha256": sha(args.views_core),
                                         "proof": "generated bundles validated; not installed"})
    elif args.stage == "probe":
        require_current(out / "bundle_build.json", args.selection, selection)
        fp = fingerprint(out, args.selection, selection)
        built = load(out / "bundle_build.json")
        if built.get("inputHashes") != fp["inputHashes"]:
            raise ShipError("delivery changed since bundle build")
        shutil.copy2(PROBE_SCRIPT, PROJECT / "Assets/Editor" / PROBE_SCRIPT.name)
        spec = {"schema": "homm3_def_retarget_bundle_probe_spec.v1", "units": []}
        for r in rows:
            plan = load(unit_dir(out, r["labSid"]) / "unity/vfx_plan.json")
            spec["units"].append({
                "labSid": r["labSid"], "bundlePath": str(BUILD_OUT / r["bundleName"]),
                "prefabAssetPath": f"Assets/CustomUnits/homm3_lab/{r['labSid']}/OwnedSkinned/owned_skinned.prefab",
                "clipNames": sorted(plan["clipLengths"]), "idleLength": plan["clipLengths"][IDLE],
                "quadNames": [q["name"] for q in plan["quads"]], "lightNames": [l["name"] for l in plan["lights"]],
                "uvAtlasCells": len(plan["uvAtlas"]["cells"]) if plan["uvAtlas"] else 0,
                # mergeMeshes: the one SMR's vertex count (0 = not checked) and the body's own leading range
                "meshVertices": plan["mergedMaster"]["totalVertices"] if plan.get("mergedMaster") else 0,
                "bodyVertices": plan["mergedMaster"]["bodyVertices"] if plan.get("mergedMaster") else 0,
                "checks": probe_checks(plan, glb_morph_peak(unit_dir(out, r["labSid"]) / "delivered_idle_retimed.glb"),
                                       # the unit config belongs to the retarget unit the row is built from (the frozen
                                       # spec's "unit"; toa_boar_rider ships h3_boar_rider), not to the lab sid
                                       glb_densify_record(unit_dir(out, r["labSid"]) / "delivered_idle_retimed.glb",
                                                          load(unit_dir(out, r["labSid"]) / "inputs" / f"{r['labSid']}.json")["unit"]))
                          + rubble_probe_checks(plan, unit_dir(out, r["labSid"]) / "delivered_idle_retimed.glb")})
        spec_path, report = out / "bundle_probe_spec.json", out / "bundle_probe_report.json"
        dump(spec_path, spec)
        if report.exists():
            report.rename(report.with_name(f"bundle_probe_report_{datetime.now():%Y%m%d_%H%M%S}.json"))
        result = unity("OldenEra.Homm3Import.ProbeDefRetargetDeliveryBundles.Run",
                       ["-defRetargetProbeSpec", spec_path, "-defRetargetProbeOut", report], out / "logs/unity_probe.log")
        probe = load(report)
        if {u["labSid"] for u in probe["units"]} != {r["labSid"] for r in rows} or any(not u["ok"] for u in probe["units"]):
            raise ShipError("offline bundle probe did not pass: " + json.dumps([u.get("errors") for u in probe["units"]])[:2000])
        disp = displacement_probe(rows, out)
        dump(out / "bundle_probe.json", {**fp, **result, "report": str(report), "reportSha256": sha(report),
                                         **({"displacementProbe": disp} if disp else {}),
                                         "probeSourceSha256": sha(PROBE_SCRIPT),
                                         "bundleHashes": {r["bundleName"]: sha(BUILD_OUT / r["bundleName"]) for r in rows}})
    else:
        require_game_stopped()
        for record in ("bundle_build.json", "bundle_probe.json"):
            require_current(out / record, args.selection, selection)
        fp = fingerprint(out, args.selection, selection)
        built, probe = load(out / "bundle_build.json"), load(out / "bundle_probe.json")
        if built.get("inputHashes") != fp["inputHashes"] or probe.get("inputHashes") != fp["inputHashes"]:
            raise ShipError("delivery changed since bundle build/probe")
        if sha(Path(probe["report"])) != probe["reportSha256"] or probe["probeSourceSha256"] != sha(PROBE_SCRIPT):
            raise ShipError("offline bundle probe is stale")
        for r in rows:
            if sha(BUILD_OUT / r["bundleName"]) != probe["bundleHashes"][r["bundleName"]]:
                raise ShipError(f"bundle changed since the probe: {r['bundleName']}")
        payload_gate(BUILD_OUT, rows, out)
        require_displacement_compiled(rows, out)
        want_disp = {r["labSid"]: dm["sha256"] for r in rows for dm in [displacement_mask_glb(r, out, bake=False)] if dm}
        if want_disp:
            dp = probe.get("displacementProbe") or {}
            if dp.get("units") != want_disp or dp.get("probeSourceSha256") != sha(DISPLACEMENT_PROBE_SCRIPT)                     or sha(Path(dp["report"])) != dp.get("reportSha256"):
                raise ShipError("displacementMaskGlb rows have no current bundle colour-stream readback; rerun probe")
        target = GOLDEN / "BepInEx/plugins/OfflineUnlockMod/homm3_bundles"
        runtime = load(out / "runtime_capability_build.json")
        abi_version = validate_runtime_capability(runtime, rows)
        try:
            installed_abi = payload_abi.require_installed_surface(PAYLOAD_SURFACE, abi_version, target.parent)
        except payload_abi.AbiError as e:
            raise ShipError(f"{e}; deploy the plugin through the established build first") from e
        backup = out / ("installed_backup_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
        backup.mkdir(exist_ok=False)
        prune_backups(out, "installed_backup")
        installed_table = target.parent / "homm3_import.json"
        shutil.copy2(installed_table, backup / installed_table.name)
        shutil.copy2(IMPORT, installed_table)
        if sha(installed_table) != sha(IMPORT):
            raise ShipError("installed homm3_import.json readback differs")
        installed_import = load(installed_table)
        try:
            import_bindings.check(runtime.get(import_bindings.KEY), installed_import, rows, "installed homm3_import.json")
        except ValueError as e:
            raise ShipError(str(e)) from e
        for r in rows:
            prefab = f"Assets/CustomUnits/homm3_lab/{r['labSid']}/OwnedSkinned/owned_skinned.prefab"
            if not any(e.get("battlePrefabAssetPath") == prefab and e.get("bundleName") == r["bundleName"]
                       and r["gameSid"] in e.get("gameUnitSids", []) for e in installed_import["entries"]):
                raise ShipError(f"installed import table has no binding for {r['labSid']}")
        installed_dll = target.parent / "OfflineUnlockMod.dll"
        for r in rows:
            dest = target / r["bundleName"]
            if dest.is_file():
                shutil.copy2(dest, backup / dest.name)
        # vanilla-style effects ride the plugin folder (homm3_mesh_fx catalog + emission PNGs), pinned by the record
        mesh_fx = runtime.get("meshFx") or {}
        if any(r.get("vfxAuthority") == "vanilla_style" for r in rows) and not mesh_fx:
            raise ShipError("vanilla-style rows need the runtime record's meshFx file pins")
        overrides = {}
        for spec in args.mesh_fx_source:
            relp, sep, path = spec.partition("=")
            if not sep or relp not in mesh_fx:
                raise ShipError(f"--mesh-fx-source {spec!r}: not REL=PATH with REL pinned by the runtime record")
            src = Path(path).resolve()
            committed = subprocess.run(["git", "show", f"HEAD:{(PLUGIN_DIR / relp).relative_to(ROOT).as_posix()}"],
                                       cwd=ROOT, capture_output=True)
            if committed.returncode != 0:
                raise ShipError(f"--mesh-fx-source {relp}: no blob committed at HEAD")
            if not src.is_file() or sha(src) != mesh_fx[relp]                     or hashlib.sha256(committed.stdout).hexdigest() != mesh_fx[relp]:
                raise ShipError(f"--mesh-fx-source {relp}: {src} differs from the record pin or the HEAD blob")
            overrides[relp] = src
        for relp, want in sorted(mesh_fx.items()):
            src, dest = overrides.get(relp, PLUGIN_DIR / relp), target.parent / relp
            if not src.is_file() or sha(src) != want:
                raise ShipError(f"plugin data changed since the runtime record: {relp}")
            if dest.is_file():
                (backup / Path(relp).parent).mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, backup / relp)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            if sha(dest) != want:
                raise ShipError(f"installed readback differs: {dest}")
        readback = []
        for r in rows:
            src, dest = BUILD_OUT / r["bundleName"], target / r["bundleName"]
            shutil.copy2(src, dest)
            if sha(src) != sha(dest):
                raise ShipError(f"installed readback differs: {dest}")
            readback.append({"bundle": dest.name, "sha256": sha(dest), "bytes": dest.stat().st_size})
            # the Unity .manifest travels with its bundle: installed-side gates (stopgap census) read
            # clip names from it, and a stale one from an older lane would describe the wrong bundle
            src_m, dest_m = src.with_name(src.name + ".manifest"), dest.with_name(dest.name + ".manifest")
            if not src_m.is_file():
                raise ShipError(f"built bundle has no Unity manifest: {src_m}")
            if dest_m.is_file():
                shutil.copy2(dest_m, backup / dest_m.name)
            shutil.copy2(src_m, dest_m)
            if sha(src_m) != sha(dest_m):
                raise ShipError(f"installed readback differs: {dest_m}")
        payload_gate(target, rows, out)
        dump(out / "installed_readback.json", {**fp, "target": str(target), "backup": str(backup),
                                               "runtimeDll": str(installed_dll), "runtimeDllSha256": sha(installed_dll),
                                               payload_abi.RECORD_KEY: {"surface": PAYLOAD_SURFACE, "version": abi_version,
                                                                        "installedDllSha256": installed_abi["dllSha256"]},
                                               "importTableSha256": sha(installed_table),
                                               "meshFx": {k: sha(target.parent / k) for k in sorted(mesh_fx)},
                                               "meshFxSources": {k: str(v) for k, v in sorted(overrides.items())},
                                               "bundles": readback,
                                               "proof": "installed payload validated; runtime appearance unproven"})
    print(f"{args.stage}: complete", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ShipError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)
