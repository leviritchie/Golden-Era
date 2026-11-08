#!/usr/bin/env python3
"""Focused proofs for portal / subterranean gate face rotation.

Run from repo root:
  PYTHONPATH=experiments/campaign_port_poc/raw_translation:experiments/campaign_port_poc/approach_cell:experiments/campaign_port_poc \\
    python experiments/campaign_port_poc/raw_translation/test_gate_face_rotation_portals.py
"""
from __future__ import annotations

import sys
from pathlib import Path

POC = Path(__file__).resolve().parents[1]
for path in (POC / "raw_translation", POC / "approach_cell", POC):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)

import gate_face_rotation as gfr
import surface_emit as single


PORTAL_5 = {
    "id": "portal_5",
    "sizeX": 2,
    "sizeZ": 2,
    "nodes": [1, 0, 0, 2],
    "canBeMirrored": True,
}


def _atlas(*, width: int = 8, height: int = 8, void_nodes: set[int] | None = None):
    cells = width * height
    tiles = [7] * cells  # Dirt
    water = [0] * cells
    for node in void_nodes or ():
        tiles[node] = 23
    return tiles, water


def _portal_group(*, object_id: int, anchor: int, rotation: int = 0) -> list[dict]:
    return [
        {
            "sid": "portal_5",
            "ids": [object_id],
            "nodes": [anchor],
            "rotations": [rotation],
            "levels": [0],
        }
    ]


def test_portal_5_is_eligible() -> None:
    assert gfr.is_eligible_gated_mirror_object("portal_5", PORTAL_5) is True
    assert gfr.is_eligible_gated_mirror_object(
        "homm3_subterranean_gate_portal",
        {**PORTAL_5, "id": "homm3_subterranean_gate_portal", "nodes": [1, 2, 2, 2]},
    ) is True


def test_covered_portal_5_mirrors_to_free_face() -> None:
    """Default GATE faces void rock; mirror faces open dirt — must rotate to 10."""
    width = height = 8
    anchor = 3 + 3 * width  # 27
    configs = {"portal_5": PORTAL_5}
    previous_w, previous_h = single.OLDEN_WIDTH, single.OLDEN_HEIGHT
    single.OLDEN_WIDTH = width
    single.OLDEN_HEIGHT = height
    try:
        default_gates = single.gate_nodes_for_object_instance(
            "portal_5", PORTAL_5, anchor, 0
        )
        default_occ = single.occupied_nodes_for_object_instance(
            "portal_5", PORTAL_5, anchor, 0
        )
        # Seal every land cardinal of the default GATE with Void (underground rock).
        # Do not void the mirrored GATE's free land cardinals.
        void_nodes: set[int] = set()
        for gate in default_gates:
            for neighbor in gfr._cardinal_neighbors(gate, width=width, height=height):
                if neighbor in default_occ or neighbor in default_gates:
                    continue
                void_nodes.add(neighbor)
        tiles, water = _atlas(width=width, height=height, void_nodes=void_nodes)

        free0 = gfr.free_cardinal_approaches(
            "portal_5",
            PORTAL_5,
            anchor,
            0,
            foreign_occupied=set(),
            tiles_map=tiles,
            water_map=water,
            width=width,
            height=height,
        )
        free10 = gfr.free_cardinal_approaches(
            "portal_5",
            PORTAL_5,
            anchor,
            10,
            foreign_occupied=set(),
            tiles_map=tiles,
            water_map=water,
            width=width,
            height=height,
        )
        assert not free0, f"fixture must seal default face; got {free0}"
        assert free10, f"fixture must leave mirrored face open; got {free10}"

        objects = _portal_group(object_id=100, anchor=anchor, rotation=0)
        report = gfr.apply_single_gate_face_rotations(
            objects,
            configs,
            tiles_map=tiles,
            water_map=water,
            width=width,
            height=height,
        )
    finally:
        single.OLDEN_WIDTH = previous_w
        single.OLDEN_HEIGHT = previous_h

    assert report["rotatedCount"] == 1, report
    row = report["rotated"][0]
    assert row["sid"] == "portal_5"
    assert row["fromRotation"] == 0
    assert row["toRotation"] == 10
    assert objects[0]["rotations"][0] == 10


def test_void_sealed_portal_carves_before_terrain_skip() -> None:
    """All land approaches void → carve Burrow then rotate/open rather than soft terrain-skip."""
    width = height = 8
    anchor = 3 + 3 * width
    previous_w, previous_h = single.OLDEN_WIDTH, single.OLDEN_HEIGHT
    single.OLDEN_WIDTH = width
    single.OLDEN_HEIGHT = height
    try:
        void_nodes: set[int] = set()
        for rotation in (0, 10):
            gates = single.gate_nodes_for_object_instance(
                "portal_5", PORTAL_5, anchor, rotation
            )
            occ = single.occupied_nodes_for_object_instance(
                "portal_5", PORTAL_5, anchor, rotation
            )
            for gate in gates:
                for neighbor in gfr._cardinal_neighbors(
                    gate, width=width, height=height
                ):
                    if neighbor not in occ and neighbor not in gates:
                        void_nodes.add(neighbor)
        tiles, water = _atlas(width=width, height=height, void_nodes=void_nodes)
        objects = _portal_group(object_id=101, anchor=anchor, rotation=0)
        report = gfr.apply_single_gate_face_rotations(
            objects,
            {"portal_5": PORTAL_5},
            tiles_map=tiles,
            water_map=water,
            width=width,
            height=height,
        )
    finally:
        single.OLDEN_WIDTH = previous_w
        single.OLDEN_HEIGHT = previous_h

    assert report["skippedTerrainSealedInstanceCount"] == 0, report
    assert report["rotatedCount"] == 1, report
    carved = report["rotated"][0].get("carvedVoidApproaches") or []
    assert carved, "expected void→Burrow carve on underground seal"
    assert any(int(tiles[row["node"]]) != 23 for row in carved)


def main() -> int:
    test_portal_5_is_eligible()
    test_covered_portal_5_mirrors_to_free_face()
    test_void_sealed_portal_carves_before_terrain_skip()
    print("test_gate_face_rotation_portals: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
