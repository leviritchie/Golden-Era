#!/usr/bin/env python3
"""Conflux 3D town buildings from HoMM3 town-screen sprites (paid Meshy, staged).

    python tools/homm3_town_scene_meshes/generate_conflux_town_meshes.py prep    --layer tbelhall [--layer ...]
    python tools/homm3_town_scene_meshes/generate_conflux_town_meshes.py concept --start|--poll --layer L [--attempt N]
    python tools/homm3_town_scene_meshes/generate_conflux_town_meshes.py mesh    --start|--poll --layer L [--attempt N] [--concept-attempt N]
    python tools/homm3_town_scene_meshes/generate_conflux_town_meshes.py ledger

Pipeline per layer (one HoMM3 town-screen building sprite):
  1. prep    (free)  sprite from town_scene_refs/homm3_conflux/layers/<layer>.png, alpha-cropped,
                     4x Lanczos upscale, centred on white -> source_prep.png
  2. concept (~6 cr) Meshy image-to-image (nano-banana-2): same building as an isolated clean 3D-render
                     concept on white, three-quarter view from slightly above (the town camera's view)
  3. mesh    (~30 cr) Meshy image-to-3d meshy-7 standard, textured, PBR, remove_lighting=false
                     (painted lighting is kept: native town buildings are Hex/Lit, which reads base
                     colour only, see docs/homm3_prebaked_lighting.md)

A queued or finished attempt is never re-created, so rerunning --start cannot be charged twice.
`ledger` writes artifacts/meshy_town_scene_meshes/homm3_conflux/meshy_spend.json (task ids +
consumed credits per building). Proof tier: generated artifact.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "homm3_meshy_frame_pose"))
from meshy_client import (create_image_to_3d, create_image_to_image, download_url, get_task,  # noqa: E402
                          load_api_key, poll_task, task_error_message)

LAYERS = (ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "homm3_runtime_assets"
          / "town_scene_refs" / "homm3_conflux" / "layers")
OUT = ROOT / "artifacts" / "meshy_town_scene_meshes" / "homm3_conflux"

# What each HoMM3 layer depicts; the prompt must describe the object, never invent a new design.
# Moving parts (portal surface, water jets, smoke, flames) are deliberately left OUT of the mesh: they are
# built as separate native-style effects (docs/conflux_town3d_pilot.md "Effects and animation").
_HALL_BASE = ("a square pink terracotta-brick palace hall with thick round copper-banded corner pillars, teal "
              "ornamental scrollwork crest over an arched wooden double door, and one large copper onion dome "
              "with a teal neck, a ring of copper beads and a tall gold spire on top of the roof")
SUBJECT = {
    "tbelhall": _HALL_BASE + "; the four corner pillars are short and flat-topped; no other towers",
    "tbelhall_2": _HALL_BASE + "; exactly four slender round corner towers rise above the roof, each capped by "
                  "its own small copper onion dome with a gold spire (the two front towers stand at the front "
                  "corners of the entrance facade)",
    "tbelhall_3": _HALL_BASE + "; around the central block stand six slender round towers each capped by a small "
                  "copper onion dome with a gold spire: four at the corners of the central block and one at the "
                  "far end of each of two long symmetrical side wings; each wing is a two-storey arcade gallery "
                  "with teal balconies connecting the central block to its end tower",
    "tbelhall_4": _HALL_BASE + "; around the central block stand six slender round towers each capped by a small "
                  "copper onion dome with a gold spire: four at the corners of the central block and one at the "
                  "end of each of two long symmetrical two-storey arcade side wings with teal balconies; beyond "
                  "each wing's round tower stands one more tall square tower, the left with a tall pointed gold "
                  "cone roof and the right with a teal pyramidal roof and small pinnacles (the reference is cut off "
                  "at its left edge: complete the palace symmetrically)",
    "tbelcstl": "a walled terracotta-brick fort: a low square keep with a small copper dome in the centre of a "
                "crenellated brick curtain wall, two tall round copper-banded corner towers capped by teal onion "
                "domes with spires at the left and right ends, arched gate with steps down the front; no river",
    "tbelcstl_2": "a walled terracotta-brick citadel: a square keep crowned by a copper dome and one very tall "
                  "slender central minaret tower with a small cupola and spire, inside a crenellated brick "
                  "curtain wall with two tall round copper-banded corner towers capped by teal onion domes, "
                  "arched gate with steps down the front; no river",
    "tbelcstl_3": "a walled terracotta-brick castle: a square keep with a large copper dome and one very tall "
                  "slender central minaret, surrounded by four more tall slender round copper towers behind it, "
                  "inside a crenellated brick curtain wall with two round corner towers capped by teal onion "
                  "domes, arched gate with steps down the front; no river",
    # Castle regen (coordinator relay 3, ~36 cr under conflux_placeable_2026-09-26): the a1 concept came from
    # a source full of painted terrain and invented a ring of equal minarets. The keep crop drops the terrain
    # and the prompt states the HoMM3 layout exactly.
    "tbelcstl_3_keep": "a walled terracotta-brick castle with this exact layout: ONE tall slender round copper "
                       "central tower, much taller than everything else, crowned by a small gold-and-teal domed "
                       "cupola with a gold finial, rising from behind a large copper dome over the square gate "
                       "keep; the gate keep has an ornate copper crest over an arched door flanked by two small "
                       "round turrets; four thinner copper towers with small teal caps cluster just behind the "
                       "central tower, two on each side; at the two front corners of the brick curtain wall stand "
                       "two thick round copper-banded towers capped by teal onion domes with gold spires; at the "
                       "two back corners stand two tall plain round flat-topped copper towers; arched windows and "
                       "small copper domes along the walls; no terrain, no river, no stairs",
    # Fort L2 regen (lower-tier relay, ~36 cr under conflux_lower_tier_2026-09-26): the a1 mesh stood on a
    # full-footprint slab and flattened the keep into a plain wall block. Keep crop, exact layout, as tbelcstl_3_keep.
    # Input critique: the crop still carries painted hillside behind the towers and a grass strip under the wall
    # (a colour matte cut into the teal domes, so it was not used); the concept step renders the fort alone on
    # white and is itself reviewed before the mesh step is paid for.
    "tbelcstl_2_keep": "a walled terracotta-brick citadel with this exact layout: ONE very tall slender round "
                       "copper central minaret, much taller than everything else, crowned by a small teal-domed "
                       "cupola with a gold finial, rising from a large copper dome over the square brick gate keep; "
                       "the gate keep has an ornate copper crest over an arched door flanked by two small round "
                       "turrets; a low crenellated brick curtain wall runs left and right of the keep with small "
                       "copper domes and arches along its top; at the two front corners stand two thick round "
                       "copper-banded towers capped by teal onion domes with gold spires; no other towers; the "
                       "walls rise straight from their own footprint: no ground plate, no base platform, no "
                       "terrain, no grass, no river, no stairs",
    "tbelmage": "a mage guild tower, level 1: a short octagonal stone tower with copper bands, arched windows "
                "and door, capped by a copper onion dome with a spire, on an octagonal stepped stone base",
    "tbelmage_2": "a mage guild tower, level 2: an octagonal stone tower with copper bands, two storeys of arched "
                  "windows and a gallery ring of round blue gem windows under a copper dome with a spire, on an "
                  "octagonal stepped stone base",
    "tbelmage_3": "a mage guild tower, level 3: a tall octagonal stone tower of three stacked storeys, each storey "
                  "separated by a copper band with a ring of round blue gem windows and arched windows, capped by "
                  "a small copper dome with a spire, on an octagonal stepped stone base",
    "tbelmage_4": "a mage guild tower, level 4: a very tall slender octagonal stone tower of four stacked storeys, "
                  "each separated by copper bands with rings of round blue gem windows and arched windows, capped "
                  "by a small copper dome with a spire, on an octagonal stepped stone base",
    "tbeltvrn": "a small cottage tavern: pink brick walls, two-tier green tiled pyramidal roofs with a small "
                "copper cupola on top, a hanging sign by the door and barrels in front",
    "tbelblak": "a blacksmith workshop: a long brick building with a barrel-vaulted green tiled roof, a wide "
                "arched wooden door, and a tall round brick chimney at its left end; no smoke",
    "tbelsilo": "a resource silo: a tall square pink brick tower with copper bands and arched windows capped by a "
                "copper onion dome, with a smaller round side turret capped by a teal onion dome, on a low brick "
                "base building with arched doors",
    "tbelspec": "a small clock tower chapel: a round pink brick tower with a clock face and arched doors, "
                "capped by a teal flared pagoda-like roof with a spire",
    "tbeldock": "a small wooden shipyard jetty: a plank pier on wooden posts with a low wooden railing, an "
                "orange-roofed wooden boat shed and a few barrels; no water",
    "tbelmark_a": "a market stall pavilion: a row of three peaked dark blue canvas tent roofs with gold trim and "
                  "scalloped edges on wooden posts, tall slender copper-capped poles at both ends, crates, "
                  "baskets and bottles of goods underneath",
    "tbelmark_b": "a market stall pavilion: a row of three peaked orange canvas tent roofs with gold trim and a "
                  "scalloped yellow valance on wooden posts, slender copper-capped poles at both ends, pots, "
                  "jars and bottles of goods underneath",
    "tbeldw_0": "a fairy lantern house: a small ornate golden lantern-shaped house with glass windows and a "
                "gabled roof, hanging from the curled tip of a tall curving green vine stalk rooted in a small "
                "grassy mound; lantern unlit",
    "tbeldw_2": "an ornate round fountain basin of golden-brown carved stone with a small central statue "
                "pedestal and dolphin-like spouts on the rim; the basin is empty and dry, no water jets",
    "tbeldw_5": "a magical portal shrine: a large upright golden ring frame holding a glowing blue oval portal, "
                "topped by a gold star, standing on a round stepped golden pedestal",
    "tbeldw_5_frame": "a magical portal gate: a large upright ornate golden ring frame, topped by a gold star, "
                      "standing on a round stepped golden pedestal; the inside of the ring is an open empty hole "
                      "(no portal surface, you can see through it)",
    "tbeldw_3": "an elemental fire altar: a round crater of molten glowing lava and flames set in dark volcanic "
                "rock, with a rocky rim, seen as a compact circular ground feature",
}

# Virtual layers: one generated object from a column span of a HoMM3 layer sprite (x0, x1 in sprite px).
CROP = {
    "tbelmark_a": ("tbelmark", (0, 92)),
    "tbelmark_b": ("tbelmark", (108, 201)),
    "tbeldw_5_frame": ("tbeldw_5", None),
    "tbelcstl_3_keep": ("tbelcstl_3", (190, 0, 322, 120)),  # (x0, y0, x1, y1): the keep without its terrain
    "tbelcstl_2_keep": ("tbelcstl_2", (190, 0, 322, 120)),
    # Full-3D town (docs/homm3_conflux_full_3d_town.md): the mushroom garden of the Tier_1 upgrade / horde sprite.
    "prop_mushrooms": ("tbelhrd1", (0, 55, 70, 124)),
}

# Full-3D town props and tile textures have no building sprite: their source is a crop (x0, y0, x1, y1) of the
# HoMM3 background TBELBACK (Conflux-in-background.png, 800x374), so the concept keeps the painting's style.
BACKGROUND = LAYERS.parent / "Conflux-in-background.png"
BG_CROP = {
    "prop_conifer_a": (0, 150, 70, 215),
    "prop_conifer_b": (20, 165, 90, 215),
    "prop_bush": (560, 225, 640, 262),
    "prop_boulders": (575, 115, 650, 165),
    "prop_bridge": (215, 292, 285, 318),
    "tile_grass": (330, 250, 450, 300),
    "tile_forest": (0, 165, 90, 215),
    "tile_rock": (575, 115, 650, 165),
    "tile_snow": (160, 55, 215, 95),
    "tile_dirt": (205, 285, 300, 305),
}
SUBJECT.update({
    # Terrain-embedded dwellings (were projected 2D). The prompt asks for the object alone, never its terrain.
    "tbeldw_1": "an air elemental shrine: a tall pointed stone archway gate of pale grey carved stone with a dark "
                "doorway, flanked by small stone obelisk spires, with a short stone staircase leading up to the gate, "
                "standing on a compact snowy rock crag; wisps of white cloud; no mountain range, no sky",
    "tbeldw_4": "an earth elemental ring: a circle of eight tall jagged dark grey standing stones and rock spires "
                "around an empty round clearing of bare earth, on a low round rocky base; no grass field, no sky",
    "prop_mushrooms": "a cluster of five giant orange-capped fairy-tale mushrooms of different heights with pale "
                      "stems, growing from one small mossy clump; nothing else",
    "prop_conifer_a": "one single tall slender dark green conifer pine tree with a straight brown trunk and dense "
                      "layered needle branches, a stylised game-art tree; only this one tree, no ground",
    "prop_conifer_b": "one single medium-height bushy dark green spruce fir tree, conical, stylised game-art tree; "
                      "only this one tree, no ground",
    "prop_bush": "one single round leafy green shrub bush with a few small yellow flowers, stylised game-art "
                 "vegetation; only this one bush, no ground",
    "prop_boulders": "a small cluster of three weathered grey-brown rounded boulders with patches of green moss, "
                     "stylised game-art rocks; nothing else",
    "prop_bridge": "a small single-arch stone footbridge of pale weathered stone blocks with low parapet walls, "
                   "as would span a narrow stream; no water, no ground, no river banks",
})
# Tile textures: image-to-image only (no mesh), a flat seamless top-down material swatch.
TEXTURE_SUBJECT = {
    "tile_grass": "lush green meadow grass with small darker tufts and a few tiny yellow flowers",
    "tile_forest": "dense dark green conifer forest canopy seen from above, clumps of needle foliage",
    "tile_rock": "weathered brown-grey mountain rock with cracks and small green moss patches",
    "tile_snow": "wind-packed white mountain snow with soft blue-grey shading and a few rock specks",
    "tile_dirt": "pale sandy brown dirt path with small pebbles",
}
TEXTURE_PROMPT = (
    "Create a seamless tileable square ground texture swatch of {subject}, in the same colours and painterly style as "
    "the reference image (a classic 1999 fantasy strategy game landscape). Straight top-down orthographic view, "
    "uniform flat lighting, no shadows, no horizon, no perspective, no objects, no text; the pattern fills the whole "
    "square evenly."
)
# Per-layer mesh options: scattered vegetation must be light (hundreds of instances).
MESH_OPTS = {"prop_conifer_a": {"decimation_mode": 4}, "prop_conifer_b": {"decimation_mode": 4},
             "prop_bush": {"decimation_mode": 4}, "prop_boulders": {"decimation_mode": 4}}
MIN_BALANCE = 500  # coordinator relay: never leave the shared account below this

# Spend approvals. Every new task is tagged with the active approval; starting one is refused when the
# approval's committed spend (consumed credits, or list price while pending) plus the new task would pass
# its cap. The 2026-09-26 pilot (108 credits) predates the tag.
# Closed approvals stay listed with their caps so the ledger keeps reporting them.
APPROVALS = {"conflux_placeable_2026-09-26": 1200,
             # Lower-tier town-screen buildings (coordinator relay 2026-09-26: "~600 credits", town screen only).
             "conflux_lower_tier_2026-09-26": 600,
             # Full-3D town screen (user decision 2026-09-26; coordinator relay: up to 8000, the whole balance, spend
             # what the scene needs, stop before the shared balance falls below 500).
             "conflux_full3d_2026-09-26": 8000}
APPROVAL = "conflux_full3d_2026-09-26"
APPROVAL_CAP = APPROVALS[APPROVAL]
PRICE = {"image-to-image": 6, "image-to-3d": 30}

CONCEPT_PROMPT = (
    "Recreate the building in the reference image as a single clean high-detail 3D model render. It is {subject}. "
    "Keep exactly the same design, silhouette, proportions, materials and colours as the reference "
    "(it comes from a classic 1999 fantasy strategy game town screen). Show the whole object, centred, "
    "three-quarter front view from slightly above, soft even studio lighting, plain pure white background, "
    "no surrounding landscape, no other buildings, no text."
)


def approval_spend(approval: str = APPROVAL) -> int:
    total = 0
    for tf in OUT.glob("*/*_a*/task.json"):
        meta = json.loads(tf.read_text(encoding="utf-8"))
        if meta.get("approval") != approval:
            continue
        rf = tf.parent / "task_result.json"
        task = json.loads(rf.read_text(encoding="utf-8")) if rf.is_file() else {}
        if task.get("status") in ("FAILED", "CANCELED", "EXPIRED") and not task.get("consumed_credits"):
            continue
        total += int(task.get("consumed_credits") or PRICE[meta["kind"]])
    return total


def balance(key: str) -> int:
    from meshy_client import _request
    return int(_request("GET", "/balance", key).get("balance"))


def guard_budget(kind: str, key: str | None = None) -> None:
    spent = approval_spend()
    if spent + PRICE[kind] > APPROVAL_CAP:
        raise SystemExit(f"budget: approval {APPROVAL} has {spent} credits committed; a {kind} "
                         f"({PRICE[kind]}) would pass the {APPROVAL_CAP} cap. Stop and report.")
    if key is not None:
        bal = balance(key)
        if bal - PRICE[kind] < MIN_BALANCE:
            raise SystemExit(f"budget: shared Meshy balance {bal}; a {kind} ({PRICE[kind]}) would leave it below "
                             f"{MIN_BALANCE}. Stop and report.")


def layer_dir(layer: str) -> Path:
    return OUT / layer


def prep(layer: str) -> dict:
    from PIL import Image

    sprite, span = CROP.get(layer, (layer, None))
    src = LAYERS / f"{sprite}.png"
    if layer in BG_CROP:
        src, span = BACKGROUND, BG_CROP[layer]
    if not src.is_file():
        raise SystemExit(f"{layer}: sprite missing {src}")
    im = Image.open(src).convert("RGBA")
    if layer.startswith("tile_"):  # texture swatch: the plain crop, upscaled, no white margin
        im = im.crop(span).convert("RGB")
        s = max(1, 1024 // max(im.size))
        d = layer_dir(layer)
        d.mkdir(parents=True, exist_ok=True)
        im.resize((im.width * s, im.height * s), Image.LANCZOS).save(d / "source_prep.png")
        return {"layer": layer, "status": "prepped", "size": [im.width * s, im.height * s], "upscale": s}
    if span:
        im = im.crop(span if len(span) == 4 else (span[0], 0, span[1], im.height))
    bbox = im.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
    if not bbox:
        raise SystemExit(f"{layer}: sprite is empty")
    im = im.crop(bbox)
    scale = max(1, 1024 // max(im.size))
    im = im.resize((im.width * scale, im.height * scale), Image.LANCZOS)
    side = int(max(im.size) * 1.15)
    canvas = Image.new("RGBA", (side, side), (255, 255, 255, 255))
    canvas.alpha_composite(im, ((side - im.width) // 2, (side - im.height) // 2))
    d = layer_dir(layer)
    d.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(d / "source_prep.png")
    return {"layer": layer, "status": "prepped", "size": canvas.size, "upscale": scale}


def _task_file(layer: str, step: str, attempt: int) -> Path:
    return layer_dir(layer) / f"{step}_a{attempt}" / "task.json"


def concept_start(key: str, layer: str, attempt: int) -> dict:
    tf = _task_file(layer, "concept", attempt)
    if tf.is_file():
        return {"layer": layer, "status": "already_queued", "taskId": json.loads(tf.read_text())["taskId"]}
    if layer not in SUBJECT and layer not in TEXTURE_SUBJECT:
        raise SystemExit(f"{layer}: no SUBJECT description")
    src = layer_dir(layer) / "source_prep.png"
    if not src.is_file():
        raise SystemExit(f"{layer}: run prep first")
    prompt = (TEXTURE_PROMPT.format(subject=TEXTURE_SUBJECT[layer]) if layer in TEXTURE_SUBJECT
              else CONCEPT_PROMPT.format(subject=SUBJECT[layer]))
    guard_budget("image-to-image", key)
    tid = create_image_to_image(key, prompt=prompt, reference_paths=[src], ai_model="nano-banana-2",
                                aspect_ratio="1:1")
    tf.parent.mkdir(parents=True, exist_ok=True)
    tf.write_text(json.dumps({"taskId": tid, "kind": "image-to-image", "prompt": prompt,
                              "source": src.as_posix(), "approval": APPROVAL}, indent=2) + "\n", encoding="utf-8")
    return {"layer": layer, "status": "queued", "taskId": tid}


def mesh_start(key: str, layer: str, attempt: int, concept_attempt: int) -> dict:
    tf = _task_file(layer, "mesh", attempt)
    if tf.is_file():
        return {"layer": layer, "status": "already_queued", "taskId": json.loads(tf.read_text())["taskId"]}
    concept = layer_dir(layer) / f"concept_a{concept_attempt}" / "concept.png"
    if not concept.is_file():
        raise SystemExit(f"{layer}: concept_a{concept_attempt}/concept.png missing (poll the concept first)")
    if layer in TEXTURE_SUBJECT:
        raise SystemExit(f"{layer}: a tile texture has no mesh step")
    guard_budget("image-to-3d", key)
    dec = MESH_OPTS.get(layer, {}).get("decimation_mode", 3)
    tid = create_image_to_3d(key, image_path=concept, should_texture=True, target_polycount=None,
                             model_type="standard", ai_model="meshy-7", should_remesh=True, enable_pbr=True,
                             remove_lighting=False, texture_resolution="4k", decimation_mode=dec,
                             image_enhancement=False)
    tf.parent.mkdir(parents=True, exist_ok=True)
    tf.write_text(json.dumps({"taskId": tid, "kind": "image-to-3d", "source": concept.as_posix(),
                              "policy": f"meshy-7 standard textured pbr remove_lighting=false 4k decimation {dec}",
                              "approval": APPROVAL},
                             indent=2) + "\n", encoding="utf-8")
    return {"layer": layer, "status": "queued", "taskId": tid}


def poll(key: str, layer: str, step: str, attempt: int) -> dict:
    tf = _task_file(layer, step, attempt)
    if not tf.is_file():
        return {"layer": layer, "status": "not_queued"}
    meta = json.loads(tf.read_text(encoding="utf-8"))
    kind = meta["kind"]
    task = poll_task(key, kind, meta["taskId"], timeout_s=3600, interval_s=10)
    (tf.parent / "task_result.json").write_text(json.dumps(task, indent=2) + "\n", encoding="utf-8")
    res = {"layer": layer, "step": step, "status": task.get("status"), "taskId": meta["taskId"],
           "credits": task.get("consumed_credits")}
    if task.get("status") != "SUCCEEDED":
        res["error"] = task_error_message(task)
        return res
    if kind == "image-to-image":
        urls = task.get("image_urls") or []
        if not urls:
            res.update(status="FAILED", error="no image_urls")
            return res
        download_url(str(urls[0]), tf.parent / "concept.png")
        res["concept"] = (tf.parent / "concept.png").as_posix()
    else:
        urls = task.get("model_urls") or {}
        if not urls.get("glb"):
            res.update(status="FAILED", error="no glb url")
            return res
        download_url(str(urls["glb"]), tf.parent / "model.glb")
        for i, row in enumerate(task.get("texture_urls") or []):
            for tex in ("base_color", "metallic", "normal", "roughness", "emission"):
                if isinstance(row, dict) and row.get(tex):
                    download_url(str(row[tex]), tf.parent / f"texture_{i}_{tex}.png")
        res["glb"] = (tf.parent / "model.glb").as_posix()
    return res


def ledger(key: str | None) -> dict:
    rows = []
    total = 0
    for tf in sorted(OUT.glob("*/*_a*/task.json")):
        meta = json.loads(tf.read_text(encoding="utf-8"))
        rf = tf.parent / "task_result.json"
        task = json.loads(rf.read_text(encoding="utf-8")) if rf.is_file() else None
        if task is None and key:
            task = get_task(key, meta["kind"], meta["taskId"])
        credits = (task or {}).get("consumed_credits")
        total += int(credits or 0)
        rows.append({"layer": tf.parent.parent.name, "step": tf.parent.name, "kind": meta["kind"],
                     "taskId": meta["taskId"], "status": (task or {}).get("status"), "credits": credits,
                     "approval": meta.get("approval", "pilot_2026-09-26")})
    out = {"schema": "homm3_conflux_town_meshy_spend.v1", "tasks": rows, "totalCredits": total,
           "approvals": {k: {"cap": c, "committed": approval_spend(k)} for k, c in APPROVALS.items()},
           "activeApproval": APPROVAL,
           "note": "credits are Meshy consumed_credits; null = not yet polled to completion"}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "meshy_spend.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["prep", "concept", "mesh", "ledger"])
    ap.add_argument("--layer", action="append", default=[])
    ap.add_argument("--start", action="store_true")
    ap.add_argument("--poll", action="store_true")
    ap.add_argument("--attempt", type=int, default=1)
    ap.add_argument("--concept-attempt", type=int, default=1)
    a = ap.parse_args()
    if a.step == "prep":
        for layer in a.layer:
            print(json.dumps(prep(layer)))
        return 0
    key = load_api_key()
    if a.step == "ledger":
        print(json.dumps(ledger(key), indent=2))
        return 0
    if a.start == a.poll:
        ap.error("select exactly one of --start or --poll")
    for layer in a.layer:
        if a.start:
            r = concept_start(key, layer, a.attempt) if a.step == "concept" else \
                mesh_start(key, layer, a.attempt, a.concept_attempt)
        else:
            r = poll(key, layer, a.step, a.attempt)
        print(json.dumps(r), flush=True)
    ledger(None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
