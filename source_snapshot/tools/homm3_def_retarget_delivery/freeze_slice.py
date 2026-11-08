"""Freeze a faction slice for ship_def_retarget_slice.py from the canonical, look-applied chain.

    python tools/homm3_def_retarget_delivery/freeze_slice.py <slice_name> <unit> [<unit> ...] [--note TEXT]

Per unit (labSid; the import row gives bundleName and the game sid):
  - refuses unless the look stamp's deliveredGlbSha256 / basecolorSha256 / vfxManifestSha256 / specSha256 match
    the canonical GLB, basecolor, vfx manifest and look spec on disk (the look was applied on this build), the
    retarget glb_verify passes and the corrective-morph extent is under the slice gate. A rawAccepted stamp
    (look.py --accept-raw: every grade mode measured further from the DEF than the raw bake) is accepted only when
    it passes spec.raw_accepted_errors and its basecolor is raw_basecolor.png, the GLB's own body image; a unit
    with no stamp refuses;
  - copies them to artifacts/homm3_def_retarget_delivery/<slice>/<unit>/inputs/ (look_delivered.glb, stamp.json,
    <unit>.json, basecolor.png, vfx/);
  - runs tools/homm3_idle_cadence/retime_idle.py on the frozen GLB (-> delivered_idle_retimed.glb + report);
  - refuses a retimed GLB whose Unit_Idle frame 0 does not face glTF +Z within the facing contract's tolerance
    (tools/validate_homm3_owned_skinned_facing_contract.py measures every selection the same way);
  - refuses a retimed GLB whose Unit_Move is under-articulated by flyer_articulation.gate (wings that do not beat,
    a body that turns more than its wings, legs that do not swing; the articulation contract validator gates
    every selection the same way);
  - refuses a retimed GLB any clip of which holds one pose over 3+ DEF frames while the DEF moves
    (flyer_articulation.freeze_check; the idle retime's resampled Idle is measured on inputs/look_delivered.glb).
  - refuses a retimed GLB off the ground against its DEF (ground_check.ground_check: a sinking or entering-off-floor
    clip, a Hips step beyond the DEF, a dead body off the floor; exemptions from the unit config, stamped), and a
    canonical GLB without the ground stage's stamp (ground_glb.stamp_errors; fleet_rebuild.py runs ground_glb.py apply)
    or, for a unit whose config has "propFloor", without the prop-floor stamp (prop_floor_glb.stamp_errors).
  - refuses a unit whose config sets silhouetteRefine.propAimDepth "imagePlane" unless its refine log shows the rule ran
    (depthLock + screenDeg on every propAim row) and every swing stays within propAimRange of the capture's hand pose
    (prop_aim_errors).
  - refuses a canonical GLB not built from the unit's reviewed source mesh (source_mesh_identity.attest: the
    homm3DefRetargetSourceMesh stamp against identity_reviews.json, else the unit's own current smartrigged file; an
    unstamped pre-stamp build only through source_mesh_legacy.json); the row records sourceMeshSha256 + identityReview.
Writes tools/homm3_def_retarget_delivery/<slice>.json (selection schema v1) with every pin; top-level keys it does not
own (supersededBy, supersededNote, ...) are kept as the file had them (merge_selection).
Albedo is "uvAtlas" when the look manifest carries a uvAtlas layer, else "basecolor".
A unit with a vanilla-style spec (tools/homm3_vfx/vanilla_style/units/<labSid>.json) is frozen as a vanilla_style row
(vfxAuthority vanilla_style, albedo basecolor, vanillaStyleSpec), fail closed: the spec must exist for this labSid,
pass vanilla_style_fx.check_spec against the probed vanilla sources (the static validation compile runs; compile
itself needs the frozen row and the delivery lab's stock map, so it runs after the freeze), and supersede every
uvAtlas/defFlipbook/effectLight/volumetricFire layer of the frozen look manifest, so the row ships no defFlipbook
layer. vanilla_style_fx.py check then pins the compiled catalog to the row, and the ship step needs meshFx pins.
A unit with a recolor spec (tools/homm3_unit_look/recolor/<labSid>.json, homm3_unit_recolor.v1; 2026-10-08 user: royal
and battle griffin are recolors of h3_griffin) is frozen from another row's frozen inputs instead of its own chain
(freeze_recolor): the source row's pins must hold, tools/homm3_unit_look/recolor.py's output must match the spec and the
source pins, the delivered GLB is the source's frozen look_delivered.glb with only the body base colour swapped, the
idle retime must reproduce the source's retimed GLB except that image (so the source's facing, articulation, stall,
ground and stride gates carry over byte for byte), and the unit keeps its own look spec, VFX manifest, vanilla-style
spec, gameSid and bundle. Identity: the unit's review must accept the source's mesh (defRetargetMesh).
After a successful freeze each superseded folder is removed or, while a selection still pins it, renamed to
<lab>.pinned_<idlesha> (release_prior); then every <slice>/*.pinned_* folder of every slice that no selection pins any
more is removed (sweep_pinned). Both keep everything when a selection cannot be read.
Proof tier: generated artifact (nothing built).
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from fleet_census import MORPH_DELTA_MAX_HEIGHT_RATIO, ROOT, IMPORT, load, morph_extent, sha, verify_status  # noqa: E402

sys.path.insert(0, str(ROOT / "tools/homm3_unit_look"))
import spec as look_spec  # noqa: E402
from glbpatch import Glb, sha256_bytes  # noqa: E402

sys.path.insert(0, str(ROOT / "tools"))
from validate_homm3_owned_skinned_facing_contract import GLB_FORWARD_TOL, glb_idle0_forward_rule  # noqa: E402
from flyer_articulation import GATE_CLIP, freeze_check, glb_clips, gate as articulation_gate, move_rule, wing_rule  # noqa: E402
from ground_check import debt_entry, debt_uncovered, ground_check, ground_check_cached  # noqa: E402
from ground_glb import stamp_errors as ground_stamp_errors  # noqa: E402
from prop_floor_glb import stamp_errors as prop_floor_stamp_errors  # noqa: E402
from stride_match_glb import DEFAULT_MAX_SLIP as STRIDE_MAX_SLIP, MAX_RATIO as STRIDE_MAX_RATIO, STAMP as STRIDE_STAMP  # noqa: E402
from stride_match_glb import check_exempt_rig, measure as stride_measure, unit_flier as stride_unit_flier  # noqa: E402
from stride_match_glb import stride_faults_after, unit_inputs as stride_unit_inputs, unit_stride_exempt  # noqa: E402
from ship_def_retarget_slice import ShipError, verify_freeze  # noqa: E402
import merge_rubble_glb  # noqa: E402
from source_mesh_identity import IdentityError, attest as source_mesh_attest  # noqa: E402


VS_UNITS = ROOT / "tools/homm3_vfx/vanilla_style/units"
VS_SUPERSEDED_TYPES = ("uvAtlas", "defFlipbook", "effectLight", "volumetricFire", "event")   # = vanilla_style_fx.SUPERSEDED_TYPES


def vanilla_style_row(lab: str, spec_path: Path, layers: dict) -> dict:
    """Fail-closed acceptance of a vanilla-style row at freeze. layers: the frozen look manifest {id: type}."""
    sys.path.insert(0, str(ROOT / "tools/homm3_vfx"))
    import vanilla_style_fx as vs  # noqa: E402
    if tuple(vs.SUPERSEDED_TYPES) != VS_SUPERSEDED_TYPES:
        raise SystemExit(f"{lab}: vanilla_style_fx.SUPERSEDED_TYPES {vs.SUPERSEDED_TYPES} drifted from freeze_slice's")
    spec = load(spec_path)
    if not spec or spec.get("unit") != lab:
        raise SystemExit(f"{lab}: vanilla-style spec {spec_path.name} is missing or names unit {spec and spec.get('unit')}")
    src = load(vs.SOURCES) or {}
    if src.get("schema") != vs.SOURCES_SCHEMA:
        raise SystemExit(f"{lab}: {vs.SOURCES.name} missing or not {vs.SOURCES_SCHEMA}")
    try:
        vs.check_spec(lab, spec, src["sources"])
    except vs.VsError as e:
        raise SystemExit(f"{lab}: vanilla-style spec does not validate: {e}")
    sup = set(spec["supersedes"]["lookLayers"])
    need = {k for k, t in layers.items() if t in VS_SUPERSEDED_TYPES}
    if sup != need:
        raise SystemExit(f"{lab}: vanilla-style spec supersedes {sorted(sup)} but the frozen look manifest carries "
                         f"{sorted(need)}")
    left = sorted(k for k, t in layers.items() if t == "defFlipbook" and k not in sup)
    if left:
        raise SystemExit(f"{lab}: defFlipbook layers {left} would still ship")
    return {"spec": spec_path.relative_to(ROOT).as_posix(), "specSha256": vs.canonical_sha(spec),
            "superseded": sorted(sup)}


RUBBLE_REASON = ("the death shatter's rubble mesh (build_unit.py shatter) is a second SkinnedMeshRenderer; this lane builds "
                 "exactly one body SMR and the runtime's uvAtlas/Hex/Lit rebind assume one. Without it the body still collapses "
                 "at the shatter frame, so the death ends in a vanish instead of falling chunks")


def prop_aim_errors(u: str) -> list[str]:
    """A unit whose config opts into silhouetteRefine.propAimDepth "imagePlane" must be frozen from a build that ran it:
    every refine row of every propAim bone carries depthLock and screenDeg (build_unit.py) and a swing within
    propAimRange of the capture's hand pose. A pre-rule build had a free depth tilt whose sign flipped frame to frame
    (2026-09-30 troglodyte-line spear flail: idle 77.6 deg, attack 94.7, hitted 105 between consecutive frames)."""
    cfg = load(ROOT / "tools/homm3_def_retarget/units" / f"{u}.json") or {}
    sr = cfg.get("silhouetteRefine") or {}
    if sr.get("propAimDepth") != "imagePlane":
        return []
    rng = float(sr.get("propAimRange", 100))
    rows = load(ROOT / "artifacts/homm3_def_retarget" / u / f"{u}_def_retarget.blend.refine.json")
    if not rows:
        return ["no refine log"]
    bad = []
    for bone in sr.get("propAim", []):
        rec = [r.get(bone) for r in rows]
        missing = [i for i, x in enumerate(rec) if not x or "depthLock" not in x or "screenDeg" not in x]
        if missing:
            bad.append(f"{bone}: {len(missing)} refine rows without depthLock/screenDeg (first frame {missing[0]})")
            continue
        over = [(i, x["aim1"]) for i, x in enumerate(rec) if abs(x["aim1"]) > rng + 0.05]   # log rounds to 0.1 deg
        if over:
            bad.append(f"{bone}: swing beyond propAimRange {rng:g} at {over[:4]}")
    return bad


def read_glb_json(p: Path) -> dict:
    with open(p, "rb") as f:
        head = f.read(20)
        return json.loads(f.read(int.from_bytes(head[12:16], "little")))


def freeze_unit(arg: str, out: Path, entries: list) -> dict:
    # "<unit>" or "<source unit>:<lab sid>" when the import row's lab sid differs from the retarget unit id
    u, _, lab = arg.partition(":")
    lab = lab or u
    prefab = f"Assets/CustomUnits/homm3_lab/{lab}/OwnedSkinned/owned_skinned.prefab"
    e = [x for x in entries if x.get("battlePrefabAssetPath") == prefab]
    if len(e) != 1:
        raise SystemExit(f"{u}: {len(e)} import rows bind {prefab}")
    e = e[0]
    vs_path = VS_UNITS / f"{lab}.json"
    if (RECOLOR_SPECS / f"{lab}.json").is_file():
        if lab != u:
            raise SystemExit(f"{u}: a recolor row is frozen by its lab sid {lab}, not as {arg}")
        return freeze_recolor(lab, out, e, vs_path)
    if lab != u and (VS_UNITS / f"{u}.json").is_file():
        raise SystemExit(f"{u}: vanilla-style spec is named for the source unit {u}, the row is {lab}")
    C = ROOT / "artifacts/homm3_def_retarget" / u
    L = ROOT / "artifacts/homm3_unit_look" / u
    glb, basecolor, vfx = C / f"{u}_def_retarget.glb", L / "basecolor.png", L / "vfx"
    spec_p = ROOT / "tools/homm3_unit_look/units" / f"{u}.json"
    stamp = load(L / "stamp.json")
    if not stamp:
        raise SystemExit(f"{u}: no look stamp")
    if stamp.get("kind") == look_spec.RAW_ACCEPTED:
        bad = look_spec.raw_accepted_errors(stamp, u)
        if bad:
            raise SystemExit(f"{u}: rawAccepted look stamp refused: {'; '.join(bad)}")
        basecolor = L / look_spec.RAW_BASECOLOR
        g = Glb(glb.read_bytes())
        if not basecolor.is_file() or sha256_bytes(g.image_bytes(g.body_base_color_image())) != sha(basecolor):
            raise SystemExit(f"{u}: rawAccepted {basecolor.name} is not the delivered GLB's body image")
    elif stamp.get("kind") is not None:
        raise SystemExit(f"{u}: unknown look stamp kind {stamp.get('kind')!r}")
    checks = {"deliveredGlbSha256": sha(glb), "basecolorSha256": sha(basecolor),
              "vfxManifestSha256": sha(vfx / "vfx_manifest.json"), "specSha256": look_spec.canonical_sha(load(spec_p))}
    for k, got in checks.items():
        if stamp.get(k) != got:
            raise SystemExit(f"{u}: look stamp {k} {str(stamp.get(k))[:12]} != on disk {got[:12]} (re-run look.py {u} --force)")
    v = verify_status(u)
    if v["status"] != "ok":
        raise SystemExit(f"{u}: retarget verify {v}")
    bad = prop_aim_errors(u)
    if bad:
        raise SystemExit(f"{u}: propAimDepth imagePlane not in this build: {'; '.join(bad)} (re-run run_unit.sh {u})")
    m = morph_extent(glb)
    if m["ratio"] is None or m["ratio"] > MORPH_DELTA_MAX_HEIGHT_RATIO:
        raise SystemExit(f"{u}: morph ratio {m['ratio']} over the slice gate")
    try:   # mesh identity: built from the reviewed source mesh (source_mesh_identity.py)
        ident = source_mesh_attest(u, glb)
    except IdentityError as exc:
        raise SystemExit(f"{u}: source mesh identity: {exc}")
    d = out / lab
    inp = d / "inputs"
    if d.exists():
        shutil.rmtree(d)
    inp.mkdir(parents=True)
    shutil.copy2(glb, inp / "look_delivered.glb")
    shutil.copy2(L / "stamp.json", inp / "stamp.json")
    shutil.copy2(spec_p, inp / f"{lab}.json")
    shutil.copy2(basecolor, inp / "basecolor.png")
    shutil.copytree(vfx, inp / "vfx")
    for p, want in ((inp / "look_delivered.glb", checks["deliveredGlbSha256"]), (inp / "basecolor.png", checks["basecolorSha256"])):
        if sha(p) != want:
            raise SystemExit(f"{u}: copy of {p.name} changed under the freeze")
    rel = lambda p: p.relative_to(ROOT).as_posix()  # noqa: E731
    r = subprocess.run([sys.executable, ROOT / "tools/homm3_idle_cadence/retime_idle.py", rel(inp / "look_delivered.glb"),
                        rel(d / "delivered_idle_retimed.glb"), "--unit", u, "--report", rel(d / "idle_retime_report.json")],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"{u}: retime_idle failed: {(r.stdout + r.stderr)[-600:]}")
    rep = load(d / "idle_retime_report.json")
    f, facing_rule, facing_note = glb_idle0_forward_rule(d / "delivered_idle_retimed.glb")
    ang = None if f is None else math.degrees(math.atan2(f[0], f[2]))
    if ang is None or abs(ang) > GLB_FORWARD_TOL:
        shutil.rmtree(d)
        raise SystemExit(f"{u}: Unit_Idle frame 0 faces glTF yaw {ang} (rule {facing_rule}: {facing_note}); the facing contract "
                         f"needs +Z within {GLB_FORWARD_TOL:.0f} "
                         "(a castle_yaw/necropolis_yaw body turn baked for the DEF render; needs a delivery build without it)")
    move = glb_clips(d / "delivered_idle_retimed.glb").get(GATE_CLIP)
    bad = ["no " + GATE_CLIP] if move is None else articulation_gate(move, u)
    if bad:
        shutil.rmtree(d)
        raise SystemExit(f"{u}: under-articulated {GATE_CLIP}: {'; '.join(bad)} "
                         "(tools/validate_homm3_owned_skinned_articulation_contract.py; rebuild with articulated wings/limbs)")
    fbad, _ = freeze_check(u, d / "delivered_idle_retimed.glb", inp / "look_delivered.glb")
    if fbad:
        shutil.rmtree(d)
        raise SystemExit(f"{u}: frozen pose (stall) while the DEF moves: {'; '.join(fbad)} "
                         "(flyer_articulation.freeze_check; fix the clip, never widen FREEZE_RUN_MAX)")
    # ground gate (ground_check.py): feet on the floor per clip, no Hips step beyond the DEF, the dead body on the floor;
    # the canonical GLB the look delivered must carry the ground stage's stamp (ground_glb.py, run by fleet_rebuild.py)
    cjs = read_glb_json(C / f"{u}_def_retarget.glb")
    gbad = [f"canonical GLB: {e}" for e in ground_stamp_errors(cjs) + prop_floor_stamp_errors(u, cjs)]
    try:
        gbad += ground_check(u, d / "delivered_idle_retimed.glb")[0]
    except SystemExit as e:
        gbad.append(str(e))
    if gbad:
        shutil.rmtree(d)
        raise SystemExit(f"{u}: off the ground: {'; '.join(gbad)} "
                         "(tools/homm3_def_retarget_delivery/ground_check.py; fleet_rebuild.py runs ground_glb.py apply, "
                         "never widen GROUND_TOL)")
    # stride gate (docs/homm3_stride_match.md): a ground walker's Move must cover OE's ground speed without skating.
    # Measured on the retimed GLB with the installed moveSpeed / hex scale, so it does not rely on a stamp surviving look.
    _, sg, sh, sscale, sms = stride_unit_inputs(u, d / "delivered_idle_retimed.glb", None)
    # flier class from reference/homm3_fliers.json (fail closed); an exempt walker declares strideExempt and its rig
    # must have no leg chain or exactly its strideExemptLegs; a walker without a readable leg chain raises
    try:
        why = unit_stride_exempt(u)
        if why:
            check_exempt_rig(u, sg, why)
        sres = {"airborne": True, "strideExempt": why} if why else stride_measure(sg, sms, sscale, sh, flier=stride_unit_flier(u))
    except SystemExit as e:
        shutil.rmtree(d)
        raise SystemExit(f"{u}: stride gate: {e}")
    stamped = STRIDE_STAMP in read_glb_json(C / f"{u}_def_retarget.glb").get("asset", {}).get("extras", {})
    sbad = [] if sres.get("airborne") else stride_faults_after(u, sres["slipRatio"], sres["requiredOverActual"], STRIDE_MAX_SLIP, STRIDE_MAX_RATIO)
    if sbad:
        shutil.rmtree(d)
        raise SystemExit(f"{u}: {GATE_CLIP} skates: {'; '.join(sbad)}; slip {sres['slipRatio']} (max {STRIDE_MAX_SLIP}), required/actual stride "
                         f"{sres['requiredOverActual']} (max {STRIDE_MAX_RATIO}); stride-matched={stamped} "
                         "(fleet_rebuild.py runs stride_match_glb.py apply)")
    stride = ({"strideExempt": sres["strideExempt"]} if sres.get("strideExempt") else {"airborne": True}) if sres.get("airborne") else {"slipRatio": sres["slipRatio"], "requiredOverActual": sres["requiredOverActual"],
                                                              "strideMatched": stamped}
    js = read_glb_json(d / "delivered_idle_retimed.glb")
    extra = [n["name"] for n in js["nodes"] if "skin" in n and "mesh" in n and n.get("name") != u]
    if [n for n in extra if n != f"{u}_Rubble"]:
        shutil.rmtree(d)
        raise SystemExit(f"{u}: skinned meshes besides the body the lane cannot defer: {extra}")
    manifest = load(inp / "vfx/vfx_manifest.json")
    layers = {k: v["type"] for k, v in manifest.get("layers", {}).items()}
    if stamp.get("kind") == look_spec.RAW_ACCEPTED and "uvAtlas" in layers.values():
        shutil.rmtree(d)
        raise SystemExit(f"{u}: a rawAccepted unit ships its raw albedo; its look manifest must carry no uvAtlas layer")
    row = {"labSid": lab, "gameSid": e["gameUnitSids"][0], "bundleName": e["bundleName"],
           "albedo": "uvAtlas" if "uvAtlas" in layers.values() else "basecolor", **ident}
    vs_facts = None
    if vs_path.is_file():
        try:
            vs_facts = vanilla_style_row(lab, vs_path, layers)
        except SystemExit:
            shutil.rmtree(d)
            raise
        row.update({"albedo": "basecolor", "vfxAuthority": "vanilla_style", "vanillaStyleSpec": rel(vs_path)})
    if extra:
        row["deferMeshes"] = {extra[0]: RUBBLE_REASON}
    return {**row,
            "frozen": {"lookDeliveredGlbSha256": checks["deliveredGlbSha256"], "idleRetimedGlbSha256": rep["dstSha256"],
                       "vfxManifestSha256": checks["vfxManifestSha256"], "specSha256": checks["specSha256"],
                       "basecolorSha256": checks["basecolorSha256"],
                       **({"lookStampSha256": sha(inp / "stamp.json")} if stamp.get("kind") == look_spec.RAW_ACCEPTED else {})},
            "_facts": {"sourceUnit": u, "facingRule": facing_rule,
                       "wingRule": list(wing_rule(u)) if move.get("wingBones") else None, "moveRule": move_rule(u), "morphRatio": m["ratio"], "idleTreatment": rep["treatment"]["treatment"], "lookLayers": layers, "lookKind": stamp.get("kind") or "applied",
                       "stride": stride, "vfxAuthority": row.get("vfxAuthority", "unit_look"), "vanillaStyle": vs_facts}}


RECOLOR_SPECS = ROOT / "tools/homm3_unit_look/recolor"
RECOLOR_OUT = ROOT / "artifacts/homm3_unit_look_recolor"


def image_only_equal(a: Path, b: Path, png: bytes) -> bool:
    """True when GLBs a and b are identical once both carry ``png`` as their body base-colour image."""
    ga, gb = Glb.load(a), Glb.load(b)
    ga.replace_image(ga.body_base_color_image(), png)
    gb.replace_image(gb.body_base_color_image(), png)
    return ga.to_bytes() == gb.to_bytes()


def freeze_recolor(lab: str, out: Path, e: dict, vs_path: Path) -> dict:
    """Freeze ``lab`` as a palette recolor of another frozen row (module docstring)."""
    import recolor as rc
    rspec = rc.load_spec(lab)
    src_lab, src_sel = rspec["source"]["labSid"], rspec["source"]["selection"]
    sel = load(HERE / f"{src_sel}.json") or {}
    srow = next((r for r in sel.get("units", []) if r.get("labSid") == src_lab), None)
    if srow is None:
        raise SystemExit(f"{lab}: recolor source {src_lab} is not a row of {src_sel}.json")
    sout = ROOT / sel["out"]
    try:
        verify_freeze({"units": [srow]}, sout, pins_only=True)
    except (ShipError, OSError, KeyError, ValueError) as exc:
        raise SystemExit(f"{lab}: recolor source {src_lab} frozen inputs changed or are incomplete: {exc}") from exc
    sdir = sout / src_lab
    sfz = srow["frozen"]
    R = RECOLOR_OUT / lab
    rep = load(R / "recolor_report.json") or {}
    bc = R / "basecolor.png"
    if rep.get("specSha256") != rc.spec_sha(rspec) or rep.get("source", {}).get("lookDeliveredSha256") != sfz["lookDeliveredGlbSha256"] \
            or not bc.is_file() or sha(bc) != rep.get("basecolorSha256"):
        raise SystemExit(f"{lab}: {R.relative_to(ROOT).as_posix()} is not the current recolor of {src_lab} "
                         f"(run python tools/homm3_unit_look/recolor.py {lab})")
    # the unit's own look: its spec + VFX manifest as its look stamp applied them (the body image is the recolor)
    L = ROOT / "artifacts/homm3_unit_look" / lab
    spec_p = ROOT / "tools/homm3_unit_look/units" / f"{lab}.json"
    lstamp = load(L / "stamp.json")
    if not lstamp or lstamp.get("kind") is not None:
        raise SystemExit(f"{lab}: recolor needs the unit's applied look stamp (VFX manifest + spec)")
    spec_sha = look_spec.canonical_sha(load(spec_p))
    if lstamp.get("specSha256") != spec_sha or lstamp.get("vfxManifestSha256") != sha(L / "vfx/vfx_manifest.json"):
        raise SystemExit(f"{lab}: look stamp spec/vfx manifest pins do not match disk (re-run look.py {lab} --force)")
    d = out / lab
    inp = d / "inputs"
    if d.exists():
        shutil.rmtree(d)
    inp.mkdir(parents=True)
    png = bc.read_bytes()
    g = Glb.load(sdir / "inputs/look_delivered.glb")
    g.replace_image(g.body_base_color_image(), png)
    (inp / "look_delivered.glb").write_bytes(g.to_bytes())
    shutil.copy2(bc, inp / "basecolor.png")
    shutil.copy2(spec_p, inp / f"{lab}.json")
    shutil.copytree(L / "vfx", inp / "vfx")
    rel = lambda p: p.relative_to(ROOT).as_posix()  # noqa: E731
    look_sha, bc_sha = sha(inp / "look_delivered.glb"), sha(inp / "basecolor.png")
    stamp = {k: v for k, v in lstamp.items() if k not in ("deliveredGlbStat", "superseded")}
    stamp.update({"deliveredGlbSha256": look_sha, "basecolorSha256": bc_sha,
                  "recolor": {"spec": rel(RECOLOR_SPECS / f"{lab}.json"), "specSha256": rep["specSha256"],
                              "report": rel(R / "recolor_report.json"), "sourceSelection": src_sel, "sourceLabSid": src_lab,
                              "sourceLookDeliveredGlbSha256": sfz["lookDeliveredGlbSha256"],
                              "sourceIdleRetimedGlbSha256": sfz["idleRetimedGlbSha256"],
                              "unitLookStampDeliveredGlbSha256": lstamp.get("deliveredGlbSha256"),
                              "reason": rspec["reason"]}})
    (inp / "stamp.json").write_text(json.dumps(stamp, indent=1) + "\n", encoding="utf-8")
    src_unit = load(sdir / "inputs/stamp.json").get("unit") or src_lab
    r = subprocess.run([sys.executable, ROOT / "tools/homm3_idle_cadence/retime_idle.py", rel(inp / "look_delivered.glb"),
                        rel(d / "delivered_idle_retimed.glb"), "--unit", src_unit, "--report", rel(d / "idle_retime_report.json")],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        shutil.rmtree(d)
        raise SystemExit(f"{lab}: retime_idle failed: {(r.stdout + r.stderr)[-600:]}")
    rrep = load(d / "idle_retime_report.json")
    if not image_only_equal(d / "delivered_idle_retimed.glb", sdir / "delivered_idle_retimed.glb", png):
        shutil.rmtree(d)
        raise SystemExit(f"{lab}: the retimed recolor differs from {src_lab}'s frozen retimed GLB beyond the body image; "
                         "the source's gates would not carry over")
    try:   # the unit's identity review must accept the source's mesh (2026-10-08 user decision)
        ident = source_mesh_attest(lab, inp / "look_delivered.glb")
    except IdentityError as exc:
        shutil.rmtree(d)
        raise SystemExit(f"{lab}: source mesh identity: {exc} (its identity review needs defRetargetMesh = {src_lab}'s mesh)")
    manifest = load(inp / "vfx/vfx_manifest.json")
    layers = {k: v["type"] for k, v in manifest.get("layers", {}).items()}
    if "uvAtlas" in layers.values():
        shutil.rmtree(d)
        raise SystemExit(f"{lab}: a uvAtlas layer is bound to the unit's own UVs; a recolor ships the source's mesh")
    row = {"labSid": lab, "gameSid": e["gameUnitSids"][0], "bundleName": e["bundleName"], "albedo": "basecolor", **ident}
    vs_facts = None
    if vs_path.is_file():
        try:
            vs_facts = vanilla_style_row(lab, vs_path, layers)
        except SystemExit:
            shutil.rmtree(d)
            raise
        row.update({"vfxAuthority": "vanilla_style", "vanillaStyleSpec": rel(vs_path)})
    if "deferMeshes" in srow:
        row["deferMeshes"] = srow["deferMeshes"]
    if "mergeMeshes" in srow:
        row["mergeMeshes"] = srow["mergeMeshes"]
    row["recolor"] = {"of": src_lab, "selection": src_sel, "spec": rel(RECOLOR_SPECS / f"{lab}.json"),
                      "specSha256": rep["specSha256"], "sourceIdleRetimedGlbSha256": sfz["idleRetimedGlbSha256"]}
    return {**row,
            "frozen": {"lookDeliveredGlbSha256": look_sha, "idleRetimedGlbSha256": rrep["dstSha256"],
                       "vfxManifestSha256": sha(inp / "vfx/vfx_manifest.json"), "specSha256": spec_sha,
                       "basecolorSha256": bc_sha},
            "_facts": {"sourceUnit": src_unit, "recolorOf": src_lab, "idleTreatment": rrep["treatment"]["treatment"],
                       "lookLayers": layers, "lookKind": "recolor", "morphRatio": "as " + src_lab,
                       "vfxAuthority": row.get("vfxAuthority", "unit_look"), "vanillaStyle": vs_facts}}


def validate_request(units: list[str], drop: list[str], old_rows: list[dict]) -> None:
    old_labs = {r["labSid"] for r in old_rows}
    unknown = set(drop) - old_labs
    if unknown:
        raise SystemExit(f"--drop {sorted(unknown)}: not in the existing selection")
    requested = [arg.partition(":")[2] or arg.partition(":")[0] for arg in units]
    duplicate = sorted({lab for lab in requested if requested.count(lab) > 1})
    if duplicate:
        raise SystemExit(f"duplicate requested lab sid: {duplicate}")
    overlap = set(drop) & set(requested)
    if overlap:
        raise SystemExit(f"cannot freeze and --drop the same lab sid: {sorted(overlap)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slice")
    ap.add_argument("units", nargs="+", help="<unit> or <source unit>:<lab sid>")
    ap.add_argument("--note", default="")
    ap.add_argument("--drop", action="append", default=[], help="lab sid to remove from the selection")
    a = ap.parse_args()
    out_rel = f"artifacts/homm3_def_retarget_delivery/{a.slice}"
    out = ROOT / out_rel
    p = HERE / f"{a.slice}.json"
    old_doc = load(p) if p.is_file() else {}
    old_rows = old_doc.get("units", [])
    validate_request(a.units, a.drop, old_rows)
    entries = load(IMPORT)["entries"]
    labs = [arg.partition(":")[2] or arg.partition(":")[0] for arg in a.units]
    held = hold_prior(out, labs)
    try:
        freeze_run(a, out, out_rel, p, old_doc, entries)
    except BaseException:
        restore_prior(out, labs, held)
        raise
    docs = selection_docs()
    for lab, prev in held.items():
        release_prior(out_rel, lab, prev, docs)
    sweep_pinned(ROOT / DELIVERY_REL, docs, only=a.slice)
    return 0


SELECTION_SCHEMA = "homm3_def_retarget_delivery_selection.v1"
PRIOR_FILES = ("delivered_idle_retimed.glb", "inputs/look_delivered.glb")


def selection_docs() -> list[tuple[str, dict]] | None:
    """Every delivery selection, from the working tree and from HEAD, as (label, doc); None when any read fails,
    so the caller keeps what it cannot prove unpinned."""
    docs: list[tuple[str, dict]] = []
    try:
        for f in sorted(HERE.glob("*.json")):
            doc = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(doc, dict) and doc.get("schema") == SELECTION_SCHEMA:
                docs.append((f"worktree:{f.name}", doc))
        rel = HERE.relative_to(ROOT).as_posix()
        names = subprocess.run(["git", "ls-tree", "--name-only", "HEAD", rel + "/"], cwd=ROOT, check=True,
                               capture_output=True, text=True).stdout.split()
        for name in names:
            if not name.endswith(".json"):
                continue
            text = subprocess.run(["git", "show", f"HEAD:{name}"], cwd=ROOT, check=True,
                                  capture_output=True, text=True, encoding="utf-8").stdout
            doc = json.loads(text)
            if isinstance(doc, dict) and doc.get("schema") == SELECTION_SCHEMA:
                docs.append((f"HEAD:{Path(name).name}", doc))
    except (OSError, subprocess.CalledProcessError, ValueError, UnicodeDecodeError):
        return None
    return docs


def folder_pins(out_rel: str, lab: str, prior_shas: set[str], docs: list[tuple[str, dict]]) -> list[str]:
    """Selections that still point at a prior frozen folder: a same-``out`` row for ``lab`` pinning one of its shas,
    or any other selection naming ``<out_rel>/<lab>``."""
    pins = []
    for label, doc in docs:
        if doc.get("out") == out_rel:
            for row in doc.get("units", []):
                frozen = row.get("frozen") or {}
                if row.get("labSid") == lab and {frozen.get("lookDeliveredGlbSha256"),
                                                 frozen.get("idleRetimedGlbSha256")} & prior_shas:
                    pins.append(label)
        elif f"{out_rel}/{lab}" in json.dumps(doc):
            pins.append(label)
    return pins


def release_prior(out_rel: str, lab: str, prev: Path, docs: list[tuple[str, dict]] | None) -> None:
    """Free a superseded frozen folder after a successful freeze, unless a selection still pins it (then it is
    renamed aside) or pinning cannot be proven either way (then it is kept)."""
    if docs is None:
        print(f"KEEP {prev}: could not read every selection to prove it unpinned", flush=True)
        return
    try:
        prior_shas = {sha(prev / f) for f in PRIOR_FILES if (prev / f).is_file()}
    except OSError as e:
        print(f"KEEP {prev}: cannot hash it ({e})", flush=True)
        return
    pins = folder_pins(out_rel, lab, prior_shas, docs)
    if not pins:
        shutil.rmtree(prev)
        return
    idle = sha(prev / PRIOR_FILES[0])[:12] if (prev / PRIOR_FILES[0]).is_file() else "noidle"
    dest, n = prev.with_name(f"{lab}.pinned_{idle}"), 1
    while dest.exists():
        dest, n = prev.with_name(f"{lab}.pinned_{idle}_{n}"), n + 1
    prev.rename(dest)
    print(f"PINNED {dest.name}: still referenced by {', '.join(sorted(set(pins)))}", flush=True)


PINNED_TAG = ".pinned_"
DELIVERY_REL = "artifacts/homm3_def_retarget_delivery"


def sweep_pinned(delivery: Path, docs: list[tuple[str, dict]] | None, only: str | None = None) -> list[Path]:
    """Remove every ``<slice>/<lab>.pinned_*`` folder under ``delivery`` that no selection pins any more (folder_pins,
    the rule release_prior set it aside by); returns the removed folders. Runs after each successful freeze, so a
    folder kept for a selection that has since moved on does not pile up (229 folders, ~25 GB on 2026-10-09). Keeps
    everything when the selections could not all be read, and a folder it cannot hash. ``only`` limits the sweep to
    that slice's folder: a freeze never removes another slice's pins, which a concurrent lane may still need as its
    before (2026-10-11: a necropolis freeze swept dungeon pins mid-review)."""
    if docs is None:
        print("KEEP pinned folders: could not read every selection to prove them unpinned", flush=True)
        return []
    removed = []
    for d in sorted(delivery.glob(f"{only or '*'}/*{PINNED_TAG}*")):
        if not d.is_dir():
            continue
        out_rel, lab = f"{DELIVERY_REL}/{d.parent.name}", d.name.partition(PINNED_TAG)[0]
        # Hash only when a same-out row for this lab could match; other pins are by path and need no hash.
        wanted = any(doc.get("out") == out_rel and row.get("labSid") == lab
                     for _, doc in docs for row in doc.get("units", []))
        try:
            prior_shas = {sha(d / f) for f in PRIOR_FILES if (d / f).is_file()} if wanted else set()
        except OSError as e:
            print(f"KEEP {d}: cannot hash it ({e})", flush=True)
            continue
        if folder_pins(out_rel, lab, prior_shas, docs):
            continue
        shutil.rmtree(d)
        removed.append(d)
        print(f"UNPINNED {d.parent.name}/{d.name}: no selection pins it any more, removed", flush=True)
    return removed


PRIOR_SUFFIX = ".prior_freeze"


def hold_prior(out: Path, labs: list[str]) -> dict[str, Path]:
    """Set each requested unit's existing frozen folder aside, so a refused freeze gives it back unchanged."""
    held: dict[str, Path] = {}
    for lab in labs:
        d, prev = out / lab, out / (lab + PRIOR_SUFFIX)
        if prev.exists():
            raise SystemExit(f"{prev} exists: an interrupted freeze left it; restore or remove it by hand first")
        if d.exists():
            d.rename(prev)
            held[lab] = prev
    return held


