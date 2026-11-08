"""Vanilla-style effects on HoMM3 adventure-map building meshes (lane ``vanilla_style_effect``).

    python tools/homm3_map_building_meshes/map_building_fx.py sources   # static read of the installed game (UnityPy)
    python tools/homm3_map_building_meshes/map_building_fx.py compile   # anim catalog + presets -> mesh-fx catalog rows
    python tools/homm3_map_building_meshes/map_building_fx.py check     # committed data only (build validator core)

Smoke, fire, glow and water on a map building are the game's own map-object ParticleSystems, cloned from a native
prefab subtree (``map_building_fx_presets.json``) onto a ``HOMM3_anim_anchor_<id>`` empty that
``map_building_anim.py build`` bakes into ``model_anim.glb``. No HoMM3 sprite is shown (the user rejected ripped
flipbooks, 2026-09-26). The anchor carries the subtree's native world rotation (``nativeWorldRotation``) turned by
the runtime billboard front yaw, so the clone keeps the orientation it has in its own prefab.

``compile`` turns every effect of the anim catalog into one ``homm3_mesh_fx`` row (lane ``map_building``, origin
``map_building_fx:<stem>``, socket ``bones`` = the anchor, ``vanillaStyle`` with the per-node runtime facts of
``tools/homm3_vfx/vanilla_style_fx.runtime_ps_facts``) and drops the superseded whole-prefab altar row.
``check`` recompiles in memory and fails on any difference, on a kept node whose material is not magic/VfxUber
(the shader that discards under fog of war), and on an effect without a row or a row without an effect.

Proof tier: generated artifact. Nothing here proves how the effects look in game.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tools/homm3_vfx"))
import vanilla_style_fx as VS  # noqa: E402  (flatten / resolve_child / subtree / runtime_ps_facts)

PLUGIN = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
PRESETS = TOOL_DIR / "map_building_fx_presets.json"
SOURCES = TOOL_DIR / "map_building_fx_sources.json"
ANIM_CATALOG = PLUGIN / "homm3_map_building_meshes" / "anim" / "catalog.json"
FX_CATALOG = PLUGIN / "homm3_mesh_fx" / "catalog.json"
PRESETS_SCHEMA = "homm3_map_building_fx_presets.v1"
SOURCES_SCHEMA = "homm3_map_building_fx_sources.v1"
ORIGIN_PREFIX = "map_building_fx:"
ANCHOR_PREFIX = "HOMM3_anim_anchor_"
FOW_SHADER = "magic/VfxUber"
# Whole-prefab map row this lane supersedes (fx_map_fire dropped on the avgfire0 mesh bounds).
SUPERSEDED_IDS = ("altar_of_fire_avgfire0",)
PROOF = "generated artifact; in-game look unproven"


class FxError(RuntimeError):
    pass


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def dump(p: Path, v) -> None:
    p.write_text(json.dumps(v, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def canonical_sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def presets() -> dict:
    doc = load(PRESETS)
    if doc.get("schema") != PRESETS_SCHEMA:
        raise FxError(f"{PRESETS.name}: schema {doc.get('schema')!r} != {PRESETS_SCHEMA}")
    return doc["presets"]


def cmd_sources() -> None:
    import vanilla_vfx_probe as probe  # UnityPy; read-only
    paths = sorted({p["resPath"] for p in presets().values()})
    out = {"schema": SOURCES_SCHEMA, "game": probe.GAME,
           "proof": "static read of installed serialized assets (tools/homm3_vfx/vanilla_vfx_probe.py); not runtime",
           "sources": {}}
    for p in paths:
        res = [r for r in probe.probe(p) if r["type"] == "GameObject"]
        if len(res) != 1:
            raise FxError(f"{p}: expected one GameObject in the ResourceManager container, got {len(res)}")
        out["sources"][p] = {"root": res[0]["tree"]["name"], "nodes": VS.flatten(res[0]["tree"], res[0].get("materials"))}
    dump(SOURCES, out)
    print(f"sources: {len(paths)} prefab(s) -> {SOURCES.relative_to(ROOT).as_posix()}")


def preset_facts(name: str, preset: dict, sources: dict, recolor) -> dict:
    """Resolved childPath, runtime per-node facts; refuses non-VfxUber, Shape-mode and scripted/animated nodes."""
    where = f"preset {name}"
    src = sources.get(preset["resPath"])
    if src is None:
        raise FxError(f"{where}: {preset['resPath']} not in {SOURCES.name}; rerun `sources`")
    full = VS.resolve_child(src, preset["childPath"], where)
    if full != preset["childPath"]:
        raise FxError(f"{where}: childPath must be the full path {full!r} (Transform.Find at runtime)")
    nodes = VS.subtree(src, full)
    for n in nodes.values():
        if n["director"] or n["animator"]:
            raise FxError(f"{where}: subtree node {n['path']!r} carries a director/animator")
    for k in preset["keepNodes"]:
        n = nodes.get(k)
        if n is None or not n.get("particleSystem"):
            raise FxError(f"{where}: keepNode {k!r} is not a ParticleSystem of the subtree")
        mats = (n.get("ps") or {}).get("materials") or []
        if not mats or any(m is None or m.get("shader") != FOW_SHADER for m in mats):
            raise FxError(f"{where}: keepNode {k!r} renders with {[m and m.get('shader') for m in mats]}; only "
                          f"{FOW_SHADER} (own fog-of-war discard) is allowed on the map")
    an = preset.get("anchorNode", "")
    if an and an not in preset["keepNodes"]:
        raise FxError(f"{where}: anchorNode {an!r} must be a kept node")
    layer = {"source": {"keepNodes": list(preset["keepNodes"])}, "recolor": recolor}
    return {"childPath": full, **VS.runtime_ps_facts(layer, nodes, where)}


def build_rows(anim_entries: list[dict], sources: dict) -> list[dict]:
    pre = presets()
    rows = []
    for e in anim_entries:
        for fx in e.get("effects") or []:
            p = pre.get(fx["preset"])
            if p is None:
                raise FxError(f"{e['relativePng']}: unknown preset {fx['preset']!r}")
            recolor = fx.get("recolor")
            facts = preset_facts(fx["preset"], p, sources, recolor)
            vs = {"childPath": facts["childPath"], "keepNodes": list(p["keepNodes"]), "worldScale": float(fx["scale"]),
                  "rateMul": float(fx.get("rateMul", 1.0)), "loop": True, "zeroChildPositions": False,
                  "orient": "bone", "bodyYawDeg": 0.0, "anchorNode": p.get("anchorNode", ""),
                  "recolor": [float(c) for c in recolor] if recolor else None,
                  "localScaleNodes": facts["localScaleNodes"], "recolorNodes": facts["recolorNodes"],
                  "endBehaviour": "stopEmitting"}
            stem = e["stem"]
            rows.append({"id": fx["fxId"], "lane": "map_building", "origin": ORIGIN_PREFIX + stem,
                         "match": {"prefabKeyContains": e["prefabKey"]}, "source": {"nativeResPath": p["resPath"]},
                         "socket": {"kind": "bones", "names": [fx["anchor"]], "localScale": [1.0, 1.0, 1.0]},
                         "trigger": {"mode": "always"}, "vanillaStyle": vs, "keepExistingGlow": False,
                         "proof": PROOF})
    return rows


def anim_entries() -> list[dict]:
    cat = load(ANIM_CATALOG)
    out = []
    for e in cat["entries"]:
        if e.get("effects"):
            out.append(e)
    return out


def cmd_compile() -> None:
    sources = load(SOURCES)
    if sources.get("schema") != SOURCES_SCHEMA:
        raise FxError(f"{SOURCES.name} missing or stale; run `sources`")
    rows = build_rows(anim_entries(), sources["sources"])
    catalog = load(FX_CATALOG)
    keep = [r for r in catalog["entries"]
            if not (r.get("origin") or "").startswith(ORIGIN_PREFIX) and r.get("id") not in SUPERSEDED_IDS]
    clash = {r["id"] for r in keep} & {r["id"] for r in rows}
    if clash:
        raise FxError(f"catalog ids already used by other rows: {sorted(clash)}")
    catalog["entries"] = keep + rows
    inv = catalog.get("inventory") or {}
    inv.pop("altarFireDonor", None)
    inv["mapBuildingEffects"] = ("map-object ParticleSystem subtrees of native prefabs (objects/fx, objects/interactive, "
                                 "objects/resource) cloned onto HOMM3_anim_anchor_* empties of the map-building meshes; "
                                 "tools/homm3_map_building_meshes/map_building_fx.py, origin map_building_fx:<stem>")
    catalog["inventory"] = inv
    catalog["proof"] = "source/static until in-map building effects and in-combat Crusader attack sparks are exercised"
    dump(FX_CATALOG, catalog)
    print(f"compile: {len(rows)} map-building effect row(s) -> {FX_CATALOG.relative_to(ROOT).as_posix()}")


def check() -> int:
    """Committed data only; returns the number of map-building effect rows. Raises FxError."""
    sources = load(SOURCES) if SOURCES.is_file() else {}
    if sources.get("schema") != SOURCES_SCHEMA:
        raise FxError(f"{SOURCES.name} missing or not {SOURCES_SCHEMA}")
    entries = anim_entries()
    want = build_rows(entries, sources["sources"])
    catalog = load(FX_CATALOG)
    have = [r for r in catalog["entries"] if (r.get("origin") or "").startswith(ORIGIN_PREFIX)]
    for r in catalog["entries"]:
        if r.get("id") in SUPERSEDED_IDS:
            raise FxError(f"catalog still carries the superseded map row {r['id']}")
        if r.get("lane") == "map_building" and not (r.get("origin") or "").startswith(ORIGIN_PREFIX):
            raise FxError(f"catalog row {r.get('id')}: every map_building row is a vanilla-style map_building_fx row")
    if canonical_sha(have) != canonical_sha(want):
        wid = {r["id"] for r in want}
        hid = {r["id"] for r in have}
        raise FxError("mesh-fx catalog map_building_fx rows differ from the anim catalog + presets "
                      f"(missing {sorted(wid - hid)}, extra {sorted(hid - wid)}); rerun `compile`")
    for e in entries:
        for fx in e["effects"]:
            if not fx["anchor"].startswith(ANCHOR_PREFIX):
                raise FxError(f"{e['relativePng']}: effect anchor {fx['anchor']!r} is not {ANCHOR_PREFIX}*")
    return len(want)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("sources", "compile", "check"))
    a = ap.parse_args()
    if a.command == "sources":
        cmd_sources()
    elif a.command == "compile":
        cmd_compile()
    else:
        print(f"check: ok {check()} map-building effect row(s)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (FxError, VS.VsError) as ex:
        print(f"FAIL: {ex}", file=sys.stderr)
        sys.exit(1)
