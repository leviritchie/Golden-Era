"""Unit-look spec (homm3_unit_look.v1): loading, static validation, hashing, clip/DEF-frame helpers.

Shared by look.py (the entry point) and tools/validate_homm3_unit_look_contract.py.
The contract is documented in docs/homm3_unit_look_pipeline.md.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC_DIR = ROOT / "tools/homm3_unit_look/units"
OUT_ROOT = ROOT / "artifacts/homm3_unit_look"
RETARGET = ROOT / "artifacts/homm3_def_retarget"
RUNS = ROOT / "artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/runs"
SCHEMA = "homm3_unit_look.v1"
STAMP_SCHEMA = "homm3_unit_look_stamp.v1"
SUPERSEDED = "_superseded_do_not_use"
UNPREBAKED_EXT = ".glb.unprebaked"

MODES = ("v7c", "v6m")
# A rawAccepted stamp (look.py --accept-raw) delivers the un-prebaked GLB when every grade mode measured
# further from the DEF than the raw base colour. Its albedo is the GLB's own body image, saved as RAW_BASECOLOR.
RAW_ACCEPTED = "rawAccepted"
RAW_BASECOLOR = "raw_basecolor.png"
RAW_SOURCE_IMAGE = "raw_source_image.jpg"   # a JPEG raw body image, kept so its PNG transcode can be re-verified
RAW_TRANSCODE_FROM = ("image/jpeg",)


def image_pixels_sha256(data: bytes) -> str:
    """sha256 of the decoded pixels (mode, size, raw bytes): what a lossless transcode must preserve."""
    import hashlib
    import io
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    im.load()
    h = hashlib.sha256(f"{im.mode}:{im.size[0]}x{im.size[1]}:".encode())
    h.update(im.tobytes())
    return h.hexdigest()


def raw_accepted_errors(stamp: dict, expected_unit: str | None = None) -> list[str]:
    """Fail-closed rule of a rawAccepted stamp: a reason, every MODES grade tried, and the raw body L-hist
    strictly below each mode's. Shared by look.py, the look validator and freeze_slice.py."""
    ra = stamp.get("rawAccepted") or {}
    e = []
    if stamp.get("schema") != STAMP_SCHEMA:
        e.append(f"rawAccepted stamp schema must be {STAMP_SCHEMA}")
    if not isinstance(stamp.get("unit"), str) or not stamp["unit"].strip():
        e.append("rawAccepted stamp carries no unit")
    elif expected_unit is not None and stamp["unit"] != expected_unit:
        e.append(f"rawAccepted stamp unit {stamp['unit']!r} differs from {expected_unit!r}")
    if stamp.get("kind") != RAW_ACCEPTED:
        e.append(f"stamp kind {stamp.get('kind')!r} is not {RAW_ACCEPTED}")
    if not str(ra.get("reason") or "").strip():
        e.append("rawAccepted stamp carries no reason")
    if stamp.get("basecolorFile") != RAW_BASECOLOR:
        e.append(f"rawAccepted basecolorFile must be {RAW_BASECOLOR}")
    tc = stamp.get("rawTranscode")
    if tc is None:
        if stamp.get("sourceGlbSha256") != stamp.get("deliveredGlbSha256"):
            e.append("rawAccepted delivers its source GLB unchanged, but the stamp's source and delivered shas differ")
    else:
        # a JPEG body image is re-encoded as PNG with identical decoded pixels; nothing else in the GLB changes
        if not isinstance(tc, dict) or tc.get("from") not in RAW_TRANSCODE_FROM:
            e.append(f"rawTranscode must record a source image type in {RAW_TRANSCODE_FROM}")
        else:
            if tc.get("pngSha256") != stamp.get("basecolorSha256"):
                e.append("rawTranscode pngSha256 is not the stamped raw base colour")
            if tc.get("sourceImageFile") != RAW_SOURCE_IMAGE or not tc.get("sourceImageSha256"):
                e.append(f"rawTranscode must keep the source image as {RAW_SOURCE_IMAGE} with its sha")
            if not tc.get("pixelsSha256"):
                e.append("rawTranscode records no decoded-pixel sha")
            if stamp.get("sourceGlbSha256") == stamp.get("deliveredGlbSha256"):
                e.append("rawTranscode stamp delivers the source GLB unchanged (nothing was transcoded)")
    raw, tried = ra.get("rawLhistBody"), ra.get("modesTried") or {}
    missing = [m for m in MODES if m not in tried]
    if missing:
        e.append(f"rawAccepted did not try mode(s) {missing}")
    def finite_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

    if not finite_number(raw):
        e.append("rawAccepted records no finite raw body L-hist")
    else:
        for m, v in tried.items():
            lh = (v or {}).get("lhistBody")
            if not finite_number(lh) or lh <= raw:
                e.append(f"mode {m} body L-hist {lh} does not lose to the raw {raw}")
    return e