def restore_prior(out: Path, labs: list[str], held: dict[str, Path]) -> None:
    """Undo a refused run: drop every folder it wrote for the requested units and put the prior ones back."""
    for lab in labs:
        d = out / lab
        if d.exists():
            shutil.rmtree(d)
        if lab in held:
            held[lab].rename(d)


NOTE_SEP = " | "


def slice_note(prev: str | None, this: str) -> str:
    """The slice note after a freeze: the previous note kept, this freeze's text appended (a freeze used to replace the
    whole note and drop the earlier freezes' prose, 2026-10-01 dungeon troglodyte note). An identical last entry is
    not appended twice."""
    prev = (prev or "").strip()
    if not prev:
        return this
    if prev == this or prev.endswith(NOTE_SEP + this):
        return prev
    return prev + NOTE_SEP + this


def merge_selection(old_doc: dict, owned: dict) -> dict:
    """The rewritten selection: every key freeze_slice owns (``owned``) replaced, every other top-level key of the
    existing file (supersededBy, supersededNote, ...) kept as it was, in the file's own order."""
    merged = dict(old_doc)
    merged.update(owned)
    return merged


def keep_merge_opt_in(row: dict, old_rows: list[dict]) -> dict:
    """A row moved from deferMeshes to mergeMeshes (merge_rubble_glb.py rows: the shatter rubble ships on the body SMR)
    keeps that on a re-freeze; freeze_unit itself still writes deferMeshes for a row that never opted in."""
    old = next((r for r in old_rows if r.get("labSid") == row.get("labSid")), None)
    keep = [n for n in (row.get("deferMeshes") or {}) if n in ((old or {}).get("mergeMeshes") or {})]
    if keep:
        merge_rubble_glb.migrate_rows({"units": [row]}, [row["labSid"]])
    return row


