"""Elemental Fusion (Conflux): the 105 fused units' delivered assets and mesh-fx rows (Option B delivery).

    python tools/homm3_vfx/fusion_fx.py specs   [--out DIR]                       resolved pair specs
    python tools/homm3_vfx/fusion_fx.py assets  [--out DIR] [--pairs SID,..] [--device cuda|cpu]
    python tools/homm3_vfx/fusion_fx.py compile [--out DIR] [--pairs SID,..]      mesh-fx rows + compiled records
    python tools/homm3_vfx/fusion_fx.py check   [--out DIR]                       re-verify rows/files/records
    python tools/homm3_vfx/fusion_fx.py merge-catalog --out DIR --plugin-dir DIR  (install step: rows + PNGs into a
                                                                                   homm3_mesh_fx folder; dry run unless --write)

A fused unit ``h3_fusion_<host>_<guest>`` (short names air .. astral) is the host elemental's own delivered skinned
mesh, skeleton and clips (host = the denser element, Earth > Water > Fire > Air > Psychic; inside a family the
upgrade hosts the base and _upg hosts _upg_alt) infused with the guest at ~30%:

  L1  the host albedo baked with the guest palette inside a ridged 3D-noise mask, a Hex/Lit emission map
      (battle_emission: ONE map and ONE blink per unit, the host's), and the stock VfxUber body overlay
      (World_watcher_mask_vfx, battle_body_overlay) whose ``_Mask`` is this unit's vein-core mask
      (``source.textures``) and whose ``_Color`` is the guest tint (``source.colors``);
  L2  the guest's head crest cut from its delivered mesh, styled per guest (wind / crown), scaled by
      min(neck ratio, head-width ratio) and rigidly skinned to the host Head inside the host body primitive
      (the crest sits right after the body vertices, before a merged death-rubble range), UVs on the right half of
      a 2:1 atlas (left half = host);
  L3  the guest's shipped vanilla-style vanillaParticles layers moved onto host bones through the topology chains,
      rate x0.5, scale x0.85, always-on Head layers dropped (the crest sits there), the guest's flash nodes dropped,
      attack windows retimed onto the host Unit_AttackFront contact key, ``orient`` kept (body layers compile with
      the guest's bodyYawDeg on the host root), per-guest overrides (guestLayerOverrides);
  L4  the family-pair reaction recipe (fusion/reactions), '@' anchors and '@hostContactKey' resolved per pair,
      ``tintByGuest`` layers recoloured to the guest tint.

The host's own vanilla-style particle and overlay rows are re-emitted for the fused sid; the host's emission row is
replaced by the fused map. The host's bodyDisplacement (FLAG ripple on COLOR_0.r) is NOT carried: the fused mesh's
COLOR_0 is white because the stock VfxUber overlay multiplies vertex colour, and a displacement mask in r would erase
the guest tint's red over most of a displaced host's body (measured: r < 0.1 on 54-90% of the vertices).

Outputs (``--out``, default V:/olden_port_work/elemental_fusion/v4/ship):
  pairs/<sid>.json                     resolved pair spec (homm3_elemental_fusion_pair.v2)
  units/<sid>/fused.glb                lab master for the owned-skinned builder (host lab master + crest, 2:1 UVs)
  units/<sid>/fused_basecolor.png      2048x1024 albedo atlas;  units/<sid>/build_meta.json
  homm3_mesh_fx/emission/<sid>__fused_emission.png   2048x1024 Hex/Lit emission map
  homm3_mesh_fx/fusion/<sid>__mask.png               1024x512 VfxUber _Mask
  homm3_mesh_fx/fusion_rows.json       catalog rows (origin ``elemental_fusion:<sid>``)
  compiled/<sid>.json                  input hashes + rows (homm3_elemental_fusion_compiled.v1)

Proof tier: generated artifact. Bundles are built by tools/homm3_def_retarget_delivery/fusion_bundles.py; nothing
here proves the in-game look. The ``source.textures`` overlay override needs the Homm3MeshFx reader (patch owned by
the plugin lane); until it ships, the plugin rejects those rows fail-closed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import sys
import time
from itertools import combinations
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools/homm3_unit_look"))
import vanilla_style_fx as VSF  # noqa: E402
from glb_io import Glb  # noqa: E402

FUSION_DIR = VSF.VS_DIR / "fusion"
ELEM = json.loads((FUSION_DIR / "elements.json").read_text(encoding="utf-8"))
TOPO = json.loads((FUSION_DIR / "topology_bones.json").read_text(encoding="utf-8"))["chains"]
DEFAULT_OUT = Path("V:/olden_port_work/elemental_fusion/v4/ship")
PAIR_SCHEMA = "homm3_elemental_fusion_pair.v2"
COMPILED_SCHEMA = "homm3_elemental_fusion_compiled.v1"
ROWS_SCHEMA = "homm3_elemental_fusion_rows.v1"
ORIGIN_PREFIX = "elemental_fusion:"
LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)
FAM_ORDER = ["earth", "water", "fire", "air", "psychic"]
ATTACK_CLIPS = ("Unit_AttackFront", "Unit_ShootFront")
FAMILY, ROLE = {}, {}
for _f, _e in ELEM["elements"].items():
    for _role, _u in _e["units"].items():
        FAMILY[_u], ROLE[_u] = _f, _role
UNITS = [ELEM["elements"][f]["units"][r] for f in FAM_ORDER for r in ("base", "upg", "upg_alt")]


class FusionError(Exception):
    pass


# ------------------------------------------------------------------ pairs and names
def short(u: str) -> str:
    return u[3:].replace("_elemental", "")


def fused_sid(h: str, g: str) -> str:
    return f"{ELEM['delivery']['sidPrefix']}{short(h)}_{short(g)}"


def bundle_name(sid: str) -> str:
    return ELEM["delivery"]["bundlePrefix"] + sid


def host_guest(a: str, b: str) -> tuple[str, str]:
    fa, fb = FAMILY[a], FAMILY[b]
    if fa != fb:
        ra, rb = ELEM["elements"][fa]["densityRank"], ELEM["elements"][fb]["densityRank"]
        return (a, b) if ra < rb else (b, a)
    rank = {"upg": 0, "upg_alt": 1, "base": 2}       # upgrades host the base; _upg hosts _upg_alt
    return (a, b) if rank[ROLE[a]] < rank[ROLE[b]] else (b, a)


def all_pairs() -> list[tuple[str, str]]:
    return [host_guest(a, b) for a, b in combinations(UNITS, 2)]


def pair_by_sid() -> dict[str, tuple[str, str]]:
    return {fused_sid(h, g): (h, g) for h, g in all_pairs()}


def fam_key(h: str, g: str) -> str:
    return "_".join(sorted({FAMILY[h], FAMILY[g]})) if FAMILY[h] != FAMILY[g] else f"{FAMILY[h]}_{FAMILY[h]}"


def game_sid(u: str) -> str:
    return f"h3_{FAMILY[u]}_elemental" + {"base": "", "upg": "_upg", "upg_alt": "_upg_alt"}[ROLE[u]]


def remap(bone: str, have) -> str | None:
    for b in TOPO.get(bone, [bone]):
        if b in have:
            return b
    return None


# ------------------------------------------------------------------ unit facts (shipped spec + frozen delivery)
_UNIT: dict[str, dict] = {}


def sha(path: Path) -> str:
    return VSF.sha(path)


def unit(u: str) -> dict:
    """The unit's shipped vanilla-style spec, its frozen delivery (lab master, basecolor, plan, compiled record) and
    the DEF key facts the L3 retime needs."""
    if u in _UNIT:
        return _UNIT[u]
    import spec as S  # tools/homm3_unit_look (DEF segment facts)
    spec_path = VSF.SPEC_DIR / f"{u}.json"
    spec = VSF.load(spec_path)
    rec = VSF.load(VSF.COMPILED_DIR / f"{u}.json")
    sel = VSF.load(ROOT / spec["delivery"]["selection"])
    d = (ROOT / sel["out"] / u).resolve()
    report = VSF.load(d / "lab_report.json")
    plan = VSF.load(d / "unity/vfx_plan.json")
    master = None
    for cand in (d / "unity/merged_master.glb", d / "delivered_idle_retimed.color0.glb", d / "delivered_idle_retimed.glb"):
        if cand.is_file() and sha(cand) == report["masterGlbSha256"]:
            master = cand
            break
    if master is None:
        raise FusionError(f"{u}: no delivery file hashes to the lab report's master {report['masterGlbSha256'][:12]}")
    seg = S.clip_segments(u)
    defkeys = {k: len(v["defFrames"]) for k, v in seg.items()}
    em = next(l for l in spec["layers"] if l["type"] == "emissionMap")
    atk = []
    for l in spec["layers"]:
        for t in l.get("triggers", []):
            if t["mode"] == "window" and t["clip"] in ATTACK_CLIPS:
                atk.append((t["startKey"], t["clip"], l))
    af = [a for a in atk if a[1] == "Unit_AttackFront"]
    contact = min(a[0] for a in af) if af else int(round(defkeys["Unit_AttackFront"] * 0.5))
    gcontact = min(a[0] for a in (af or atk)) if atk else None
    hit_bone = (af or atk)[0][2]["bones"][0] if atk else None
    _UNIT[u] = {"spec": spec, "specPath": spec_path, "record": rec, "selection": sel, "dir": d, "master": master,
                "plan": plan, "report": report, "basecolor": d / "inputs/basecolor.png",
                "deliveredGlb": d / "delivered_idle_retimed.glb", "joints": set(rec["joints"]), "defKeys": defkeys,
                "emission": em, "contact": contact, "guestContact": gcontact, "hitBone": hit_bone}
    return _UNIT[u]


def host_df(h: str) -> dict:
    """vanilla_style_fx delivery facts of the host (the fused unit plays the host's clips through the host's stock
    controller map and idle retime)."""
    hu = unit(h)
    if "df" not in hu:
        hu["df"] = VSF.delivery_facts(h, hu["spec"])
    return hu["df"]


# ------------------------------------------------------------------ L3 / L4 resolution
def guest_layers(h: str, g: str) -> tuple[list, list, list]:
    gf = ELEM["guestFx"]
    hu, gu = unit(h), unit(g)
    have = hu["joints"]
    shift = (hu["contact"] - gu["guestContact"]) if gu["guestContact"] is not None else 0
    over = gf.get("guestLayerOverrides", {}).get(g, {})
    out, anchors, notes = [], [], []
    for l in gu["spec"]["layers"]:
        if l["type"] != "vanillaParticles":
            continue
        ov = over.get(l["id"], {})
        always = any(t["mode"] == "always" for t in l["triggers"])
        bones = []
        for b in ov.get("bones", l["bones"]):
            m = remap(b, have)
            if m is None or (always and b in gf["dropAlwaysOnBones"]):
                notes.append(f"{l['id']}:{b} dropped")
                continue
            if m != b:
                notes.append(f"{l['id']}:{b}->{m}")
            if m not in bones:
                bones.append(m)
        if ov.get("bones"):
            notes.append(f"{l['id']}: bones overridden to {ov['bones']}")
        if not bones:
            continue
        trig, seen = [], False
        for t in l["triggers"]:
            if t["mode"] == "always":
                trig.append(t)
            elif t["clip"] in ATTACK_CLIPS:
                if seen:
                    continue           # one attack window, on the host's AttackFront
                seen = True
                nk = hu["defKeys"]["Unit_AttackFront"]
                t2 = {"mode": "window", "clip": "Unit_AttackFront", "startKey": max(0, min(nk - 1, t["startKey"] + shift))}
                if "endKey" in t:
                    t2["endKey"] = max(t2["startKey"] + 1, min(nk, t["endKey"] + shift))
                trig.append(t2)
            elif t["clip"] in hu["defKeys"]:
                nk = hu["defKeys"][t["clip"]]
                if t["startKey"] < nk:
                    trig.append(dict(t, endKey=max(t["startKey"] + 1, min(nk, t["endKey"]))) if "endKey" in t else t)
        if not trig:
            continue
        sm = gf["scaleMul"] * gf["layerScaleMul"].get(l["id"], 1.0) * ov.get("scaleMul", 1.0)
        nl = {k: v for k, v in l.items() if k not in ("bones", "triggers", "scale", "rateMul", "boneAnchor", "note")}
        keep = list(l["source"]["keepNodes"])
        if "keepNodes" in ov:
            keep = [n for n in ov["keepNodes"] if n in keep]
        drop = [n for n in keep if n in gf.get("dropKeepNodes", [])]
        keep = [n for n in keep if n not in drop]
        if drop:
            notes.append(f"{l['id']}: dropped flash nodes {drop}")
        if not keep:
            continue
        nl["source"] = dict(l["source"], keepNodes=keep)
        if l.get("alignToReach") and bones != list(l["bones"]):
            nl.pop("alignToReach")
            notes.append(f"{l['id']}: alignToReach dropped (bone remapped)")
        if "boneAnchor" in l:
            notes.append(f"{l['id']}: boneAnchor dropped (a guest mesh point)")
        nl.update(id=f"g_{l['id']}", bones=bones, triggers=trig, scale=round(l["scale"] * sm, 4),
                  rateMul=round(l.get("rateMul", 1.0) * gf["rateMul"] * ov.get("rateMul", 1.0), 4))
        out.append(nl)
        if always:
            anchors += [b for b in bones if b not in anchors]
    return out, anchors, notes


def guest_tint_rgb(g: str) -> list[float]:
    c = np.array(unit(g)["emission"]["color"], float)
    if c.max() <= 0:
        c = np.array(ELEM["elements"][FAMILY[g]]["overlayTintDefault"][:3], float)
    return [round(float(x), 4) for x in c / c.max()]


def reaction_path(h: str, g: str) -> Path | None:
    if FAMILY[h] == FAMILY[g]:
        return None
    fam = "_".join(sorted({FAMILY[h], FAMILY[g]}))
    hits = sorted((FUSION_DIR / "reactions").glob(f"reaction_{fam}_*.json"))
    if len(hits) != 1:
        raise FusionError(f"{fam}: expected one reaction recipe, found {[p.name for p in hits]}")
    return hits[0]


def keep_parent(src: dict, where: str) -> dict:
    """Recipes name keepNodes by leaf under a root childPath; the shipped row format (vanilla_style_fx build_rows)
    wants childPath = the transform that holds them and keepNodes relative to it. Resolve the one common parent."""
    if src.get("childPath"):
        return src
    nodes = [n["path"] for n in VSF.load(VSF.SOURCES)["sources"][src["resPath"]]["nodes"]]
    parents = set()
    for k in src["keepNodes"]:
        hits = [q for q in nodes if q == k or q.endswith("/" + k)]
        if len(hits) != 1:
            raise FusionError(f"{where}: keepNode {k!r} matches {len(hits)} nodes of {src['resPath']}")
        parents.add(hits[0][: -len(k)].rstrip("/"))
    if len(parents) != 1:
        raise FusionError(f"{where}: keepNodes sit under several parents {sorted(parents)}")
    return dict(src, childPath=parents.pop())


def resolve_reaction(path: Path, h: str, g: str, anchors: list) -> tuple[str, list, dict]:
    R = json.loads(path.read_text(encoding="utf-8"))
    have = unit(h)["joints"]
    sock = remap(ELEM["crest"]["bone"], have)
    pool = [sock] + [a for a in anchors if a != sock] if anchors else [remap("Spine2", have), remap("Hips", have)]
    pri = R["anchorPriority"]
    pool = sorted(dict.fromkeys(pool), key=lambda b: pri.index(b) if b in pri else len(pri))[: R["maxAnchors"]]
    gu = unit(g)
    contact_bone = remap(gu["hitBone"], have) if gu["hitBone"] else remap("RightHand", have)
    res = {"@guestFxBones": pool, "@hostBase": [remap("Root", have)], "@hostSpine": [remap("Spine2", have)],
           "@hostContact": [contact_bone]}
    layers = []
    for l in R["layers"]:
        l = json.loads(json.dumps(l))
        bones = []
        for b in l["bones"]:
            for x in res.get(b, [remap(b, have)]):
                if x and x not in bones:
                    bones.append(x)
        l["bones"] = bones
        for t in l["triggers"]:
            if t.get("startKey") == "@hostContactKey":
                t["startKey"] = unit(h)["contact"]
        if l.pop("tintByGuest", False):
            l["recolor"] = guest_tint_rgb(g)
            l.pop("recolorMode", None)
        l.pop("note", None)
        l["source"] = keep_parent(l["source"], f"{path.name}/{l['id']}")
        l["id"] = f"rx_{l['id']}"
        layers.append(l)
    return R["id"], layers, res


# ------------------------------------------------------------------ L1 parameters
_GAIN: dict[str, float] = {}


def load_rgb(path: Path, size=None) -> np.ndarray:
    im = Image.open(path).convert("RGB")
    if size and im.size != tuple(size):
        im = im.resize(tuple(size), Image.LANCZOS)
    return np.asarray(im).astype(np.float32) / 255


def host_gain(h: str) -> float:
    """Additive veins/overlay read twice as strong on a dark host: scale by the host albedo's median luminance
    against water's (0.28), floored at 0.55."""
    if h not in _GAIN:
        a = load_rgb(unit(h)["basecolor"], (512, 512)) @ LUMA
        _GAIN[h] = round(float(np.clip(np.median(a[a > 0.03]) / 0.28, 0.55, 1.0)), 3)
    return _GAIN[h]


