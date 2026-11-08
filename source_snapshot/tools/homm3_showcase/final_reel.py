"""Final showcase reel: one screen per faction x upgrade level, every DEF clip of every unit, with VFX + metal shine.

    python tools/homm3_showcase/final_reel.py screens                    # list the screens and their units
    python tools/homm3_showcase/final_reel.py icons                      # extract the ability icons once
    python tools/homm3_showcase/final_reel.py screen castle_base         # render + encode one screen (resumable)
    python tools/homm3_showcase/final_reel.py all [--skip conflux]       # every screen, one Unity job at a time
    python tools/homm3_showcase/final_reel.py concat                     # the full reel from the screen MP4s

Groups: faction = tools/homm3_authenticity/ledger.json `faction`; upgrade level = the gameSid's `branch` in the ability
catalog regenerated from the installed Core.zip (tools/generate_homm3_custom_unit_ability_catalog.py --json-output
<work>/abilities/catalog.json); the tracked static catalog is older than the installed Core. Neutrals (absent from
the catalog) are one screen. Parked units are excluded (PARKED).

Assets: the pinned frozen GLB + inputs/basecolor.png of each unit's live delivery selection
(tools/homm3_authenticity/sources.shipped_glb; a fallback canonical GLB is refused).

Render: tools/homm3_vfx/unity/Homm3VanillaStyleVfxLab.cs (Hex/Lit emission replica, vanilla-style particle replicas)
through the Unity queue, one job per screen, as a generated copy (LAB_CLASS) that adds
  * streaming backpressure (as tools/homm3_authenticity/showcase_video.py), and
  * the shipped metal shine: OldenEra/Homm3/MetalShine appended to the body SMR with the plugin catalog's mask and
    values (OfflineUnlockMod/homm3_mesh_fx/metal_shine/catalog.json), lit by the same sun as the body.
Vanilla-style units get their compiled effect rows (as showcase_video.py) plus the spec's emissionMap and bodyOverlay
layers. The PPv2-like bloom runs on the GPU in the frame consumer.

Timeline: the screen plays phases (Idle, Move = MoveStart + Move cycles + MoveEnd, Mouse-over, Attack, Ranged, Defend,
Hit, Death, any other DEF clip). In a phase every unit plays its clip as whole cycles only; a unit done before the
longest one holds its last (loop-seam) pose, so no clip is cut mid-cycle. A unit without the phase's clip is dimmed.
Every unit on a screen shares one world scale (game-distance relative sizes); no close-ups.

Proof tier: generated artifact (Unity editor lab render with replica shaders), not an in-game capture. Engine-spawned
projectiles are not drawn.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/homm3_authenticity"))
from sources import def_reference, shipped_glb, unit_ids  # noqa: E402
import showcase_video as SV  # noqa: E402  (battle camera, bloom, compiled-row effects, encode)

VSL = SV.VSL
WORK = Path("V:/olden_port_work/showcase/final_reel")
CATALOG = WORK / "abilities/catalog.json"
ICONS = WORK / "abilities/icons"
LEDGER = ROOT / "tools/homm3_authenticity/ledger.json"
PLUGIN = ROOT / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod"
SHINE_CATALOG = PLUGIN / "homm3_mesh_fx/metal_shine/catalog.json"
SHINE_SHADER = ROOT / "tools/homm3_import/unity_shaders/Homm3MetalShine.shader"
MOD_ICONS = PLUGIN / "homm3_skill_icons"
GAME_DATA = Path("V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era/HeroesOldenEra_Data")

PARKED = {"hota_factory_sandworm_larva", "h3_satyr", "h3_cannon"}
FACTION_ORDER = ["castle", "rampart", "tower", "inferno", "necropolis", "dungeon", "stronghold", "fortress", "conflux",
                 "cove", "factory", "bulwark", "neutral"]
LEVELS = [("base", "Unupgraded"), ("upg", "Upgraded"), ("alt", "Alternate upgrades")]
NEUTRAL_TIER = {"h3_peasant": 1, "h3_neutral_halfling": 1, "h3_boar": 2, "h3_rogue": 2, "h3_leprechaun": 2,
                "h3_mummy": 3, "h3_nomad": 3, "h3_steel_golem": 4, "h3_troll": 5, "h3_fangarm": 6}

W, H, FPS = 1920, 1080, 30
SS = 1.5                       # Unity render density over the final tile px (no MSAA in the lab; downsampled)
BG = SV.BG
FG, DIM = SV.FG, SV.DIM
HEADER_H = 92
ABIL_H = 112                   # ability strip under each unit (always reserved so rows line up)
NAME_H = 30
MARGIN = 0.10                  # world margin around a unit's motion box (particles, bloom)
GAME_PPU = 150.0               # cap: px per world unit at 1080p (keeps a tier-1 unit near in-game battle size)
TITLE_S = 2.0
MIN_LOOP_S = 2.4               # Idle / Move phases run at least this long (whole cycles)
ONE_SHOT_TAIL_S = 0.35
MOVE_EDGE_TAIL_S = 0.0         # MoveStart / MoveEnd lead straight into the next part
DEATH_HOLD_S = 0.8
GAP_S = 0.25                   # still beat between phases
STAGE_SUB = "final_showcase"
LAB_CLASS = "Homm3FinalShowcaseLab"
LAB_SCRIPT = "Assets/Editor/Homm3FinalShowcase/Homm3FinalShowcaseLab.cs"
LAB_METHOD = f"OldenEra.Homm3Vfx.{LAB_CLASS}.RunFromCommandLine"
SHINE_ASSET = f"{VSL.ASSET_ROOT}/{STAGE_SUB}/Homm3MetalShine.shader"
MAX_PENDING_FRAMES = 60
PAIR_GAP = 14                  # px between a unit's DEF (left) and mesh (right) halves
MIN_COL_W = 290
CAP_H = 18                     # "HoMM3 DEF" / "mesh" captions above each half

PHASES = [  # (phase label, clip sequence; '*' marks the looping body of the phase)
    ("Idle", ["*Unit_Idle"]),
    ("Move", ["Unit_MoveStart", "*Unit_Move", "Unit_MoveEnd"]),
    ("Mouse-over", ["Unit_Mouseover"]),
    ("Melee attack", ["Unit_AttackFront"]),
    ("Ranged attack / cast", ["Unit_ShootFront"]),
    ("Defend", ["Unit_Defence"]),
    ("Hit", ["Unit_Hitted"]),
    ("Death", ["Unit_Death"]),
]
KNOWN = {c.lstrip("*") for _, seq in PHASES for c in seq}


def font(size, bold=False):
    return SV.font(size, bold)


# ------------------------------------------------------------------ groups
def load_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8-sig"))


def catalog():
    if not CATALOG.is_file():
        raise SystemExit(f"no regenerated ability catalog at {CATALOG}; run tools/generate_homm3_custom_unit_ability_"
                         f"catalog.py --output {CATALOG.with_suffix('.md')} --json-output {CATALOG}")
    return {u["sid"]: u for u in load_json(CATALOG)["units"]}


def level_of(branch: str) -> str:
    if branch.startswith("base"):
        return "base"
    if branch.startswith("standard"):
        return "upg"
    if branch.startswith("alternate"):
        return "alt"
    raise SystemExit(f"unknown catalog branch {branch!r}")


def screens() -> list[dict]:
    units = load_json(LEDGER)["units"]
    cat = catalog()
    groups: dict[tuple, list] = {}
    for lab, row in units.items():
        if lab in PARKED:
            continue
        fac = row["faction"]
        gsid = row["gameSids"][0]
        if fac == "neutral":
            lvl, tier, name, cu = "base", NEUTRAL_TIER.get(lab, 9), lab.replace("h3_", "").replace("_", " ").title(), None
        else:
            cu = cat.get(gsid)
            if cu is None:
                raise SystemExit(f"{lab}: gameSid {gsid} not in the regenerated catalog")
            lvl, tier, name = level_of(cu["branch"]), cu["tier"], cu["name"]
        groups.setdefault((fac, lvl), []).append({"lab": lab, "gameSid": gsid, "tier": tier, "name": name,
                                                  "actives": (cu or {}).get("actives", [])})
    out = []
    for fac in FACTION_ORDER:
        for lvl, label in LEVELS:
            us = groups.pop((fac, lvl), None)
            if not us:
                continue
            us.sort(key=lambda u: (u["tier"], u["gameSid"]))
            title = "Neutral creatures" if fac == "neutral" else f"{fac.title()}  \u00b7  {label}"
            out.append({"id": f"{fac}_{lvl}", "faction": fac, "level": lvl, "title": title, "units": us})
    if groups:
        raise SystemExit(f"ungrouped units: {sorted(groups)}")
    for i, s in enumerate(out, 1):
        s["index"] = i
    return out


# ------------------------------------------------------------------ ability icons
def icons() -> None:
    """Every active ability's icon: the mod's own keys from OfflineUnlockMod/homm3_skill_icons, the game's from the
    installed resources.assets (UnityPy, read-only). Keys with no art are listed in icons_missing.json."""
    need = {a["icon"] for u in catalog().values() for a in u["actives"] if a.get("icon")}
    ICONS.mkdir(parents=True, exist_ok=True)
    todo = set()
    for k in sorted(need):
        dst = ICONS / f"{k}.png"
        if dst.is_file():
            continue
        mod = MOD_ICONS / f"{k}.png"
        if mod.is_file():
            Image.open(mod).convert("RGBA").save(dst)
        else:
            todo.add(k)
    if todo:
        import UnityPy
        env = UnityPy.load(str(GAME_DATA / "resources.assets"))
        for o in env.objects:
            if o.type.name != "Texture2D":
                continue
            nm = o.peek_name()
            if nm in todo:
                o.read().image.convert("RGBA").save(ICONS / f"{nm}.png")
                todo.discard(nm)
    # a key with no art in the mod or the game (the game would draw its placeholder) is shown as text only
    (ICONS.parent / "icons_missing.json").write_text(json.dumps(sorted(todo), indent=1), encoding="utf-8")
    if todo:
        print(f"icons with no art anywhere (text only): {sorted(todo)}")
    print(f"icons: {len(need)} in {ICONS}")


# ------------------------------------------------------------------ per-unit plan
def shine_rows() -> dict:
    doc = load_json(SHINE_CATALOG)
    out = {}
    for e in doc["entries"]:
        for sid in e["match"]["unitSids"]:
            out[sid] = e
    return out


def plan_unit(lab: str, gsid: str, shines: dict, fps: int) -> dict:
    import torch
    import raster as R
    from gltf_scene import Scene

    lab, src = unit_ids(lab)
    sel = shipped_glb(lab, src)
    if sel["mode"] != "shipped" or not sel.get("albedo"):
        raise RuntimeError(f"no pinned shipped GLB + basecolor ({sel['notes']})")
    row = sel["row"] or {}
    ref = def_reference(src)
    scene = Scene(sel["path"], body_name=src, skip_meshes=tuple((row.get("deferMeshes") or {})))
    defs = {c["clip"]: c for c in ref["clips"]}
    names = [c for c in [x.lstrip("*") for _, seq in PHASES for x in seq] if c in defs and c in scene.anims]
    names += [c for c in defs if c not in KNOWN and c in scene.anims]       # any other DEF clip, DEF order
    clips = []
    for name in names:
        c = defs[name]
        rng = scene.clip_range(name)
        loop = bool(c.get("loop")) or name in ("Unit_Idle", "Unit_Move")
        length = rng["end"]
        tail = MOVE_EDGE_TAIL_S if name in ("Unit_MoveStart", "Unit_MoveEnd") else ONE_SHOT_TAIL_S
        frames = max(1, int(round(length * fps))) if loop else int(math.ceil((length + tail) * fps))
        clips.append({"name": name, "n": len(c["frames"]), "length": length, "loop": loop, "frames": frames})
    if not clips:
        raise RuntimeError("no clip in both the DEF reference and the GLB")
    # DEF view: the board's SpriteCam (+ delivery deyaw) turned by the per-unit view yaw fitted in def_view.py, so the
    # mesh faces the way the DEF does; DEF pixels map to world through that fit's Idle frame-0 similarity
    import def_view
    view = def_view.view_for(lab)
    deyaw = view["deyawDeg"]
    right, up, fwd = (np.asarray(view[k], np.float64) for k in ("right", "up", "fwd"))
    dev = R.resolve_device("cuda")
    mesh = R.DeviceMesh(scene, dev, np.zeros((2, 2, 4), np.float32))
    rt, ut = (torch.as_tensor(x, dtype=torch.float32, device=dev) for x in (right, up))
    lo, hi = [1e9, 1e9], [-1e9, -1e9]
    for c in clips:
        t = np.minimum(np.arange(1, c["frames"] + 1) / fps, c["length"])
        Jm, mw = scene.pose(c["name"], t)
        P, _ = mesh.skin(Jm, mw)
        u, v = (P @ rt), (P @ ut)
        lo = [min(lo[0], float(u.min())), min(lo[1], float(v.min()))]
        hi = [max(hi[0], float(u.max())), max(hi[1], float(v.max()))]
    dmap = view["defMap"]
    dnote = f"view yaw {view['viewYawDeg']:+g} deg off the SpriteCam; {view['defMapNote']}"
    del mesh
    torch.cuda.empty_cache()
    for c in clips:
        d = defs[c["name"]]
        rng = scene.clip_range(c["name"])
        tk = int((d.get("loop") or {}).get("transitionKeys", 0))
        msteps = (c["n"] - 1) + ((1 + tk) if d.get("loop") else 0)
        c["def"] = {"frames": [str(f) for f in d["frames"]], "start": rng["start"],
                    "step": rng["duration"] / msteps if msteps > 0 else 1 / 12}
        for f in d["frames"]:
            a = np.asarray(Image.open(f).convert("RGBA").getchannel("A")) > 0
            yy, xx = np.nonzero(a)
            if len(xx):
                lo = [min(lo[0], (xx.min() - dmap["cx"]) / dmap["s"]), min(lo[1], (dmap["cy"] - yy.max() - 1) / dmap["s"])]
                hi = [max(hi[0], (xx.max() + 1 - dmap["cx"]) / dmap["s"]), max(hi[1], (dmap["cy"] - yy.min()) / dmap["s"])]
    lo, hi = [float(x) for x in lo], [float(x) for x in hi]
    m = MARGIN * max(hi[0] - lo[0], hi[1] - lo[1])
    lo, hi = [lo[0] - m, lo[1] - m * 0.25], [hi[0] + m, hi[1] + m]
    effects, overlays, emission, fx_note = [], [], None, "no unit VFX in the shipped selection row"
    if row.get("vfxAuthority") == "vanilla_style":
        spec, tier = VSL.unit_spec(lab)
        if tier != "shipped":
            raise RuntimeError(f"selection row is vanilla_style but the spec is a {tier}")
        comp = load_json(ROOT / "tools/homm3_vfx/vanilla_style/compiled" / f"{lab}.json")
        rows = {r["id"]: r for r in comp["rows"]}
        lengths = comp["clipLengths"]
        body_orient = [l["id"] for l in spec["layers"] if l["type"] == "vanillaParticles" and l.get("orient") == "body"]
        if body_orient:   # orient body: built as bone layers, then the root turned like Homm3MeshFx.OrientVanilla
            spec = dict(spec, layers=[dict(l, orient="bone") if l["id"] in body_orient else l for l in spec["layers"]])
        for e in VSL.spec_layer_effects(lab, spec):
            lid = next(l["id"] for l in spec["layers"] if e["id"].startswith(l["id"] + "_"))
            layer = next(l for l in spec["layers"] if l["id"] == lid)
            # compiled row ids (vanilla_style_fx.compile rows): vs_<lab>_<layer>[_<bone> if several bones]
            # [_t<k> per spec trigger if several]; the lab effect id is <layer>_<bone>
            bone = e["id"][len(lid) + 1:]
            base = f"vs_{lab}_{lid}" + (f"_{bone}" if len(layer.get("bones") or []) > 1 else "")
            trs = layer.get("triggers") or [{"mode": "always"}]
            pairs = [(t, rows[base + (f"_t{k}" if len(trs) > 1 else "")]) for k, t in enumerate(trs)]
            if not pairs:
                raise RuntimeError(f"no compiled row for {base}")
            if any(t.get("mode") != "always" for t, _ in pairs):
                e["triggers"], e["stops"] = [], []
                for t, r in pairs:
                    if t.get("mode") == "always":
                        continue
                    nt, clip = r["trigger"]["normalizedTime"], t["clip"]
                    e["triggers"].append({"clip": clip, "time": nt[0] * lengths[clip]})
                    if nt[1] < 1.0:
                        e["stops"].append({"clip": clip, "time": nt[1] * lengths[clip]})
            r = pairs[0][1]
            if lid in body_orient:
                # runtime: root.rotation = basis * Euler(0, bodyYawDeg, 0); the lab body root is the identity basis
                half = math.radians(float(r["vanillaStyle"].get("bodyYawDeg", 0.0))) / 2
                e["rootWorldRot"] = [0.0, math.sin(half), 0.0, math.cos(half)]
            if r["vanillaStyle"].get("boneLocalRot"):
                e["rot"] = r["vanillaStyle"]["boneLocalRot"]
            effects.append(e)
        lab_clips = [{"name": c["name"], "frames": c["frames"], "frameStep": 1.0 / fps} for c in clips]
        overlays = VSL.spec_overlays(spec, lab_clips)
        em = next((l for l in spec["layers"] if l["type"] == "emissionMap"), None)
        if em and (any(em["color"]) or em["minPower"] or em["blinkPower"]):
            emission = em
        fx_note = (f"vanilla-style: {len(effects)} effects, {len(overlays)} overlays, "
                   f"emission {'on' if emission else 'off'}"
                   + (f"; orient body (root yaw from the compiled row): {', '.join(body_orient)}" if body_orient else ""))
    shine = shines.get(gsid) or shines.get(lab)
    return {"lab": lab, "src": src, "gameSid": gsid, "glb": str(sel["path"]), "glbSha256": sel["sha256"],
            "selection": sel["selection"], "albedo": str(sel["albedo"]), "clips": clips, "box": [lo, hi],
            "effects": effects, "overlays": overlays, "emission": emission, "fxNote": fx_note,
            "shine": shine, "notes": sel["notes"], "dirs": {"right": right.tolist(), "up": up.tolist(), "fwd": fwd.tolist()},
            "defMap": dmap, "defNote": dnote, "deyawDeg": deyaw}


# ------------------------------------------------------------------ layout
def layout(plans: list[dict]) -> dict:
    """Rows in tier order, one shared px-per-world-unit (capped at GAME_PPU). Each unit gets a column as wide as its
    DEF + mesh pair (at least MIN_COL_W for the ability text); spare row width is shared out. The pair sits on the
    row's ground line, the name + ability strip under it."""
    n = len(plans)
    pw = {p["lab"]: p["box"][1][0] - p["box"][0][0] for p in plans}

    def col_w(p, ppu):
        return max(2 * pw[p["lab"]] * ppu + PAIR_GAP + 16, MIN_COL_W)

    from itertools import combinations

    def abil_h(ch):           # the ability strip is reserved only on rows that have one
        return ABIL_H if any(p.get("actives") for p in ch) else 0

    best = None
    splits = [()] + [c for r in range(1, min(4, n)) for c in combinations(range(1, n), r)]
    for cut in splits:
        edges = (0,) + tuple(cut) + (n,)
        chunks = [plans[a:b] for a, b in zip(edges, edges[1:])]
        avail_h = H - HEADER_H - 10 - sum(abil_h(ch) + NAME_H + CAP_H for ch in chunks)
        hs = [max(p["box"][1][1] - p["box"][0][1] for p in ch) for ch in chunks]
        lo_, hi_ = 1.0, min(GAME_PPU, avail_h / sum(hs))
        if hi_ <= lo_:
            continue
        for _ in range(40):
            mid = (lo_ + hi_) / 2
            if all(sum(col_w(p, mid) for p in ch) <= W - 40 for ch in chunks):
                lo_ = mid
            else:
                hi_ = mid
        ppu = lo_
        if best is None or ppu > best[0] * 1.001:
            best = (ppu, chunks, hs)
    ppu, chunks, hs = best
    used = sum(h * ppu + abil_h(ch) + NAME_H + CAP_H for ch, h in zip(chunks, hs))
    y = HEADER_H + max(0, (H - HEADER_H - used) / 2)
    rects = {}
    for ch, rh in zip(chunks, hs):
        cws = [col_w(p, ppu) for p in ch]
        extra = (W - 40 - sum(cws)) / len(ch)
        cws = [c + extra for c in cws]
        x0 = 20
        base = y + CAP_H + rh * ppu       # the row's ground line (box bottoms)
        for p, cw in zip(ch, cws):
            w = (p["box"][1][0] - p["box"][0][0]) * ppu
            h = (p["box"][1][1] - p["box"][0][1]) * ppu
            cx = x0 + cw / 2
            rects[p["lab"]] = {"x": int(round(cx + PAIR_GAP / 2)), "defX": int(round(cx - PAIR_GAP / 2 - w)),
                               "y": int(round(base - h)), "w": max(8, int(round(w))),
                               "h": max(8, int(round(h))), "labelY": int(round(base + 4)), "cx": int(round(cx)),
                               "colW": int(cw - 12)}
            x0 += cw
        y = base + NAME_H + abil_h(ch)
    return {"ppu": ppu, "rects": rects}


