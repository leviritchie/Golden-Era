#!/usr/bin/env python3
"""Fail-closed contract for the vanilla-style unit effect layers (docs/olden_era_vanilla_vfx_style.md 8.3).

Layer types replacing defFlipbook sprite sheets, the uvAtlas stepped glow and steady effect lights:
  * vanillaParticles - a bare Shuriken subtree of a native prefab under a bone (real magic/VfxUber materials);
  * emissionMap      - the Hex/Lit emission map of the body material (steady glow is emission, never a light);
  * bodyDisplacement - Hex/Lit FLAG vertex displacement of the body, masked by a baked COLOR_0.r (refused without it);
                       shipped by the def_retarget ship step's displacementMaskGlb (bake -> lab master -> bundle
                       colour readback), proven on one candidate (vanilla_style/displacement_ship_proof.json);
  * bodyOverlay      - a vanilla renderer's material appended to the body SMR (always or on an animator window),
                       optionally tinted per unit (source.colors on the shader's allowed colour properties).

This gate proves (source/static + generated artifact):
  * every spec under tools/homm3_vfx/vanilla_style/units is valid against the static read of the installed
    prefabs, compiled, and its catalog rows / emission PNGs are exactly the compiled record
    (tools/homm3_vfx/vanilla_style_fx.py check);
  * no active def_retarget selection still ships a superseded flipbook / glow atlas / light for such a unit;
  * the plugin runtime keeps the contract: bare-subtree clone, keyword readback through shaderKeywords (never
    Material.IsKeywordEnabled), emission applied after the Hex/Lit rebind, ParticleSystemModule referenced,
    native loads only through the Il2Cpp runtime-invoke loader from LateUpdate.
It does not prove the in-combat look.
"""
from __future__ import annotations

import copy
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
sys.path.insert(0, str(ROOT / "tools" / "homm3_vfx"))


def fail(msg: str) -> None:
    print(f"homm3-vanilla-style-fx-contract: {msg}", file=sys.stderr)
    raise SystemExit(1)


def require(cond: bool, msg: str) -> None:
    if not cond:
        fail(msg)


def method_body(src: str, signature: str) -> str:
    start = src.find(signature)
    require(start >= 0, f"Homm3MeshFx.cs: {signature} missing")
    depth = 0
    i = src.index("{", start)
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
    fail(f"Homm3MeshFx.cs: {signature} body not closed")
    return ""


