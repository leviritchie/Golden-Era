"""Vanilla-style unit effects: the emissionMap and vanillaParticles layer types (docs/olden_era_vanilla_vfx_style.md).

    python tools/homm3_vfx/vanilla_style_fx.py sources            # static read of the installed game (UnityPy)
    python tools/homm3_vfx/vanilla_style_fx.py compile [--unit U]  # needs the unit's def_retarget delivery artifacts
    python tools/homm3_vfx/vanilla_style_fx.py check               # committed data only (the build validator's core)
    python tools/homm3_vfx/vanilla_style_fx.py check-drafts        # drafts: spec validity against the probed sources
                                                                   # and every layer bone on the unit's canonical GLB
    python tools/homm3_vfx/vanilla_style_fx.py plan --unit U       # draft dry run on the unit's frozen unit_look row

Drafts (tools/homm3_vfx/vanilla_style/drafts/<unit>.json, same schema) are redesigns for units whose active delivery
row still ships the unit-look layers. They are never compiled into the catalog and ``check`` ignores them (it would
refuse the unit's own selection row); ``check-drafts`` proves them against the probed sources and ``plan`` resolves
their bones, clips, windows and stock states against the frozen selection row without writing anything. Promotion
(done at freeze): move the draft to units/, flip the selection row to vfxAuthority vanilla_style, then ``compile``.

A unit's spec lives in tools/homm3_vfx/vanilla_style/units/<unit>.json (schema homm3_vanilla_style_fx.v1). It
replaces the unit-look layers it names under ``supersedes.lookLayers`` (uvAtlas stepped glow, defFlipbook sprite
sheets, effectLight steady lights, volumetricFire, event): steady glow becomes a Hex/Lit emission map, motion becomes
the game's own ParticleSystems cloned from vanilla prefabs, and lights only flash from those particles' Lights modules.
An ``event`` layer (hideMesh / missile) is superseded by the native engine behaviour its reason names (the Core view's
no-corpse death fade, the Core view's projectile), never deferred.

Layer types:

  emissionMap       one per unit. ``mask.rule`` derives the emission texture from the delivered base colour (and,
                    for ``funnel_helix``, the delivered mesh). The runtime (Homm3MeshFx, lane battle_emission) loads
                    the PNG from the plugin folder and enables HEX_EMISSION_MAP_ENABLED on the unit's Hex/Lit body
                    material with ``color`` (HDR) and the blink values.
  bodyDisplacement  at most one per unit. Hex/Lit FLAG vertex displacement of the body (lane battle_body_displacement):
                    ``mask`` is a displacement_mask_bake.py rule (boneWeights / heightBand / region) baked into the
                    delivered GLB's COLOR_0.r, and ``direction`` / ``power`` (xyz) / ``speed`` drive
                    posWS += power * sin(dot(posWS, direction) + t * speed) * COLOR.r. The baked GLB and its stamp land
                    in artifacts/vanilla_vfx_style/displacement/<unit>/; the ship step must deliver that GLB.
  bodyOverlay       a vanilla prefab renderer's material (``source.resPath`` + ``rendererPath`` + ``materialIndex``)
                    appended to the owned body SkinnedMeshRenderer (lane battle_body_overlay), with one ``always`` or
                    window trigger, as BhBattleTimelineHelper.AppendMaterial does for vanilla units. Optional
                    ``colors`` [{property, rgba}] tints the private copy (OVERLAY_TINT_PROPERTIES per shader, e.g.
                    magic/Fresnel _Color/_EdgeColor); the plugin requires each property and reads it back.
  vanillaParticles  a child of a vanilla ResManager prefab (``source.resPath`` + ``source.childPath``), cloned under
                    each named bone, with only ``keepNodes`` ParticleSystems emitting, and overrides: world
                    ``scale`` (lab units: the unit's unscaled GLB space), ``rateMul``, ``recolor`` (luminance kept;
                    ``recolorMode: "multiply"`` darkens the colour-over-lifetime gradient instead, the only recolour
                    of a material without _Color such as every vanilla feather), ``loop``, ``zeroChildPositions``, ``orient`` (bone / emitUp / body + bodyYawDeg),
                    ``anchorNode``, ``alignToReach`` (orient bone or emitUp, one bone: the source-root-local axis turned onto
                    the direction from that bone to the skin it rigidly owns, e.g. a held blade; compiled to
                    ``boneLocalRot``), ``boneAnchor`` ({bone: [x, y, z]}: the rest-pose GLB mesh-space point the clone
                    root sits at instead of that joint, e.g. a muzzle in front of a Head joint buried in the skull;
                    every key must be one of the layer's bones; compiled per bone through the skin's inverse bind
                    matrix to ``boneLocalPos``). ``triggers`` are ``always`` or DEF-key windows on a clip; key k opens at
                    (k + 0.5) / 12 s of the source clip (the idle through the delivered idle retime), divided by the
                    delivered clip length, on every animator state the stock controller maps to that clip.

``compile`` writes the emission PNGs into OfflineUnlockMod/homm3_mesh_fx/emission/, replaces the unit's rows in
homm3_mesh_fx/catalog.json (origin ``vanilla_style:<unit>``) and records every input hash in
tools/homm3_vfx/vanilla_style/compiled/<unit>.json. ``check`` proves the committed catalog, PNGs and records still
agree with the specs and the probed vanilla sources, and that no active def_retarget selection still delivers a
superseded layer for the unit.

A layer type compiles only once its end-to-end lane exists (RUNTIME_LANES: the plugin lane constant, and for
bodyDisplacement the ship step's ``displacementMaskGlb`` delivery of the baked GLB). A lane stays in
PENDING_SHIP_LANES until a candidate unit has shipped it end to end; bodyDisplacement's proof is
tools/homm3_vfx/vanilla_style/displacement_ship_proof.json (tools/validate_homm3_vanilla_style_fx_contract.py). A
draft may carry a lane-pending layer (it is a lab design, never compiled); ``plan`` and promotion refuse it
(``pending_lanes``).

bodyDisplacement ordering: the ship prepare stage bakes the mask into the delivery's own
``delivered_idle_retimed.color0.glb`` and the lab builds from it, so the lab report's master is that bake;
``delivery_facts`` accepts it only when its stamp chains to the frozen idle-retimed GLB. ``compile`` bakes the same
rule from the same GLB (the bake is deterministic) and the ship bundles/deploy stages require the two shas to agree.

Proof tier: generated artifact. Nothing here proves how the effects look in game.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VS_DIR = ROOT / "tools/homm3_vfx/vanilla_style"
SPEC_DIR = VS_DIR / "units"
DRAFT_DIR = VS_DIR / "drafts"
SOURCES = VS_DIR / "vanilla_sources.json"
COMPILED_DIR = VS_DIR / "compiled"
PLUGIN = ROOT / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod"
CATALOG = PLUGIN / "homm3_mesh_fx/catalog.json"
EMISSION_DIR = PLUGIN / "homm3_mesh_fx/emission"
LOOK_SPECS = ROOT / "tools/homm3_unit_look/units"
SELECTIONS = ROOT / "tools/homm3_def_retarget_delivery"

SPEC_SCHEMA = "homm3_vanilla_style_fx.v1"
SOURCES_SCHEMA = "homm3_vanilla_style_sources.v1"
COMPILED_SCHEMA = "homm3_vanilla_style_compiled.v1"
ORIGIN_PREFIX = "vanilla_style:"
LAYER_TYPES = ("emissionMap", "vanillaParticles", "bodyDisplacement", "bodyOverlay")
SOURCE_TYPES = ("vanillaParticles", "bodyOverlay")  # layer types that read a probed vanilla prefab
DISPLACEMENT_DIR = ROOT / "artifacts/vanilla_vfx_style/displacement"
MESH_FX_CS = PLUGIN / "Homm3MeshFx.cs"
SHIP_STEP = ROOT / "tools/homm3_def_retarget_delivery/ship_def_retarget_slice.py"
# Source markers are necessary but not sufficient. A displacement row also needs
# ship-step artifact/readback proof before PENDING_SHIP_LANES can be cleared.
RUNTIME_LANES = {
    "bodyDisplacement": ((MESH_FX_CS, 'LaneBattleBodyDisplacement = "battle_body_displacement"'),
                         (SHIP_STEP, "displacementMaskGlb")),
    "bodyOverlay": ((MESH_FX_CS, 'LaneBattleBodyOverlay = "battle_body_overlay"'),),
}
PENDING_SHIP_LANES: set[str] = set()
DISPLACEMENT_SHIP_PROOF = VS_DIR / "displacement_ship_proof.json"
# unit-look layer types a vanilla-style unit must supersede: none of them may ship beside it
SUPERSEDED_TYPES = ("uvAtlas", "defFlipbook", "effectLight", "volumetricFire", "event")
MASK_RULES = ("warm_luminance", "luminance", "funnel_helix", "hot_chroma")
ORIENTS = ("bone", "emitUp", "body")
# follow: "bone" rides the socket; "release" detaches at each window start so a burst stays where it was emitted.
FOLLOWS = ("bone", "release")
FPS = 12.0
LUMA = (0.2126, 0.7152, 0.0722)


class VsError(Exception):
    pass


def load(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def dump(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical_sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def rel(path: Path) -> str:
    return Path(path).resolve().relative_to(ROOT.resolve()).as_posix()


def specs(drafts: bool = False) -> dict[str, tuple[Path, dict]]:
    out = {}
    for p in sorted((DRAFT_DIR if drafts else SPEC_DIR).glob("*.json")):
        s = load(p)
        unit = s.get("unit")
        if p.stem != unit:
            raise VsError(f"{p.name}: file name must be the unit sid ({unit})")
        out[unit] = (p, s)
    return out


# ------------------------------------------------------------------ vanilla sources (static read of the install)
def flatten(tree: dict, mats: dict | None = None) -> list[dict]:
    rows = []
    mats = mats or {}

    def walk(node, path, parent_active):
        comps = {c["type"]: c for c in node["components"]}
        ps = "ParticleSystem" in comps
        rend = comps.get("ParticleSystemRenderer")
        psc = comps.get("ParticleSystem") or {}
        facts = None
        if ps:
            mat_colors = []
            for pid in (rend or {}).get("materials", []):
                mi = mats.get(pid) if pid else None
                mat_colors.append({"name": mi.get("name"), "shader": mi.get("shader"),
                                   "color": (mi.get("colors") or {}).get("_Color")} if mi else None)
            # Facts the runtime cannot read back through the stripped interop (MainModule has no
            # scalingMode/startColor accessors, ColorOverLifetime has no getter): compile bakes them.
            facts = {"scalingMode": psc.get("scalingMode"), "looping": psc.get("looping"),
                     "playOnAwake": psc.get("playOnAwake"), "startColor": psc.get("startColor"),
                     "colorOverLife": psc.get("colorOverLife"), "materials": mat_colors}
        mesh = comps.get("SkinnedMeshRenderer") or comps.get("MeshRenderer")
        mesh_mats = None
        if mesh and not ps:
            mesh_mats = []
            for pid in mesh.get("materials", []):
                mi = mats.get(pid) if pid else None
                mesh_mats.append({"name": mi.get("name"), "shader": mi.get("shader")} if mi else None)
        scripts = sorted(c.get("script") or "?" for c in node["components"] if c["type"] == "MonoBehaviour")
        rows.append({"path": path, "active": bool(node["active"]), "activeInHierarchy": bool(node["active"]) and parent_active,
                     "particleSystem": ps, "rendererMaterials": len([m for m in (rend or {}).get("materials", []) if m]),
                     "light": "Light" in comps, "director": "PlayableDirector" in comps, "animator": "Animator" in comps,
                     "scripts": scripts, **({"ps": facts} if facts else {}),
                     **({"meshMaterials": mesh_mats} if mesh_mats is not None else {})})
        for ch in node["children"]:
            walk(ch, f"{path}/{ch['name']}" if path else ch["name"], bool(node["active"]) and parent_active)
    walk(tree, "", True)
    return rows


def cmd_sources(extra: list[str]) -> None:
    sys.path.insert(0, str(ROOT / "tools/homm3_vfx"))
    import vanilla_vfx_probe as probe  # noqa: E402  (UnityPy; read-only)
    every = list(specs().values()) + list(specs(drafts=True).values())
    paths = sorted({l["source"]["resPath"] for _, s in every for l in s["layers"] if l["type"] in SOURCE_TYPES}
                   | set(extra))
    out = {"schema": SOURCES_SCHEMA, "game": probe.GAME,
           "proof": "static read of installed serialized assets (tools/homm3_vfx/vanilla_vfx_probe.py); not runtime",
           "sources": {}}
    for p in paths:
        res = [r for r in probe.probe(p) if r["type"] == "GameObject"]
        if len(res) != 1:
            raise VsError(f"{p}: expected one GameObject in the ResourceManager container, got {len(res)}")
        out["sources"][p] = {"root": res[0]["tree"]["name"], "nodes": flatten(res[0]["tree"], res[0].get("materials"))}
    dump(SOURCES, out)
    print(f"sources: {len(paths)} prefab(s) -> {rel(SOURCES)}")


# ------------------------------------------------------------------ spec validation (shared by compile and check)
def resolve_child(source: dict, child: str, where: str) -> str:
    paths = [n["path"] for n in source["nodes"]]
    if child in paths:
        return child
    hits = [p for p in paths if p.rsplit("/", 1)[-1] == child]
    if len(hits) != 1:
        raise VsError(f"{where}: childPath {child!r} resolves to {len(hits)} nodes; give the full path")
    return hits[0]


def subtree(source: dict, child_full: str) -> dict[str, dict]:
    """Relative path -> node; with same-named siblings the FIRST one in serialized order wins (as Transform.Find)."""
    pre = child_full + "/"
    out: dict[str, dict] = {}
    for n in source["nodes"]:
        if n["path"] == child_full or n["path"].startswith(pre):
            out.setdefault(n["path"][len(pre):] if n["path"] != child_full else "", n)
    return out



def unit_sources_sha(spec: dict, sources: dict) -> str:
    """Hash of only the probed prefabs this spec reads: adding a source for another unit never stales this one."""
    used = sorted({l["source"]["resPath"] for l in spec["layers"] if l["type"] in SOURCE_TYPES})
    return canonical_sha({p: sources[p] for p in used})


def rec_color(rgb, target):
    """Luminance-preserving recolour (the lab's rule): rgb -> lum(rgb) * target / lum(target)."""
    lt = sum(a * b for a, b in zip(LUMA, target))
    lum = sum(a * b for a, b in zip(LUMA, rgb[:3]))
    return [lum * t / lt for t in target]


REACH_MIN_VERTICES = 50


def bone_reach_axis(glb_path: Path, bone: str) -> list[float]:
    """Unit direction, in the bone's Unity-local frame (glTFast flips glTF x), from the joint to the farthest fifth
    of the skin it rigidly owns (weight > 0.6): a held blade's axis. Fails closed when the bone owns too little."""
    import numpy as np
    from glb_io import Glb  # noqa: E402
    g = Glb(glb_path)
    skin = g.json["skins"][0]
    names = [g.json["nodes"][j]["name"] for j in skin["joints"]]
    if bone not in names:
        raise VsError(f"{bone}: not a joint of {glb_path.name}")
    bi = names.index(bone)
    ibm = g.accessor(skin["inverseBindMatrices"]).astype(np.float64)[bi].reshape(4, 4).T
    pts = []
    for mesh in g.json["meshes"]:
        for prim in mesh["primitives"]:
            at = prim["attributes"]
            if "JOINTS_0" not in at:
                continue
            P = g.accessor(at["POSITION"]).astype(np.float64)
            J = g.accessor(at["JOINTS_0"]).astype(np.int64)
            wa = g.json["accessors"][at["WEIGHTS_0"]]
            W = g.accessor(at["WEIGHTS_0"]).astype(np.float64)
            if wa["componentType"] != 5126:
                W /= 255.0 if wa["componentType"] == 5121 else 65535.0
            pts.append(P[np.where(J == bi, W, 0.0).sum(1) > 0.6])
    P = np.concatenate(pts) if pts else np.zeros((0, 3))
    if len(P) < REACH_MIN_VERTICES:
        raise VsError(f"{bone}: owns {len(P)} rigid vertices (< {REACH_MIN_VERTICES}); no reach to align to")
    L = (ibm @ np.c_[P, np.ones(len(P))].T).T[:, :3]
    d = np.linalg.norm(L, axis=1)
    u = L[d >= np.percentile(d, 80)].mean(0)
    u[0] = -u[0]
    return [round(float(v), 5) for v in u / np.linalg.norm(u)]


BONE_ANCHOR_MAX = 100.0


def bone_local_point(glb_path: Path, bone: str, point) -> list[float]:
    """A rest-pose mesh-space point in the bone's Unity-local frame (glTFast flips glTF x): the inverse bind matrix
    takes the point to the joint's frame, where it then rides the bone. Fails closed on an unknown joint."""
    import numpy as np
    from glb_io import Glb  # noqa: E402
    g = Glb(glb_path)
    skin = g.json["skins"][0]
    names = [g.json["nodes"][j]["name"] for j in skin["joints"]]
    if bone not in names:
        raise VsError(f"{bone}: not a joint of {glb_path.name}")
    ibm = g.accessor(skin["inverseBindMatrices"]).astype(np.float64)[names.index(bone)].reshape(4, 4).T
    u = (ibm @ np.array([float(point[0]), float(point[1]), float(point[2]), 1.0]))[:3]
    u[0] = -u[0]
    if not np.all(np.isfinite(u)) or np.abs(u).max() > BONE_ANCHOR_MAX:
        raise VsError(f"{bone}: boneAnchor {list(point)} lands at {u.tolist()} in the bone frame (not finite or "
                      f"beyond {BONE_ANCHOR_MAX})")
    return [round(float(v), 6) for v in u]


def check_bone_anchor(layer: dict, bones: list, lw: str) -> None:
    """boneAnchor keys are the layer's own bones (an unknown bone fails closed), values finite [x, y, z]."""
    if "boneAnchor" not in layer:
        return
    ba = layer["boneAnchor"]
    if not isinstance(ba, dict) or not ba:
        raise VsError(f"{lw}: boneAnchor must be a non-empty {{bone: [x, y, z]}} map")
    for b, pt in ba.items():
        if b not in bones:
            raise VsError(f"{lw}: boneAnchor names {b!r}, which is not one of the layer's bones {bones}")
        if not (isinstance(pt, list) and len(pt) == 3
                and all(isinstance(c, (int, float)) and not isinstance(c, bool) and math.isfinite(c) for c in pt)):
            raise VsError(f"{lw}: boneAnchor[{b!r}] must be a rest-pose mesh-space point [x, y, z]")


LOOK_OUT = ROOT / "artifacts/homm3_unit_look"          # look.py stamps: <unit>/stamp.json (tools/homm3_unit_look/spec.py)
LOOK_GLB = ROOT / "artifacts/homm3_def_retarget"       # the look's canonical GLB: <unit>/<unit>_def_retarget.glb


def glb_joint_names(glb_path: Path) -> list[str]:
    """Skin joint names of a GLB, read from its JSON chunk only (a unit GLB is ~50 MB of buffers)."""
    import struct
    with open(glb_path, "rb") as f:
        head = f.read(20)
        if len(head) < 20 or head[:4] != b"glTF" or head[16:20] != b"JSON":
            raise VsError(f"{rel(glb_path)}: not a binary glTF with a leading JSON chunk")
        doc = json.loads(f.read(struct.unpack("<I", head[12:16])[0]))
    skins = doc.get("skins") or []
    if not skins:
        raise VsError(f"{rel(glb_path)}: has no skin (no joints to attach effects to)")
    return [doc["nodes"][j].get("name", "") for j in skins[0]["joints"]]


def draft_skeleton(unit: str, spec: dict) -> tuple[Path | None, str]:
    """The canonical GLB a draft's bones must exist on, or (None, why not).

    A delivery row for the unit in spec.delivery.selection -> that row's delivered_idle_retimed.glb (what compile
    reads); no row -> the unit-look GLB its look stamp was applied to (what the lab renders). A row whose delivered GLB
    is not on this machine, or a unit with neither, is reported, never silently passed and never swapped for the other
    GLB."""
    sel_name = (spec.get("delivery") or {}).get("selection")
    sel_path = ROOT / sel_name if sel_name else None
    if sel_path is not None and sel_path.is_file():
        selection = load(sel_path)
        row = next((r for r in selection.get("units", []) if r.get("labSid") == unit), None)
        if row is not None:
            glb = (ROOT / selection["out"]).resolve() / unit / "delivered_idle_retimed.glb"
            if not glb.is_file():
                return None, f"delivery row in {rel(sel_path)} but its delivered GLB {glb.name} is not built here"
            return glb, "delivery"
    stamp = LOOK_OUT / unit / "stamp.json"
    glb = LOOK_GLB / unit / f"{unit}_def_retarget.glb"
    if not stamp.is_file():
        return None, f"no delivery row in {sel_name or '(no delivery.selection)'} and no look stamp {rel(stamp)}"
    if not glb.is_file():
        return None, f"look stamp {rel(stamp)} but no look GLB {rel(glb)}"
    return glb, "look"


def check_bones_on_glb(unit: str, spec: dict, glb: Path) -> None:
    """Every bone a layer names is a skin joint of the unit's canonical GLB (fails closed: the lab and the runtime
    both refuse a missing bone, so a draft naming one is broken, not optional)."""
    joints = set(glb_joint_names(glb))
    for layer in spec["layers"]:
        missing = [b for b in layer.get("bones") or [] if b not in joints]
        if missing:
            raise VsError(f"vanilla_style/{unit}/{layer['id']}: bone(s) {missing} are not joints of {rel(glb)} "
                          f"(joints: {sorted(joints)})")


def bone_local_positions(glb_path: Path, layer: dict) -> dict[str, list[float]]:
    """boneLocalPos per anchored bone of a layer (vanilla_style_fx boneAnchor); bones without an anchor sit at 0."""
    return {b: bone_local_point(glb_path, b, pt) for b, pt in (layer.get("boneAnchor") or {}).items()}


def from_to_quat(a, b) -> list[float]:
    """Shortest-arc rotation (x, y, z, w) turning direction a onto direction b (Unity Quaternion.FromToRotation)."""
    na, nb = math.sqrt(sum(v * v for v in a)), math.sqrt(sum(v * v for v in b))
    a, b = [v / na for v in a], [v / nb for v in b]
    dot = sum(x * y for x, y in zip(a, b))
    if dot < -0.999999:
        axis = [0.0, -a[2], a[1]] if abs(a[0]) < 0.9 else [a[2], 0.0, -a[0]]
        n = math.sqrt(sum(v * v for v in axis))
        return [round(v / n, 6) for v in axis] + [0.0]
    cx = [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
    q = cx + [1.0 + dot]
    n = math.sqrt(sum(v * v for v in q))
    return [round(v / n, 6) for v in q]


def reach_rotation(glb_path: Path, layer: dict) -> list[float] | None:
    """boneLocalRot for an alignToReach layer: the source axis it names turned onto its one bone's skinned reach."""
    axis = layer.get("alignToReach")
    return None if axis is None else from_to_quat(axis, bone_reach_axis(glb_path, layer["bones"][0]))


def runtime_ps_facts(layer: dict, nodes: dict[str, dict], lw: str) -> dict:
    """What the plugin must do per kept node, from the static read, because the live interop is stripped.

    The live UnityEngine.ParticleSystemModule interop has no MainModule.scalingMode / startColor accessors and no
    ColorOverLifetime getter (checked 2026-09-26 against Golden Era BepInEx/interop), so the lab's
    `scalingMode = Hierarchy` and its start/over-life recolour cannot be done at runtime. Equivalents:
      * a Local-mode system uses only its own localScale, so the plugin sets that to the lossy scale the node
        would have under the hierarchy (``localScaleNodes``); Shape mode has no equivalent and is refused;
      * recolour writes a new colour-over-lifetime gradient (setter present) with the recoloured start colour
        folded in, and moves any channel above 1 into the renderer material's _Color (particle vertex colour is 8-bit);
        a system with colour-over-lifetime off is recoloured through _Color alone.
    """
    keep = layer["source"]["keepNodes"]
    local_nodes = []
    for k in keep:
        f = nodes[k].get("ps") or {}
        mode = f.get("scalingMode")
        if mode not in (0, 1):
            raise VsError(f"{lw}: keepNode {k!r} scalingMode {mode!r} (2 = Shape) has no runtime equivalent of the "
                          "lab's Hierarchy scaling; drop it")
        if mode == 1:
            local_nodes.append(k)
    for k in local_nodes:
        pre = (k + "/") if k else ""
        below = [d for d in keep if d != k and d.startswith(pre)]
        if below and not layer.get("zeroChildPositions"):
            raise VsError(f"{lw}: Local-mode keepNode {k!r} has kept descendants; its runtime rescale moves them "
                          "unless zeroChildPositions is set")
        hier = [d for d in below if (nodes[d].get("ps") or {}).get("scalingMode") == 0]
        if hier:
            raise VsError(f"{lw}: Hierarchy-mode keepNodes {hier} sit under Local-mode {k!r}, whose runtime rescale "
                          "would scale them twice")
    recolor_nodes = []
    target = layer.get("recolor")
    if target:
        for k in keep:
            f = nodes[k].get("ps") or {}
            sc = f.get("startColor") or {}
            if sc.get("mode") != 0:
                raise VsError(f"{lw}: recolour needs a constant start colour on {k!r} (mode {sc.get('mode')!r})")
            mats = f.get("materials") or []
            if len(mats) != 1 or not mats[0]:
                raise VsError(f"{lw}: recolour needs exactly one renderer material on {k!r}")
            # a material without _Color (every vanilla feather: magic/test/Disappearance_01 and friends) can only be
            # recoloured through the colour-over-lifetime gradient, as a plain multiply (recolorMode "multiply"): the
            # runtime skips the _Color multiply when materialColorMul is 1, and vertex colours cannot exceed 1
            gradient_only = mats[0].get("color") is None
            multiply = layer.get("recolorMode") == "multiply"
            col = f.get("colorOverLife")
            entry = {"node": k, "gradient": None, "materialColorMul": [1.0, 1.0, 1.0]}
            if gradient_only != multiply:
                raise VsError(f"{lw}: {k!r} " + ("material has no _Color: use recolorMode 'multiply'" if gradient_only
                                                  else "has a _Color material: recolorMode 'multiply' is only for "
                                                       "materials without one"))
            if multiply:
                if not col or [round(v, 4) for v in sc["max"][:3]] != [1.0, 1.0, 1.0]:
                    raise VsError(f"{lw}: a multiply recolour needs a white start colour and a colour-over-lifetime "
                                  f"gradient on {k!r}")
                entry["gradient"] = {"color": [[round(c[0], 4)] + [round(v * t, 5) for v, t in zip(c[1:4], target)]
                                               for c in col["rgb"]],
                                     "alpha": [[round(a[0], 4), round(a[1], 5)] for a in col["alpha"]]}
                if len(entry["gradient"]["color"]) > 8 or len(entry["gradient"]["alpha"]) > 8:
                    raise VsError(f"{lw}: {k!r} gradient has more than Unity's 8 keys")
                recolor_nodes.append(entry)
                continue
            start = rec_color(sc["max"], target)
            if col:
                keys = [[c[0]] + [a * b for a, b in zip(start, rec_color(c[1:4], target))] for c in col["rgb"]]
                peak = max(1.0, max(v for key in keys for v in key[1:]))
                entry["gradient"] = {"color": [[round(key[0], 4)] + [round(v / peak, 5) for v in key[1:]] for key in keys],
                                     "alpha": [[round(a[0], 4), round(a[1], 5)] for a in col["alpha"]]}
                entry["materialColorMul"] = [round(peak, 5)] * 3
            else:
                entry["materialColorMul"] = [round(v, 5) for v in start]
            if len(entry["gradient"]["color"] if entry["gradient"] else []) > 8 or                     len(entry["gradient"]["alpha"] if entry["gradient"] else []) > 8:
                raise VsError(f"{lw}: {k!r} gradient has more than Unity's 8 keys")
            recolor_nodes.append(entry)
    return {"localScaleNodes": local_nodes, "recolorNodes": recolor_nodes}


def require_runtime_lane(typ: str, lw: str) -> None:
    if typ in PENDING_SHIP_LANES:
        raise VsError(f"{lw}: {typ} has no end-to-end ship proof yet; the draft is lab-only")
    for path, marker in RUNTIME_LANES[typ]:
        if not path.is_file() or marker not in path.read_text(encoding="utf-8"):
            raise VsError(f"{lw}: {typ} has no end-to-end lane yet ({rel(path)} lacks {marker!r}); it cannot compile")


def trigger_problem(triggers, loop: bool | None) -> str | None:
    if not isinstance(triggers, list) or not triggers:
        return "triggers must be a non-empty list"
    for t in triggers:
        if t.get("mode") == "always":
            if len(triggers) != 1:
                return "an always trigger stands alone"
            if loop is False:
                return "an always-on effect must loop"
        elif t.get("mode") == "window":
            if not isinstance(t.get("clip"), str) or not isinstance(t.get("startKey"), int) or t["startKey"] < 0:
                return "window trigger needs clip and startKey >= 0"
            if "endKey" in t and (not isinstance(t["endKey"], int) or t["endKey"] <= t["startKey"]):
                return "endKey must be an int after startKey"
        else:
            return f"trigger mode {t.get('mode')!r} not in always/window"
    return None


def check_displacement_layer(layer: dict, lw: str) -> None:
    import displacement_mask_bake as bake  # noqa: E402
    def finite_number(value) -> bool:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return False
        try:
            return math.isfinite(value)
        except OverflowError:
            return False

    extra = set(layer) - {"id", "type", "mask", "direction", "power", "speed", "note"}
    if extra:
        raise VsError(f"{lw}: unknown bodyDisplacement keys {sorted(extra)}")
    try:
        bake.check_rule(layer.get("mask"))
    except bake.BakeError as ex:
        raise VsError(f"{lw}: mask {ex}") from None
    for k in ("direction", "power"):
        v = layer.get(k)
        if not (isinstance(v, list) and len(v) == 3 and all(finite_number(c) for c in v)):
            raise VsError(f"{lw}: {k} must be a finite numeric [x, y, z]")
    if not any(layer["direction"]):
        raise VsError(f"{lw}: direction must be non-zero")
    if not any(layer["power"]):
        raise VsError(f"{lw}: power must be non-zero")
    # vanilla FLAG materials (Mtl_QuietLake 0.002..0.005, banners) stay at millimetre-to-centimetre scale; a unit that
    # needs more is a pose, not a ripple
    if max(abs(c) for c in layer["power"]) > 0.25:
        raise VsError(f"{lw}: power above 0.25 world units is a pose, not a ripple")
    speed = layer.get("speed")
    if not finite_number(speed):
        raise VsError(f"{lw}: speed must be a finite number")


# bodyOverlay ``colors`` (a per-unit tint) may only rewrite a shader's own colour properties that drive what it draws.
# magic/Fresnel: rgb = sat(T*_Emission + f)*_Color + sat(f)*_EdgeColor*_EdgePower (DXBC read, Homm3VfxFresnelReplica).
OVERLAY_TINT_PROPERTIES = {"magic/Fresnel": ("_Color", "_EdgeColor")}


def check_overlay_tint(colors, shader: str, lw: str) -> None:
    allowed = OVERLAY_TINT_PROPERTIES.get(shader, ())
    if not isinstance(colors, list) or not colors:
        raise VsError(f"{lw}: colors must be a non-empty list of {{property, rgba}}")
    seen = set()
    for i, c in enumerate(colors):
        if not isinstance(c, dict) or set(c) != {"property", "rgba"}:
            raise VsError(f"{lw}: colors[{i}] needs exactly property and rgba")
        prop, rgba = c["property"], c["rgba"]
        if prop not in allowed:
            raise VsError(f"{lw}: colors[{i}] {prop!r} is not a tint property of {shader!r} (allowed {list(allowed)})")
        if prop in seen:
            raise VsError(f"{lw}: colors[{i}] repeats {prop!r}")
        seen.add(prop)
        if (not isinstance(rgba, list) or len(rgba) != 4
                or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                           and 0 <= v <= 16 for v in rgba)):
            raise VsError(f"{lw}: colors[{i}] rgba must be four finite numbers in [0, 16]")


def check_overlay_layer(layer: dict, sources: dict, lw: str) -> None:
    src = layer.get("source") or {}
    res = src.get("resPath")
    if not isinstance(res, str) or res != res.strip().lower() or res not in sources:
        raise VsError(f"{lw}: resPath {res!r} is not a probed canonical ResourceManager key (run `sources`)")
    rpath = src.get("rendererPath")
    idx = src.get("materialIndex")
    if not isinstance(rpath, str) or not isinstance(idx, int) or isinstance(idx, bool) or idx < 0:
        raise VsError(f"{lw}: source needs rendererPath (string, '' = root) and materialIndex >= 0")
    full = resolve_child(sources[res], rpath, lw)
    node = next((n for n in sources[res]["nodes"] if n["path"] == full), None)
    if node is None or node.get("meshMaterials") is None:
        raise VsError(f"{lw}: {full!r} is not a (Skinned)MeshRenderer node (particle renderers are vanillaParticles)")
    mats = node["meshMaterials"]
    if idx >= len(mats) or not mats[idx]:
        raise VsError(f"{lw}: {full!r} has no material [{idx}] (it has {len(mats)})")
    if mats[idx].get("shader") == "Hex/Lit":
        raise VsError(f"{lw}: {mats[idx].get('name')!r} is a Hex/Lit body sheet; an overlay is an effect material "
                      "(magic/Fresnel, lava, SlimeVertex, ...), never a second body")
    dup = [n for n in sources[res]["nodes"] if n["path"] == full]
    if len(dup) != 1:
        raise VsError(f"{lw}: rendererPath {full!r} is ambiguous (duplicate sibling names)")
    problem = trigger_problem(layer.get("triggers"), None)
    if problem or len(layer["triggers"]) != 1:
        raise VsError(f"{lw}: {problem or 'an overlay has exactly one trigger'}")
    if "colors" in layer:
        check_overlay_tint(layer["colors"], mats[idx].get("shader"), lw)
    extra = set(layer) - {"id", "type", "source", "triggers", "colors", "note"}
    if extra:
        raise VsError(f"{lw}: unknown bodyOverlay keys {sorted(extra)}")


def pending_lanes(spec: dict) -> list[str]:
    """Layer types in the spec whose end-to-end runtime lane does not exist yet (RUNTIME_LANES)."""
    out = []
    for typ in sorted({l.get("type") for l in spec.get("layers", [])} & set(RUNTIME_LANES)):
        try:
            require_runtime_lane(typ, typ)
        except VsError:
            out.append(typ)
    return out


def check_spec(unit: str, spec: dict, sources: dict, draft: bool = False) -> None:
    where = f"vanilla_style/{unit}"
    if spec.get("schema") != SPEC_SCHEMA:
        raise VsError(f"{where}: schema {spec.get('schema')!r} != {SPEC_SCHEMA}")
    sids = spec.get("gameUnitSids")
    if not isinstance(sids, list) or not sids or not all(isinstance(s, str) and s for s in sids):
        raise VsError(f"{where}: gameUnitSids must be a non-empty list")
    sup = (spec.get("supersedes") or {}).get("lookLayers")
    if not isinstance(sup, dict) or not all(isinstance(v, str) and v.strip() for v in sup.values()):
        raise VsError(f"{where}: supersedes.lookLayers must map every replaced look layer id to its reason")
    look_path = LOOK_SPECS / f"{unit}.json"
    if not look_path.is_file():
        raise VsError(f"{where}: no unit-look spec {rel(look_path)}")
    look_layers = {l["id"]: l["type"] for l in load(look_path).get("vfx", {}).get("layers", [])}
    need = sorted(i for i, t in look_layers.items() if t in SUPERSEDED_TYPES)
    if sorted(sup) != need:
        raise VsError(f"{where}: supersedes.lookLayers {sorted(sup)} must be exactly the look's "
                      f"{'/'.join(SUPERSEDED_TYPES)} layers {need}")
    ids = set()
    emission = 0
    displacement = 0
    for layer in spec.get("layers", []):
        lid, typ = layer.get("id"), layer.get("type")
        lw = f"{where}/{lid}"
        if not lid or lid in ids:
            raise VsError(f"{lw}: missing or duplicate layer id")
        ids.add(lid)
        if typ not in LAYER_TYPES:
            raise VsError(f"{lw}: type {typ!r} not in {LAYER_TYPES}")
        if typ == "emissionMap":
            emission += 1
            mask = layer.get("mask") or {}
            if mask.get("rule") not in MASK_RULES:
                raise VsError(f"{lw}: mask.rule {mask.get('rule')!r} not in {MASK_RULES}")
            col = layer.get("color")
            if not (isinstance(col, list) and len(col) == 3 and all(isinstance(c, (int, float)) and c >= 0 for c in col)):
                raise VsError(f"{lw}: color must be three HDR values >= 0")
            for k in ("minPower", "blinkPower", "blinkSpeed"):
                if not isinstance(layer.get(k), (int, float)) or layer[k] < 0:
                    raise VsError(f"{lw}: {k} must be a number >= 0")
            continue
        if typ in RUNTIME_LANES and not draft:
            require_runtime_lane(typ, lw)
        if typ == "bodyDisplacement":
            displacement += 1
            check_displacement_layer(layer, lw)
            continue
        if typ == "bodyOverlay":
            check_overlay_layer(layer, sources, lw)
            continue
        src = layer.get("source") or {}
        res = src.get("resPath")
        # resPath ships verbatim as the catalog's nativeResPath -> ResManager.Get<GameObject>: it must be the exact
        # (lowercase) ResourceManager container key the probe resolved, never a cased or rootless alias.
        if not isinstance(res, str) or res != res.strip().lower():
            raise VsError(f"{lw}: resPath {res!r} is not a canonical ResourceManager container key (lowercase, "
                          "root folder included)")
        if res not in sources:
            raise VsError(f"{lw}: resPath {res!r} is not in the probed vanilla sources (run `sources`)")
        full = resolve_child(sources[res], src.get("childPath") or "", lw)
        nodes = subtree(sources[res], full)
        keep = src.get("keepNodes")
        if not isinstance(keep, list) or not keep:
            raise VsError(f"{lw}: keepNodes must list the ParticleSystems that emit")
        for k in keep:
            n = nodes.get(k)
            if n is None or not n["particleSystem"] or not n["rendererMaterials"]:
                raise VsError(f"{lw}: keepNode {k!r} is not a rendering ParticleSystem under {full}")
            # Transform.Find takes the first of same-named siblings (serialized child order, kept by Instantiate).
            # A duplicated path is kept only when the spec names it in source.firstOfDuplicates, and then it is
            # the first sibling of that name in the static read; the later ones are silenced like any unkept system.
            dup = [i for i, m in enumerate(sources[res]["nodes"]) if m["path"] == n["path"]]
            if len(dup) != 1:
                if k not in (src.get("firstOfDuplicates") or []):
                    raise VsError(f"{lw}: keepNode {k!r} is ambiguous (duplicate sibling names); list it in "
                                  "source.firstOfDuplicates to keep the first one")
                first = sources[res]["nodes"][dup[0]]
                if not first["particleSystem"] or not first["rendererMaterials"]:
                    raise VsError(f"{lw}: keepNode {k!r}: the first same-named sibling is not a rendering ParticleSystem")
        if any(nodes[p]["director"] or nodes[p]["animator"] for p in nodes):
            raise VsError(f"{lw}: {full} carries a PlayableDirector/Animator; clone a child below it")
        scripted = sorted(p or "<root>" for p in nodes if nodes[p]["scripts"])
        if scripted:
            raise VsError(f"{lw}: the cloned subtree carries MonoBehaviours at {scripted}; clone a child below them "
                          "(a bare subtree must never run game scripts)")
        # Steady glow is the emission map and flashes are particle glows: a Light in the clone must stay dark. The
        # runtime activates only kept nodes and their ancestors, so a Light is dark iff its own GameObject is inactive
        # (every vanilla FlashLight/*Light probed so far is: the source timeline switches it on, and it is not cloned).
        lit = sorted(p or "<root>" for p in nodes if nodes[p]["light"] and nodes[p]["active"])
        if lit:
            raise VsError(f"{lw}: the cloned subtree has active Light GameObjects {lit}; glow is emission or particles, "
                          "never a dynamic light")
        runtime_ps_facts(layer, nodes, lw)
        anchor = layer.get("anchorNode")
        if anchor is not None and anchor not in nodes:
            raise VsError(f"{lw}: anchorNode {anchor!r} is not under {full}")
        bones = layer.get("bones")
        if not isinstance(bones, list) or not bones or len(set(bones)) != len(bones):
            raise VsError(f"{lw}: bones must be a non-empty list of distinct joint names")
        if not isinstance(layer.get("scale"), (int, float)) or not 0 < layer["scale"] <= 4:
            raise VsError(f"{lw}: scale must be in (0, 4]")
        if not isinstance(layer.get("rateMul", 1.0), (int, float)) or layer.get("rateMul", 1.0) <= 0:
            raise VsError(f"{lw}: rateMul must be > 0")
        rc = layer.get("recolor")
        if rc is not None and not (isinstance(rc, list) and len(rc) == 3 and all(isinstance(c, (int, float)) and c >= 0 for c in rc)
                                   and sum(rc) > 0):
            raise VsError(f"{lw}: recolor must be three values >= 0")
        mode = layer.get("recolorMode", "luminance")
        if mode not in ("luminance", "multiply") or ("recolorMode" in layer and rc is None):
            raise VsError(f"{lw}: recolorMode is 'luminance' (default) or 'multiply', and only with recolor")
        if mode == "multiply" and not all(c <= 1 for c in rc):
            raise VsError(f"{lw}: a multiply recolour darkens only; every recolor channel must be <= 1")
        orient = layer.get("orient", "bone")
        if orient not in ORIENTS:
            raise VsError(f"{lw}: orient {orient!r} not in {ORIENTS}")
        if (orient == "body") != ("bodyYawDeg" in layer):
            raise VsError(f"{lw}: bodyYawDeg is required with orient body and only there")
        reach = layer.get("alignToReach")
        if reach is not None:
            if orient not in ("bone", "emitUp") or len(bones) != 1:
                raise VsError(f"{lw}: alignToReach turns the clone root in one bone's frame: orient bone or emitUp "
                              "(emitters then still aim up) and exactly one bone")
            if not (isinstance(reach, list) and len(reach) == 3 and all(isinstance(c, (int, float)) for c in reach)
                    and sum(c * c for c in reach) > 1e-6):
                raise VsError(f"{lw}: alignToReach must be a non-zero source-root-local axis [x, y, z]")
        check_bone_anchor(layer, bones, lw)
        triggers = layer.get("triggers")
        if not isinstance(triggers, list) or not triggers:
            raise VsError(f"{lw}: triggers must be a non-empty list")
        for t in triggers:
            if t.get("mode") == "always":
                if len(triggers) != 1:
                    raise VsError(f"{lw}: an always trigger stands alone")
                if not layer.get("loop"):
                    raise VsError(f"{lw}: an always-on effect must loop")
            elif t.get("mode") == "window":
                if not isinstance(t.get("clip"), str) or not isinstance(t.get("startKey"), int) or t["startKey"] < 0:
                    raise VsError(f"{lw}: window trigger needs clip and startKey >= 0")
                if "endKey" in t and (not isinstance(t["endKey"], int) or t["endKey"] <= t["startKey"]):
                    raise VsError(f"{lw}: endKey must be an int after startKey")
                if t.get("end", "stopEmitting") != "stopEmitting":
                    raise VsError(f"{lw}: a window ends by stopEmitting (particles finish their life)")
            else:
                raise VsError(f"{lw}: trigger mode {t.get('mode')!r} not in always/window")
    if emission != 1:
        raise VsError(f"{where}: exactly one emissionMap layer (steady glow is emission, never a light); found {emission}")
    if displacement > 1:
        raise VsError(f"{where}: at most one bodyDisplacement layer (one COLOR_0 mask per mesh); found {displacement}")


# ------------------------------------------------------------------ delivery facts (compile only)
def delivery_facts(unit: str, spec: dict) -> dict:
    sys.path.insert(0, str(ROOT / "tools/homm3_def_retarget_delivery"))
    import ship_def_retarget_slice as ship  # noqa: E402
    sel_path = ROOT / spec["delivery"]["selection"]
    selection = load(sel_path)
    row = next((r for r in selection["units"] if r["labSid"] == unit), None)
    if row is None:
        raise VsError(f"{unit}: selection {rel(sel_path)} has no row")
    if row.get("gameSid") not in spec["gameUnitSids"]:
        # rows match the live unit by game sid: a lab sid here (h3_archangel for h3_angel_upg) is a silent miss
        raise VsError(f"{unit}: gameUnitSids {spec['gameUnitSids']} lacks the delivery row's gameSid {row.get('gameSid')!r}")
    out = (ROOT / selection["out"]).resolve()
    facts = ship.verify_freeze({**selection, "units": [row]}, out)[unit]
    tmap, idle_map = ship.make_time_map(unit, facts)
    d = ship.unit_dir(out, unit)
    lab_report = d / "lab_report.json"
    if not lab_report.is_file():
        raise VsError(f"{unit}: no lab_report.json in {d} (run the delivery lab stage first: it records the stock state map)")
    report = load(lab_report)
    glb = d / "delivered_idle_retimed.glb"
    if report.get("masterGlbSha256") != sha(glb):
        # a bodyDisplacement unit's lab master is the ship step's COLOR_0 bake of this very GLB (displacementMaskGlb)
        import displacement_mask_bake as dmb  # noqa: E402
        masked = d / ship.COLOR0_GLB
        try:
            stamp = dmb.verify(masked) if masked.is_file() else None
        except dmb.BakeError as ex:
            raise VsError(f"{unit}: lab master displacementMaskGlb {ex}") from None
        sources = {sha(glb)}
        if stamp and stamp["sourceGlbSha256"] == sha(glb):
            sources.add(stamp["outGlbSha256"])
        # a mergeMeshes row's lab master is prepare's stamped rubble merge of that source (unity/merged_master.glb)
        merged, mst = d / "unity/merged_master.glb", None
        if merged.is_file() and sha(merged) == report.get("masterGlbSha256"):
            try:
                mst = ship.merge_rubble_glb.verify(merged)
            except ship.merge_rubble_glb.MergeError as ex:
                raise VsError(f"{unit}: lab master merged_master.glb {ex}") from None
        if not ((stamp and stamp["sourceGlbSha256"] == sha(glb) and stamp["outGlbSha256"] == report.get("masterGlbSha256"))
                or (mst and mst["sourceGlbSha256"] in sources)):
            raise VsError(f"{unit}: lab report was built from another GLB")
    return {"selection": rel(sel_path), "row": row, "facts": facts, "tmap": tmap, "idleMap": idle_map,
            "clips": {c: v["last"] for c, v in facts["glb"]["clips"].items() if c.startswith("Unit_")},
            "joints": facts["glb"]["joints"], "stockMap": report["stockMap"],
            "basecolor": d / "inputs/basecolor.png", "glb": glb, "labReport": lab_report}


def smoothstep(a, b, x):
    import numpy as np
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def raster_positions(glb_path: Path, size: tuple[int, int]):
    """Bind-pose position per texel (UV-space raster of every triangle) and a coverage mask."""
    import numpy as np
    sys.path.insert(0, str(ROOT / "tools/homm3_vfx"))
    from glb_io import Glb  # noqa: E402
    g = Glb(glb_path)
    w, h = size
    pos = np.zeros((h, w, 3), np.float32)
    cov = np.zeros((h, w), bool)
    for mesh in g.json["meshes"]:
        for prim in mesh["primitives"]:
            P = g.accessor(prim["attributes"]["POSITION"]).astype(np.float64)
            UV = g.accessor(prim["attributes"]["TEXCOORD_0"]).astype(np.float64)
            idx = g.accessor(prim["indices"]).reshape(-1, 3)
            px = np.stack([UV[:, 0] * w - 0.5, UV[:, 1] * h - 0.5], 1)
            for tri in idx:
                a, b, c = px[tri]
                x0, x1 = int(max(0, math.floor(min(a[0], b[0], c[0])))), int(min(w - 1, math.ceil(max(a[0], b[0], c[0]))))
                y0, y1 = int(max(0, math.floor(min(a[1], b[1], c[1])))), int(min(h - 1, math.ceil(max(a[1], b[1], c[1]))))
                if x1 < x0 or y1 < y0:
                    continue
                den = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
                if abs(den) < 1e-12:
                    continue
                gx, gy = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
                l0 = ((b[1] - c[1]) * (gx - c[0]) + (c[0] - b[0]) * (gy - c[1])) / den
                l1 = ((c[1] - a[1]) * (gx - c[0]) + (a[0] - c[0]) * (gy - c[1])) / den
                l2 = 1 - l0 - l1
                inside = (l0 >= -1e-3) & (l1 >= -1e-3) & (l2 >= -1e-3)
                if not inside.any():
                    continue
                pa, pb, pc = P[tri]
                pts = l0[..., None] * pa + l1[..., None] * pb + l2[..., None] * pc
                yy, xx = gy[inside], gx[inside]
                pos[yy, xx] = pts[inside]
                cov[yy, xx] = True
    return pos, cov


def dilate(img, cov, steps: int = 6):
    """Grow texel values across UV seams so bilinear/mip sampling at island edges does not pull in black."""
    import numpy as np
    img, cov = img.copy(), cov.copy()
    for _ in range(steps):
        acc = np.zeros_like(img)
        n = np.zeros(cov.shape, np.float32)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            sc = np.roll(cov, (dy, dx), (0, 1))
            acc += np.roll(img, (dy, dx), (0, 1)) * sc[..., None]
            n += sc
        grow = (~cov) & (n > 0)
        img[grow] = acc[grow] / n[grow][:, None]
        cov = cov | grow
    return img


def build_emission(unit: str, layer: dict, df: dict, dest: Path) -> dict:
    import numpy as np
    from PIL import Image
    bc = np.asarray(Image.open(df["basecolor"]).convert("RGB")).astype(np.float32) / 255.0
    lum = bc @ np.array(LUMA, np.float32)
    mask = layer["mask"]
    rule = mask["rule"]
    if rule == "warm_luminance":
        warm = np.clip((bc[..., 0] - bc[..., 2]) * float(mask["warmGain"]), 0, 1)
        m = smoothstep(float(mask["lo"]), float(mask["hi"]), lum) * warm
        out = bc * m[..., None]
    elif rule == "luminance":
        m = smoothstep(float(mask["lo"]), float(mask["hi"]), lum)
        out = np.repeat(m[..., None], 3, -1)
    elif rule == "hot_chroma":
        # painted hot spots (eyes, mouth, embers): texels that are warm (R - B), saturated (max - min) and not dark,
        # all three at once, so a warm body's broad highlights stay out. The map is the grey mask; ``color`` carries
        # the DEF's own hot colour.
        sat = bc.max(-1) - bc.min(-1)
        m = (smoothstep(float(mask["warmLo"]), float(mask["warmHi"]), bc[..., 0] - bc[..., 2])
             * smoothstep(float(mask["satLo"]), float(mask["satHi"]), sat)
             * smoothstep(float(mask["lumLo"]), float(mask["lumHi"]), lum))
        out = np.repeat(m[..., None], 3, -1)
    else:
        # funnel_helix: a painted-style mask. Below ``funnelTopY`` (the funnel) the glow is ``streaks`` bands that
        # wind ``turns`` times around the funnel axis from tip to top, broken up by the base colour's own
        # brightness; above it (arms, chest, head) only the brightest base-colour streaks glow, at ``bodyGain``.
        pos, cov = raster_positions(df["glb"], (bc.shape[1], bc.shape[0]))
        y = pos[..., 1]
        top = float(mask["funnelTopY"])
        ang = np.arctan2(pos[..., 2], pos[..., 0])
        phase = float(mask["streaks"]) * ang + 2 * math.pi * float(mask["turns"]) * np.clip(y / top, 0, 1)
        band = smoothstep(1.0 - float(mask["width"]), 1.0, 0.5 + 0.5 * np.cos(phase))
        lum_n = smoothstep(float(mask["lumLo"]), float(mask["lumHi"]), lum)
        funnel = band * (float(mask["lumFloor"]) + (1 - float(mask["lumFloor"])) * lum_n)
        funnel *= smoothstep(0.0, float(mask["tipFadeY"]), y)                      # the tip dissolves
        blend = smoothstep(top - float(mask["blendY"]), top + float(mask["blendY"]), y)
        body = smoothstep(float(mask["bodyLo"]), float(mask["bodyHi"]), lum) * float(mask["bodyGain"])
        m = np.where(cov, funnel * (1 - blend) + body * blend, 0.0)
        out = dilate(np.repeat(m[..., None], 3, -1).astype(np.float32), cov)
    dest.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray((np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8)).save(dest, optimize=True)
    return {"coverage": round(float((m > 0.05).mean()), 4), "meanMask": round(float(m.mean()), 4)}


def emission_glow_error(unit: str, lid: str, layer: dict, stats: dict) -> str | None:
    """A glowing emissionMap row (any non-zero ``color`` or power) whose compiled mask covers no texel lights nothing:
    that is an empty mask, not a design. The black no-glow placeholder (colour 0, minPower 0, blinkPower 0; see
    docs/homm3_vanilla_style_effects_rollout.md) is exempt: it is inert by design whatever its coverage."""
    glows = any(float(c) > 0 for c in layer["color"]) or float(layer["minPower"]) > 0 or float(layer["blinkPower"]) > 0
    if glows and not float(stats.get("coverage", 0.0)) > 0.0:
        return (f"{unit}/{lid}: emissionMap glows (color {list(layer['color'])}, minPower {layer['minPower']}, "
                f"blinkPower {layer['blinkPower']}) but its compiled mask coverage is {stats.get('coverage')}: the mask "
                "selects no texel, so the row lights nothing; retune mask.lo/hi or make it the black no-glow map")
    return None


def key_time(k: int) -> float:
    return (k + 0.5) / FPS


def compile_triggers(unit: str, lid: str, triggers: list, df: dict, states_by_clip: dict) -> list[dict]:
    """Spec triggers -> catalog triggers: DEF key k opens at (k + 0.5) / 12 s of the source clip, through the
    delivered retime, as a fraction of the delivered clip, on every stock state that plays it."""
    trigs = []
    for t in triggers:
        if t["mode"] == "always":
            trigs.append({"mode": "always"})
            continue
        clip = t["clip"]
        if clip not in df["clips"]:
            raise VsError(f"{unit}/{lid}: clip {clip} is not in the delivered GLB")
        states = sorted(states_by_clip.get(clip, []))
        if not states:
            raise VsError(f"{unit}/{lid}: no stock animator state plays {clip}; the trigger could never fire")
        length = df["clips"][clip]
        s = df["tmap"](clip, key_time(t["startKey"])) / length
        e = df["tmap"](clip, key_time(t["endKey"])) / length if "endKey" in t else 1.0
        if not 0 <= s < min(e, 1.0):
            raise VsError(f"{unit}/{lid}: window {s:.3f}..{e:.3f} is outside {clip}")
        trigs.append({"mode": "animator_window", "states": states, "normalizedTime": [round(s, 5), round(min(e, 1.0), 5)]})
    return trigs


def build_rows(unit: str, spec: dict, df: dict, emission_files: dict, displacement: dict | None = None) -> list[dict]:
    rows = []
    origin = ORIGIN_PREFIX + unit
    sids = sorted(set(spec["gameUnitSids"]) | {unit})
    states_by_clip: dict[str, list[str]] = {}
    for state, clip in df["stockMap"].items():
        states_by_clip.setdefault(clip, []).append(state)
    for layer in spec["layers"]:
        lid = layer["id"]
        if layer["type"] == "bodyDisplacement":
            bake = (displacement or {}).get(lid)
            if bake is None:
                raise VsError(f"{unit}/{lid}: bodyDisplacement compiled without its COLOR_0 bake")
            rows.append({"id": f"vs_{unit}_{lid}", "lane": "battle_body_displacement", "origin": origin,
                         "match": {"unitSids": sids},
                         "displacement": {"mode": "flag", "direction": [float(c) for c in layer["direction"]],
                                          "power": [float(c) for c in layer["power"]], "speed": float(layer["speed"]),
                                          "maskGlbSha256": bake["outGlbSha256"]},
                         "proof": "generated artifact; in-game look unproven"})
            continue
        if layer["type"] == "bodyOverlay":
            src = layer["source"]
            trig = compile_triggers(unit, lid, layer["triggers"], df, states_by_clip)[0]
            rows.append({"id": f"vs_{unit}_{lid}", "lane": "battle_body_overlay", "origin": origin,
                         "match": {"unitSids": sids},
                         "source": {"nativeResPath": src["resPath"], "rendererPath": src["rendererPath"],
                                    "materialIndex": int(src["materialIndex"]),
                                    **({"colors": [{"property": c["property"],
                                                    "rgba": [float(v) for v in c["rgba"]]}
                                                   for c in layer["colors"]]} if "colors" in layer else {})},
                         "trigger": trig, "proof": "generated artifact; in-game look unproven"})
            continue
        if layer["type"] == "emissionMap":
            name, digest = emission_files[lid]
            rows.append({"id": f"vs_{unit}_{lid}", "lane": "battle_emission", "origin": origin, "match": {"unitSids": sids},
                         "emission": {"texture": f"emission/{name}", "textureSha256": digest,
                                      "color": [float(c) for c in layer["color"]], "minPower": float(layer["minPower"]),
                                      "blinkPower": float(layer["blinkPower"]), "blinkSpeed": float(layer["blinkSpeed"])},
                         "proof": "generated artifact; in-game look unproven"})
            continue
        for bone in layer["bones"]:
            if bone not in df["joints"]:
                raise VsError(f"{unit}/{lid}: bone {bone} is not a joint of the delivered GLB")
        src = layer["source"]
        source = load(SOURCES)["sources"][src["resPath"]]
        full = resolve_child(source, src["childPath"], f"{unit}/{lid}")
        ps_facts = runtime_ps_facts(layer, subtree(source, full), f"{unit}/{lid}")
        vs = {"childPath": full, "keepNodes": list(src["keepNodes"]), "worldScale": float(layer["scale"]),
              "rateMul": float(layer.get("rateMul", 1.0)), "loop": bool(layer.get("loop", False)),
              "zeroChildPositions": bool(layer.get("zeroChildPositions", False)), "orient": layer.get("orient", "bone"),
              "bodyYawDeg": float(layer.get("bodyYawDeg", 0.0)), "anchorNode": layer.get("anchorNode") or "",
              "recolor": [float(c) for c in layer["recolor"]] if layer.get("recolor") else None,
              "localScaleNodes": ps_facts["localScaleNodes"], "recolorNodes": ps_facts["recolorNodes"],
              "endBehaviour": "stopEmitting"}
        follow = layer.get("follow", "bone")
        if follow not in FOLLOWS:
            raise VsError(f"{unit}/{lid}: follow {follow!r} not in {FOLLOWS}")
        if follow == "release":
            if any(t.get("mode") != "window" for t in layer["triggers"]):
                raise VsError(f"{unit}/{lid}: follow 'release' needs window triggers (it detaches at each window start)")
            vs["follow"] = "release"
        rot = reach_rotation(df["glb"], layer)
        if rot is not None:
            vs["boneLocalRot"] = rot
        trigs = compile_triggers(unit, lid, layer["triggers"], df, states_by_clip)
        anchors = bone_local_positions(df["glb"], layer)
        for bone in layer["bones"]:
            bone_vs = dict(vs, boneLocalPos=anchors[bone]) if bone in anchors else vs
            for i, trig in enumerate(trigs):
                suffix = f"_{bone}" if len(layer["bones"]) > 1 else ""
                suffix += f"_t{i}" if len(trigs) > 1 else ""
                rows.append({"id": f"vs_{unit}_{lid}{suffix}", "lane": "battle_skinned", "origin": origin,
                             "match": {"unitSids": sids}, "source": {"nativeResPath": src["resPath"]},
                             "socket": {"kind": "bones", "names": [bone], "localScale": [1.0, 1.0, 1.0]},
                             "trigger": trig, "vanillaStyle": bone_vs, "keepExistingGlow": False,
                             "proof": "generated artifact; in-game look unproven"})
    return rows


def write_catalog_rows(unit: str, rows: list[dict]) -> None:
    catalog = load(CATALOG)
    origin = ORIGIN_PREFIX + unit
    entries = catalog["entries"]
    at = next((i for i, r in enumerate(entries) if r.get("origin") == origin), None)
    keep = [r for r in entries if r.get("origin") != origin]
    clash = {r["id"] for r in keep} & {r["id"] for r in rows}
    if clash:
        raise VsError(f"{unit}: catalog ids already used by other rows: {sorted(clash)}")
    # rows keep their place (a recompile is then a no-op diff); a new unit appends
    at = len(keep) if at is None else sum(1 for r in entries[:at] if r.get("origin") != origin)
    catalog["entries"] = keep[:at] + rows + keep[at:]
    # the catalog's own format (indent 1, LF), shared with map_building_fx.py; indent 2 rewrote every line
    CATALOG.write_text(json.dumps(catalog, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def cmd_compile(only: str | None) -> None:
    sources = load(SOURCES)
    if sources.get("schema") != SOURCES_SCHEMA:
        raise VsError("vanilla sources missing or stale; run `sources`")
    for unit, (path, spec) in specs().items():
        if only and unit != only:
            continue
        check_spec(unit, spec, sources["sources"])
        df = delivery_facts(unit, spec)
        if df["row"].get("vfxAuthority") != "vanilla_style" or df["row"].get("albedo") != "basecolor":
            raise VsError(f"{unit}: the delivery row must be vfxAuthority vanilla_style with the basecolor albedo")
        emission_files, stats = {}, {}
        for layer in spec["layers"]:
            if layer["type"] == "emissionMap":
                name = f"{unit}__{layer['id']}.png"
                stats[layer["id"]] = build_emission(unit, layer, df, EMISSION_DIR / name)
                err = emission_glow_error(unit, layer["id"], layer, stats[layer["id"]])
                if err:
                    raise VsError(err)
                emission_files[layer["id"]] = (name, sha(EMISSION_DIR / name))
        bakes = {}
        for layer in spec["layers"]:
            if layer["type"] == "bodyDisplacement":
                import displacement_mask_bake as dmb  # noqa: E402
                out = DISPLACEMENT_DIR / unit / "delivered_idle_retimed.color0.glb"
                try:
                    stamp = dmb.bake(df["glb"], out, layer["mask"])
                except dmb.BakeError as ex:
                    raise VsError(f"{unit}/{layer['id']}: {ex}") from None
                bakes[layer["id"]] = {"glb": rel(out), "outGlbSha256": stamp["outGlbSha256"],
                                      "sourceGlbSha256": stamp["sourceGlbSha256"], "primitives": stamp["primitives"]}
        rows = build_rows(unit, spec, df, emission_files, bakes)
        write_catalog_rows(unit, rows)
        record = {"schema": COMPILED_SCHEMA, "unit": unit, "spec": rel(path), "specSha256": canonical_sha(spec),
                  "sourcesSha256": unit_sources_sha(spec, sources["sources"]),
                  "delivery": {"selection": df["selection"], "basecolorSha256": sha(df["basecolor"]),
                               "glbSha256": sha(df["glb"]), "labReportSha256": sha(df["labReport"])},
                  "joints": df["joints"], "clipLengths": df["clips"], "idleTimeMap": df["idleMap"],
                  "stockMap": df["stockMap"],
                  "emission": {lid: {"file": f"emission/{n}", "sha256": d, **stats[lid]} for lid, (n, d) in emission_files.items()},
                  "displacementBake": bakes,
                  "rows": rows, "rowsSha256": canonical_sha(rows),
                  "proof": "generated artifact; in-game look unproven"}
        dump(COMPILED_DIR / f"{unit}.json", record)
        print(f"compile: {unit} rows={len(rows)} emission={stats}")


# ------------------------------------------------------------------ check (committed data only)
def check() -> list[str]:
    """Returns the checked unit sids; raises VsError on the first violation."""
    sources = load(SOURCES) if SOURCES.is_file() else {}
    if sources.get("schema") != SOURCES_SCHEMA:
        raise VsError(f"{rel(SOURCES)} missing or not {SOURCES_SCHEMA}")
    catalog = load(CATALOG)
    by_origin: dict[str, list[dict]] = {}
    for r in catalog["entries"]:
        o = r.get("origin") or ""
        if o.startswith(ORIGIN_PREFIX):
            by_origin.setdefault(o[len(ORIGIN_PREFIX):], []).append(r)
        elif o.startswith("map_building_fx:") and r.get("lane") == "map_building":
            continue  # map-building effects: tools/homm3_map_building_meshes/map_building_fx.py check
        elif r.get("lane") == "battle_emission" or "vanillaStyle" in r:
            raise VsError(f"catalog row {r.get('id')}: vanilla-style fields without a vanilla_style origin")
    all_specs = specs()
    orphans = sorted(set(by_origin) - set(all_specs))
    if orphans:
        raise VsError(f"catalog rows for units without a vanilla-style spec: {orphans}")
    for unit, (path, spec) in all_specs.items():
        check_spec(unit, spec, sources["sources"])
        rec_path = COMPILED_DIR / f"{unit}.json"
        if not rec_path.is_file():
            raise VsError(f"{unit}: not compiled ({rel(rec_path)} missing)")
        rec = load(rec_path)
        if rec.get("schema") != COMPILED_SCHEMA or rec.get("specSha256") != canonical_sha(spec):
            raise VsError(f"{unit}: spec changed since compile; rerun compile")
        if rec.get("sourcesSha256") != unit_sources_sha(spec, sources["sources"]):
            raise VsError(f"{unit}: vanilla sources changed since compile; rerun compile")
        if canonical_sha(rec["rows"]) != rec["rowsSha256"] or canonical_sha(by_origin.get(unit, [])) != rec["rowsSha256"]:
            raise VsError(f"{unit}: catalog rows differ from the compiled record (hand edit?); rerun compile")
        for lid, b in (rec.get("displacementBake") or {}).items():
            import displacement_mask_bake as dmb  # noqa: E402
            try:
                stamp = dmb.verify(ROOT / b["glb"])
            except dmb.BakeError as ex:
                raise VsError(f"{unit}/{lid}: displacement bake {ex}") from None
            if stamp["outGlbSha256"] != b["outGlbSha256"] or stamp["sourceGlbSha256"] != rec["delivery"]["glbSha256"]:
                raise VsError(f"{unit}/{lid}: displacement bake is not of the delivered GLB; rerun compile")
        layers = {l["id"]: l for l in spec["layers"]}
        for lid, e in rec["emission"].items():
            if lid not in layers:
                raise VsError(f"{unit}/{lid}: compiled emission has no spec layer; rerun compile")
            err = emission_glow_error(unit, lid, layers[lid], e)
            if err:
                raise VsError(err)
            p = PLUGIN / "homm3_mesh_fx" / e["file"]
            if not p.is_file() or sha(p) != e["sha256"]:
                raise VsError(f"{unit}/{lid}: emission texture {e['file']} missing or changed")
        for r in rec["rows"]:
            for bone in (r.get("socket") or {}).get("names", []):
                if bone not in rec["joints"]:
                    raise VsError(f"{unit}: row {r['id']} bone {bone} is not a delivered joint")
            for st in (r.get("trigger") or {}).get("states", []):
                if st not in rec["stockMap"]:
                    raise VsError(f"{unit}: row {r['id']} state {st} is not a stock controller state")
        check_superseded(unit, spec, rec)
    check_drafts(sources["sources"], all_specs)
    return sorted(all_specs)


def check_drafts(sources: dict, shipped: dict) -> list[str]:
    """Drafts are statically valid against the probed sources and never shadow a shipped spec."""
    drafts = specs(drafts=True)
    both = sorted(set(drafts) & set(shipped))
    if both:
        raise VsError(f"units with both a draft and a shipped spec (promotion moves the file): {both}")
    unchecked = {}
    for unit, (_, spec) in drafts.items():
        check_spec(unit, spec, sources, draft=True)
        glb, why = draft_skeleton(unit, spec)
        if glb is None:
            unchecked[unit] = why
        else:
            check_bones_on_glb(unit, spec, glb)
    for unit, why in sorted(unchecked.items()):
        print(f"check-drafts: bones UNCHECKED for {unit}: {why}", file=sys.stderr)
    return sorted(drafts)


def cmd_plan(unit: str) -> None:
    """Dry run of a draft against its frozen unit_look selection row: bones, clips, windows, stock states. Writes nothing."""
    drafts = specs(drafts=True)
    if unit not in drafts:
        raise VsError(f"{unit}: no draft spec in {rel(DRAFT_DIR)}")
    _, spec = drafts[unit]
    check_spec(unit, spec, load(SOURCES)["sources"], draft=True)
    pending = pending_lanes(spec)
    if pending:
        raise VsError(f"{unit}: layer type(s) {pending} have no end-to-end runtime and ship proof yet; "
                      "the draft is lab-only until they land")
    df = delivery_facts(unit, spec)
    emission = {l["id"]: (f"{unit}__{l['id']}.png", "<not built>") for l in spec["layers"] if l["type"] == "emissionMap"}
    # the COLOR_0 bake is made by compile from the frozen GLB; the dry run only needs its row shape
    bakes = {l["id"]: {"outGlbSha256": "<not built>"} for l in spec["layers"] if l["type"] == "bodyDisplacement"}
    rows = build_rows(unit, spec, df, emission, bakes)
    print(f"plan: {unit} selection={df['selection']} rowAuthority={df['row'].get('vfxAuthority', 'unit_look')} rows={len(rows)}")
    for r in rows:
        t = r.get("trigger") or {}
        where = ",".join((r.get("socket") or {}).get("names", [])) or "-"
        when = t.get("mode", "emission") if t.get("mode") != "animator_window" else             f"{'/'.join(t['states'])} {t['normalizedTime'][0]:.3f}..{t['normalizedTime'][1]:.3f}"
        print(f"  {r['id']:<44} {r['lane']:<15} {where:<14} {when}")


def check_superseded(unit: str, spec: dict, rec: dict) -> None:
    """No active def_retarget selection may still deliver a layer this unit's vanilla-style spec supersedes."""
    for sel_path in sorted(SELECTIONS.glob("*.json")):
        sel = load(sel_path)
        if sel.get("schema") != "homm3_def_retarget_delivery_selection.v1":
            continue
        row = next((r for r in sel.get("units", []) if r.get("labSid") == unit), None)
        if row is None:
            continue
        if sel.get("supersededBy"):
            continue
        name = sel_path.name
        if row.get("vfxAuthority") != "vanilla_style" or row.get("albedo") != "basecolor":
            raise VsError(f"{name}: {unit} still ships the unit-look layers {sorted(spec['supersedes']['lookLayers'])}; "
                          "set vfxAuthority vanilla_style + albedo basecolor, or mark the selection supersededBy")
        if row.get("vanillaStyleSpec") != rel(SPEC_DIR / f"{unit}.json"):
            raise VsError(f"{name}: {unit} vanillaStyleSpec must name {rel(SPEC_DIR / f'{unit}.json')}")
        if "deferLayers" in row:
            raise VsError(f"{name}: {unit} a vanilla-style row supersedes layers; it never defers them")
        # generated plan (artifact; present on the machine that built it)
        plan = (ROOT / sel["out"] / unit / "unity/vfx_plan.json")
        if plan.is_file():
            p = load(plan)
            if p.get("uvAtlas") or p.get("quads") or p.get("lights"):
                raise VsError(f"{rel(plan)}: a vanilla-style unit's plan still carries uvAtlas/quads/lights")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("sources", "compile", "check", "check-drafts", "plan"))
    ap.add_argument("--unit")
    ap.add_argument("--extra", nargs="*", default=[], help="sources: more ResourceManager paths to record")
    a = ap.parse_args()
    if a.command == "sources":
        cmd_sources(a.extra)
    elif a.command == "compile":
        cmd_compile(a.unit)
    elif a.command == "check-drafts":
        print("check-drafts: ok " + ",".join(check_drafts(load(SOURCES)["sources"], specs())))
    elif a.command == "plan":
        if not a.unit:
            raise VsError("plan needs --unit")
        cmd_plan(a.unit)
    else:
        print("check: ok " + ",".join(check()))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except VsError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)