def panel_cam(p: dict, rect: dict, ppu: float) -> dict:
    right, up, fwd = (np.asarray(p["dirs"][k]) for k in ("right", "up", "fwd"))
    (x0, y0), (x1, y1) = p["box"]
    c = right * (x0 + x1) / 2 + up * (y0 + y1) / 2
    return {"camRight": SV.g2u(right), "camUp": SV.g2u(up), "camForward": SV.g2u(fwd), "camCentre": SV.g2u(c),
            "orthoSize": (y1 - y0) / 2, "width": int(round(rect["w"] * SS)), "height": int(round(rect["h"] * SS))}


# ------------------------------------------------------------------ stage + Unity
# Measured 2026-10-12: building the Animator path (a curve-by-curve clip copy, .anim + controller assets, SaveAssets)
# took ~4.4 s per unit, ~70% of the in-editor time, while rendering + readback took ~4 ms per tile-frame. The glTF
# clips are sampled directly instead (AnimationClip.SampleAnimation at the same absolute clip time, quaternion
# continuity fixed in memory; nothing is written to the project).
ANIM_OLD = """                b.animator = b.go.GetComponent<Animator>() ?? b.go.AddComponent<Animator>();
                b.animator.applyRootMotion = false; b.animator.cullingMode = AnimatorCullingMode.AlwaysAnimate;
                string clipRoot = job.assetRoot + "/clips_" + p.id;
                if (!AssetDatabase.IsValidFolder(clipRoot)) AssetDatabase.CreateFolder(job.assetRoot, "clips_" + p.id);
                string ctrlPath = clipRoot + "/lab.controller";
                AssetDatabase.DeleteAsset(ctrlPath);
                AnimatorController ctrl = AnimatorController.CreateAnimatorControllerAtPath(ctrlPath);
                foreach (ClipDef c in p.clips)
                {
                    AnimationClip src = glbClips.FirstOrDefault(x => x.name == c.name || x.name.EndsWith(c.name, StringComparison.Ordinal));
                    if (src == null) throw new InvalidOperationException("clip " + c.name + " missing");
                    var copy = new AnimationClip { name = "vs_" + c.name, frameRate = src.frameRate, legacy = false };
                    foreach (EditorCurveBinding eb in AnimationUtility.GetCurveBindings(src)) AnimationUtility.SetEditorCurve(copy, eb, AnimationUtility.GetEditorCurve(src, eb));
                    copy.EnsureQuaternionContinuity();
                    string cp = clipRoot + "/" + copy.name + ".anim";
                    AssetDatabase.DeleteAsset(cp); AssetDatabase.CreateAsset(copy, cp);
                    AnimatorState st = ctrl.AddMotion(copy); st.name = c.name;
                    b.lengths[c.name] = copy.length;
                }
                AssetDatabase.SaveAssets();
                b.animator.runtimeAnimatorController = ctrl; b.animator.Rebind();"""