def check_runtime_source() -> None:
    fx = (PLUGIN / "Homm3MeshFx.cs").read_text(encoding="utf-8")
    require("IsKeywordEnabled" not in fx, "Homm3MeshFx.cs must read keywords through shaderKeywords, never IsKeywordEnabled")
    ensure = method_body(fx, "private static bool EnsureVanillaInstance(")
    require("TryLoadNativeResManagerGameObjectIl2Cpp" in ensure and "if (!allowIl2CppNativeLoad)" in ensure,
            "EnsureVanillaInstance must load natives only through the Il2Cpp runtime-invoke loader, gated to LateUpdate")
    require("template.transform.Find(vs.ChildPath)" in ensure and "Instantiate(child.gameObject)" in ensure,
            "EnsureVanillaInstance must clone only the childPath subtree, never the whole source prefab")
    require("renderer.enabled = false" in ensure, "EnsureVanillaInstance must silence unkept systems")
    tick = method_body(fx, "private static void TickVanillaSlot(")
    require("ParticleSystemStopBehavior.StopEmitting)" in tick,
            "a vanilla-style window must end by StopEmitting (particles finish their life), not SetActive(false)")
    require("SetActive(false)" not in tick, "TickVanillaSlot must not hide effects by deactivating them")
    emission = method_body(fx, "internal static void TryApplyBodyEmission(")
    require('EnableKeyword(EmissionKeyword)' in emission and "MaterialHasKeyword(material, EmissionKeyword)" in emission,
            "TryApplyBodyEmission must enable the Hex/Lit emission keyword and verify it by shaderKeywords readback")
    require('internal const string EmissionKeyword = "HEX_EMISSION_MAP_ENABLED";' in fx,
            "EmissionKeyword must be HEX_EMISSION_MAP_ENABLED")
    load = method_body(fx, "private static Texture2D LoadEmissionTexture(")
    require("TextureSha256" in load, "emission textures must be sha-checked against the catalog at load")
    attach = method_body(fx, "private static void AttachRows(")
    require("allowIl2CppNativeLoad: false" in attach and "allowIl2CppNativeLoad: true" not in attach,
            "AttachRows must stay cache-only (native loads only from LateUpdate)")

    # AnimatorOverrideController[string] marshals through Il2CppSystem.ReadOnlySpan<char>, missing from the live
    # mscorlib (MissingMethodException in game 2026-09-26); only the clip-keyed indexer is safe.
    require(re.search(r"aoc\[\s*slotName\s*\]|aoc\[\s*\"", fx) is None and "aoc[stock]" in fx,
            "Homm3MeshFx must resolve override clips via aoc[AnimationClip], never aoc[string]")
    iv = (PLUGIN / "Homm3ImportVisuals.cs").read_text(encoding="utf-8")
    m = re.search(r"ApplyOwnedSkinnedHexLitPbr\(fallback,[^;]*;\s*(//[^\n]*\n\s*)*Homm3MeshFx\.TryApplyBodyEmission\(fallback, entry, lane, log\);", iv)
    require(m is not None, "Homm3ImportVisuals must call Homm3MeshFx.TryApplyBodyEmission right after ApplyOwnedSkinnedHexLitPbr "
                           "(the rebind sanitise blacks _EmissionColor first)")

    # alignToReach: the compiled boneLocalRot is the clone root's rotation in the bone frame
    require("root.localRotation = vs.BoneLocalRot;" in ensure,
            "EnsureVanillaInstance must apply the compiled boneLocalRot (alignToReach) to the clone root")

    # boneAnchor: the compiled boneLocalPos is the clone root's position in the bone frame, parsed fail-closed,
    # and the anchorNode re-seat aims at that point, not at the bare joint
    require("root.localPosition = vs.BoneLocalPos;" in ensure,
            "EnsureVanillaInstance must place the clone root at the compiled boneLocalPos (boneAnchor)")
    orient = method_body(fx, "private static void OrientVanilla(")
    require("slot.Socket.TransformPoint(vs.BoneLocalPos) - slot.Anchor.position" in orient
            and "slot.Socket.position - slot.Anchor.position" not in orient,
            "OrientVanilla's anchorNode re-seat must target the boneLocalPos point, not the joint")
    parse = method_body(fx, "private static bool TryParseVanillaStyle(")
    require('vs["boneLocalPos"]' in parse and "vanillaStyle boneLocalPos needs [x, y, z] of finite numbers." in parse
            and "return false;" in parse[parse.index('vs["boneLocalPos"]'):]
            and "BoneLocalPos = boneLocalPos," in parse,
            "TryParseVanillaStyle must parse boneLocalPos as three finite numbers and refuse the row otherwise")

    # battle_body_displacement: Hex/Lit FLAG displacement, masked by the mesh's baked COLOR_0.r
    require('internal const string FlagDisplacementKeyword = "HEX_VERTEX_DISPLACEMENT_FLAG";' in fx,
            "FlagDisplacementKeyword must be HEX_VERTEX_DISPLACEMENT_FLAG")
    disp = method_body(fx, "internal static void TryApplyBodyDisplacement(")
    require("HasVertexAttribute(VertexAttribute.Color)" in disp,
            "TryApplyBodyDisplacement must refuse a mesh without a vertex colour stream (the whole body would wave)")
    require("EnableKeyword(FlagDisplacementKeyword)" in disp and "MaterialHasKeyword(material, FlagDisplacementKeyword)" in disp
            and 'GetFloat("_VertexDisplacementType")' in disp,
            "TryApplyBodyDisplacement must enable the FLAG keyword and read back keyword and displacement type")
    m = re.search(r"Homm3MeshFx\.TryApplyBodyEmission\(fallback, entry, lane, log\);\s*(//[^\n]*\n\s*)*"
                  r"Homm3MeshFx\.TryApplyBodyDisplacement\(fallback, skin, entry, lane, log\);", iv)
    require(m is not None, "Homm3ImportVisuals must call TryApplyBodyDisplacement(fallback, skin, ...) right after "
                           "TryApplyBodyEmission in the Hex/Lit rebind")

    # battle_body_overlay: native material appended from LateUpdate only, with readback
    overlay = method_body(fx, "private static bool EnsureOverlayMaterial(")
    require("TryLoadNativeResManagerGameObjectIl2Cpp" in overlay and "new Material(" in overlay,
            "EnsureOverlayMaterial must load through the Il2Cpp ResManager loader and append a private copy")
    tick_overlay = method_body(fx, "private static void TickOverlaySlot(")
    require("EnsureOverlayMaterial(" in tick_overlay and "LoadFailed = true" in tick_overlay,
            "TickOverlaySlot (LateUpdate) owns the overlay load and fails the row closed")
    set_overlay = method_body(fx, "private static bool SetOverlay(")
    require("var readback = skin.sharedMaterials;" in set_overlay and "IsFxDescendant(" in set_overlay,
            "SetOverlay must read sharedMaterials back and skip effect renderers")
    require(fx.count("EnsureOverlayMaterial(") == 2, "EnsureOverlayMaterial must be called only from TickOverlaySlot")
    # bodyOverlay tint (source.colors): parsed fail-closed, written to the private copy only, each property required
    # and read back before the overlay is appended
    require("ApplyOverlayTint(copy, row, log)" in overlay and overlay.index("new Material(") < overlay.index("ApplyOverlayTint(")
            and overlay.index("ApplyOverlayTint(") < overlay.index("slot.OverlayMaterial = copy;"),
            "EnsureOverlayMaterial must tint the private copy before it becomes the slot's overlay")
    tint = method_body(fx, "private static bool ApplyOverlayTint(")
    require("HasProperty(property)" in tint and "GetColor(property)" in tint and "return false;" in tint,
            "ApplyOverlayTint must require each property and read each colour back")
    parse_tint = method_body(fx, "private static bool TryReadOverlayTint(")
    require('"property"' in parse_tint and '"rgba"' in parse_tint and "float.IsNaN" in parse_tint
            and "16f" in parse_tint and "Array.IndexOf(properties, property) < 0" in parse_tint,
            "TryReadOverlayTint must refuse repeated, non-finite or out-of-range tint colours")
    require('TryReadOverlayTint(source["colors"]' in method_body(fx, "private static bool TryParseOverlayRow("),
            "battle_body_overlay rows must parse source.colors through TryReadOverlayTint")

    csproj = (PLUGIN / "OfflineUnlockMod.csproj").read_text(encoding="utf-8")
    require('Include="UnityEngine.ParticleSystemModule"' in csproj, "csproj must reference UnityEngine.ParticleSystemModule")
    require("validate_homm3_vanilla_style_fx_contract.py" in csproj, "csproj must run this validator before build")