FRONTS = ("auto", "+x", "-x", "+y", "-y")
ARENAS = ("sand", "grass", "snow")
TREATMENTS = ("baked", "dynamic")
LAYER_TYPES = ("defFlipbook", "uvAtlas", "particles", "volumetricFire", "effectLight", "event")   # volumetricFire: volfire.py (opt-in)
MASK_METHODS = ("lumaSparse", "palette", "paletteLuma", "defEffects", "file")
DEF_EFFECT_CLASSES = ("electric", "fire", "magic", "water", "smoke")   # tools/homm3_vfx/def_effects.EFFECT_CLASSES
EVENT_ACTIONS = ("missile", "activate", "deactivate", "mark", "hideMesh", "showMesh")
RENDERS = ("billboard", "groundPlane", "unitPlane", "trail")   # unitPlane / trail: vfx_depth.py (opt-in)
REGION_TARGETS = ("grade", "defPalette")
REGION_KNOBS = {"grade": {"toeMax"}, "defPalette": {"skyCompensation"}}
VERTEX_CHANNELS = ("r", "g", "b", "a")

TOP_KEYS = {"schema", "unit", "status", "excludedReason", "lighting", "lights", "vfx", "notes"}
LIGHTING_KEYS = {"mode", "front", "arena", "knobs", "bakedGlow", "regions", "defSegmenter", "metal", "finish", "notes"}
FINISH_MODES = ("vanilla", "none")   # finish.py: "vanilla" (look B, the default when absent) or "none" (A, comparison)
REGION_KEYS = {"name", "mask", "target", "defRegion", "knobs", "notes"}
GLOW_KEYS = {"lightId", "materialClass", "maskPath", "rgb", "strength"}
LIGHT_KEYS = {"id", "treatment", "notes"}
LAYER_KEYS = {
    "defFlipbook": {"id", "type", "provenance", "def", "clips", "effectMask", "bodyMask", "anchor", "texelsPerDefPx", "light",
                    "render", "unitPlane", "trail", "notes"},
    "uvAtlas": {"id", "type", "provenance", "regions", "modulate", "source", "gutterPx", "clips", "atlas", "cells", "notes"},
    "particles": {"id", "type", "provenance", "prefab", "anchor", "clips", "notes"},
    "volumetricFire": {"id", "type", "provenance", "source", "emitter", "systems", "anchor", "light", "clips", "clearAt",
                       "notes"},
    "effectLight": {"id", "type", "provenance", "lightId", "carrier", "anchor", "rgb", "range", "intensity", "floor",
                    "intensitySource", "notes"},
    "event": {"id", "type", "provenance", "clip", "defFrame", "action", "missile", "layer", "renderers", "notes"},
}
ANCHOR_KEYS = {"bone", "point", "towardLayerCentroid", "towardCameraU", "defOrigin", "boneTip"}
FLIP_CLIP_KEYS = {"defGroup", "frames"}
MASK_KEYS = {"method", "minLuma", "maxNeighbours", "indices", "path", "blueOverRed",
             "classes", "includeDetached", "novelMaxIdleCount", "minComponentPx", "rows"}
BODY_KEYS = {"subtractMeshSilhouette", "dilatePx", "rects"}


def spec_path(unit: str) -> Path:
    return SPEC_DIR / f"{unit}.json"


def out_dir(unit: str) -> Path:
    return OUT_ROOT / unit


def glb_path(unit: str) -> Path:
    return RETARGET / unit / f"{unit}_def_retarget.glb"


# The def_retarget GLB's bytes as the look stages see them. fleet_rebuild.py's fused delivery stages hand look apply
# their last output in memory (look.run_unit(glb_bytes=...)) instead of writing it to glb_path first; every read of
# the GLB in this package goes through glb_bytes() so the in-memory GLB is the one each check measures.
_GLB_IN_MEMORY: dict[str, bytes] = {}


@contextlib.contextmanager
def glb_in_memory(unit: str, data: bytes):
    if unit in _GLB_IN_MEMORY:
        raise RuntimeError(f"{unit}: an in-memory GLB is already installed")
    _GLB_IN_MEMORY[unit] = bytes(data)
    try:
        yield
    finally:
        del _GLB_IN_MEMORY[unit]


def glb_exists(unit: str) -> bool:
    return unit in _GLB_IN_MEMORY or glb_path(unit).is_file()


def glb_bytes(unit: str) -> bytes:
    b = _GLB_IN_MEMORY.get(unit)
    return glb_path(unit).read_bytes() if b is None else b


def blend_path(unit: str) -> Path:
    return RETARGET / unit / f"{unit}_def_retarget.blend"


def canonical_sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load(unit_or_path) -> dict:
    p = Path(unit_or_path)
    if not p.suffix:
        p = spec_path(str(unit_or_path))
    return json.loads(p.read_text(encoding="utf-8"))


def knobs_sha(spec: dict) -> str:
    lt = spec.get("lighting", {})
    d = {k: lt.get(k) for k in ("mode", "front", "arena", "knobs", "bakedGlow")}
    if lt.get("metal"):          # only when present, so every spec without it keeps its sha (and its stamp)
        d["metal"] = lt["metal"]
    if "finish" in lt:           # likewise: absent = the default finish, every existing sha kept
        d["finish"] = lt["finish"]
    return canonical_sha(d)