ANIM_NEW = """                foreach (Animator an in b.go.GetComponentsInChildren<Animator>(true)) UnityEngine.Object.DestroyImmediate(an);
                b.animator = null;
                // the Animator path wrote defaults (the instantiated pose) for curves a clip lacks; keep that
                foreach (Transform t in b.go.GetComponentsInChildren<Transform>(true)) b.rest.Add((t, t.localPosition, t.localRotation, t.localScale));
                foreach (SkinnedMeshRenderer sk in b.go.GetComponentsInChildren<SkinnedMeshRenderer>(true))
                    if (sk.sharedMesh != null && sk.sharedMesh.blendShapeCount > 0)
                        b.restW.Add((sk, Enumerable.Range(0, sk.sharedMesh.blendShapeCount).Select(i => sk.GetBlendShapeWeight(i)).ToArray()));
                foreach (ClipDef c in p.clips)
                {
                    AnimationClip src = glbClips.FirstOrDefault(x => x.name == c.name || x.name.EndsWith(c.name, StringComparison.Ordinal));
                    if (src == null) throw new InvalidOperationException("clip " + c.name + " missing");
                    src.EnsureQuaternionContinuity();
                    b.clips[c.name] = src;
                    b.lengths[c.name] = src.length;
                }"""
POSE_OLD = """                    if (body.animator != null)
                    {"""
