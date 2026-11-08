#!/usr/bin/env python3
"""Town full-3D: the build states a player can reach, from the HoMM3 building tree (docs/homm3_city_building_tree.md).

    TOWN_FULL3D_FACTION=<t> python town_full3d_build_states.py      (prints the enumeration)

Why (Castle zs_v5, 2026-10-01): the certificate measured the profile's three hand-picked states (start, full, anim).
A player sees every prerequisite-closed subset of the tree, and a building's neighbours change what shows behind it.
All subsets are far too many, so the set is bounded:

  start    the profile's start state (what a new town has);
  full     the profile's full state;
  anim     the profile's animated state (when it has one);
  min_<layer>   for every reachable building layer (building_layer_map.json nativeLevels): the smallest
           prerequisite-closed state that contains it. That is start, plus the layer's building at its level, plus
           every requirement it needs (tools/release_port/homm3_city_building_tree.canonical_prereqs, the same
           table the shipped Core's prevBuildings come from), each building shown by its highest level's layer.

So every layer is seen present, both alone with what it needs and among everything (full). States that come out
identical are kept once, under the first name. enumerate_states() fails closed when a reachable layer's building is
not in the tree, or a required level has no layer and is not one the scene leaves unbuilt on purpose.

The recipe records the enumeration (names, layers, sha) in its result, and `verify` re-derives it: the set cannot
shrink silently (tools/validate_town_zero_streak_contract.py).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SCHEMA = "town_build_states.v1"


def _tree():
    sys.path.insert(0, str(ROOT / "tools" / "release_port"))
    import homm3_city_building_tree as BT
    return BT


def prereq_table(fraction: str, native: dict) -> dict:
    """{(sid, level): (reqs...)} over every level the tree or the layer map names."""
    BT = _tree()
    if fraction not in BT.FACTION_LEVEL_REQS:
        raise SystemExit(f"build states: no HoMM3 building tree for {fraction}")
    keys = {BT._parse(k) for k in BT.COMMON_LEVEL_REQS} | {BT._parse(k) for k in BT.FACTION_LEVEL_REQS[fraction]}
    keys |= {(sid, int(lv)) for sid, lvs in native.items() for lv in lvs}
    for sid, lv in list(keys):                   # every level below a present one is present
        keys |= {(sid, l) for l in range(1, lv)}
    while True:                                  # and every requirement the table names
        try:
            return BT.canonical_prereqs(fraction, sorted(keys))
        except ValueError as e:
            add = set()
            for part in str(e).split(";"):
                if " requires " in part and "which this city does not have" in part:
                    sid, lv = part.split(" requires ", 1)[1].split(",", 1)[0].strip().split("@")
                    add.add((sid, int(lv)))
            if not add or add <= keys:
                raise SystemExit(f"build states: {e}")
            keys |= add


GRAIL_SLOT = "Build_Golden_Calf"


def grail_aliased(fraction: str, native: dict) -> dict:
    """The layer map keys every town's grail layer by the engine's generic grail scene slot (Build_Golden_Calf); the
    tree names the faction's own grail (inferno Build_Eternal_Flame, necropolis Build_Gaping_Maw, ...). Rename the
    slot to the tree's grail SID: exactly one grail in the faction's tree, else fail closed (2026-10-01, inferno /
    necropolis / dungeon: "Build_Golden_Calf@1 has no canonical prerequisite entry"). Castle-like trees whose grail
    is Build_Golden_Calf are unchanged."""
    if GRAIL_SLOT not in native:
        return native
    BT = _tree()
    grails = sorted({BT._parse(k)[0] for k in BT.FACTION_LEVEL_REQS.get(fraction, {})} & BT.GRAIL_SIDS)
    if len(grails) != 1:
        raise SystemExit(f"build states: {fraction}: the tree names {len(grails)} grail buildings {grails}; the layer "
                         f"map's {GRAIL_SLOT} slot needs exactly one")
    if grails[0] == GRAIL_SLOT:
        return native
    if grails[0] in native:
        raise SystemExit(f"build states: {fraction}: the layer map names both {GRAIL_SLOT} and {grails[0]}")
    return {(grails[0] if k == GRAIL_SLOT else k): v for k, v in native.items()}


def closure(table: dict, key: tuple) -> set:
    out, todo = set(), [key]
    while todo:
        k = todo.pop()
        if k in out:
            continue
        if k not in table:
            raise SystemExit(f"build states: {k[0]}@{k[1]} is not in the building tree")
        out.add(k)
        todo.extend(table[k])
    return out


def enumerate_states(fp, layer_map: dict) -> dict:
    """{state name: [layers]} (see the module doc); fp is the faction profile (STATES, FRACTION)."""
    native = grail_aliased(fp.FRACTION, layer_map["nativeLevels"])
    table = prereq_table(fp.FRACTION, native)
    layer_of = {(sid, int(lv)): layer for sid, lvs in native.items() for lv, layer in lvs.items()}
    sid_of_layer = {layer: k for k, layer in layer_of.items()}
    start = list(fp.STATES["start"])
    start_keys = set()
    for layer in start:
        if layer not in sid_of_layer:
            raise SystemExit(f"build states: start layer {layer} has no native level")
        start_keys |= closure(table, sid_of_layer[layer])
    states = {"start": start, "full": list(fp.STATES["full"])}
    if "anim" in fp.STATES:
        states["anim"] = list(fp.STATES["anim"])
    seen = {tuple(sorted(v)): k for k, v in states.items()}
    for key in sorted(layer_of):
        built = start_keys | closure(table, key)
        top = {}
        for sid, lv in built:
            top[sid] = max(top.get(sid, 0), lv)
        layers = []
        for sid, lv in sorted(top.items()):
            # a building is drawn by its highest level that has a layer (a level the scene has no layer for, such
            # as a grail-only or OE-only level, draws nothing new)
            have = [l for l in range(lv, 0, -1) if (sid, l) in layer_of]
            if have:
                layers.append(layer_of[(sid, have[0])])
        sig = tuple(sorted(layers))
        if sig in seen:
            continue
        name = f"min_{layer_of[key]}"
        seen[sig] = name
        states[name] = sorted(layers)
    return states


def states_sha(states: dict) -> str:
    return hashlib.sha256(json.dumps(states, sort_keys=True).encode()).hexdigest()


def main() -> int:
    sys.path.insert(0, str(HERE))
    import stronghold_full3d_common as SC
    st = enumerate_states(SC.FP, SC.layer_map())
    print(json.dumps({"schema": SCHEMA, "faction": SC.FP.FRACTION, "count": len(st), "sha256": states_sha(st),
                      "states": st}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