def check_pending_draft_boundary(vs) -> None:
    import promote_vanilla_style as promote  # noqa: E402

    if not vs.PENDING_SHIP_LANES:
        return
    sources = vs.load(vs.SOURCES)["sources"]
    for unit, (_, spec) in vs.specs(drafts=True).items():
        if not vs.pending_lanes(spec):
            continue
        for action, run in (
            ("shipped validation", lambda: vs.check_spec(unit, spec, sources)),
            ("plan", lambda: vs.cmd_plan(unit)),
            ("promotion", lambda: promote.dry_run(unit, unit)),
        ):
            try:
                run()
            except (vs.VsError, promote.PromoteError) as ex:
                require("no end-to-end" in str(ex),
                        f"{unit}: {action} refused for the wrong reason: {ex}")
            else:
                fail(f"{unit}: {action} accepted a draft with an undeliverable layer")


SHIP_PROOF_SCHEMA = "homm3_displacement_ship_proof.v1"


def check_displacement_ship_lane(vs) -> None:
    """bodyDisplacement ships end to end: the ship step bakes and delivers displacementMaskGlb, reads the colour stream
    back out of the built bundle, and a committed candidate proof records one unit's compile -> lab -> bundle ->
    install chain. While the lane is pending the proof is not required (check_pending_draft_boundary holds it)."""
    ship = vs.SHIP_STEP.read_text(encoding="utf-8")
    for marker, why in (
            ("def displacement_mask_glb(", "bake/verify of the COLOR_0 mask GLB"),
            ('stamp["sourceGlbSha256"] != row["frozen"]["idleRetimedGlbSha256"]', "the bake must chain to the frozen GLB"),
            ('plan["displacementMaskGlb"] = dm', "prepare must record the mask GLB in the vfx plan"),
            ('"masterGlb": str(master.resolve())', "the lab must build from the mask GLB"),
            ("def displacement_probe(", "bundle colour-stream readback"),
            ("def require_displacement_compiled(", "compiled record must pin the shipped mask")):
        require(marker in ship, f"ship step lacks {marker!r} ({why})")
    require(ship.count("require_displacement_compiled(rows, out)") == 2,
            "the bundles and deploy stages must both call require_displacement_compiled")
    require('"displacementProbe"' in ship and "rerun probe" in ship,
            "deploy must refuse a displacement row without the bundle colour-stream readback")
    probe = (ROOT / "tools/homm3_import/unity_editor/ProbeDisplacementMaskBundles.cs").read_text(encoding="utf-8")
    require("HasVertexAttribute(VertexAttribute.Color)" in probe and "mesh.colors" in probe,
            "ProbeDisplacementMaskBundles must check the colour stream and read COLOR.r back")
    if "bodyDisplacement" in vs.PENDING_SHIP_LANES:
        return
    path = vs.DISPLACEMENT_SHIP_PROOF
    require(path.is_file(), f"bodyDisplacement is no longer pending but {path.name} (candidate ship proof) is missing")
    proof = vs.load(path)
    require(proof.get("schema") == SHIP_PROOF_SCHEMA, f"{path.name}: schema must be {SHIP_PROOF_SCHEMA}")
    unit = proof.get("unit")
    rec_path = vs.COMPILED_DIR / f"{unit}.json"
    require(rec_path.is_file(), f"{path.name}: candidate {unit} has no compiled record")
    bakes = vs.load(rec_path).get("displacementBake") or {}
    mask = proof.get("maskGlbSha256")
    require(any(b.get("outGlbSha256") == mask for b in bakes.values()),
            f"{path.name}: maskGlbSha256 is not the candidate's compiled displacementBake")
    probe_rec = proof.get("bundleProbe") or {}
    require(probe_rec.get("vertexColors") is True and probe_rec.get("ok") is True
            and isinstance(probe_rec.get("maskMean"), (int, float)) and probe_rec.get("maskMax", 0) > 0,
            f"{path.name}: bundle probe must show a non-zero colour stream")
    inst = proof.get("installed") or {}
    require(inst.get("bundleSha256") and inst.get("bundleSha256") == proof.get("bundleSha256"),
            f"{path.name}: installed readback must equal the probed bundle")