POSE_NEW = """                    if (body.clips.TryGetValue(c.name, out AnimationClip sc))
                    {
                        float ts = c.loop ? Mathf.Repeat(tau, len) : Mathf.Clamp(tau, 0f, len);
                        foreach (var r in body.rest) { r.t.localPosition = r.p; r.t.localRotation = r.r; r.t.localScale = r.s; }
                        foreach (var rw in body.restW) for (int i = 0; i < rw.w.Length; i++) rw.s.SetBlendShapeWeight(i, rw.w[i]);
                        sc.SampleAnimation(body.go, ts);
                    }
                    else if (body.animator != null)
                    {"""
FRAME_BLOCK_OLD = """                    cam.Render();
                    RenderTexture.active = rt;
                    read.ReadPixels(new Rect(0, 0, p.width, p.height), 0, 0);
                    read.Apply();
                    RenderTexture.active = null;
                    File.WriteAllBytes(Path.Combine(dir, c.name + "_" + frame.ToString("000") + ".bin"), read.GetRawTextureData());"""
FRAME_BLOCK_NEW = """                    tSim += swSim.Elapsed.TotalSeconds; swSim.Restart();
                    cam.Render();
                    RenderTexture.active = rt;
                    read.ReadPixels(new Rect(0, 0, p.width, p.height), 0, 0);
                    read.Apply();
                    RenderTexture.active = null;
                    tRender += swSim.Elapsed.TotalSeconds; swSim.Restart();
                    File.WriteAllBytes(Path.Combine(dir, c.name + "_" + frame.ToString("000") + ".bin"), read.GetRawTextureData());
                    tWrite += swSim.Elapsed.TotalSeconds; swSim.Restart(); nFrames++;
                    if (job.maxPendingFrames > 0)
                    {
                        while (Directory.GetFiles(dir, "*.bin").Length > job.maxPendingFrames)
                        {
                            if (swSim.Elapsed.TotalSeconds > 600) throw new InvalidOperationException("showcase frame consumer stalled for 600 s: " + dir);
                            System.Threading.Thread.Sleep(20);
                        }
                    }
                    tWait += swSim.Elapsed.TotalSeconds;"""
ENTRY_OLD = """            JobDef job = JsonUtility.FromJson<JobDef>(File.ReadAllText(specPath));
            if (job.schema != "homm3_vanilla_style_lab.v1") throw new InvalidOperationException("schema " + job.schema);
            AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
            var lib = JsonUtility.FromJson<MatLib>(File.ReadAllText(job.materialLib));
            var mats = new MaterialCache(job.assetRoot, lib);
            foreach (PanelDef p in job.panels) RunPanel(job, p, mats);
            if (job.requireCompleteEffects && mats.Unsupported.Count != 0)
                throw new InvalidOperationException("selected native effects are unsupported: " + string.Join(", ", mats.Unsupported));
            Log("unsupported", "[" + string.Join(", ", mats.Unsupported.Select(s => "\\"" + s + "\\"")) + "]");
            File.WriteAllText(Path.Combine(job.outDir, "lab_report.json"), Report.ToString() + "\\n}\\n");
            Debug.Log("HOMM3_VSTYLE_LAB_OK");"""
# -homm3VanillaStyleSpec names a manifest: one screen spec path per line. The editor waits for each spec (Python plans
# ahead of it), renders it, and writes screen_done.json with the measured stage times.
ENTRY_NEW = """            MaterialCache mats = null;
            foreach (string line in File.ReadAllLines(specPath))
            {
                string sp = line.Trim();
                if (sp.Length == 0) continue;
                var swWait = System.Diagnostics.Stopwatch.StartNew();
                while (!File.Exists(sp)) { if (swWait.Elapsed.TotalSeconds > 1800) throw new InvalidOperationException("spec never appeared: " + sp); System.Threading.Thread.Sleep(200); }
                double specWait = swWait.Elapsed.TotalSeconds;
                JobDef job = JsonUtility.FromJson<JobDef>(File.ReadAllText(sp));
                if (job.schema != "homm3_vanilla_style_lab.v1") throw new InvalidOperationException("schema " + job.schema);
                var swScreen = System.Diagnostics.Stopwatch.StartNew();
                AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
                double tImport = swScreen.Elapsed.TotalSeconds;
                if (mats == null) mats = new MaterialCache(job.assetRoot, JsonUtility.FromJson<MatLib>(File.ReadAllText(job.materialLib)));
                Report.Clear(); tBuild = tSim = tRender = tWrite = tWait = 0; nFrames = 0;
                foreach (PanelDef p in job.panels) RunPanel(job, p, mats);
                Log("unsupported", "[" + string.Join(", ", mats.Unsupported.Select(s => "\\"" + s + "\\"")) + "]");
                File.WriteAllText(Path.Combine(job.outDir, "lab_report.json"), Report.ToString() + "\\n}\\n");
                string inv(double v) => v.ToString("0.00", CultureInfo.InvariantCulture);
                File.WriteAllText(Path.Combine(job.outDir, "screen_done.json"), "{\\"specWaitS\\": " + inv(specWait) + ", \\"importS\\": " + inv(tImport)
                    + ", \\"buildS\\": " + inv(tBuild) + ", \\"simS\\": " + inv(tSim) + ", \\"renderReadS\\": " + inv(tRender) + ", \\"writeS\\": " + inv(tWrite)
                    + ", \\"consumerWaitS\\": " + inv(tWait) + ", \\"frames\\": " + nFrames + ", \\"screenS\\": " + inv(swScreen.Elapsed.TotalSeconds) + "}");
            }
            Debug.Log("HOMM3_VSTYLE_LAB_OK");"""