def contrast_rule(h: str, g: str) -> dict:
    for r in ELEM.get("contrast", {}).get("rules", []):
        if g in r["guests"] and h in r["hosts"]:
            return r
    return {}


def overlay_tint(h: str, g: str) -> list[float]:
    rule = contrast_rule(h, g)
    if "overlayTint" in rule:
        n = np.array(rule["overlayTint"], float)
    else:
        c = np.array(unit(g)["emission"]["color"], float)
        if c.max() <= 0:
            n = np.array(ELEM["elements"][FAMILY[g]]["overlayTintDefault"][:3], float)
        else:
            n = (c / c.max()) ** 2 * ELEM["tonedDown"]["overlayMaxChannel"]
    return [round(float(x) * host_gain(h), 3) for x in n] + [1.0]


def crest_style(g: str) -> str | None:
    return ELEM["crest"].get("styles", {}).get(g)


# ------------------------------------------------------------------ pair spec
def pair_spec(h: str, g: str) -> dict:
    hu, gu = unit(h), unit(g)
    sid = fused_sid(h, g)
    l3, anchors, notes = guest_layers(h, g)
    rp = reaction_path(h, g)
    rid, l4, res = resolve_reaction(rp, h, g, anchors) if rp else (None, [], {})
    blink_src = hu["emission"] if any(hu["emission"]["color"]) else gu["emission"]
    gaps = []
    if not l3:
        gaps.append(f"L3: {g} brings no vanillaParticles layer onto this host")
    if not any(gu["emission"]["color"]):
        gaps.append(f"L1: {g} has no emission (color 0); veins and crest take palette + overlay only")
    rule = contrast_rule(h, g)
    return {
        "schema": PAIR_SCHEMA, "sid": sid, "bundleName": bundle_name(sid), "host": h, "guest": g,
        "hostGameSid": game_sid(h), "guestGameSid": game_sid(g),
        "families": [FAMILY[h], FAMILY[g]], "familyPair": fam_key(h, g), "sameFamily": FAMILY[h] == FAMILY[g],
        "guestIntensity": ELEM["guestIntensity"],
        "L1_material": {
            "albedoBlend": rule.get("albedoBlend", ELEM["tonedDown"]["albedoBlend"]),
            "emissionBlink": {k: blink_src[k] for k in ("minPower", "blinkPower", "blinkSpeed")},
            "overlay": {"source": ELEM["overlay"]["source"], "tint": overlay_tint(h, g), "hostGain": host_gain(h)},
            "contrastRule": rule.get("why")},
        "L2_crest": {"from": g, "socket": remap("Head", hu["joints"]), "style": crest_style(g),
                     "heightFrac": ELEM["crest"]["heightFrac"], "minWeight": ELEM["crest"]["minWeight"]},
        "L3_guestFx": {"spec": VSF.rel(gu["specPath"]), "layers": l3, "remap": notes,
                       "hostContactKey": hu["contact"], "guestContactKey": gu["guestContact"]},
        "L4_reaction": {"recipe": rp.name if rp else None, "id": rid, "layers": l4, "anchors": res},
        "gaps": gaps}