def check_displacement_inputs(vs) -> None:
    import displacement_mask_bake as bake  # noqa: E402

    rule = {"rule": "boneWeights", "bones": ["Spine1"], "lo": 0.2, "hi": 0.8}
    layer = {"id": "flow", "type": "bodyDisplacement", "mask": rule,
             "direction": [1.0, 0.0, 0.0], "power": [0.01, 0.0, 0.0], "speed": 1.0}
    bake.check_rule(rule)
    bake.check_rule({"rule": "heightBand", "lo": 0.2, "hi": 0.8})
    bake.check_rule({"rule": "region", "center": [0.5, 0.5, 0.5], "radius": 0.2, "falloff": 0.1})
    vs.check_displacement_layer(layer, "contract/flow")
    for bad in ({**rule, "radius": 0.2}, {**rule, "gain": math.nan},
                {**rule, "lo": True}, {**rule, "hi": math.inf},
                {"rule": "heightBand", "lo": 0.2, "hi": 0.8, "bones": ["Spine1"]},
                {"rule": "region", "center": [0.5, 0.5, 0.5], "radius": 0.2,
                 "falloff": 0.1, "hi": 0.8}):
        try:
            bake.check_rule(bad)
        except bake.BakeError:
            pass
        else:
            fail(f"displacement mask accepted invalid rule {bad}")
    for key, value in (("unused", 1), ("direction", [0, 0, 0]),
                       ("power", [math.nan, 0, 0]), ("speed", math.inf),
                       ("speed", True)):
        bad = copy.deepcopy(layer)
        bad[key] = value
        try:
            vs.check_displacement_layer(bad, "contract/flow")
        except vs.VsError:
            pass
        else:
            fail(f"displacement layer accepted invalid {key}={value}")