def stage_lab() -> None:
    src = (VSL.SRC / "Homm3VanillaStyleVfxLab.cs").read_text(encoding="utf-8")
    shine_build = (
        '                if (!string.IsNullOrEmpty(bd.shineMask))\n'
        '                {\n'
        f'                    Shader shs = AssetDatabase.LoadAssetAtPath<Shader>("{SHINE_ASSET}");\n'
        '                    if (shs == null || !shs.isSupported) throw new InvalidOperationException("metal shine shader missing or unsupported");\n'
        '                    var sm = new Material(shs) { name = "HOMM3_metal_shine_" + p.id };\n'
        '                    sm.SetTexture("_ShineMask", ImportTex(R(bd.shineMask), true, false));\n'
        '                    sm.SetFloat("_ShineIntensity", bd.shine[0]); sm.SetFloat("_ShineGloss", bd.shine[1]);\n'
        '                    sm.SetFloat("_SheenStrength", bd.shine[2]); sm.SetFloat("_TintAmount", bd.shine[3]);\n'
        '                    sm.SetVector("_ShineSunDir", sun);\n'
        '                    sm.SetColor("_ShineSunColor", new Color(1f, 0.905f, 0.672f, 1f));\n'
        '                    body.sharedMaterials = body.sharedMaterials.Concat(new[] { sm }).ToArray();\n'
        '                    Log(p.id + "_metal_shine", "{\\"materials\\": " + body.sharedMaterials.Length + ", \\"queue\\": " + sm.renderQueue + "}");\n'
        '                }\n'
        '                b.animator = b.go.GetComponent<Animator>() ?? b.go.AddComponent<Animator>();')
    subs = [("public static class Homm3VanillaStyleVfxLab", f"public static class {LAB_CLASS}"),
            ("public PanelDef[] panels; public bool requireCompleteEffects; }",
             "public PanelDef[] panels; public bool requireCompleteEffects; public int maxPendingFrames; }"),
            ("public OverlayDef[] overlays;\n", "public OverlayDef[] overlays; public string shineMask; public float[] shine;\n"),
            ("                b.animator = b.go.GetComponent<Animator>() ?? b.go.AddComponent<Animator>();", shine_build),
            (ANIM_OLD, ANIM_NEW),
            (POSE_OLD, POSE_NEW),
            ("public List<Renderer> skins = new List<Renderer>();",
             "public List<Renderer> skins = new List<Renderer>(); public Dictionary<string, AnimationClip> clips = new Dictionary<string, AnimationClip>();"
             " public List<(Transform t, Vector3 p, Quaternion r, Vector3 s)> rest = new List<(Transform t, Vector3 p, Quaternion r, Vector3 s)>();"
             " public List<(SkinnedMeshRenderer s, float[] w)> restW = new List<(SkinnedMeshRenderer s, float[] w)>();"),
            (FRAME_BLOCK_OLD, FRAME_BLOCK_NEW),
            # a Water_fire_stylized material beyond the lab's two verified donors (gorgon gaze_breath's
            # Coatl_acid_02_vfx) is dropped and listed as unsupported instead of failing the whole batch
            ("                if (water) RequireWaterDonor(d);",
             "                if (water && d.name != \"Water_aqualotl_04_vfx\" && d.name != \"Naiad_water_06_vfx\")\n"
             "                { Unsupported.Add(name + \" (\" + d.shader + \", not replicated)\"); mats[name] = null; return null; }\n"
             "                if (water) RequireWaterDonor(d);"),
            (ENTRY_OLD, ENTRY_NEW),
            ("        private static readonly StringBuilder Report = new StringBuilder();",
             "        private static readonly StringBuilder Report = new StringBuilder();\n"
             "        private static double tBuild, tSim, tRender, tWrite, tWait; private static long nFrames;"),
            ("            Body body = BuildBody(job, p, sun);",
             "            var swBuild = System.Diagnostics.Stopwatch.StartNew();\n"
             "            Body body = BuildBody(job, p, sun);\n"
             "            tBuild += swBuild.Elapsed.TotalSeconds;"),
            ("                    float tNext = (frame + 1) * c.frameStep;\n",
             "                    var swSim = System.Diagnostics.Stopwatch.StartNew();\n"
             "                    float tNext = (frame + 1) * c.frameStep;\n")]
    for a, b in subs:
        if src.count(a) != 1:
            raise SystemExit(f"final showcase lab: the lab source changed; {a[:60]!r} matched {src.count(a)} times")
        src = src.replace(a, b)
    dst = VSL.PROJECT / LAB_SCRIPT
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.is_file() or dst.read_text(encoding="utf-8") != src:
        dst.write_text(src, encoding="utf-8")


def stage_common() -> Path:
    lib = VSL.stage_common()
    stage_lab()
    root = VSL.PROJECT / VSL.ASSET_ROOT / STAGE_SUB
    root.mkdir(parents=True, exist_ok=True)
    VSL.stage_file(SHINE_SHADER, root / "Homm3MetalShine.shader")
    return lib


