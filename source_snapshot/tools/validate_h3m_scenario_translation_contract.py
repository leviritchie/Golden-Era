#!/usr/bin/env python3
"""Validate neutral HoMM3 scenario translation helpers."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def require_raises(fn: Callable[[], object], expected: type[Exception], label: str, errors: list[str]) -> None:
    try:
        fn()
    except expected:
        return
    except Exception as exc:  # noqa: BLE001 - contract should report wrong exception type.
        errors.append(f"{label} raised {type(exc).__name__}, expected {expected.__name__}: {exc}")
        return
    errors.append(f"{label} did not raise {expected.__name__}")


def make_gate(object_id: int, layer: int, x: int, y: int, template_object_id: int) -> dict[str, object]:
    return {
        "sourceIndex": object_id,
        "sourceLayer": layer,
        "sourceX": x,
        "sourceY": y,
        "templateObjectId": template_object_id,
        "templateAnimation": "AvTCave.def",
        "category": "travel_link_candidate",
        "payloadKind": "explicit_no_payload",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=Path(__file__).resolve().parents[1], type=Path)
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    sys.path.insert(0, str(repo_root / "experiments" / "campaign_port_poc"))

    import h3m_object_registry as h3obj
    import h3m_scenario_translation as scenario

    errors: list[str] = []

    layout36 = scenario.build_side_by_side_layer_atlas(source_width=36, source_height=36, layer_ids=[0, 1], view_names={0: "surface", 1: "underground"}, underground_layers={1})
    require(layout36.layer_width == 48 and layout36.layer_height == 48, f"36x36 layer alignment mismatch: {layout36}", errors)
    require(layout36.atlas_width == 96 and layout36.atlas_height == 48, f"36x36 atlas size mismatch: {layout36}", errors)
    require(layout36.source_offset_x == 6 and layout36.source_offset_y == 6, f"36x36 centered offset mismatch: {layout36}", errors)
    require(layout36.layers[0]["view"] == {"name": "surface", "minSecX": 0, "minSecZ": 0, "secSizeX": 3, "secSizeZ": 3, "isUnderground": False, "stack": -1}, "36x36 surface view mismatch", errors)
    require(layout36.layers[1]["view"] == {"name": "underground", "minSecX": 3, "minSecZ": 0, "secSizeX": 3, "secSizeZ": 3, "isUnderground": True, "stack": -1}, "36x36 underground view mismatch", errors)
    require(layout36.target_node(0, 0, 0) == (35 + 6) * 96 + 6, "36x36 surface target node mismatch", errors)
    require(layout36.target_node(1, 35, 35) == (0 + 6) * 96 + 48 + 6 + 35, "36x36 underground target node mismatch", errors)

    layout72 = scenario.build_side_by_side_layer_atlas(source_width=72, source_height=72, layer_ids=[0, 1], view_names={0: "surface", 1: "underground"}, underground_layers={1})
    require(layout72.layer_width == 80 and layout72.layer_height == 80, "72x72 layer alignment mismatch", errors)
    require(layout72.atlas_width == 160 and layout72.atlas_height == 80, "72x72 atlas size mismatch", errors)
    require(layout72.layers[0]["view"]["secSizeX"] == 5 and layout72.layers[1]["view"]["minSecX"] == 5, "72x72 view section mismatch", errors)
    require(layout72.target_node(1, 49, 3) == (71 - 3 + 4) * 160 + 84 + 49, "72x72 underground target node mismatch", errors)

    layout144 = scenario.build_side_by_side_layer_atlas(source_width=144, source_height=144, layer_ids=[0, 1], view_names={0: "surface", 1: "underground"}, underground_layers={1})
    require(layout144.layer_width == 144 and layout144.layer_height == 144, "144x144 exact-sector layer mismatch", errors)
    require(layout144.source_offset_x == 0 and layout144.source_offset_y == 0, "144x144 offset mismatch", errors)
    require(layout144.layers[1]["view"] == {"name": "underground", "minSecX": 9, "minSecZ": 0, "secSizeX": 9, "secSizeZ": 9, "isUnderground": True, "stack": -1}, "144x144 underground view mismatch", errors)

    default_underground = scenario.build_side_by_side_layer_atlas(source_width=72, source_height=72, layer_ids=[0, 1])
    require(default_underground.layers[0]["view"]["isUnderground"] is False and default_underground.layers[1]["view"]["isUnderground"] is True, "default underground layer policy mismatch", errors)
    no_underground = scenario.build_side_by_side_layer_atlas(source_width=72, source_height=72, layer_ids=[0, 1], underground_layers=set())
    require(no_underground.layers[0]["view"]["isUnderground"] is False and no_underground.layers[1]["view"]["isUnderground"] is False, "explicit empty underground layer set was not preserved", errors)

    require_raises(lambda: scenario.build_side_by_side_layer_atlas(source_width=0, source_height=72, layer_ids=[0, 1]), scenario.ScenarioTranslationError, "zero source width", errors)
    require_raises(lambda: scenario.build_side_by_side_layer_atlas(source_width=72, source_height=72, layer_ids=[0, 0]), scenario.ScenarioTranslationError, "duplicate layer ids", errors)
    require_raises(lambda: scenario.build_side_by_side_layer_atlas(source_width=72, source_height=72, layer_ids=[0, 1], underground_layers={2}), scenario.ScenarioTranslationError, "unknown underground layer id", errors)
    require_raises(lambda: layout72.target_node(2, 0, 0), scenario.ScenarioTranslationError, "unsupported target layer", errors)
    require_raises(lambda: layout72.target_node(0, 72, 0), scenario.ScenarioTranslationError, "target x out of bounds", errors)

    require(scenario.project_h3_road_code(0, 0) == 0, "zero road mapping mismatch", errors)
    require(scenario.project_h3_road_code(0, 1) == 1, "H3 road code 1 mapping mismatch", errors)
    require(scenario.project_h3_road_code(0, 2) == 2, "H3 road code 2 mapping mismatch", errors)
    require(scenario.project_h3_road_code(0, 3) == 2, "H3 road code 3→Olden 2 lossy mapping mismatch", errors)
    require(scenario.project_h3_road_code(1, 1) == 1, "underground road code 1 mapping mismatch", errors)
    require(scenario.project_h3_road_code(1, 3) == 2, "underground road code 3→2 mapping mismatch", errors)
    require_raises(lambda: scenario.project_h3_road_code(0, 4), scenario.ScenarioTranslationError, "unsupported surface road code", errors)

    paired = scenario.pair_subterranean_gates_by_nearest_cross_layer_rule([
        make_gate(10, 0, 5, 5, h3obj.OBJECT_SUBTERRANEAN_GATE),
        make_gate(11, 1, 6, 6, h3obj.OBJECT_SUBTERRANEAN_GATE),
        make_gate(12, 0, 40, 40, h3obj.OBJECT_SUBTERRANEAN_GATE),
        make_gate(13, 1, 42, 41, h3obj.OBJECT_SUBTERRANEAN_GATE),
    ])
    require(paired.get("objectId") == h3obj.OBJECT_SUBTERRANEAN_GATE, "paired contract object id mismatch", errors)
    require(paired.get("policy") == scenario.SUBTERRANEAN_GATE_PAIRING_POLICY, "paired contract policy mismatch", errors)
    require(paired.get("pairCount") == 2, "paired contract pair count mismatch", errors)
    require(
        [(row["surfaceObjectId"], row["undergroundObjectId"], row["sourceDistanceSquared"]) for row in paired.get("pairs") or []] == [(10, 11, 2), (12, 13, 5)],
        f"paired contract records mismatch: {paired.get('pairs')}",
        errors,
    )

    empty = scenario.pair_subterranean_gates_by_nearest_cross_layer_rule([])
    require(empty.get("pairCount") == 0 and empty.get("pairs") == [], "empty gate pairing contract mismatch", errors)
    require_raises(lambda: scenario.pair_subterranean_gates_by_nearest_cross_layer_rule([make_gate(20, 0, 1, 1, h3obj.OBJECT_SUBTERRANEAN_GATE)]), scenario.ScenarioTravelPairingError, "gate count mismatch", errors)
    require_raises(lambda: scenario.pair_subterranean_gates_by_nearest_cross_layer_rule([make_gate(20, 0, 1, 1, h3obj.OBJECT_SUBTERRANEAN_GATE), make_gate(21, 2, 1, 1, h3obj.OBJECT_SUBTERRANEAN_GATE)]), scenario.ScenarioTravelPairingError, "unsupported gate layers", errors)
    conflict = scenario.pair_subterranean_gates_by_nearest_cross_layer_rule([
        make_gate(30, 0, 0, 0, h3obj.OBJECT_SUBTERRANEAN_GATE),
        make_gate(31, 0, 1, 0, h3obj.OBJECT_SUBTERRANEAN_GATE),
        make_gate(32, 1, 0, 0, h3obj.OBJECT_SUBTERRANEAN_GATE),
        make_gate(33, 1, 100, 100, h3obj.OBJECT_SUBTERRANEAN_GATE),
    ])
    require(
        conflict.get("policy") == "greedy_min_distance_fallback_when_mutual_nearest_conflicts",
        "non-mutual nearest conflict should use greedy fallback policy",
        errors,
    )
    require(conflict.get("pairCount") == 2, "greedy fallback pair count mismatch", errors)
    require(
        [(row["surfaceObjectId"], row["undergroundObjectId"]) for row in conflict.get("pairs") or []]
        == [(30, 32), (31, 33)],
        f"greedy fallback records mismatch: {conflict.get('pairs')}",
        errors,
    )

    def make_monolith(object_id: int, layer: int, x: int, y: int, animation: str) -> dict[str, object]:
        return {
            "sourceIndex": object_id,
            "sourceLayer": layer,
            "sourceX": x,
            "sourceY": y,
            "templateObjectId": h3obj.OBJECT_TWO_WAY_MONOLITH,
            "templateAnimation": animation,
            "category": "travel_link_candidate",
            "payloadKind": "explicit_no_payload",
        }

    # Classic RoE/AB/SoD maps pair same-color two-way monoliths across layers.
    cross_layer = scenario.pair_two_way_monoliths_by_animation_same_layer_rule([
        make_monolith(190, 0, 35, 12, "AVXmn2g0.def"),
        make_monolith(1055, 1, 39, 4, "AVXmn2g0.def"),
        make_monolith(191, 0, 56, 35, "AVXmn2p0.def"),
        make_monolith(1052, 1, 67, 34, "AVXmn2p0.def"),
    ])
    require(cross_layer.get("policy") == scenario.MONOLITH_TWO_WAY_PAIRING_POLICY, "monolith animation policy mismatch", errors)
    require(cross_layer.get("pairCount") == 4, f"cross-layer monolith pair count mismatch: {cross_layer.get('pairCount')}", errors)
    require(
        [
            (
                row["objectIdA"],
                row["sourceLayerA"],
                row["objectIdB"],
                row["sourceLayerB"],
                row["templateAnimation"],
                row["routing"],
            )
            for row in cross_layer.get("pairs") or []
        ]
        == [
            (190, 0, 1055, 1, "AVXmn2g0.def", "mutual_pair"),
            (1055, 1, 190, 0, "AVXmn2g0.def", "mutual_pair"),
            (191, 0, 1052, 1, "AVXmn2p0.def", "mutual_pair"),
            (1052, 1, 191, 0, "AVXmn2p0.def", "mutual_pair"),
        ],
        f"cross-layer monolith records mismatch: {cross_layer.get('pairs')}",
        errors,
    )
    require_raises(
        lambda: scenario.pair_two_way_monoliths_by_animation_same_layer_rule([
            make_monolith(1, 0, 0, 0, "AVXmn2g0.def"),
        ]),
        scenario.ScenarioTravelPairingError,
        "monolith singleton animation group",
        errors,
    )

    if errors:
        print("H3M scenario translation contract FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("H3M scenario translation contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())