# ---------------------------------------------------------------------------- clips / DEF frames
def master_sequence(unit: str) -> dict:
    p = RUNS / unit / "linked_master/master_sequence/master_sequence.json"
    return json.loads(p.read_text(encoding="utf-8"))


def frames_meta(unit: str) -> dict:
    return json.loads((RETARGET / unit / f"{unit}_def_retarget.blend.frames.json").read_text(encoding="utf-8"))


def clip_segments(unit: str) -> dict:
    """GLB clip name -> the segment build_unit.py keyed it from (longest segment per contractSuffix),
    with the DEF (group, frame) of every key: {"Unit_X": {"defGroup", "masterFrames": [t...],
    "defFrames": [(g, f)...]}}. Master frame t is Blender frame t+1 and DEF source sources[t]."""
    ms = master_sequence(unit)
    fm = frames_meta(unit)
    clips = {}
    for s in ms["segments"]:
        n = "Unit_" + s["contractSuffix"]
        if n not in clips or s["frameCount"] > clips[n]["frameCount"]:
            clips[n] = s
    out = {}
    for n, s in clips.items():
        ts = list(range(s["globalStart"], s["globalEnd"]))
        df = []
        for t in ts:
            g, f = (int(x) for x in Path(fm["sources"][t]).stem.split("_")[:2])
            df.append((g, f))
        out[n] = {"defGroup": s["defGroup"], "masterFrames": ts, "defFrames": df}
    return out


def def_name(unit: str) -> str:
    src = Path(frames_meta(unit)["sources"][0])
    return src.parent.name.rsplit(".", 1)[0].upper() + ".DEF"


def glb_renderers(unit: str) -> set[str] | None:
    """Names of the GLB nodes that carry a mesh (the unit's renderers: body, rubble, props)."""
    import struct
    if unit in _GLB_IN_MEMORY:
        b = _GLB_IN_MEMORY[unit]
        n = struct.unpack("<I", b[12:16])[0]
        j = json.loads(b[20:20 + n])
        return {x.get("name", "") for x in j.get("nodes", []) if "mesh" in x}
    p = glb_path(unit)
    if not p.is_file():
        return None
    with open(p, "rb") as f:
        head = f.read(20)
        n = struct.unpack("<I", head[12:16])[0]
        j = json.loads(f.read(n))
    return {x.get("name", "") for x in j.get("nodes", []) if "mesh" in x}


def def_canvas(unit: str) -> tuple[int, int] | None:
    """(width, height) of the build's DEF frames (the SpriteCam canvas)."""
    try:
        from PIL import Image
        with Image.open(frames_meta(unit)["sources"][0]) as im:
            return im.size
    except Exception:  # noqa: BLE001
        return None


def build_info(unit: str) -> dict:
    return {"renderers": glb_renderers(unit), "canvas": def_canvas(unit)}


def light_floor(ly: dict, clip: str) -> float:
    """An effectLight's floor on ``clip``: a scalar floor holds in every clip, an object only in the clips it names."""
    fl = ly.get("floor", 0.0)
    if isinstance(fl, dict):
        return float(fl.get(clip, 0.0))
    return float(fl or 0.0)


def light_clips(ly: dict, clips: dict) -> list[str]:
    """Clips on which an effectLight exists: its curves plus every clip its floor holds in."""
    out = list(ly.get("intensity", {}))
    fl = ly.get("floor")
    if isinstance(fl, dict):
        out += [c for c, v in fl.items() if v > 0]
    elif isinstance(fl, (int, float)) and fl > 0:
        out += list(clips)
    return [c for c in dict.fromkeys(out) if c in clips]


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _xy(v) -> bool:
    return isinstance(v, list) and len(v) == 2 and all(_num(x) for x in v)


def _check_origin(e, w, org, ly, canvas):
    """anchor.defOrigin: "auto" | [x, y] | {clip: ["auto" | [x, y], ... one per listed frame]}."""
    pts = []
    if org == "auto":
        return
    if _xy(org):
        pts.append(org)
    elif isinstance(org, dict):
        cl = ly.get("clips") or {}
        for cn, seq in org.items():
            if cn not in cl:
                e.append(f"{w}: anchor.defOrigin names clip {cn!r} that the layer does not list")
                continue
            if not isinstance(seq, list) or len(seq) != len(cl[cn].get("frames") or []):
                e.append(f"{w}: anchor.defOrigin.{cn} must have one entry per listed frame ({len(cl[cn].get('frames') or [])})")
                continue
            for v in seq:
                if v == "auto":
                    continue
                if not _xy(v):
                    e.append(f"{w}: anchor.defOrigin.{cn} entries must be \"auto\" or [x, y]")
                else:
                    pts.append(v)
    else:
        e.append(f"{w}: anchor.defOrigin must be \"auto\", [x, y] or {{clip: [...per listed frame]}}")
    if canvas:
        W, H = canvas
        for x, y in pts:
            if not (0 <= x < W and 0 <= y < H):
                e.append(f"{w}: anchor.defOrigin [{x}, {y}] lies outside the DEF frame ({W}x{H})")