def check_overlay_tint_inputs(vs) -> None:
    """The bodyOverlay tint data: every draft and shipped tint is on an allowed shader property, and bad tints refuse."""
    require(vs.OVERLAY_TINT_PROPERTIES.get("magic/Fresnel") == ("_Color", "_EdgeColor"),
            "magic/Fresnel tint properties changed without re-reading its DXBC (Homm3VfxFresnelReplica)")
    sources = vs.load(vs.SOURCES)["sources"]
    tinted = []
    for drafts in (False, True):
        for unit, (_, spec) in vs.specs(drafts=drafts).items():
            for layer in spec["layers"]:
                if layer["type"] == "bodyOverlay" and "colors" in layer:
                    try:
                        vs.check_overlay_layer(layer, sources, f"{unit}/{layer['id']}")
                    except vs.VsError as ex:
                        fail(f"tint data: {ex}")
                    tinted.append(unit)
    for unit in ("h3_psychic_elemental", "h3_magic_elemental"):
        require(unit in tinted, f"{unit}: its Flicker Fresnel rim must carry a tint (the vanilla green is off-palette)")
    good = [{"property": "_Color", "rgba": [2.6, 0.5, 1.6, 1.0]}]
    vs.check_overlay_tint(good, "magic/Fresnel", "contract/tint")
    for bad, shader in (([{"property": "_Tint", "rgba": [1, 1, 1, 1]}], "magic/Fresnel"),
                        (good + good, "magic/Fresnel"),
                        ([{"property": "_Color", "rgba": [1, 1, 1]}], "magic/Fresnel"),
                        ([{"property": "_Color", "rgba": [1, math.nan, 1, 1]}], "magic/Fresnel"),
                        ([{"property": "_Color", "rgba": [1, 17, 1, 1]}], "magic/Fresnel"),
                        ([{"property": "_Color", "rgba": [1, -0.1, 1, 1]}], "magic/Fresnel"),
                        ([{"property": "_Color", "rgba": [1, True, 1, 1]}], "magic/Fresnel"),
                        ([{"property": "_Color", "rgba": [1, 1, 1, 1], "gain": 2}], "magic/Fresnel"),
                        ([], "magic/Fresnel"),
                        (good, "magic/VfxUber")):
        try:
            vs.check_overlay_tint(bad, shader, "contract/tint")
        except vs.VsError:
            pass
        else:
            fail(f"overlay tint accepted invalid {bad} on {shader}")
    compiler = (ROOT / "tools" / "homm3_vfx" / "vanilla_style_fx.py").read_text(encoding="utf-8")
    require('**({"colors": [{"property": c["property"]' in compiler,
            "the compiler must carry a bodyOverlay tint into the row's source.colors")