def cmd_specs(out: Path, only=None) -> list[dict]:
    (out / "pairs").mkdir(parents=True, exist_ok=True)
    specs = []
    for h, g in all_pairs():
        sid = fused_sid(h, g)
        if only and sid not in only:
            continue
        sp = pair_spec(h, g)
        VSF.dump(out / "pairs" / f"{sid}.json", sp)
        specs.append(sp)
    print(f"specs: {len(specs)} pair specs -> {out / 'pairs'}")
    return specs


# ------------------------------------------------------------------ geometry helpers
def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def joint_positions(g: Glb):
    skin = g.json["skins"][0]
    names = [g.json["nodes"][j]["name"] for j in skin["joints"]]
    ibm = g.accessor(skin["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1).astype(np.float64)
    return names, {n: np.linalg.inv(m)[:3, 3] for n, m in zip(names, ibm)}


def weights(g: Glb, prim) -> np.ndarray:
    acc = g.json["accessors"][prim["attributes"]["WEIGHTS_0"]]
    w = g.accessor(prim["attributes"]["WEIGHTS_0"]).astype(np.float64)
    if acc["componentType"] != 5126:
        w /= 255.0 if acc["componentType"] == 5121 else 65535.0
    return w


def head_width(glb: Path, min_w: float = 0.5) -> tuple[float, float]:
    """(head-neck joint distance, horizontal extent of the Head-weighted vertices) in the GLB's bind space."""
    g = Glb(glb)
    names, jp = joint_positions(g)
    hi = names.index("Head")
    prim = g.json["meshes"][0]["primitives"][0]
    pos = g.accessor(prim["attributes"]["POSITION"]).astype(np.float64)
    jn = g.accessor(prim["attributes"]["JOINTS_0"]).astype(np.int64)
    hw = np.where(jn == hi, weights(g, prim), 0).sum(1)
    p = pos[hw >= min_w]
    if len(p) < 10:
        raise FusionError(f"{glb.name}: fewer than 10 Head-weighted vertices")
    ext = np.percentile(p[:, [0, 2]], 98, 0) - np.percentile(p[:, [0, 2]], 2, 0)
    return float(np.linalg.norm(jp["Head"] - jp["Neck"])), float(ext.max())


def subdivide(pos, nrm, uv, tri):
    """One linear midpoint subdivision (each triangle -> 4), shared edge midpoints de-duplicated."""
    e = np.sort(np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]]), 1)
    uniq, inv = np.unique(e, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    n0 = len(pos)
    mid = lambda a: 0.5 * (a[uniq[:, 0]] + a[uniq[:, 1]])  # noqa: E731
    pos2, uv2 = np.concatenate([pos, mid(pos)]), np.concatenate([uv, mid(uv)])
    nm = mid(nrm)
    nrm2 = np.concatenate([nrm, nm / np.maximum(np.linalg.norm(nm, axis=1, keepdims=True), 1e-9)])
    k = len(tri)
    m01, m12, m20 = n0 + inv[:k], n0 + inv[k:2 * k], n0 + inv[2 * k:]
    a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]
    tri2 = np.concatenate([np.stack([a, m01, m20], 1), np.stack([m01, b, m12], 1), np.stack([m20, m12, c], 1),
                           np.stack([m01, m12, m20], 1)])
    return pos2, nrm2, uv2, tri2


