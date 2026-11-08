"""Which GLB the board renders and which DEF frames it compares against.

GLB selection (``shipped_glb``): the GLB the game ships for a lab sid is the frozen
``<selection out>/<labSid>/delivered_idle_retimed.glb`` of a delivery selection
(tools/homm3_def_retarget_delivery/*_slice_v1.json, schema homm3_def_retarget_delivery_selection.v1, not
``supersededBy``): freeze_slice.py copies the look-delivered canonical GLB to ``inputs/look_delivered.glb``, runs the
idle retime into ``delivered_idle_retimed.glb`` and pins its sha256 as ``frozen.idleRetimedGlbSha256``;
ship_def_retarget_slice.py hands that file to the Unity lab builder as the master (or its byte-derived
``delivered_idle_retimed.color0.glb`` when a vanilla-style spec bakes a displacement mask into COLOR_0: same
geometry and clips, so the board renders the uncoloured one and says so). The file must hash to its pin. When more
than one live selection carries the lab sid (e.g. h3_royal_griffin in castle_slice_v1 and castle_griffin_slice_v1)
the one whose bundle build (``bundle_build.json`` naming the unit) is newest wins, i.e. the last built bundle,
and every candidate is listed. No selection: the canonical retarget GLB with a loud note.
The base colour shipped is the selection's ``inputs/basecolor.png`` (the look's albedo; ``albedo`` uvAtlas units also
ship it as the body albedo); a --glb override or the fallback uses the GLB's own image.

Unit ids: a lab sid can be built from another retarget unit (fleet_census.SOURCE_UNIT, e.g. toa_boar_rider <-
h3_boar_rider). Selections are keyed by lab sid, retarget/mocap artifacts by the source unit.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SELECTIONS = ROOT / "tools/homm3_def_retarget_delivery"
RETARGET = ROOT / "artifacts/homm3_def_retarget"
MOCAP_RUNS = ROOT / "artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/runs"
SELECTION_SCHEMA = "homm3_def_retarget_delivery_selection.v1"
sys.path.insert(0, str(SELECTIONS))
from fleet_census import SOURCE_UNIT  # noqa: E402


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def load(p: Path):
    return json.loads(Path(p).read_text(encoding="utf-8-sig"))


def unit_ids(arg: str) -> tuple[str, str]:
    """(labSid, sourceUnit) for a lab sid or a source unit id."""
    if arg in SOURCE_UNIT:
        return arg, SOURCE_UNIT[arg]
    inv = {v: k for k, v in SOURCE_UNIT.items()}
    if arg in inv:
        return inv[arg], arg
    return arg, arg


def shipped_glb(lab: str, src: str) -> dict:
    cands = []
    for sp in sorted(SELECTIONS.glob("*.json")):
        try:
            doc = load(sp)
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict) or doc.get("schema") != SELECTION_SCHEMA:
            continue
        for row in doc.get("units", []):
            if row.get("labSid") != lab:
                continue
            out = ROOT / doc["out"]
            d = out / lab
            glb = d / "delivered_idle_retimed.glb"
            bb = out / "bundle_build.json"
            built = bb.is_file() and f'"{lab}"' in bb.read_text(encoding="utf-8", errors="replace")
            cands.append({"selection": sp.name, "supersededBy": doc.get("supersededBy"), "glb": glb, "dir": d,
                          "pin": (row.get("frozen") or {}).get("idleRetimedGlbSha256"), "row": row,
                          "bundleBuilt": built, "bundleBuildMtime": bb.stat().st_mtime if bb.is_file() else 0.0})
    live = [c for c in cands if not c["supersededBy"]]
    notes = []
    for c in live:
        c["exists"] = c["glb"].is_file()
        c["sha256"] = sha256(c["glb"]) if c["exists"] else None
        c["pinOk"] = c["exists"] and c["sha256"] == c["pin"]
    ok = [c for c in live if c["pinOk"]]
    listing = [{"selection": c["selection"], "glb": c["glb"].relative_to(ROOT).as_posix(), "pinOk": c.get("pinOk"),
                "bundleBuilt": c["bundleBuilt"]} for c in cands]
    if ok:
        ok.sort(key=lambda c: (c["bundleBuilt"], c["bundleBuildMtime"]), reverse=True)
        c = ok[0]
        if len(ok) > 1:
            notes.append(f"{lab} is in {len(ok)} live selections; chose {c['selection']} (newest bundle build naming "
                         f"the unit)")
        color0 = c["dir"] / "delivered_idle_retimed.color0.glb"
        if color0.is_file():
            notes.append("a displacement-mask master (delivered_idle_retimed.color0.glb) ships; it is this GLB plus "
                         "COLOR_0, so the board renders the uncoloured one")
        base = c["dir"] / "inputs/basecolor.png"
        return {"mode": "shipped", "path": c["glb"], "sha256": c["sha256"], "selection": c["selection"],
                "row": c["row"], "albedo": base if base.is_file() else None, "candidates": listing, "notes": notes}
    bad = [c for c in live if not c["pinOk"]]
    if bad:
        notes.append("FALLBACK: live selection rows exist but their frozen GLB is missing or off its pin: "
                     + "; ".join(f"{c['selection']} exists={c['exists']}" for c in bad))
    fb = RETARGET / src / f"{src}_def_retarget.glb"
    if not fb.is_file():
        raise SystemExit(f"{lab}: no frozen selection GLB and no canonical retarget GLB at {fb}")
    notes.append(f"FALLBACK: {lab} is in no live delivery selection; rendering the canonical retarget GLB "
                 f"{fb.relative_to(ROOT).as_posix()}, which is NOT what the game ships (no idle retime, look not frozen)")
    return {"mode": "fallback_canonical", "path": fb, "sha256": sha256(fb), "selection": None, "row": None,
            "albedo": None, "candidates": listing, "notes": notes}


def def_reference(src: str) -> dict:
    """DEF groups as the retarget build saw them: master_sequence.json (groups, roles, contract suffixes) and the
    build's frames.json (the PNG list the sprite camera was calibrated on; it must agree with the master), the
    sprite camera and the loop facts (closing + transition keys of Idle/Move)."""
    msp = MOCAP_RUNS / src / "linked_master/master_sequence/master_sequence.json"
    if not msp.is_file():
        raise SystemExit(f"{src}: no linked master at {msp}")
    ms = load(msp)
    C = RETARGET / src
    fjp = C / f"{src}_def_retarget.blend.frames.json"
    scp = C / f"{src}_def_retarget.blend.spritecam.json"
    if not scp.is_file():
        raise SystemExit(f"{src}: no sprite camera at {scp}")
    notes = []
    fj = load(fjp) if fjp.is_file() else None
    pngs = [f["sourcePng"] for f in ms["frames"]]
    loops = {}
    if fj:
        if fj["segments"] != [[s["clipKey"], s["globalStart"], s["globalEnd"]] for s in ms["segments"]]:
            raise SystemExit(f"{src}: frames.json segments disagree with master_sequence.json")
        if fj["sources"] != pngs:
            notes.append("frames.json sources differ from master_sequence sourcePng; using frames.json (the sprite "
                         "camera's calibration set)")
            pngs = fj["sources"]
        loops = fj.get("loops", {})
    else:
        notes.append("no frames.json: loop transition keys unknown (assumed 0)")
    clips = []
    for s in ms["segments"]:
        if s["role"] == "bookend" or not s.get("exportsClip", True):
            continue
        clips.append({"clipKey": s["clipKey"], "defGroup": s["defGroup"], "clip": "Unit_" + s["contractSuffix"],
                      "frames": pngs[s["globalStart"]:s["globalEnd"]], "loop": loops.get("Unit_" + s["contractSuffix"])})
    sip = C / "sprite_info.json"
    return {"master": msp, "framesJson": fjp if fj else None, "spritecam": load(scp), "spritecamPath": scp,
            "spriteInfo": load(sip) if sip.is_file() else None,
            "clips": clips, "skipped": ms.get("skippedClips", []), "notes": notes}


def preview_framing(lab: str, game_sid: str | None) -> dict | None:
    p = ROOT / "tools/homm3_import/owned_preview_framing.json"
    if not p.is_file():
        return None
    rows = load(p).get("rows", {})
    return rows.get(lab) or (rows.get(game_sid) if game_sid else None)