def stage(plans: list[dict], lay: dict, work: Path, lib: Path) -> Path:
    """Stages the screen's GLBs/textures, then writes its spec atomically (the waiting editor picks it up)."""
    import vanilla_style_fx as VSF
    root = VSL.PROJECT / VSL.ASSET_ROOT / STAGE_SUB
    panels = []
    for p in plans:
        u = p["lab"]
        dest = root / u
        dest.mkdir(parents=True, exist_ok=True)
        VSL.stage_file(Path(p["glb"]), dest / f"{u}_shipped.glb")
        VSL.stage_file(Path(p["albedo"]), dest / "basecolor.png")
        body = {"kind": "glb", "glbAssetPath": f"{VSL.ASSET_ROOT}/{STAGE_SUB}/{u}/{u}_shipped.glb",
                "texture": f"{STAGE_SUB}/{u}/basecolor.png", "emissionTex": "", "emissionColor": [0, 0, 0],
                "cellST": [], "emissionMin": 0, "blinkSpeed": 0, "blinkPower": 0, "overlays": p["overlays"],
                "shineMask": "", "shine": []}
        em = p["emission"]
        if em:
            VSF.build_emission(u, em, {"basecolor": Path(p["albedo"]), "glb": Path(p["glb"])}, dest / "emission.png")
            body.update(emissionTex=f"{STAGE_SUB}/{u}/emission.png", emissionColor=em["color"],
                        emissionMin=em["minPower"], blinkSpeed=em["blinkSpeed"], blinkPower=em["blinkPower"])
        if p["shine"]:
            s = p["shine"]
            mask = SHINE_CATALOG.parent / s["mask"]["file"]
            VSL.stage_file(mask, dest / "metal.png")
            body.update(shineMask=f"{STAGE_SUB}/{u}/metal.png",
                        shine=[s["shine"]["intensity"], s["shine"]["gloss"], s["shine"]["sheen"], s["shine"]["tint"]])
        clips = [{"name": c["name"], "keys": c["n"], "frames": c["frames"], "frameStep": 1.0 / FPS, "boilCells": [],
                  "loop": c["loop"]} for c in p["clips"]]
        right, up, fwd = (np.asarray(p["dirs"][k]) for k in ("right", "up", "fwd"))
        from_dir = SV._n(-0.55 * right + 0.85 * up - 0.45 * fwd)
        panels.append({"id": f"fs_{u}", "body": body, "clips": clips, "effects": p["effects"], "flipbooks": [],
                       "oldLights": [], "sunTravelUnity": SV.g2u(-from_dir), "warmupS": 1.0,
                       **panel_cam(p, lay["rects"][u], lay["ppu"])})
    raw = work / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    job = {"schema": "homm3_vanilla_style_lab.v1", "assetRoot": VSL.ASSET_ROOT, "materialLib": str(lib),
           "outDir": str(raw), "requireCompleteEffects": False, "maxPendingFrames": MAX_PENDING_FRAMES, "panels": panels}
    sp = work / "lab_job.json"
    tmp = work / "lab_job.json.tmp"
    tmp.write_text(json.dumps(job, indent=1), encoding="utf-8")
    os.replace(tmp, sp)
    return sp


def unstage(units) -> None:
    root = VSL.PROJECT / VSL.ASSET_ROOT
    for u in units:
        for p in (root / STAGE_SUB / u, root / f"clips_fs_{u}"):
            shutil.rmtree(p, ignore_errors=True)
            Path(str(p) + ".meta").unlink(missing_ok=True)


def unstage_all() -> None:
    d = (VSL.PROJECT / LAB_SCRIPT).parent
    shutil.rmtree(d, ignore_errors=True)
    Path(str(d) + ".meta").unlink(missing_ok=True)
    root = VSL.PROJECT / VSL.ASSET_ROOT
    shutil.rmtree(root / STAGE_SUB, ignore_errors=True)
    Path(str(root / STAGE_SUB) + ".meta").unlink(missing_ok=True)
    for p in root.glob("clips_fs_*"):
        shutil.rmtree(p, ignore_errors=True)
        Path(str(p) + ".meta").unlink(missing_ok=True)


def finish_tile(raw: np.ndarray, dev, size) -> Image.Image:
    import torch
    t = torch.as_tensor(raw, device=dev).float().flip(0)
    bg = torch.tensor([(c / 255.0) for c in BG], device=dev)
    bg = torch.where(bg <= 0.04045, bg / 12.92, ((bg + 0.055) / 1.055) ** 2.4)
    rgb = t[..., :3] + bg * (1 - t[..., 3:4].clamp(0, 1))
    rgb = SV._bloom_t(rgb.permute(2, 0, 1)).permute(1, 2, 0).clamp(0, 1)
    s = torch.where(rgb <= 0.0031308, rgb * 12.92, 1.055 * rgb.pow(1 / 2.4) - 0.055)
    im = Image.fromarray((s * 255 + 0.5).to(torch.uint8).cpu().numpy())
    return im.resize(size, Image.LANCZOS)


class Consumer(threading.Thread):
    """raw/fs_<unit>/<clip>_NNN.bin -> tiles/<unit>/<clip>_NNN.png (bin deleted), as Unity writes them."""

    def __init__(self, work: Path, plans, lay):
        super().__init__(daemon=True)
        import torch
        if not torch.cuda.is_available():
            raise SystemExit("final reel: CUDA required for the frame consumer (GPU-first; no CPU fallback)")
        self.dev = torch.device("cuda")
        self.work = work
        self.todo = []
        for p in plans:
            r = lay["rects"][p["lab"]]
            (work / "tiles" / p["lab"]).mkdir(parents=True, exist_ok=True)
            w, h = int(round(r["w"] * SS)), int(round(r["h"] * SS))
            for c in p["clips"]:
                for i in range(c["frames"]):
                    self.todo.append((p["lab"], w, h, (r["w"], r["h"]), c["name"], i))
        self.stop = threading.Event()
        self.done, self.error = 0, None

    def _path(self, item):
        u, w, h, size, clip, i = item
        return (self.work / "raw" / f"fs_{u}" / f"{clip}_{i:03d}.bin",
                self.work / "tiles" / u / f"{clip}_{i:03d}.png")

    def _one(self, item):
        u, w, h, size, clip, i = item
        src, out = self._path(item)
        raw = np.fromfile(src, np.float16).reshape(h, w, 4)
        finish_tile(raw, self.dev, size).save(out, compress_level=1)
        src.unlink()

    def run(self):
        from concurrent.futures import ThreadPoolExecutor
        try:
            pending, inflight = list(self.todo), []
            with ThreadPoolExecutor(6) as pool:
                while pending or inflight:
                    for f in [f for f in inflight if f.done()]:
                        f.result()
                        inflight.remove(f)
                        self.done += 1
                    if not pending or len(inflight) >= 12:
                        time.sleep(0.02)
                        continue
                    item = pending[0]
                    src, out = self._path(item)
                    if out.is_file() and not src.exists():
                        pending.pop(0)
                        self.done += 1
                        continue
                    _, w, h, *_ = item
                    nxt = len(pending) > 1 and self._path(pending[1])[0].exists()
                    ready = src.is_file() and src.stat().st_size == w * h * 8 and (
                        self.stop.is_set() or nxt or time.time() - src.stat().st_mtime > 1.5)
                    if not ready:
                        if self.stop.is_set() and not src.exists():
                            raise RuntimeError(f"Unity finished without {src}")
                        time.sleep(0.1)
                        continue
                    inflight.append(pool.submit(self._one, item))
                    pending.pop(0)
        except Exception as e:  # noqa: BLE001
            self.error = e


def game_running() -> str:
    out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True).stdout
    hits = [l.split(",")[0].strip('"') for l in out.splitlines()
            if re.match(r'^"(Heroes|OldenEra|Olden|Warhammer)', l, re.I)]
    return ", ".join(hits)


def wait_for_no_game() -> None:
    while True:
        g = game_running()
        if not g:
            return
        print(f"game running ({g}); waiting before queueing Unity", flush=True)
        time.sleep(120)