def check_multiply_recolor(vs) -> None:
    """recolorMode multiply: a gradient-only darkening for materials without _Color (the runtime then skips _Color)."""
    def node(color):
        return {"F": {"ps": {"scalingMode": 0, "startColor": {"mode": 0, "max": [1.0, 1.0, 1.0, 1.0]},
                             "colorOverLife": {"rgb": [[0.0, 1.0, 1.0, 1.0], [1.0, 1.0, 1.0, 1.0]],
                                               "alpha": [[0.0, 0.0], [1.0, 1.0]]},
                             "materials": [{"name": "m", "color": color}]}}}
    layer = {"source": {"keepNodes": ["F"]}, "recolor": [0.5, 0.4, 0.2], "recolorMode": "multiply"}
    facts = vs.runtime_ps_facts(layer, node(None), "contract/multiply")
    entry = facts["recolorNodes"][0]
    require(entry["materialColorMul"] == [1.0, 1.0, 1.0] and entry["gradient"]["color"][0][1:] == [0.5, 0.4, 0.2],
            "a multiply recolour must write only the gradient (materialColorMul 1: the runtime skips _Color)")
    for bad, color in (({**layer, "recolorMode": "luminance"}, None),      # no _Color needs multiply
                       (layer, [1.0, 1.0, 1.0, 1.0])):                     # multiply is only for no-_Color materials
        try:
            vs.runtime_ps_facts(bad, node(color), "contract/multiply")
        except vs.VsError:
            pass
        else:
            fail(f"recolour accepted {bad.get('recolorMode')} on a material with _Color={color}")
    fx = (PLUGIN / "Homm3MeshFx.cs").read_text(encoding="utf-8")
    body = method_body(fx, "private static void ApplyRecolor(")
    require(body.index("colorOverLifetime.color") < body.index("Mathf.Approximately(mul.x, 1f)")
            < body.index('HasProperty("_Color")'),
            "ApplyRecolor must write the gradient and return before requiring _Color when materialColorMul is 1 "
            "(recolorMode multiply depends on it)")


def check_bone_anchor(vs) -> None:
    """boneAnchor: an unknown bone or a malformed point fails closed; the compiler emits boneLocalPos per bone row."""
    bones = ["Head", "Neck"]
    vs.check_bone_anchor({"boneAnchor": {"Head": [0, 1.2, 0.5]}}, bones, "contract/anchor")
    vs.check_bone_anchor({}, bones, "contract/anchor")
    for bad in ({"Jaw": [0, 1, 0]}, {"Head": [0, 1]}, {"Head": [0, math.nan, 0]}, {"Head": [0, True, 0]},
                {"Head": "0,1,0"}, {}, [["Head", [0, 1, 0]]]):
        try:
            vs.check_bone_anchor({"boneAnchor": bad}, bones, "contract/anchor")
        except vs.VsError:
            pass
        else:
            fail(f"boneAnchor accepted {bad!r}")
    compiler = (ROOT / "tools" / "homm3_vfx" / "vanilla_style_fx.py").read_text(encoding="utf-8")
    require("check_bone_anchor(layer, bones, lw)" in compiler
            and "bone_vs = dict(vs, boneLocalPos=anchors[bone])" in compiler
            and '"vanillaStyle": bone_vs' in compiler,
            "the compiler must validate boneAnchor and carry boneLocalPos into each bone's own row")
    lab = (ROOT / "tools" / "homm3_vfx" / "vanilla_style_lab.py").read_text(encoding="utf-8")
    require('"pos": anchors.get(b, [0, 0, 0])' in lab and "VSF.bone_local_positions(" in lab,
            "the lab must render boneAnchor through the compiler's bone_local_positions")
    labcs = (ROOT / "tools" / "homm3_vfx" / "unity" / "Homm3VanillaStyleVfxLab.cs").read_text(encoding="utf-8")
    require("fx.bone.TransformPoint(V3(fx.def.pos, Vector3.zero)) - fx.anchor.position" in labcs,
            "the lab's anchorNode re-seat must target the boneAnchor point, like the runtime")