def _check_regions(e, wn, lt):
    regs = lt.get("regions")
    if regs is None:
        return []
    if not isinstance(regs, list) or not regs:
        e.append("lighting.regions must be a non-empty list when present")
        return []
    seg = lt.get("defSegmenter")
    if not (isinstance(seg, dict) and set(seg) <= {"module", "function", "notes"} and seg.get("module") and seg.get("function")):
        e.append("lighting.defSegmenter {module, function} is required with lighting.regions")
    else:
        err = segmenter_error(seg)
        if err:
            e.append(f"lighting.defSegmenter: {err}")
        elif not _tracked(seg["module"]):
            wn.append(f"lighting.defSegmenter module {seg['module']!r} is not in git (a fresh clone cannot rebuild the regions)")
    names = []
    for i, r in enumerate(regs):
        w = f"lighting.regions[{i}]"
        if not isinstance(r, dict):
            e.append(f"{w} must be an object")
            continue
        _unknown(e, w, r, REGION_KEYS)
        n = r.get("name")
        if not isinstance(n, str) or not re.fullmatch(r"[a-z0-9_]+", n or ""):
            e.append(f"{w}.name must be a lower-case id")
        elif n in names or n == "rest":
            e.append(f"{w}.name {n!r} is used twice or is the reserved 'rest'")
        names.append(n)
        if r.get("target") not in REGION_TARGETS:
            e.append(f"{w}.target must be one of {REGION_TARGETS}")
        if not isinstance(r.get("defRegion"), str) or not r.get("defRegion"):
            e.append(f"{w}.defRegion must name a key the defSegmenter returns")
        kn = r.get("knobs", {})
        if not isinstance(kn, dict):
            e.append(f"{w}.knobs must be an object")
        elif r.get("target") in REGION_KNOBS:
            _unknown(e, w + ".knobs", kn, REGION_KNOBS[r["target"]])
        m = r.get("mask")
        if not (isinstance(m, dict) and len(m) == 1 and next(iter(m)) in ("maskPath", "vertexColor", "bones")):
            e.append(f"{w}.mask must be exactly one of {{maskPath}}, {{vertexColor: {{channel, threshold}}}}, {{bones: [glob...]}}")
            continue
        if "maskPath" in m:
            mp = Path(m["maskPath"])
            if not (mp if mp.is_absolute() else ROOT / mp).is_file():
                e.append(f"{w}.mask.maskPath {m['maskPath']!r} does not exist")
            elif not _tracked(m["maskPath"]):
                wn.append(f"{w}.mask.maskPath {m['maskPath']!r} is not in git")
        elif "vertexColor" in m:
            vc = m["vertexColor"]
            if not (isinstance(vc, dict) and set(vc) == {"channel", "threshold"} and vc["channel"] in VERTEX_CHANNELS
                    and _num(vc["threshold"]) and 0 <= vc["threshold"] <= 1):
                e.append(f"{w}.mask.vertexColor must be {{channel: r|g|b|a, threshold: 0..1}}")
        else:
            b = m["bones"]
            if not (isinstance(b, list) and b and all(isinstance(x, str) and x for x in b)):
                e.append(f"{w}.mask.bones must be a non-empty list of joint-name globs")
    return names


_SEG_ERR: dict = {}


def segmenter_error(seg: dict) -> str:
    key = (seg.get("module"), seg.get("function"))
    if key not in _SEG_ERR:
        try:
            load_segmenter(seg)
            _SEG_ERR[key] = ""
        except Exception as ex:  # noqa: BLE001
            _SEG_ERR[key] = f"{type(ex).__name__}: {ex}"
    return _SEG_ERR[key]


def load_segmenter(seg: dict):
    """The unit's DEF segmenter: ``function(rgba_uint8 HxWx4) -> {key: bool HxW}`` from a repo module."""
    import importlib.util
    import sys
    mp = Path(seg["module"])
    mp = mp if mp.is_absolute() else ROOT / mp
    if not mp.is_file():
        raise FileNotFoundError(f"{seg['module']} does not exist")
    name = "unit_look_seg_" + re.sub(r"\W", "_", mp.stem)
    if name not in sys.modules:
        sys.path.insert(0, str(mp.parent))
        spec_ = importlib.util.spec_from_file_location(name, mp)
        mod = importlib.util.module_from_spec(spec_)
        spec_.loader.exec_module(mod)
        sys.modules[name] = mod
    fn = getattr(sys.modules[name], seg["function"], None)
    if not callable(fn):
        raise AttributeError(f"{seg['module']} has no function {seg['function']!r}")
    return fn


# ---------------------------------------------------------------------------- static validation
def _unknown(errs, where, d, allowed):
    for k in d:
        if k not in allowed:
            errs.append(f"{where}: unknown key {k!r}")