def freeze_run(a, out: Path, out_rel: str, p: Path, old_doc: dict, entries: list) -> None:
    old_rows = old_doc.get("units", [])
    new, facts = {}, {}
    for u in a.units:
        row = keep_merge_opt_in(freeze_unit(u, out, entries), old_rows)
        facts[row["labSid"]] = row.pop("_facts")
        new[row["labSid"]] = row
        print(f"{row['labSid']}: frozen {facts[row['labSid']]}", flush=True)
    # Carried rows retain their exact inputs; the ground gate's failures must be the frozen sha's debt.
    carried = [r for r in old_rows if r["labSid"] not in new and r["labSid"] not in a.drop]
    try:
        verify_freeze({"units": carried}, out, pins_only=True)
    except (ShipError, OSError, KeyError, ValueError) as exc:
        raise SystemExit(f"carried frozen inputs changed or are incomplete: {exc}") from exc
    for r in carried:
        g = out / r["labSid"] / "delivered_idle_retimed.glb"
        pin = r["frozen"]["idleRetimedGlbSha256"]
        try:
            gbad, _, _ = ground_check_cached(r["labSid"], g)
        except SystemExit as e:
            gbad = [f"config {e}"]
        left = debt_uncovered(debt_entry(a.slice, r["labSid"]), pin, gbad)
        if left:
            raise SystemExit(f"{r['labSid']}: carried over off the ground without a matching debt entry "
                             f"(sha {pin[:12]}): {'; '.join(left)}")
    rows = [new.pop(r["labSid"]) if r["labSid"] in new else r for r in old_rows
            if r["labSid"] not in a.drop and (r["labSid"] in new or r in carried)] + list(new.values())
    sel = {"schema": "homm3_def_retarget_delivery_selection.v1", "slice": a.slice,
           "disposition": "user_requested_ingame_test", "accepted": False, "out": out_rel,
           "note": slice_note(old_doc.get("note"), (a.note + " " if a.note else "") + "Fleet rollout (docs/homm3_def_retarget_fleet_census.md): every unit re-baked on the "
                   "Tikhonov corrective-smooth solve (a9de7da122) and look re-applied before this freeze; frozen by "
                   "tools/homm3_def_retarget_delivery/freeze_slice.py. Morph ratios at freeze: "
                   + ", ".join(f"{u} {f['morphRatio']}" for u, f in facts.items()) + "."
                   + (f" Carried over unchanged: {', '.join(r['labSid'] for r in carried)}." if carried else "")),
           "chain": {"retarget": "existing canonical build artifacts/homm3_def_retarget/<unit>/<unit>_def_retarget.glb, re-baked by "
                                 "tools/homm3_def_retarget_delivery/fleet_rebuild.py (emphasis deliver.py --force, or bake_cs.py + "
                                 "RENDER_ONLY run_unit.sh + verify_glb.py for non-emphasised units)",
                     "emphasis": "tools/homm3_def_retarget_emphasis/deliver.py (run by fleet_rebuild.py)",
                     "look": "tools/homm3_unit_look/look.py <unit> --force (run by fleet_rebuild.py), frozen copies under <out>/<unit>/inputs",
                     "idleRetime": "applied at freeze: tools/homm3_idle_cadence/retime_idle.py on the frozen look-delivered GLB"},
           "units": rows}
    p.write_text(json.dumps(merge_selection(old_doc, sel), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {p.relative_to(ROOT)} ({len(rows)} units)")


if __name__ == "__main__":
    sys.exit(main())
