#!/usr/bin/env python3
"""Validate the audit model against the recovered native footprint contract."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POC = ROOT / "experiments" / "campaign_port_poc"
sys.path.insert(0, str(POC))

from native_footprint_model_v2 import model_native_footprint


STABLES = {
    "canBeMirrored": True,
    "flippedOffset": 1,
    "pivotX": 1,
    "pivotZ": 0,
    "offsetX": 0.5,
    "offsetZ": 0.45,
    "sizeX": 3,
    "sizeZ": 3,
    "nodes": [0, 1, 1, 2, 1, 1, 2, 2, 0],
    "generatorConfig": {
        "buildingSizeX": 2,
        "buildingSizeZ": 2,
        "buildingLeftBottomX": 1,
        "buildingLeftBottomZ": 1,
    },
}


def validate_stables_case() -> None:
    model = model_native_footprint("stables", STABLES, 45 + 12 * 160, 10)
    assert model.native_orientation == "mirrored"
    assert model.occupied_cells == frozenset({1805, 1806, 1965, 1966})
    assert 1805 in model.occupied_cells, "native stables footprint must block [45,11]"
    assert model.legacy_occupied_cells == frozenset({2125, 2126, 2285, 2286})
    assert model.native_only_occupied_cells == frozenset({1805, 1806, 1965, 1966})
    assert model.legacy_only_occupied_cells == frozenset({2125, 2126, 2285, 2286})


def validate_unmirrored_pivot_case() -> None:
    config = {
        "sizeX": 2,
        "sizeZ": 2,
        "pivotX": 1,
        "pivotZ": 1,
        "flippedOffset": 0,
        "nodes": [1, 0, 0, 1],
    }
    model = model_native_footprint("pivot_probe", config, 10 + 10 * 160, 0)
    assert model.occupied_cells == frozenset({1769, 1610})
    assert model.native_orientation == "unmirrored"


def validate_scenery_pivot_case() -> None:
    config = {
        "tag": "Environment",
        "sizeX": 2,
        "sizeZ": 2,
        "pivotX": 0,
        "pivotZ": 0,
        "flippedOffset": 1,
        "offsetX": 0.5,
        "offsetZ": 0.5,
        "nodes": [1, 1, 1, 1],
    }
    model = model_native_footprint("scenery_probe", config, 10 + 10 * 160, 0)
    assert model.occupied_cells == frozenset({1450, 1451, 1610, 1611})
    assert model.legacy_occupied_cells == frozenset({1610, 1611, 1770, 1771})
    assert "presentation_offset_cell_semantics_unresolved" in model.unresolved


def validate_unknown_rotation_is_not_silent() -> None:
    model = model_native_footprint("unknown_rotation", {"sizeX": 1, "sizeZ": 1, "nodes": [1]}, 1, 3)
    assert model.native_orientation.startswith("unresolved_")
    assert "rotation_semantics_unresolved" in model.unresolved
    assert model.runtime_model_status == "unresolved_rotation_candidate"


def validate_missing_pivot_uses_native_zero() -> None:
    config = {
        "sizeX": 3,
        "sizeZ": 3,
        "nodes": [2, 2, 2, 2, 1, 2, 2, 2, 2],
    }
    model = model_native_footprint("environment_probe", config, 4359, 0)
    assert model.occupied_cells == frozenset({4200})
    assert "pivot_missing_or_invalid_defaulted_zero" in model.unresolved


def validate_missing_flipped_offset_uses_native_zero() -> None:
    config = {
        "sizeX": 3,
        "sizeZ": 3,
        "pivotX": 1,
        "pivotZ": 1,
        "nodes": [2, 2, 2, 2, 1, 2, 2, 2, 2],
        "canBeMirrored": True,
    }
    model = model_native_footprint("prison", config, 4359, 10)
    assert model.occupied_cells == frozenset({4358})
    assert "flipped_offset_missing_or_invalid_defaulted_zero" in model.unresolved


def main() -> int:
    validate_stables_case()
    validate_unmirrored_pivot_case()
    validate_scenery_pivot_case()
    validate_unknown_rotation_is_not_silent()
    validate_missing_pivot_uses_native_zero()
    validate_missing_flipped_offset_uses_native_zero()
    print("native footprint model contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
