#!/usr/bin/env python3
"""Measure the native adventure-map / battle size convention of stock Olden Era units.

Why
---
Owned-skinned HoMM3 units are battle-sized from ``battleHeightHexes * battleWorldHeightPerHex``
(``Homm3ImportVisuals.FitSkinnedBattleMesh``). The adventure-map lane used the same battle
target (``source=hex-map``), so every map squad stood at full battle height. Stock units do not:
each vanilla unit ships a ``<unit>`` battle prefab and a ``<unit>_map`` prefab that reuse the
same skinned mesh under a smaller scale node (troglodyte: battle node scale 44, map node 32).

What this measures
------------------
For every ``units/*/1prefabs/<unit>`` + ``<unit>_map`` pair in the installed game's
``resources.assets`` whose largest SkinnedMeshRenderer draws the *same mesh* in both prefabs,
the ratio is ``mapChainScale / battleChainScale`` (product of the transform localScale chain
down to that renderer). Because the mesh is identical, this ratio is exactly the map/battle
world-height ratio for that unit. The median over all pairs is written as
``adventureMapToBattleHeightRatio`` into ``OfflineUnlockMod/homm3_import.json`` (``--write``),
and the full measurement (per-pair rows, spread, the troglodyte map-shell donor) is written to
``native_map_battle_scale.json`` beside this script. The runtime then fits a map squad to
``battleHeightHexes * battleWorldHeightPerHex * adventureMapToBattleHeightRatio``.

Proof: static / generated artifact (installed game assets read with UnityPy). Runtime size is
proven only by the ``skinned fit source=hex-map`` log line plus in-game inspection.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GAME_DATA = Path(
    r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era/HeroesOldenEra_Data"
)
IMPORT_TABLE = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "homm3_import.json"
ARTIFACT = Path(__file__).resolve().parent / "native_map_battle_scale.json"
TABLE_KEY = "adventureMapToBattleHeightRatio"
DONOR_SHELL_UNITS = (
    "units/dungeon/1prefabs/troglodyte",
    "units/dungeon/1prefabs/troglodyte_upg",
    "units/dungeon/1prefabs/troglodyte_upg_alt",
)


def _components(go: Any) -> list[Any]:
    out = []
    for c in go.m_Component:
        ptr = c.component if hasattr(c, "component") else c
        try:
            out.append(ptr.read())
        except Exception:  # noqa: BLE001 - unreadable script components are irrelevant here
            continue
    return out


def _transform(go: Any) -> Any:
    for comp in _components(go):
        if comp.object_reader.type.name == "Transform":
            return comp
    raise RuntimeError(f"prefab root {go.m_Name!r} has no Transform")


def _skinned_renderers(t: Any, chain: float, acc: list[dict[str, Any]]) -> None:
    chain *= float(t.m_LocalScale.y)
    go = t.m_GameObject.read()
    for comp in _components(go):
        if comp.object_reader.type.name != "SkinnedMeshRenderer":
            continue
        try:
            mesh = comp.m_Mesh.read()
            mesh_name = mesh.m_Name
            mesh_ext_y = float(mesh.m_LocalAABB.m_Extent.y)
        except Exception:  # noqa: BLE001 - renderer without a readable mesh cannot be compared
            continue
        acc.append({"renderer": go.m_Name, "mesh": mesh_name, "chainScale": chain, "meshHeight": 2.0 * mesh_ext_y})
    for child in t.m_Children:
        _skinned_renderers(child.read(), chain, acc)


def _main_renderer(resources: Any, path_id: int) -> dict[str, Any] | None:
    go = resources.objects[path_id].read()
    acc: list[dict[str, Any]] = []
    _skinned_renderers(_transform(go), 1.0, acc)
    if not acc:
        return None
    return max(acc, key=lambda r: r["meshHeight"] * abs(r["chainScale"]))


def measure(game_data: Path) -> dict[str, Any]:
    import UnityPy  # local import: only the measurement needs it

    env = UnityPy.load(str(game_data / "globalgamemanagers"), str(game_data / "resources.assets"))
    manager = next(o.read() for o in env.objects if o.type.name == "ResourceManager")
    container = {str(k).lower(): v.m_PathID for k, v in manager.m_Container}
    resources = next(a for a in env.assets if a.name.endswith("resources.assets"))

    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for key in sorted(container):
        if not (key.startswith("units/") and key.endswith("_map")):
            continue
        battle_key = key[: -len("_map")]
        if battle_key not in container:
            continue
        battle = _main_renderer(resources, container[battle_key])
        adventure = _main_renderer(resources, container[key])
        if not battle or not adventure:
            skipped.append({"unit": battle_key, "reason": "no skinned renderer"})
            continue
        if battle["mesh"] != adventure["mesh"]:
            skipped.append({"unit": battle_key, "reason": "map prefab uses a different mesh"})
            continue
        if battle["chainScale"] <= 0 or adventure["chainScale"] <= 0:
            skipped.append({"unit": battle_key, "reason": "non-positive scale chain"})
            continue
        ratio = adventure["chainScale"] / battle["chainScale"]
        if not 0.05 < ratio < 2.0:
            # Prefab authored with the scale on a different node (bone-space mesh) -- the scale
            # chains are not comparable, so this pair cannot state the convention.
            skipped.append({"unit": battle_key, "reason": f"scale chains not comparable (ratio {ratio:.4g})"})
            continue
        rows.append({
            "unit": battle_key,
            "mesh": battle["mesh"],
            "battleChainScale": round(battle["chainScale"], 6),
            "mapChainScale": round(adventure["chainScale"], 6),
            "ratio": round(ratio, 6),
        })

    if not rows:
        raise RuntimeError("no comparable vanilla battle/map prefab pairs were found")
    ratios = sorted(r["ratio"] for r in rows)
    n = len(ratios)
    donors = [r for r in rows if r["unit"] in DONOR_SHELL_UNITS]
    return {
        "schema": "native_map_battle_scale.v1",
        "gameData": str(game_data).replace("\\", "/"),
        "rule": "mapChainScale / battleChainScale of the same skinned mesh in <unit>_map vs <unit>",
        "measuredPairs": n,
        "skippedPairs": len(skipped),
        "median": round(statistics.median(ratios), 3),
        "mean": round(statistics.mean(ratios), 4),
        "p10": round(ratios[n // 10], 4),
        "p90": round(ratios[(9 * n) // 10], 4),
        "min": round(ratios[0], 4),
        "max": round(ratios[-1], 4),
        "mapShellDonor": donors,
        "pairs": rows,
        "skipped": skipped,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game-data", type=Path, default=DEFAULT_GAME_DATA)
    parser.add_argument("--write", action="store_true", help=f"write {TABLE_KEY} into homm3_import.json")
    args = parser.parse_args(argv)

    result = measure(args.game_data)
    ARTIFACT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        f"{result['measuredPairs']} pairs: median {result['median']} "
        f"(p10 {result['p10']}, p90 {result['p90']}); donor shell {[d['ratio'] for d in result['mapShellDonor']]}"
    )
    if args.write:
        raw = IMPORT_TABLE.read_bytes()
        table = json.loads(raw.decode("utf-8-sig"))
        table[TABLE_KEY] = result["median"]
        out = json.dumps(table, indent=2, ensure_ascii=False) + "\n"
        if b"\r\n" in raw:
            out = out.replace("\n", "\r\n")
        IMPORT_TABLE.write_bytes(out.encode("utf-8"))
        print(f"wrote {TABLE_KEY}={result['median']} into {IMPORT_TABLE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