def cut_crest(guest_glb: Path, frac: float, min_w: float, style: str | None) -> dict:
    """The top ``frac`` of the guest's Head-weighted mesh (above the Head joint), restyled on a subdivided copy:
    ``wind`` cuts it into twisted, flared, lifted spiral ribbons (streamers, not a cap); ``crown`` into upward rock
    spikes. Positions stay in guest bind space."""
    g = Glb(guest_glb)
    names, jp = joint_positions(g)
    hi = names.index("Head")
    prim = g.json["meshes"][0]["primitives"][0]
    at = prim["attributes"]
    pos = g.accessor(at["POSITION"]).astype(np.float64)
    nrm = g.accessor(at["NORMAL"]).astype(np.float64)
    uv = g.accessor(at["TEXCOORD_0"]).astype(np.float64)
    idx = g.accessor(prim["indices"]).astype(np.int64).reshape(-1, 3)
    hw = np.where(g.accessor(at["JOINTS_0"]).astype(np.int64) == hi, weights(g, prim), 0).sum(1)
    head = jp["Head"]
    top = pos[hw >= min_w, 1].max()
    y0 = head[1] + frac * (top - head[1])
    ok = (hw >= min_w) & (pos[:, 1] >= y0)
    tri = idx[ok[idx].all(1)]
    used = np.unique(tri)
    rmap = -np.ones(len(pos), np.int64)
    rmap[used] = np.arange(len(used))
    pos, nrm, uv, tri = pos[used], nrm[used], uv[used], rmap[tri]
    p = ELEM["crest"].get("styleParams", {}).get(style or "", {})
    for _ in range(int(p.get("subdivide", 0))):
        pos, nrm, uv, tri = subdivide(pos, nrm, uv, tri)
    t = np.clip((pos[:, 1] - y0) / max(top - y0, 1e-6), 0, 1)
    rel = pos - head
    ang = np.arctan2(rel[:, 2], rel[:, 0])
    if style == "wind":
        phase = p["bands"] * ang + 2 * math.pi * p["turns"] * t
        keep_v = np.cos(phase) > p["keep"]
        th = p["twistRad"] * t
        c, s = np.cos(th), np.sin(th)
        r = 1 + p["flare"] * t
        x, z = rel[:, 0] * r, rel[:, 2] * r
        hgt = top - y0
        rel = np.stack([c * x - s * z, rel[:, 1] + p["lift"] * t * hgt, s * x + c * z - p.get("sweep", 0.0) * t * t * hgt], -1)
        nx, nz = nrm[:, 0], nrm[:, 2]
        nrm = np.stack([c * nx - s * nz, nrm[:, 1], s * nx + c * nz], -1)
    elif style == "crown":
        lobe = 0.5 + 0.5 * np.cos(p["spikes"] * ang)
        keep_v = np.cos(p["spikes"] * ang) > p["keep"]
        rel = rel.copy()
        rel[:, 1] += p["spike"] * t * lobe * (top - y0)
    else:
        keep_v = np.ones(len(pos), bool)
    tri = tri[keep_v[tri].all(1)]
    used = np.unique(tri)
    if len(used) < 12:
        raise FusionError(f"{guest_glb.name}: crest style {style} kept {len(used)} vertices")
    rmap = -np.ones(len(pos), np.int64)
    rmap[used] = np.arange(len(used))
    pos2 = head + rel
    return {"pos": pos2[used], "nrm": nrm[used], "uv": uv[used], "tri": rmap[tri], "head": head, "neck": jp["Neck"],
            "top": float(top), "style": style}


# ------------------------------------------------------------------ fused GLB
_COMP = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
_NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
TINY_PNG_RGBA = (128, 128, 128, 255)


def _acc_bytes(gltf: dict, blob: bytes, i: int) -> bytes:
    a = gltf["accessors"][i]
    bv = gltf["bufferViews"][a["bufferView"]]
    n = a["count"] * _NC[a["type"]] * _COMP[a["componentType"]]
    if bv.get("byteStride") and bv["byteStride"] != _NC[a["type"]] * _COMP[a["componentType"]]:
        raise FusionError("interleaved buffer views are not supported")
    if "sparse" in a:
        raise FusionError("sparse accessors are not supported")
    o = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    return blob[o:o + n]