def check_draft_bones(vs) -> None:
    """check-drafts proves every layer bone on the unit's canonical GLB (delivered GLB for a delivery row, else the
    look-stamped GLB), fails closed on a missing bone, and names a unit it cannot check instead of passing it."""
    import json
    import struct
    import tempfile

    def glb(path: Path, joints: list[str]) -> None:
        doc = {"asset": {"version": "2.0"}, "nodes": [{"name": j} for j in joints],
               "skins": [{"joints": list(range(len(joints)))}]}
        js = json.dumps(doc).encode()
        js += b" " * (-len(js) % 4)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"glTF" + struct.pack("<II", 2, 20 + len(js)) + struct.pack("<I", len(js)) + b"JSON" + js)

    def layer(bones):
        return {"schema": vs.SPEC_SCHEMA, "layers": [{"id": "fx", "type": "vanillaParticles", "bones": bones}]}

    saved = (vs.LOOK_OUT, vs.LOOK_GLB)
    with tempfile.TemporaryDirectory(prefix="vsfx_contract_bones_", dir=ROOT / "artifacts") as tmp:
        t = Path(tmp)
        vs.LOOK_OUT, vs.LOOK_GLB = t / "look", t / "retarget"
        try:
            unit = "contract_eye"
            legs = ["Root", "Spine1", "LeftToeBase", "RightToeBase"]
            # no delivery row and no look stamp: reported, not passed
            g, why = vs.draft_skeleton(unit, {"delivery": {"selection": str(t / "none.json")}})
            require(g is None and "no look stamp" in why, f"draft_skeleton must report a unit with no GLB: {why}")
            # look stamp without its GLB: reported
            (t / "look" / unit).mkdir(parents=True)
            (t / "look" / unit / "stamp.json").write_text("{}")
            g, why = vs.draft_skeleton(unit, {})
            require(g is None and "no look GLB" in why, f"draft_skeleton must report a stamp without its GLB: {why}")
            # look stamp + GLB: that GLB; a bone it lacks fails closed (evil eye / fargazer LeftHand, 2026-09-28)
            glb(t / "retarget" / unit / f"{unit}_def_retarget.glb", legs)
            g, why = vs.draft_skeleton(unit, {})
            require(g is not None and why == "look", f"draft_skeleton must resolve the look-stamped GLB: {why}")
            vs.check_bones_on_glb(unit, layer(["LeftToeBase", "RightToeBase"]), g)
            try:
                vs.check_bones_on_glb(unit, layer(["LeftHand", "RightToeBase"]), g)
            except vs.VsError as ex:
                require("LeftHand" in str(ex), f"missing-bone failure must name the bone: {ex}")
            else:
                fail("check_bones_on_glb accepted a bone the GLB lacks")
            # a delivery row wins over the look GLB; its unbuilt delivered GLB is reported, never swapped for the look's
            sel = t / "sel.json"
            sel.write_text(json.dumps({"out": str(t / "out"), "units": [{"labSid": unit}]}))
            g, why = vs.draft_skeleton(unit, {"delivery": {"selection": str(sel)}})
            require(g is None and "delivered GLB" in why, f"an unbuilt delivered GLB must be reported: {why}")
            glb(t / "out" / unit / "delivered_idle_retimed.glb", legs + ["LeftHand"])
            g, why = vs.draft_skeleton(unit, {"delivery": {"selection": str(sel)}})
            require(g is not None and why == "delivery", f"a delivery row must resolve its delivered GLB: {why}")
            vs.check_bones_on_glb(unit, layer(["LeftHand"]), g)
        finally:
            vs.LOOK_OUT, vs.LOOK_GLB = saved
    compiler = (ROOT / "tools" / "homm3_vfx" / "vanilla_style_fx.py").read_text(encoding="utf-8")
    require("check_bones_on_glb(unit, spec, glb)" in compiler and "bones UNCHECKED for" in compiler,
            "check_drafts must check draft bones on the canonical GLB and report units it cannot check")


def main() -> int:
    import vanilla_style_fx as vs  # noqa: E402

    require(vs.SHIP_STEP.is_file(), f"vanilla_style_fx.SHIP_STEP does not resolve to the delivery ship script: {vs.SHIP_STEP}")
    try:
        units = vs.check()
    except vs.VsError as ex:
        fail(str(ex))
    check_pending_draft_boundary(vs)
    check_displacement_ship_lane(vs)
    check_displacement_inputs(vs)
    check_overlay_tint_inputs(vs)
    check_multiply_recolor(vs)
    check_bone_anchor(vs)
    check_draft_bones(vs)
    check_runtime_source()
    print(f"homm3-vanilla-style-fx-contract: ok units={','.join(units)} "
          "proof=source/static + generated artifact; in-combat look unproven")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