# ------------------------------------------------------------------ timeline + compose
def phase_tracks(plans) -> list[dict]:
    """[{label, frames, tracks: {lab: [(clip, idx) | None ...]}}]: whole cycles only; early finishers hold."""
    out = []
    extras = []
    for p in plans:
        for c in p["clips"]:
            if c["name"] not in KNOWN and c["name"] not in extras:
                extras.append(c["name"])
    phases = PHASES + [(n.replace("Unit_", ""), [n]) for n in extras]
    for label, seq in phases:
        per = {}
        for p in plans:
            cl = {c["name"]: c for c in p["clips"]}
            parts = [(s.lstrip("*"), s.startswith("*")) for s in seq if s.lstrip("*") in cl]
            if not any(name for name, _ in parts):
                per[p["lab"]] = None
                continue
            per[p["lab"]] = (cl, parts)
        if all(v is None for v in per.values()):
            continue
        # loop body: cycles so the phase lasts >= MIN_LOOP_S (Idle/Move); one-shots play once
        fixed = {}
        for lab, v in per.items():
            if v is None:
                continue
            cl, parts = v
            fixed[lab] = sum(cl[n]["frames"] for n, lp in parts if not lp)
        target = 0
        for lab, v in per.items():
            if v is None:
                continue
            cl, parts = v
            loops = [cl[n]["frames"] for n, lp in parts if lp]
            if loops:
                k = max(2, math.ceil((MIN_LOOP_S * FPS - fixed[lab]) / loops[0]))
                target = max(target, fixed[lab] + k * loops[0])
            else:
                target = max(target, fixed[lab])
        tracks = {}
        for lab, v in per.items():
            if v is None:
                tracks[lab] = None
                continue
            cl, parts = v
            loops = [cl[n]["frames"] for n, lp in parts if lp]
            k = max(1, (target - fixed[lab]) // loops[0]) if loops else 0
            tr = []
            for n, lp in parts:
                for _ in range(k if lp else 1):
                    tr += [(n, i) for i in range(cl[n]["frames"])]
            tracks[lab] = tr
        hold = int(round((DEATH_HOLD_S if label == "Death" else GAP_S) * FPS))
        n = max(len(t) for t in tracks.values() if t) + hold
        out.append({"label": label, "frames": n, "tracks": tracks})
    return out


def wrap(d, s, f, width, max_lines):
    words, lines, cur = s.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=f) <= width:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while d.textlength(lines[-1] + "\u2026", font=f) > width and " " in lines[-1]:
            lines[-1] = lines[-1].rsplit(" ", 1)[0]
        lines[-1] += "\u2026"
    return lines


def first_sentence(s: str) -> str:
    m = re.match(r"(.+?[.!?])(\s|$)", s.strip())
    return m.group(1) if m else s.strip()


def static_layer(screen, plans, lay) -> Image.Image:
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.text((40, 18), screen["title"], font=font(40, True), fill=FG)
    f_name, f_ab, f_abt, f_cap = font(22, True), font(16), font(17, True), font(14)
    for p, u in zip(plans, [x for x in screen["units"] if x["lab"] in {q["lab"] for q in plans}]):
        r = lay["rects"][p["lab"]]
        colw = r["colW"]
        SV.text_c(d, (r["cx"], r["labelY"]), f"{u['name']}  \u00b7  T{u['tier']}", f_name, FG)
        for x, cap in ((r["defX"] + r["w"] / 2, "HoMM3 DEF"), (r["x"] + r["w"] / 2, "mesh")):
            SV.text_c(d, (x, r["y"] - CAP_H), cap, f_cap, DIM)
        y = r["labelY"] + NAME_H
        acts = u["actives"][:2]
        for a in acts:
            x0 = r["cx"] - colw / 2 + 4
            ic = ICONS / f"{a.get('icon', '')}.png"
            if a.get("icon") and ic.is_file():
                icon = Image.open(ic).convert("RGBA").resize((40, 40), Image.LANCZOS)
                im.paste(icon, (int(x0), int(y)), icon)
            tx = x0 + 46
            tw = colw - 54
            head = a["name"] + (f"  \u00b7  Focus {a['focus']}" if a.get("focus") not in (None, 0, -1) else "")
            d.text((tx, y - 2), wrap(d, head, f_abt, tw, 1)[0], font=f_abt, fill=FG)
            lines = wrap(d, first_sentence(a["description"]), f_ab, tw, 2 if len(acts) > 1 else 4)
            for i, ln in enumerate(lines):
                d.text((tx, y + 18 + i * 18), ln, font=f_ab, fill=DIM)
            y += 18 + 18 * len(lines) + 6
    return im


def compose(screen, plans, lay, work: Path, out: Path) -> float:
    base = static_layer(screen, plans, lay)
    phases = phase_tracks(plans)
    tiles = {}
    for p in plans:
        for c in p["clips"]:
            for i in range(c["frames"]):
                tiles[(p["lab"], c["name"], i)] = Image.open(work / "tiles" / p["lab"] / f"{c['name']}_{i:03d}.png").convert("RGB")
    def_cache = {}

    def def_tile(p, clip, i):
        """The DEF frame shown at the lab's clip time of tile i ((i + 1) / FPS, looped/clamped like the lab)."""
        c = next(x for x in p["clips"] if x["name"] == clip)
        tau = (i + 1) / FPS
        t = (tau % c["length"]) if c["loop"] and c["length"] > 0 else min(tau, c["length"])
        j = int(min(len(c["def"]["frames"]) - 1, max(0, math.floor((t - c["def"]["start"]) / c["def"]["step"] + 1e-4))))
        key = (p["lab"], clip, j)
        if key not in def_cache:
            r, dm = lay["rects"][p["lab"]], p["defMap"]
            (u0, v0), (u1, v1) = p["box"]
            src = Image.open(c["def"]["frames"][j]).convert("RGBA")
            box = (dm["cx"] + dm["s"] * u0, dm["cy"] - dm["s"] * v1, dm["cx"] + dm["s"] * u1, dm["cy"] - dm["s"] * v0)
            im = src.transform((r["w"], r["h"]), Image.EXTENT, box, Image.BICUBIC)
            bg = Image.new("RGBA", im.size, tuple(BG) + (255,))
            def_cache[key] = Image.alpha_composite(bg, im).convert("RGB")
        return def_cache[key]

    idle0 = {p["lab"]: (def_tile(p, p["clips"][0]["name"], 0), tiles[(p["lab"], p["clips"][0]["name"], 0)]) for p in plans}
    dim = {k: tuple(Image.blend(Image.new("RGB", v.size, BG), v, 0.3) for v in vv) for k, vv in idle0.items()}
    f_ph = font(30, True)

    def frames():
        title = base.copy()
        for p in plans:
            r = lay["rects"][p["lab"]]
            title.paste(idle0[p["lab"]][0], (r["defX"], r["y"]))
            title.paste(idle0[p["lab"]][1], (r["x"], r["y"]))
        for _ in range(int(TITLE_S * FPS)):
            yield title
        for ph in phases:
            hdr = base.copy()
            dh = ImageDraw.Draw(hdr)
            tw = dh.textlength(ph["label"], font=f_ph)
            dh.text((W - 40 - tw, 24), ph["label"], font=f_ph, fill=FG)
            for k in range(ph["frames"]):
                fr = hdr.copy()
                for p in plans:
                    r = lay["rects"][p["lab"]]
                    tr = ph["tracks"][p["lab"]]
                    if tr is None:
                        fr.paste(dim[p["lab"]][0], (r["defX"], r["y"]))
                        fr.paste(dim[p["lab"]][1], (r["x"], r["y"]))
                        continue
                    clip, i = tr[min(k, len(tr) - 1)]
                    fr.paste(def_tile(p, clip, i), (r["defX"], r["y"]))
                    fr.paste(tiles[(p["lab"], clip, i)], (r["x"], r["y"]))
                yield fr

    old_fps = SV.FPS
    SV.FPS = FPS
    try:
        n = SV.encode(frames(), out)
    finally:
        SV.FPS = old_fps
    return n / FPS


# ------------------------------------------------------------------ drivers
def screen_dir(screen) -> Path:
    return WORK / "screens" / f"{screen['index']:02d}_{screen['id']}"


def screen_mp4(screen) -> Path:
    return WORK / "screens" / f"{screen['index']:02d}_{screen['id']}.mp4"