def write_fused_glb(master: Path, crest: dict, scale: float, out_glb: Path, plan_body: int | None = None) -> dict:
    """The host lab master with the crest spliced into mesh 0 / primitive 0 right after the body vertices (before a
    merged rubble range), rigid on Head; every UV halved onto the atlas' left half (crest: right half); zero morph
    deltas for the crest; COLOR_0 kept (host displacement mask in r, crest r = 0) or added white; the embedded image
    replaced by a 4x4 placeholder (the builder takes the albedo separately). The binary is repacked: one bufferView
    per accessor, only referenced data."""
    import io
    g = Glb(master)
    gltf = json.loads(json.dumps(g.json))
    blob = g.bin
    names, jp = joint_positions(g)
    hi = names.index("Head")
    repl: dict[int, np.ndarray] = {}
    new_acc: list[tuple[dict, np.ndarray]] = []

    def put(arr, ctype, typ, target_prim, key, minmax=False, normalized=False):
        a = {"componentType": ctype, "count": int(arr.shape[0]), "type": typ}
        if normalized:
            a["normalized"] = True
        if minmax:
            a["min"] = arr.min(0).tolist()
            a["max"] = arr.max(0).tolist()
        new_acc.append((a, arr))
        return ("new", len(new_acc) - 1)

    n1 = int(len(crest["pos"]))
    insert_at = None
    for mi, mesh in enumerate(gltf["meshes"]):
        for pi, prim in enumerate(mesh["primitives"]):
            at = prim["attributes"]
            nv = gltf["accessors"][at["POSITION"]]["count"]
            uv = g.accessor(at["TEXCOORD_0"]).astype(np.float32) * np.array([0.5, 1.0], np.float32)
            if not (mi == 0 and pi == 0):
                repl[at["TEXCOORD_0"]] = uv
                if "COLOR_0" not in at:
                    at["COLOR_0"] = put(np.full((nv, 4), 255, np.uint8), 5121, "VEC4", None, None, normalized=True)
                continue
            insert_at = nv if plan_body is None else int(plan_body)
            if not 0 < insert_at <= nv:
                raise FusionError(f"{master.name}: body vertex count {plan_body} outside the primitive's {nv}")
            k = insert_at
            pos = g.accessor(at["POSITION"]).astype(np.float32)
            nrm = g.accessor(at["NORMAL"]).astype(np.float32)
            jnt = g.accessor(at["JOINTS_0"])
            wts = g.accessor(at["WEIGHTS_0"])
            idx = g.accessor(prim["indices"]).astype(np.int64)
            cpos = (jp["Head"] + scale * (crest["pos"] - crest["head"])).astype(np.float32)
            cn = crest["nrm"] / np.maximum(np.linalg.norm(crest["nrm"], axis=1, keepdims=True), 1e-9)
            cuv = (crest["uv"] * [0.5, 1.0] + [0.5, 0.0]).astype(np.float32)
            cj = np.zeros((n1, 4), jnt.dtype)
            cj[:, 0] = hi
            cw = np.zeros((n1, 4), wts.dtype)
            cw[:, 0] = 1.0 if wts.dtype == np.float32 else np.iinfo(wts.dtype).max

            def ins(a, b):
                return np.concatenate([a[:k], b, a[k:]])
            at["POSITION"] = put(ins(pos, cpos), 5126, "VEC3", None, None, minmax=True)
            at["NORMAL"] = put(ins(nrm, cn.astype(np.float32)), 5126, "VEC3", None, None)
            at["TEXCOORD_0"] = put(ins(uv, cuv), 5126, "VEC2", None, None)
            src_at = g.json["meshes"][0]["primitives"][0]["attributes"]
            at["JOINTS_0"] = put(ins(jnt, cj), g.json["accessors"][src_at["JOINTS_0"]]["componentType"], "VEC4", None, None)
            wacc = g.json["accessors"][src_at["WEIGHTS_0"]]
            at["WEIGHTS_0"] = put(ins(wts, cw), wacc["componentType"], "VEC4", None, None, normalized=bool(wacc.get("normalized")))
            # white: the VfxUber fusion overlay multiplies vertex colour (rgb * a^2), so a host's COLOR_0.r FLAG mask
            # would erase the guest tint's red on 75-90% of a displaced host's body; fused units drop the host ripple
            at["COLOR_0"] = put(np.full((nv + n1, 4), 255, np.uint8), 5121, "VEC4", None, None, normalized=True)
            idx2 = np.where(idx >= k, idx + n1, idx)
            ctri = (crest["tri"].reshape(-1) + k).astype(np.int64)
            prim["indices"] = put(np.concatenate([idx2, ctri]).astype(np.uint32), 5125, "SCALAR", None, None)
            for tgt in prim.get("targets", []):
                for key, ai in list(tgt.items()):
                    d = g.accessor(ai).astype(np.float32)
                    tgt[key] = put(ins(d, np.zeros((n1, d.shape[1]), np.float32)), 5126, "VEC3", None, None,
                                   minmax=(key == "POSITION"))
    # ---- repack: old accessors (some replaced) + new accessors, one bufferView each
    old = gltf["accessors"]
    used_old = set()

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    refs = []
    for m in gltf["meshes"]:
        for p in m["primitives"]:
            refs += list(p["attributes"].values()) + [p["indices"]] + [v for t in p.get("targets", []) for v in t.values()]
    for an in gltf.get("animations", []):
        for s in an["samplers"]:
            refs += [s["input"], s["output"]]
    for sk in gltf.get("skins", []):
        if "inverseBindMatrices" in sk:
            refs.append(sk["inverseBindMatrices"])
    order, remap_old = [], {}
    for r in refs:
        if isinstance(r, tuple):
            continue
        if r not in remap_old:
            remap_old[r] = None
            order.append(r)
    out_bin = bytearray()
    accessors, views = [], []

    def add(raw: bytes, a: dict, target=None):
        out_bin.extend(b"\0" * (-len(out_bin) % 4))
        v = {"buffer": 0, "byteOffset": len(out_bin), "byteLength": len(raw)}
        if target:
            v["target"] = target
        out_bin.extend(raw)
        views.append(v)
        a = dict(a)
        a.pop("byteOffset", None)
        a["bufferView"] = len(views) - 1
        accessors.append(a)
        return len(accessors) - 1
    for r in order:
        a = old[r]
        raw = repl[r].astype(np.float32).tobytes() if r in repl else _acc_bytes(gltf, blob, r)
        remap_old[r] = add(raw, a)
    new_idx = {}
    for i, (a, arr) in enumerate(new_acc):
        new_idx[i] = add(arr.tobytes(), a)

    def fix(v):
        if isinstance(v, tuple):
            return new_idx[v[1]]
        return remap_old[v]
    for m in gltf["meshes"]:
        for p in m["primitives"]:
            p["attributes"] = {k: fix(v) for k, v in p["attributes"].items()}
            p["indices"] = fix(p["indices"])
            if "targets" in p:
                p["targets"] = [{k: fix(v) for k, v in t.items()} for t in p["targets"]]
    for an in gltf.get("animations", []):
        for s in an["samplers"]:
            s["input"], s["output"] = fix(s["input"]), fix(s["output"])
    for sk in gltf.get("skins", []):
        if "inverseBindMatrices" in sk:
            sk["inverseBindMatrices"] = fix(sk["inverseBindMatrices"])
    buf = io.BytesIO()
    Image.new("RGBA", (4, 4), TINY_PNG_RGBA).save(buf, "PNG")
    for im in gltf.get("images", []):
        out_bin.extend(b"\0" * (-len(out_bin) % 4))
        views.append({"buffer": 0, "byteOffset": len(out_bin), "byteLength": len(buf.getvalue())})
        out_bin.extend(buf.getvalue())
        im.clear()
        im.update({"bufferView": len(views) - 1, "mimeType": "image/png", "name": "fused_placeholder"})
    gltf["accessors"], gltf["bufferViews"] = accessors, views
    gltf["buffers"] = [{"byteLength": len(out_bin)}]
    js = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    js += b" " * (-len(js) % 4)
    out_bin.extend(b"\0" * (-len(out_bin) % 4))
    out_glb.parent.mkdir(parents=True, exist_ok=True)
    with out_glb.open("wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(out_bin)))
        f.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
        f.write(struct.pack("<II", len(out_bin), 0x004E4942) + bytes(out_bin))
    return {"crestVerts": n1, "crestTris": int(len(crest["tri"])), "crestInsertAt": int(insert_at)}


# ------------------------------------------------------------------ L1 bake
def fbm_ridged(p, device, freq=3.0, octaves=4, seed=7):
    import torch
    if device == "cuda" and not torch.cuda.is_available():
        raise FusionError("--device cuda requested but CUDA is not available (use --device cpu explicitly)")
    x = torch.as_tensor(p, dtype=torch.float32, device=device) * freq
    x = x + 0.8 * torch.stack([_vnoise(x + 17.3, seed + 1), _vnoise(x + 41.1, seed + 2), _vnoise(x + 3.7, seed + 3)], -1)
    f, amp, tot = torch.zeros(x.shape[:-1], device=device), 0.5, 0.0
    for o in range(octaves):
        f = f + amp * _vnoise(x * (2 ** o), seed + 10 + o)
        tot += amp
        amp *= 0.5
    return (1 - torch.abs(2 * (f / tot) - 1)).cpu().numpy()


def _vnoise(x, seed):
    import torch
    i = torch.floor(x)
    fr = x - i
    u = fr * fr * (3 - 2 * fr)
    i = i.to(torch.int64)

    def h(dx, dy, dz):
        n = (i[..., 0] + dx) * 73856093 ^ (i[..., 1] + dy) * 19349663 ^ (i[..., 2] + dz) * 83492791 ^ seed * 2654435761
        n = (n ^ (n >> 13)) * 1274126177
        return ((n ^ (n >> 16)) & 0xFFFF).to(torch.float32) / 65535.0

    def lerp(a, b, t):
        return a + (b - a) * t
    x00 = lerp(h(0, 0, 0), h(1, 0, 0), u[..., 0])
    x10 = lerp(h(0, 1, 0), h(1, 1, 0), u[..., 0])
    x01 = lerp(h(0, 0, 1), h(1, 0, 1), u[..., 0])
    x11 = lerp(h(0, 1, 1), h(1, 1, 1), u[..., 0])
    return lerp(lerp(x00, x10, u[..., 1]), lerp(x01, x11, u[..., 1]), u[..., 2])


def palette_lut(bc, bins=64):
    lum = bc @ LUMA
    keep = lum > 0.04
    l, c = lum[keep], bc[keep]
    lo, hi = np.percentile(l, 2), np.percentile(l, 98)
    k = np.clip(((l - lo) / max(hi - lo, 1e-6) * (bins - 1)).round().astype(int), 0, bins - 1)
    lut = np.zeros((bins, 3), np.float32)
    for b in range(bins):
        sel = c[k == b]
        lut[b] = sel.mean(0) if len(sel) else np.nan
    good = ~np.isnan(lut[:, 0])
    for ch in range(3):
        lut[:, ch] = np.interp(np.arange(bins), np.nonzero(good)[0], lut[good, ch])
    return lut


def cache_dir(out: Path) -> Path:
    p = out / "cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def host_raster(out: Path, h: str, res=1024):
    p = cache_dir(out) / f"{h}_raster{res}.npz"
    glb = unit(h)["deliveredGlb"]
    if p.exists():
        z = np.load(p)
        if str(z["sha"]) == sha(glb):
            return z["pos"], z["cov"]
    pos, cov = VSF.raster_positions(glb, (res, res))
    np.savez_compressed(p, pos=pos, cov=cov, sha=sha(glb))
    return pos, cov


def unit_emission(out: Path, u: str, size) -> np.ndarray:
    """The unit's own emission texture by its shipped rule, at ``size``; zeros for a no-glow unit."""
    em = unit(u)["emission"]
    if not any(em["color"]):
        return np.zeros((size[1], size[0], 3), np.float32)
    p = cache_dir(out) / f"{u}_emission.png"
    if not p.exists():
        VSF.build_emission(u, em, {"basecolor": unit(u)["basecolor"], "glb": unit(u)["deliveredGlb"]}, p)
    return load_rgb(p, size)


_CREST: dict = {}


def crest_for(g: str) -> dict:
    if g not in _CREST:
        c = ELEM["crest"]
        _CREST[g] = cut_crest(unit(g)["deliveredGlb"], c["heightFrac"], c["minWeight"], crest_style(g))
    return _CREST[g]


_HEAD: dict = {}


def head_dims(u: str) -> tuple[float, float]:
    if u not in _HEAD:
        _HEAD[u] = head_width(unit(u)["deliveredGlb"], ELEM["crest"]["minWeight"])
    return _HEAD[u]


def crest_scale(h: str, g: str) -> dict:
    (hn, hw), (gn, gw) = head_dims(h), head_dims(g)
    neck = hn / max(gn, 1e-6)
    width = hw / max(gw, 1e-6)
    return {"neckRatio": round(neck, 4), "widthRatio": round(width, 4), "scale": round(min(neck, width), 4)}


def png_save(arr: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray((np.clip(arr, 0, 1) * 255 + 0.5).astype(np.uint8)).save(path, optimize=True)


def emission_name(sid: str) -> str:
    return f"emission/{sid}__fused_emission.png"


def mask_name(sid: str) -> str:
    return f"fusion/{sid}__mask.png"


def build_assets(out: Path, h: str, g: str, device: str = "cuda", force: bool = False) -> dict:
    sid = fused_sid(h, g)
    ud = out / "units" / sid
    meta_p = ud / "build_meta.json"
    sp = VSF.load(out / "pairs" / f"{sid}.json")
    key = VSF.canonical_sha({"pair": sp, "elements": ELEM, "tool": sha(Path(__file__)),
                             "master": unit(h)["report"]["masterGlbSha256"]})
    if not force and meta_p.exists() and VSF.load(meta_p).get("inputKey") == key and (ud / "fused.glb").exists():
        return VSF.load(meta_p)
    t0 = time.time()
    ud.mkdir(parents=True, exist_ok=True)
    td = ELEM["tonedDown"]
    dl = ELEM["delivery"]
    AW, AH = dl["atlas"]
    half = (AW // 2, AH)
    rule = contrast_rule(h, g)
    hbc = load_rgb(unit(h)["basecolor"], half)
    gbc = load_rgb(unit(g)["basecolor"], half)
    hem, gem = unit(h)["emission"], unit(g)["emission"]
    pos, cov = host_raster(out, h)
    r = cov.shape[0]
    field = np.zeros((r, r), np.float32)
    seed = int(hashlib.md5(g.encode()).hexdigest()[:6], 16) % 997 + 7
    field[cov] = fbm_ridged(pos[cov], device, seed=seed)
    thr = float(np.quantile(field[cov], 1 - rule.get("guestIntensity", ELEM["guestIntensity"])))
    m = smoothstep(thr - 0.03, thr + 0.03, field)
    core = smoothstep(thr, min(thr + 0.12, 0.999), field)
    m = VSF.dilate(np.stack([m, core, np.zeros_like(m)], -1).astype(np.float32), cov, steps=8)
    m_up = np.asarray(Image.fromarray(m[..., 0]).resize(half, Image.BILINEAR))
    core_up = np.asarray(Image.fromarray(m[..., 1]).resize(half, Image.BILINEAR))
    covered = float((m[..., 0][cov] > 0.5).mean())
    lut = palette_lut(gbc)
    hl = hbc @ LUMA
    v = hl[hl > 0.04]
    lo, hi = np.percentile(v, 2), np.percentile(v, 98)
    galb = lut[np.clip(((hl - lo) / max(hi - lo, 1e-6) * 63).round().astype(int), 0, 63)] * float(rule.get("albedoGain", 1.0))
    blend = rule.get("albedoBlend", td["albedoBlend"])
    k = (blend * m_up)[..., None]
    # crest half: the guest basecolor, tinted / lifted by a contrast rule
    sty = ELEM["crest"].get("styleParams", {}).get(crest_style(g) or "", {})
    gcrest = gbc * np.array(rule.get("crestTint", [1, 1, 1]), np.float32) * np.array(sty.get("tint", [1, 1, 1]), np.float32)
    gcrest = gcrest + (1 - gcrest) * float(rule.get("crestLift", 0.0))
    atlas = np.concatenate([hbc * (1 - k) + galb * k, np.clip(gcrest, 0, 1)], 1)
    png_save(atlas, ud / "fused_basecolor.png")
    hc, gc = np.array(hem["color"], float), np.array(gem["color"], float)
    ek = float(max(hc.max(), gc.max(), 1.0))
    cut = m_up
    if rule.get("maskDilate"):
        cut = np.asarray(Image.fromarray((m_up * 255).astype(np.uint8)).filter(
            __import__("PIL.ImageFilter", fromlist=["MaxFilter"]).MaxFilter(2 * int(rule["maskDilate"]) + 1))) / 255.0
    cut = np.clip(cut * float(rule.get("hostEmissionCut", 1.0)), 0, 1)
    h_e = unit_emission(out, h, half) * (1 - cut)[..., None] * (hc / ek)
    blink_src = hem if any(hem["color"]) else gem
    gk = (gem["minPower"] / max(blink_src["minPower"], 1e-3)) if any(gem["color"]) else 1.0
    vein = (td["veinEmission"] * host_gain(h) * core_up)[..., None] * np.clip(galb * 1.2, 0, 1) * (gc / ek * td["veinGain"] * gk)
    g_e = unit_emission(out, g, half) * (gc / ek * gk) * float(rule.get("crestEmissionGain", 1.0))
    if crest_style(g) == "crown":
        cp = ELEM["crest"]["styleParams"]["crown"]
        lum = g_e @ LUMA
        g_e = g_e * (smoothstep(cp["crackLo"] * lum.max(), cp["crackHi"] * lum.max(), lum) * cp["crackGain"])[..., None]
    emis = np.concatenate([np.clip(h_e + vein, 0, 1), np.clip(g_e, 0, 1)], 1)
    emis_p = out / "homm3_mesh_fx" / emission_name(sid)
    png_save(emis, emis_p)
    gmask = np.clip(unit_emission(out, g, half).max(-1) * 1.2, 0, 1)
    om = np.concatenate([core_up, gmask], 1)
    mask_p = out / "homm3_mesh_fx" / mask_name(sid)
    mask_p.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray((np.clip(om, 0, 1) * 255 + 0.5).astype(np.uint8)).resize(tuple(dl["mask"]), Image.BILINEAR).save(
        mask_p, optimize=True)
    cs = crest_scale(h, g)
    plan = unit(h)["plan"]
    mm = plan.get("mergedMaster")
    info = write_fused_glb(unit(h)["master"], crest_for(g), cs["scale"], ud / "fused.glb",
                           mm["bodyVertices"] if mm else None)
    meta = {"schema": "homm3_elemental_fusion_build.v1", "sid": sid, "host": h, "guest": g, "inputKey": key,
            "hostMaster": VSF.rel(unit(h)["master"]), "hostMasterSha256": unit(h)["report"]["masterGlbSha256"],
            "maskThreshold": round(thr, 4), "maskCoverage": round(covered, 4), "seed": seed,
            "emissionColor": [ek] * 3, "emissionBlink": {k2: blink_src[k2] for k2 in ("minPower", "blinkPower", "blinkSpeed")},
            "guestEmissionScale": round(gk, 3), "crest": {**cs, "style": crest_style(g), **info},
            "files": {"fused.glb": sha(ud / "fused.glb"), "fused_basecolor.png": sha(ud / "fused_basecolor.png"),
                      emission_name(sid): sha(emis_p), mask_name(sid): sha(mask_p)},
            "buildS": round(time.time() - t0, 1), "proof": "generated artifact"}
    VSF.dump(meta_p, meta)
    return meta


# ------------------------------------------------------------------ compile (mesh-fx rows)
def rows_for(out: Path, sid: str, meta: dict) -> list[dict]:
    sp = VSF.load(out / "pairs" / f"{sid}.json")
    h, g = sp["host"], sp["guest"]
    hu = unit(h)
    df = host_df(h)
    origin = ORIGIN_PREFIX + sid
    sids = [sid]
    rows = []
    # host's own non-emission rows, re-keyed
    for r in hu["record"]["rows"]:
        if r["lane"] == "battle_emission":
            continue
        r2 = json.loads(json.dumps(r))
        r2["id"] = r["id"].replace(f"vs_{h}_", f"fx_{sid}_host_", 1)
        r2["origin"], r2["match"] = origin, {"unitSids": sids}
        if r2["lane"] == "battle_body_displacement":
            continue                 # white COLOR_0 on the fused mesh (see the module doc)
        rows.append(r2)
    # L1 emission: the fused map with the host's blink
    bl = sp["L1_material"]["emissionBlink"]
    rows.append({"id": f"fx_{sid}_fused_emission", "lane": "battle_emission", "origin": origin, "match": {"unitSids": sids},
                 "emission": {"texture": emission_name(sid), "textureSha256": meta["files"][emission_name(sid)],
                              "color": [float(c) for c in meta["emissionColor"]], "minPower": float(bl["minPower"]),
                              "blinkPower": float(bl["blinkPower"]), "blinkSpeed": float(bl["blinkSpeed"])},
                 "proof": "generated artifact; in-game look unproven"})
    # L1 overlay with its own _Mask
    ov = sp["L1_material"]["overlay"]
    rows.append({"id": f"fx_{sid}_fusion_overlay", "lane": "battle_body_overlay", "origin": origin,
                 "match": {"unitSids": sids},
                 "source": {"nativeResPath": ov["source"]["resPath"], "rendererPath": ov["source"]["rendererPath"],
                            "materialIndex": int(ov["source"]["materialIndex"]),
                            "colors": [{"property": ELEM["overlay"]["tintProperty"], "rgba": [float(x) for x in ov["tint"]]}],
                            "textures": [{"property": "_Mask", "file": mask_name(sid),
                                          "sha256": meta["files"][mask_name(sid)]}]},
                 "trigger": {"mode": "always"}, "proof": "generated artifact; in-game look unproven"})
    # L3 + L4 through the shared vanilla-style row builder, on the host's delivery facts
    layers = sp["L3_guestFx"]["layers"] + sp["L4_reaction"]["layers"]
    sources = VSF.load(VSF.SOURCES)["sources"]
    for l in layers:
        res = l["source"]["resPath"]
        if res not in sources:
            raise FusionError(f"{sid}/{l['id']}: {res} is not in the probed vanilla sources (run vanilla_style_fx.py sources)")
        problem = VSF.trigger_problem(l["triggers"], l.get("loop"))
        if problem:
            raise FusionError(f"{sid}/{l['id']}: {problem}")
    built = VSF.build_rows(sid, {"gameUnitSids": sids, "layers": layers}, df, {})
    for r in built:
        r["id"] = r["id"].replace(f"vs_{sid}_", f"fx_{sid}_", 1)
        r["origin"] = origin
        r["match"] = {"unitSids": sids}
    rows += built
    ids = [r["id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise FusionError(f"{sid}: duplicate row ids")
    return rows


def cmd_compile(out: Path, only=None) -> None:
    allrows = []
    (out / "compiled").mkdir(parents=True, exist_ok=True)
    for sid, (h, g) in pair_by_sid().items():
        if only and sid not in only:
            continue
        meta = VSF.load(out / "units" / sid / "build_meta.json")
        rows = rows_for(out, sid, meta)
        rec = {"schema": COMPILED_SCHEMA, "sid": sid, "host": h, "guest": g, "bundleName": bundle_name(sid),
               "pairSpecSha256": sha(out / "pairs" / f"{sid}.json"), "buildMetaSha256": sha(out / "units" / sid / "build_meta.json"),
               "hostCompiledRowsSha256": unit(h)["record"]["rowsSha256"], "hostStockMap": host_df(h)["stockMap"],
               "files": meta["files"], "rows": rows, "rowsSha256": VSF.canonical_sha(rows),
               "proof": "generated artifact; in-game look unproven"}
        VSF.dump(out / "compiled" / f"{sid}.json", rec)
        allrows += rows
        print(f"compile: {sid} rows={len(rows)}")
    if only:
        p = out / "homm3_mesh_fx/fusion_rows.json"
        prev = VSF.load(p)["entries"] if p.exists() else []
        keep = [r for r in prev if r["origin"][len(ORIGIN_PREFIX):] not in only]
        allrows = keep + allrows
    allrows.sort(key=lambda r: (r["origin"], r["id"]))
    VSF.dump(out / "homm3_mesh_fx/fusion_rows.json", {"schema": ROWS_SCHEMA, "count": len(allrows), "entries": allrows})


def cmd_check(out: Path, plugin_dir: Path | None = None) -> int:
    rows = VSF.load(out / "homm3_mesh_fx/fusion_rows.json")["entries"]
    bad = []
    if plugin_dir:              # an installed catalog: its fusion rows and PNGs must be exactly this build's
        cat = [r for r in VSF.load(plugin_dir / "homm3_mesh_fx/catalog.json")["entries"]
               if str(r.get("origin", "")).startswith(ORIGIN_PREFIX)]
        if VSF.canonical_sha(sorted(cat, key=lambda r: r["id"])) != VSF.canonical_sha(sorted(rows, key=lambda r: r["id"])):
            bad.append(f"{plugin_dir}: catalog fusion rows differ from this build ({len(cat)} vs {len(rows)})")
        for r in rows:
            files = [(r["emission"]["texture"], r["emission"]["textureSha256"])] if r["lane"] == "battle_emission" else []
            files += [(t["file"], t["sha256"]) for t in (r.get("source") or {}).get("textures", [])]
            for f, digest in files:
                p = plugin_dir / "homm3_mesh_fx" / f
                if not p.is_file() or sha(p) != digest:
                    bad.append(f"{r['id']}: installed {f} missing or changed")
    by = {}
    for r in rows:
        by.setdefault(r["origin"][len(ORIGIN_PREFIX):], []).append(r)
    for sid in pair_by_sid():
        rec_p = out / "compiled" / f"{sid}.json"
        if not rec_p.exists():
            bad.append(f"{sid}: not compiled")
            continue
        rec = VSF.load(rec_p)
        if VSF.canonical_sha(sorted(by.get(sid, []), key=lambda r: r["id"])) != VSF.canonical_sha(sorted(rec["rows"], key=lambda r: r["id"])):
            bad.append(f"{sid}: rows differ from the compiled record")
        for rel_name, digest in rec["files"].items():
            p = (out / "homm3_mesh_fx" / rel_name) if "/" in rel_name else (out / "units" / sid / rel_name)
            if not p.exists() or sha(p) != digest:
                bad.append(f"{sid}: {rel_name} missing or changed")
        for r in rec["rows"]:
            for st in (r.get("trigger") or {}).get("states", []):
                if st not in rec["hostStockMap"]:
                    bad.append(f"{sid}: row {r['id']} state {st} not a stock state")
    print(f"check: {len(pair_by_sid())} sids, {len(rows)} rows, {len(bad)} problem(s)")
    for b in bad[:30]:
        print("  ", b)
    return 1 if bad else 0


def cmd_merge_catalog(out: Path, plugin_dir: Path, write: bool) -> None:
    """Install-lane step: replace every ``elemental_fusion:`` row in <plugin_dir>/homm3_mesh_fx/catalog.json with this
    build's rows and copy the emission/mask PNGs. Dry run unless --write."""
    import shutil
    cat_p = plugin_dir / "homm3_mesh_fx/catalog.json"
    cat = VSF.load(cat_p)
    rows = VSF.load(out / "homm3_mesh_fx/fusion_rows.json")["entries"]
    keep = [r for r in cat["entries"] if not str(r.get("origin", "")).startswith(ORIGIN_PREFIX)]
    clash = {r["id"] for r in keep} & {r["id"] for r in rows}
    if clash:
        raise FusionError(f"catalog ids already used: {sorted(clash)[:5]}")
    files = sorted({f for r in rows for f in ([r["emission"]["texture"]] if r["lane"] == "battle_emission" else [])
                    + [t["file"] for t in (r.get("source") or {}).get("textures", [])]})
    print(f"merge-catalog: {len(cat['entries']) - len(keep)} old fusion rows -> {len(rows)} rows; {len(files)} PNGs into {plugin_dir / 'homm3_mesh_fx'}")
    if not write:
        print("dry run (pass --write)")
        return
    cat["entries"] = keep + rows
    cat_p.write_text(json.dumps(cat, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    for f in files:
        dst = plugin_dir / "homm3_mesh_fx" / f
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out / "homm3_mesh_fx" / f, dst)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("specs", "assets", "compile", "check", "merge-catalog"))
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--pairs", default="")
    ap.add_argument("--device", default="cuda", choices=("cuda", "cpu"))
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--plugin-dir", type=Path)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    only = set(a.pairs.split(",")) - {""} or None
    if only and not only <= set(pair_by_sid()):
        raise FusionError(f"unknown sids {sorted(only - set(pair_by_sid()))}")
    if a.cmd == "specs":
        cmd_specs(a.out, only)
    elif a.cmd == "assets":
        t0 = time.time()
        for sid, (h, g) in pair_by_sid().items():
            if only and sid not in only:
                continue
            m = build_assets(a.out, h, g, a.device, a.force)
            print(f"assets: {sid} crest={m['crest']} {m['buildS']}s", flush=True)
        print(f"assets done {time.time() - t0:.0f}s")
    elif a.cmd == "compile":
        cmd_compile(a.out, only)
    elif a.cmd == "check":
        return cmd_check(a.out, a.plugin_dir)
    elif a.cmd == "merge-catalog":
        if not a.plugin_dir:
            raise FusionError("--plugin-dir is required")
        cmd_merge_catalog(a.out, a.plugin_dir, a.write)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (FusionError, VSF.VsError) as ex:
        print(f"fusion_fx: {ex}", file=sys.stderr)
        sys.exit(1)