def validate(spec: dict, stem: str | None = None, clips: dict | None = None, warnings: list | None = None,
             info: dict | None = None) -> list[str]:
    """Static checks. ``clips`` (from clip_segments) enables clip-name / DEF-frame range checks; ``info``
    (from build_info) enables renderer-name and DEF-canvas checks. Non-fatal findings are appended to
    ``warnings`` when given."""
    info = info or {}
    e: list[str] = []
    wn = warnings if warnings is not None else []
    if not isinstance(spec, dict):
        return ["spec is not an object"]
    _unknown(e, "spec", spec, TOP_KEYS)
    if spec.get("schema") != SCHEMA:
        e.append(f"schema must be {SCHEMA!r}")
    unit = spec.get("unit")
    if not isinstance(unit, str) or not re.fullmatch(r"[a-z0-9_]+", unit or ""):
        e.append("unit must be a lower-case id")
    if stem is not None and unit != stem:
        e.append(f"unit {unit!r} does not match file stem {stem!r}")
    status = spec.get("status")
    if status not in ("look", "excluded"):
        e.append("status must be 'look' or 'excluded'")
    if status == "excluded":
        if not spec.get("excludedReason"):
            e.append("excluded spec needs excludedReason")
        return e
    lt = spec.get("lighting")
    if not isinstance(lt, dict):
        e.append("lighting section missing")
        lt = {}
    _unknown(e, "lighting", lt, LIGHTING_KEYS)
    if lt.get("mode") not in MODES:
        e.append(f"lighting.mode must be one of {MODES}")
    if lt.get("front") not in FRONTS:
        e.append(f"lighting.front must be one of {FRONTS}")
    if lt.get("arena", "sand") not in ARENAS:
        e.append(f"lighting.arena must be one of {ARENAS}")
    if not isinstance(lt.get("knobs", {}), dict):
        e.append("lighting.knobs must be an object")
    if lt.get("finish", "vanilla") not in FINISH_MODES:
        e.append(f"lighting.finish must be one of {FINISH_MODES}")
    region_names = _check_regions(e, wn, lt)
    if "metal" in lt:
        import metal as _metal
        cls = [c.get("name") for c in (lt.get("knobs") or {}).get("classes") or []] if lt.get("mode") == "v6m" else []
        e += _metal.validate(lt["metal"], cls)

    lights = spec.get("lights", [])
    if not isinstance(lights, list):
        e.append("lights must be a list")
        lights = []
    declared = {}
    for i, L in enumerate(lights):
        _unknown(e, f"lights[{i}]", L, LIGHT_KEYS)
        lid = L.get("id")
        if not lid:
            e.append(f"lights[{i}] has no id")
            continue
        if lid in declared:
            e.append(f"light id {lid!r} declared twice")
        if L.get("treatment") not in TREATMENTS:
            e.append(f"light {lid!r}: treatment must be one of {TREATMENTS}")
        declared[lid] = L.get("treatment")

    baked_refs: dict[str, int] = {}
    for i, g in enumerate(lt.get("bakedGlow", []) or []):
        _unknown(e, f"lighting.bakedGlow[{i}]", g, GLOW_KEYS)
        lid = g.get("lightId")
        baked_refs[lid] = baked_refs.get(lid, 0) + 1
        if not (g.get("materialClass") or g.get("maskPath")):
            e.append(f"bakedGlow[{i}] needs materialClass or maskPath")
        rgb = g.get("rgb")
        if not (isinstance(rgb, list) and len(rgb) == 3 and all(isinstance(x, (int, float)) and 0 <= x <= 1 for x in rgb)):
            e.append(f"bakedGlow[{i}].rgb must be 3 numbers in [0,1]")
        if not isinstance(g.get("strength"), (int, float)) or g["strength"] < 0:
            e.append(f"bakedGlow[{i}].strength must be >= 0")

    vfx = spec.get("vfx")
    if not isinstance(vfx, dict) or not isinstance(vfx.get("layers"), list):
        e.append("vfx.layers must be a list (empty when the unit has no VFX)")
        layers = []
    else:
        _unknown(e, "vfx", vfx, {"layers", "notes"})
        layers = vfx["layers"]
    ids = {}
    for i, ly in enumerate(layers):
        t = ly.get("type")
        lid = ly.get("id")
        w = f"vfx.layers[{i}]({lid})"
        if t not in LAYER_TYPES:
            e.append(f"{w}: type must be one of {LAYER_TYPES}")
            continue
        _unknown(e, w, ly, LAYER_KEYS[t])
        if "provenance" in ly and not isinstance(ly["provenance"], str):
            e.append(f"{w}: provenance must be a string")
        if not lid:
            e.append(f"{w}: no id")
        elif lid in ids:
            e.append(f"layer id {lid!r} used twice")
        ids[lid] = ly
    dyn_refs: dict[str, int] = {}
    for i, ly in enumerate(layers):
        t = ly.get("type")
        w = f"vfx.layers[{i}]({ly.get('id')})"
        if t in ("defFlipbook", "particles", "volumetricFire", "effectLight"):
            an = ly.get("anchor")
            if not isinstance(an, dict) or not an.get("bone"):
                e.append(f"{w}: anchor.bone required")
            else:
                _unknown(e, w + ".anchor", an, ANCHOR_KEYS)
                if "boneTip" in an and not isinstance(an["boneTip"], bool):
                    e.append(f"{w}: anchor.boneTip must be a bool")
                if "defOrigin" in an:
                    if t != "defFlipbook":
                        e.append(f"{w}: anchor.defOrigin is a defFlipbook key")
                    else:
                        _check_origin(e, w, an["defOrigin"], ly, info.get("canvas"))
        if t == "defFlipbook":
            cl = ly.get("clips")
            if not isinstance(cl, dict) or not cl:
                e.append(f"{w}: clips must map clip -> {{defGroup, frames}}")
                cl = {}
            for cn, c in cl.items():
                _unknown(e, f"{w}.clips.{cn}", c, FLIP_CLIP_KEYS)
                fr = c.get("frames")
                if not (isinstance(fr, list) and fr and all(isinstance(x, int) and x >= 0 for x in fr)):
                    e.append(f"{w}.clips.{cn}.frames must be a non-empty list of DEF frame indices")
                    fr = []
                if clips is not None:
                    if cn not in clips:
                        e.append(f"{w}: clip {cn!r} is not a built clip")
                    else:
                        if c.get("defGroup") != clips[cn]["defGroup"]:
                            e.append(f"{w}: {cn} defGroup {c.get('defGroup')} != built {clips[cn]['defGroup']}")
                        have = {f for _, f in clips[cn]["defFrames"]}
                        bad = [x for x in fr if x not in have]
                        if bad:
                            e.append(f"{w}: {cn} DEF frames {bad} are not keys of the built clip")
            m = ly.get("effectMask")
            if not isinstance(m, dict) or m.get("method") not in MASK_METHODS:
                e.append(f"{w}: effectMask.method must be one of {MASK_METHODS}")
            else:
                _unknown(e, w + ".effectMask", m, MASK_KEYS)
                if "rows" in m and not (isinstance(m["rows"], list) and len(m["rows"]) == 2
                                        and all(isinstance(x, int) for x in m["rows"]) and m["rows"][0] < m["rows"][1]):
                    e.append(f"{w}: effectMask.rows must be [y0, y1] integer pixels relative to the anchor pixel, y0 < y1")
                if m["method"] in ("palette", "paletteLuma") and not m.get("indices"):
                    e.append(f"{w}: effectMask.indices required for {m['method']}")
                if m["method"] == "file":
                    if not m.get("path"):
                        e.append(f"{w}: effectMask.path required for file")
                    else:
                        if not _tracked(m["path"]):
                            wn.append(f"{w}: effectMask file masks {m['path']!r} are not in git and not reproducible "
                                      "from the spec (a fresh clone cannot rebuild this layer)")
                        mp = Path(m["path"]) if Path(m["path"]).is_absolute() else ROOT / m["path"]
                        want = [f"{c['defGroup']:02d}_{x:02d}" for c in (cl or {}).values() if isinstance(c, dict)
                                and isinstance(c.get("defGroup"), int) for x in (c.get("frames") or []) if isinstance(x, int)]
                        if not mp.is_dir():
                            wn.append(f"{w}: effectMask file directory {m['path']!r} does not exist yet (pending); "
                                      "fit/vfx refuse to run until every listed frame has its PNG")
                        else:
                            miss = [k for k in want if not (mp / f"{k}.png").is_file()]
                            if miss:
                                e.append(f"{w}: effectMask file masks missing for listed frames {miss} "
                                         f"(expected {m['path']}/<GG_FF>.png)")
                if m["method"] == "defEffects":
                    cl = m.get("classes")
                    if not (isinstance(cl, list) and cl):
                        e.append(f"{w}: effectMask.classes must be a non-empty list")
                    elif any(c not in DEF_EFFECT_CLASSES for c in cl):
                        e.append(f"{w}: effectMask.classes {cl} must be from {DEF_EFFECT_CLASSES}")
                    if "includeDetached" in m and not isinstance(m["includeDetached"], bool):
                        e.append(f"{w}: effectMask.includeDetached must be a bool")
                    if "novelMaxIdleCount" in m and not isinstance(m["novelMaxIdleCount"], (int, float)):
                        e.append(f"{w}: effectMask.novelMaxIdleCount must be a number")
                    if "minComponentPx" in m and not (isinstance(m["minComponentPx"], int) and m["minComponentPx"] >= 0):
                        e.append(f"{w}: effectMask.minComponentPx must be an int >= 0")
                    err = def_effects_import_error()
                    if err:
                        e.append(f"{w}: defEffects needs tools/homm3_vfx/def_effects.py: {err}")
            if "bodyMask" in ly:
                _unknown(e, w + ".bodyMask", ly["bodyMask"], BODY_KEYS)
            if ly.get("render", "billboard") not in RENDERS:
                e.append(f"{w}: render must be one of {RENDERS}")
            if ly.get("render") in ("unitPlane", "trail") or "unitPlane" in ly or "trail" in ly:
                import vfx_depth
                e += vfx_depth.validate_layer(ly, w)
            if ly.get("light") is not None and ly["light"] not in declared:
                e.append(f"{w}: light {ly['light']!r} is not declared in lights[]")
        elif t == "uvAtlas":
            for k in ("atlas", "cells"):
                if k in ly:
                    wn.append(f"{w}: {k!r} is ignored: the runner builds the atlas itself, grading source.scores through "
                              "lighting.regions (there is no pre-graded-atlas path); remove it")
            src = ly.get("source")
            if "source" not in ly and "regions" not in ly:
                wn.append(f"{w}: pending (no source/regions yet): the runner fails closed on this layer until it names "
                          "source.scores and the defPalette regions that grade them")
            elif not (isinstance(src, dict) and set(src) <= {"scores", "generator", "notes"} and src.get("scores")):
                e.append(f"{w}: source {{scores: <npz with 'scores' (cells, H, W) in [0,1]>, generator}} required")
            else:
                sp = Path(src["scores"])
                if not (sp if sp.is_absolute() else ROOT / sp).is_file():
                    wn.append(f"{w}: source.scores {src['scores']!r} is missing here (regenerate with {src.get('generator')!r})")
                if not src.get("generator"):
                    e.append(f"{w}: source.generator (the script that writes source.scores) is required")
            rg = ly.get("regions")
            if "modulate" in ly:     # brightness-modulate variant (vfx.modulate_cells): no regions, a gain
                md = ly["modulate"]
                if "regions" in ly:
                    e.append(f"{w}: modulate and regions are exclusive (modulate keeps the look colours)")
                if not (isinstance(md, dict) and set(md) <= {"gain", "notes"}
                        and isinstance(md.get("gain"), (int, float)) and 0 < md["gain"] <= 1):
                    e.append(f"{w}: modulate must be {{gain: 0 < g <= 1}}")
            elif "source" not in ly and "regions" not in ly:
                pass
            elif not (isinstance(rg, list) and rg and all(isinstance(x, str) for x in rg)):
                e.append(f"{w}: regions must list lighting.regions names (defPalette) the cells are graded through")
            else:
                byname = {r.get("name"): r for r in (lt.get("regions") or []) if isinstance(r, dict)}
                for x in rg:
                    if x not in region_names:
                        e.append(f"{w}: region {x!r} is not in lighting.regions")
                    elif byname[x].get("target") != "defPalette":
                        e.append(f"{w}: region {x!r} must be a defPalette region (the scores rank-map onto its DEF palette)")
            if "gutterPx" in ly and not (isinstance(ly["gutterPx"], int) and ly["gutterPx"] >= 0):
                e.append(f"{w}: gutterPx must be an int >= 0")
            if not ly.get("clips"):
                e.append(f"{w}: clips required")
            if clips is not None:
                for cn, seq in (ly.get("clips") or {}).items():
                    if cn not in clips:
                        e.append(f"{w}: clip {cn!r} is not a built clip")
                    elif len(seq) != len(clips[cn]["defFrames"]):
                        e.append(f"{w}: {cn} has {len(seq)} cells for {len(clips[cn]['defFrames'])} DEF frames")
        elif t == "particles":
            if not ly.get("prefab"):
                e.append(f"{w}: prefab required")
        elif t == "volumetricFire":
            import volfire
            volfire.validate(e, w, ly, spec, clips)
            if ly.get("light") is not None and ly["light"] not in declared:
                e.append(f"{w}: light {ly['light']!r} is not declared in lights[]")
        elif t == "effectLight":
            lid = ly.get("lightId")
            dyn_refs[lid] = dyn_refs.get(lid, 0) + 1
            car = ly.get("carrier")
            if car not in ids or ids[car].get("type") not in ("defFlipbook", "particles", "volumetricFire"):
                e.append(f"{w}: carrier must be a defFlipbook, particles or volumetricFire layer id")
            rgb = ly.get("rgb")
            if not (isinstance(rgb, list) and len(rgb) == 3):
                e.append(f"{w}: rgb must be 3 numbers")
            if not isinstance(ly.get("range"), (int, float)) or ly["range"] <= 0:
                e.append(f"{w}: range must be > 0")
            if ly.get("intensitySource") not in ("fitted", "authored"):
                e.append(f"{w}: intensitySource must be 'fitted' or 'authored'")
            inten = ly.get("intensity")
            if not isinstance(inten, dict) or not inten:
                e.append(f"{w}: intensity must map clip -> per-DEF-frame list")
                inten = {}
            fl = ly.get("floor", 0.0)
            if isinstance(fl, dict):
                bad = [c for c, v in fl.items() if not (_num(v) and v >= 0)]
                if bad:
                    e.append(f"{w}: floor.{bad[0]} must be a number >= 0")
                if clips is not None:
                    for c in fl:
                        if c not in clips:
                            e.append(f"{w}: floor names clip {c!r} that is not a built clip")
            elif not (_num(fl) and fl >= 0):
                e.append(f"{w}: floor must be a number >= 0 or {{clip: number}}")
            for cn, seq in inten.items():
                if not (isinstance(seq, list) and all(isinstance(x, (int, float)) and x >= 0 for x in seq)):
                    e.append(f"{w}: intensity.{cn} must be a list of numbers >= 0")
                    continue
                f0 = light_floor(ly, cn) if (isinstance(fl, dict) and all(_num(v) for v in fl.values())) or _num(fl) else 0.0
                if seq and f0 > min(seq) + 1e-9:
                    e.append(f"{w}: floor {f0} on {cn} exceeds the curve's minimum {min(seq)} (0 <= floor <= min(curve))")
                elif clips is not None:
                    if cn not in clips:
                        e.append(f"{w}: clip {cn!r} is not a built clip")
                    elif len(seq) != len(clips[cn]["defFrames"]):
                        e.append(f"{w}: intensity.{cn} has {len(seq)} values for {len(clips[cn]['defFrames'])} DEF frames")
        elif t == "event":
            if ly.get("action") not in EVENT_ACTIONS:
                e.append(f"{w}: action must be one of {EVENT_ACTIONS}")
            if not isinstance(ly.get("defFrame"), int):
                e.append(f"{w}: defFrame must be an int")
            if ly.get("action") in ("activate", "deactivate") and ly.get("layer") not in ids:
                e.append(f"{w}: layer must name a layer id")
            if ly.get("action") == "missile" and not isinstance(ly.get("missile"), dict):
                e.append(f"{w}: missile object required")
            if "renderers" in ly:
                rr = ly["renderers"]
                if ly.get("action") not in ("hideMesh", "showMesh"):
                    e.append(f"{w}: renderers is a hideMesh/showMesh key")
                elif not (isinstance(rr, list) and rr and all(isinstance(x, str) for x in rr)):
                    e.append(f"{w}: renderers must be a non-empty list of GLB mesh node names (omit it for all renderers)")
                elif info.get("renderers") is not None:
                    bad = [x for x in rr if x not in info["renderers"]]
                    if bad:
                        e.append(f"{w}: renderers {bad} are not GLB renderers {sorted(info['renderers'])}")
            if clips is not None:
                cn = ly.get("clip")
                if cn not in clips:
                    e.append(f"{w}: clip {cn!r} is not a built clip")
                elif isinstance(ly.get("defFrame"), int) and ly["defFrame"] not in {f for _, f in clips[cn]["defFrames"]}:
                    e.append(f"{w}: defFrame {ly['defFrame']} is not a key of {cn}")

    # the double-counting rule
    for lid, tr in declared.items():
        b, d = baked_refs.get(lid, 0), dyn_refs.get(lid, 0)
        if b and d:
            e.append(f"light {lid!r} is both baked (bakedGlow) and dynamic (effectLight): double-counted")
        elif tr == "baked" and (b != 1 or d):
            e.append(f"baked light {lid!r} must be referenced by exactly one bakedGlow and no effectLight")
        elif tr == "dynamic" and (d != 1 or b):
            e.append(f"dynamic light {lid!r} must be referenced by exactly one effectLight and no bakedGlow")
    for lid in set(baked_refs) | set(dyn_refs):
        if lid not in declared:
            e.append(f"light {lid!r} is used but not declared in lights[]")
    return e