def run_batch(batch: list[dict], timeout_s: int, keep: bool) -> list[dict]:
    """One queued Unity job (one editor launch) renders every screen of the batch. Python plans + stages screen N+1
    while the editor renders N, and composes/encodes N while the editor renders N+1."""
    batch = [s for s in batch if not (screen_mp4(s).is_file() and (screen_dir(s) / "report.json").is_file())]
    if not batch:
        return []
    wait_for_no_game()
    t0 = time.time()
    lib = stage_common()
    specs = []
    for s in batch:
        sd = screen_dir(s)
        shutil.rmtree(sd, ignore_errors=True)
        sd.mkdir(parents=True)
        specs.append(sd / "lab_job.json")
    man = WORK / "batches" / f"{batch[0]['id']}__{batch[-1]['id']}.txt"
    man.parent.mkdir(parents=True, exist_ok=True)
    man.write_text("".join(f"{p}\n" for p in specs), encoding="utf-8")
    ulog = WORK / "batches" / (man.stem + "_unity.log")
    box = {}

    def launch():
        box["t0"] = time.time()
        box["res"] = VSL.UQ.launch(kind="final_showcase_render", method=LAB_METHOD,
                                   args=["-homm3VanillaStyleSpec", str(man)], project=VSL.PROJECT, log=ulog,
                                   inputs=[man], graphics=True, requester="tools/homm3_showcase/final_reel.py",
                                   timeout_s=timeout_s, direct=VSL.UNITY_DIRECT)
        box["t1"] = time.time()

    lt = threading.Thread(target=launch, daemon=True)
    lt.start()
    shines = shine_rows()
    items, consumers = [], []
    for s in batch:
        sd = screen_dir(s)
        tp = time.time()
        plans, failed = [], []
        for u in s["units"]:
            try:
                p = plan_unit(u["lab"], u["gameSid"], shines, FPS)
                p["actives"] = u["actives"][:2]
                plans.append(p)
                print(f"plan {u['lab']}: {len(p['clips'])} clips, {sum(c['frames'] for c in p['clips'])} frames, "
                      f"{p['fxNote']}, shine {'on' if p['shine'] else 'off'} [{p['selection']}]", flush=True)
            except (RuntimeError, SystemExit, KeyError, FileNotFoundError) as e:
                failed.append({"lab": u["lab"], "reason": str(e)})
                print(f"PLAN FAILED {u['lab']}: {e}", flush=True)
        lay = layout(plans)
        stage(plans, lay, sd, lib)
        cons = Consumer(sd, plans, lay)
        cons.start()
        consumers.append(cons)
        items.append({"screen": s, "plans": plans, "lay": lay, "failed": failed, "cons": cons,
                      "planS": time.time() - tp})
        print(f"staged {s['id']} ({len(plans)} units) in {time.time() - tp:.0f}s", flush=True)
    reports = []
    try:
        for wi in items:
            s, sd = wi["screen"], screen_dir(wi["screen"])
            done = sd / "raw" / "screen_done.json"
            while (not done.is_file() or wi["cons"].is_alive()) and not wi["cons"].error:
                if not lt.is_alive() and not done.is_file():
                    break
                if done.is_file():
                    wi["cons"].stop.set()     # every frame is written; let the consumer take the last ones now
                time.sleep(0.3)
            if not done.is_file() or wi["cons"].error:
                for c in consumers:
                    c.stop.set()
                lt.join()
                res = box.get("res") or {}
                raise SystemExit(f"{s['id']}: render failed (unity {res.get('status')}: {res.get('error')}; "
                                 f"consumer {wi['cons'].error}); log {ulog}")
            lab_t = load_json(done)
            unstage([p["lab"] for p in wi["plans"]])
            tc = time.time()
            dur = compose(s, wi["plans"], wi["lay"], sd, screen_mp4(s))
            comp = time.time() - tc
            if not keep:
                shutil.rmtree(sd / "tiles", ignore_errors=True)
            rep = {"screen": s["id"], "title": s["title"], "mp4": str(screen_mp4(s)), "durationS": round(dur, 2),
                   "units": [{"lab": p["lab"], "selection": p["selection"], "glbSha256": p["glbSha256"],
                              "clips": [c["name"] for c in p["clips"]], "fx": p["fxNote"], "shine": bool(p["shine"]),
                              "notes": p["notes"], "defView": p["defNote"],
                              "deyawDeg": p["deyawDeg"]} for p in wi["plans"]],
                   "failed": wi["failed"], "ppu": wi["lay"]["ppu"],
                   "timing": {"planStageS": round(wi["planS"], 1), "lab": lab_t, "composeEncodeS": round(comp, 1)}}
            (sd / "report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
            reports.append(rep)
            print(f"screen {s['id']}: {dur:.1f}s video; lab {lab_t['screenS']}s ({lab_t['frames']} tile-frames), "
                  f"compose+encode {comp:.0f}s -> {screen_mp4(s)}", flush=True)
    finally:
        for c in consumers:
            c.stop.set()
    lt.join()
    res = box["res"]
    if res.get("status") != "ok":
        raise SystemExit(f"Unity batch failed after its screens: {res.get('error')} (log {ulog})")
    print(f"batch {man.stem}: {len(batch)} screens, wall {time.time() - t0:.0f}s (queue+editor "
          f"{box['t1'] - box['t0']:.0f}s; launchWall {res.get('launchWallSeconds')}s, in-editor "
          f"{res.get('elapsedSeconds')}s)", flush=True)
    for s in batch:
        shutil.rmtree(screen_dir(s) / "raw", ignore_errors=True)
    return reports


def concat(only_existing=False) -> Path:
    segs = []
    for s in screens():
        mp4 = WORK / "screens" / f"{s['index']:02d}_{s['id']}.mp4"
        if not mp4.is_file():
            if only_existing:
                continue
            raise SystemExit(f"missing {mp4}")
        segs.append(mp4)
    out = WORK / "homm3_final_showcase_reel.mp4"
    lst = WORK / "concat.txt"
    lst.write_text("".join(f"file '{s.as_posix()}'\n" for s in segs), encoding="utf-8")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", "-movflags", "+faststart", str(out)], check=True)
    print("wrote", out, flush=True)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=("screens", "icons", "screen", "all", "concat", "unstage"))
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--skip", default="", help="all: comma-separated factions to skip (e.g. conflux)")
    ap.add_argument("--timeout", type=int, default=7200)
    ap.add_argument("--keep-tiles", action="store_true")
    a = ap.parse_args(argv)
    if a.step == "screens":
        for s in screens():
            print(f"{s['index']:02d} {s['id']:<18} {len(s['units'])} units: " + ", ".join(u["lab"] for u in s["units"]))
        return 0
    if a.step == "icons":
        icons()
        return 0
    if a.step == "unstage":
        unstage_all()
        return 0
    if a.step == "concat":
        concat(only_existing=bool(a.ids))
        return 0
    lock = WORK / ".runner.lock"
    WORK.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise SystemExit(f"another final_reel runner holds {lock} (delete it if that runner is gone)")
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    try:
        all_s = screens()
        skip = {x for x in a.skip.split(",") if x}
        todo = [s for s in all_s if (s["id"] in a.ids if a.step == "screen" else s["faction"] not in skip)]
        if a.step == "screen" and len(todo) != len(a.ids):
            raise SystemExit(f"unknown screen ids: {set(a.ids) - {s['id'] for s in todo}}")
        if a.step == "screen":
            run_batch(todo, a.timeout, a.keep_tiles)
        else:
            for fac in FACTION_ORDER:          # one job per faction: the queue lock is released between batches
                b = [s for s in todo if s["faction"] == fac]
                if b:
                    run_batch(b, a.timeout, a.keep_tiles)
    finally:
        unstage_all()
        lock.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