def _tracked(path: str) -> bool:
    import subprocess
    p = Path(path)
    p = p if p.is_absolute() else ROOT / p
    try:
        r = subprocess.run(["git", "-C", str(ROOT), "ls-files", "--", str(p)],
                           capture_output=True, text=True, timeout=60)
    except Exception:  # noqa: BLE001
        return False
    return r.returncode == 0 and bool(r.stdout.strip())


_DEF_FX_ERR: list = []


def def_effects_import_error() -> str:
    """'' when tools/homm3_vfx/def_effects.py imports and exposes the API the runner calls."""
    if not _DEF_FX_ERR:
        import sys
        sys.path.insert(0, str(ROOT / "tools/homm3_vfx"))
        try:
            import def_effects as de  # noqa: F401
            import inspect
            missing = [n for n in ("load_unit", "baseline", "frame_effects", "EFFECT_CLASSES") if not hasattr(de, n)]
            msg = f"missing {missing}" if missing else ""
            if not missing:
                fe = inspect.signature(de.frame_effects).parameters
                bl = inspect.signature(de.baseline).parameters
                need_fe = [k for k in ("classes", "include_detached", "min_component_px") if k not in fe]
                if need_fe or "novel_max_idle_count" not in bl:
                    msg = (f"API changed: frame_effects lacks {need_fe}" if need_fe else "") + \
                          ("" if "novel_max_idle_count" in bl else " baseline lacks novel_max_idle_count")
            if not missing and tuple(de.EFFECT_CLASSES) != DEF_EFFECT_CLASSES:
                msg = f"EFFECT_CLASSES changed to {de.EFFECT_CLASSES}; update spec.DEF_EFFECT_CLASSES"
            _DEF_FX_ERR.append(msg)
        except Exception as ex:  # noqa: BLE001
            _DEF_FX_ERR.append(f"{type(ex).__name__}: {ex}")
    return _DEF_FX_ERR[0]


def dynamic_zero_frames(spec: dict, clips: dict) -> set[int]:
    """Master frames where some dynamic light exceeds its floor (excluded from the grade fit; the fit holds
    every light at its floor on the frames it keeps)."""
    lit = set()
    for ly in spec.get("vfx", {}).get("layers", []):
        if ly.get("type") != "effectLight":
            continue
        for cn, seq in ly.get("intensity", {}).items():
            if cn in clips:
                f0 = light_floor(ly, cn)
                for t, v in zip(clips[cn]["masterFrames"], seq):
                    if v > f0 + 1e-6:
                        lit.add(t)
    return lit
