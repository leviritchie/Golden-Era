#!/usr/bin/env python3
"""Probe VCMI H3M scenarios for translator-test suitability.

This is intentionally read-only: it reports scenario shape, terrain/road/river
coverage, event-template presence, and the generic object-walker stop without
generating artifacts. By default it only parses asserted maps so build-time
validation is deterministic and not affected by unsupported broad HotA parsing.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
CAMPAIGN_POC_DIR = REPO_ROOT / "experiments" / "campaign_port_poc"
if str(CAMPAIGN_POC_DIR) not in sys.path:
    sys.path.insert(0, str(CAMPAIGN_POC_DIR))

from experiments.campaign_port_poc.h3m_object_walk import (  # noqa: E402
    probe_h3m_file,
    read_h3m_bytes,
    read_h3m_summary_and_templates,
)

EVENT_OBJECT_ID = 26
H3_TERRAIN_WATER = "8"
NO_FEATURE_KEY = "0"

ASSERTED_MAPS = {
    "Good to Go.h3m": "good_to_go",
    "The Great Race.h3m": "the_great_race",
}
EXPECTED_CONTRACTS: dict[str, dict[str, Any]] = {
    "Good to Go.h3m": {
        "status": "roe_random_hero_object_walk_complete",
        "layers": 1,
        "waterTerrainTileCount": 0,
        "riverTileCount": 0,
        "roadTileCount": 0,
        "eventTemplateCount": 0,
        "walkerComplete": True,
        "walkerDecodedCount": 413,
        "walkerDecodedObjectIdsInclude": [70],
        "unsupportedStopIndex": None,
        "unsupportedRecordOffset": None,
        "unsupportedObjectId": None,
        "unsupportedDecoderStatus": None,
        "unsupportedError": None,
    },
    "The Great Race.h3m": {
        "status": "event_candidate_object_walk_complete",
        "layers": 1,
        "waterTerrainTileCount": 0,
        "eventTemplateCountMin": 1,
        "riverTileCount": 32,
        "roadTileCount": 163,
        "roadMappingStatus": "supported_feature_pending_mapping",
        "riverMappingStatus": "reported_complication_pending_mapping",
        "walkerComplete": True,
        "walkerDecodedCount": 1935,
        "walkerDecodedObjectIdsInclude": [206, 207],
        "unsupportedStopIndex": None,
        "unsupportedRecordOffset": None,
        "unsupportedObjectId": None,
        "unsupportedDecoderStatus": None,
        "unsupportedError": None,
    },
}


@dataclass(frozen=True)
class ScenarioProbe:
    title: str
    path: str
    size: int
    layers: int
    water_terrain_tile_count: int
    river_tile_count: int
    road_tile_count: int
    template_count: int
    object_count: int
    event_template_count: int
    walker_complete: bool
    walker_decoded_count: int
    walker_unsupported_object_id: int | None
    walker_unsupported_decoder_status: str | None
    walker_unsupported_stop_index: int | None
    walker_unsupported_record_offset: str | None
    walker_unsupported_error: str | None
    walker_decoded_object_ids: list[int]
    terrain_histograms: list[dict[str, int]]
    road_histograms: list[dict[str, int]]
    river_histograms: list[dict[str, int]]

    def to_json(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "path": self.path,
            "size": self.size,
            "layers": self.layers,
            "waterTerrainTileCount": self.water_terrain_tile_count,
            "riverTileCount": self.river_tile_count,
            "roadTileCount": self.road_tile_count,
            "templateCount": self.template_count,
            "objectCount": self.object_count,
            "eventTemplateCount": self.event_template_count,
            "walkerComplete": self.walker_complete,
            "walkerDecodedCount": self.walker_decoded_count,
            "walkerUnsupportedObjectId": self.walker_unsupported_object_id,
            "walkerUnsupportedDecoderStatus": self.walker_unsupported_decoder_status,
            "walkerUnsupportedStopIndex": self.walker_unsupported_stop_index,
            "walkerUnsupportedRecordOffset": self.walker_unsupported_record_offset,
            "walkerUnsupportedError": self.walker_unsupported_error,
            "terrainHistogramsByLayer": self.terrain_histograms,
            "roadHistogramsByLayer": self.road_histograms,
            "riverHistogramsByLayer": self.river_histograms,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan VCMI H3M scenarios and assert event-test candidate contracts.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root containing vcmi/Maps.",
    )
    parser.add_argument(
        "--scan-all-report-only",
        action="store_true",
        help="Also scan every vcmi/Maps .h3m and report non-asserted parse errors without making them build blockers.",
    )
    parser.add_argument(
        "--no-contract",
        action="store_true",
        help="Report parsed map facts only; asserted map parse errors still fail.",
    )
    return parser.parse_args()



def histogram_total(histograms: list[dict[str, int]], key: str) -> int:
    return sum(histogram.get(key, 0) for histogram in histograms)


def nonzero_histogram_total(histograms: list[dict[str, int]]) -> int:
    total = 0
    for histogram in histograms:
        for key, count in histogram.items():
            if key != NO_FEATURE_KEY:
                total += count
    return total



def probe_h3m(path: Path, repo_root: Path) -> ScenarioProbe:
    payload = read_h3m_bytes(path)
    summary, templates = read_h3m_summary_and_templates(payload)
    event_template_count = sum(1 for template in templates if template["objectId"] == EVENT_OBJECT_ID)
    walk = probe_h3m_file(path, include_records=True)
    object_table = walk["objectTable"]
    unsupported_stop = object_table.get("unsupportedStop")
    unsupported_record = (unsupported_stop or {}).get("record") or {}
    decoded_object_ids = [record["templateObjectId"] for record in walk.get("records", [])]
    return ScenarioProbe(
        title=summary.title,
        path=str(path.relative_to(repo_root)),
        size=summary.size,
        layers=summary.layers,
        water_terrain_tile_count=histogram_total(summary.terrain_histograms, H3_TERRAIN_WATER),
        river_tile_count=nonzero_histogram_total(summary.river_histograms),
        road_tile_count=nonzero_histogram_total(summary.road_histograms),
        template_count=summary.template_count,
        object_count=summary.object_count,
        event_template_count=event_template_count,
        walker_complete=bool(object_table["complete"]),
        walker_decoded_count=int(object_table["decodedCount"]),
        walker_unsupported_object_id=unsupported_record.get("templateObjectId"),
        walker_unsupported_decoder_status=(unsupported_stop or {}).get("decoderStatus"),
        walker_unsupported_stop_index=(unsupported_stop or {}).get("index"),
        walker_unsupported_record_offset=(unsupported_stop or {}).get("recordOffset"),
        walker_unsupported_error=(unsupported_stop or {}).get("error"),
        walker_decoded_object_ids=decoded_object_ids,
        terrain_histograms=summary.terrain_histograms,
        road_histograms=summary.road_histograms,
        river_histograms=summary.river_histograms,
    )


def require_equal(actual: Any, expected: Any, label: str, errors: list[str]) -> None:
    if actual != expected:
        errors.append(f"{label}: expected {expected!r}, got {actual!r}")


def assert_walker_contract(probe: ScenarioProbe, expected: dict[str, Any], errors: list[str]) -> None:
    require_equal(probe.walker_complete, expected["walkerComplete"], "walkerComplete", errors)
    require_equal(probe.walker_decoded_count, expected["walkerDecodedCount"], "walkerDecodedCount", errors)
    for object_id in expected.get("walkerDecodedObjectIdsInclude", []):
        if object_id not in probe.walker_decoded_object_ids:
            errors.append(f"walkerDecodedObjectIds: expected decoded object id {object_id!r}")
    if "unsupportedStopIndex" in expected:
        require_equal(probe.walker_unsupported_stop_index, expected["unsupportedStopIndex"], "unsupportedStopIndex", errors)
    if "unsupportedRecordOffset" in expected:
        require_equal(
            probe.walker_unsupported_record_offset,
            expected["unsupportedRecordOffset"],
            "unsupportedRecordOffset",
            errors,
        )
    if "unsupportedObjectId" in expected:
        require_equal(probe.walker_unsupported_object_id, expected["unsupportedObjectId"], "unsupportedObjectId", errors)
    if "unsupportedDecoderStatus" in expected:
        require_equal(
            probe.walker_unsupported_decoder_status,
            expected["unsupportedDecoderStatus"],
            "unsupportedDecoderStatus",
            errors,
        )
    if "unsupportedError" in expected:
        require_equal(probe.walker_unsupported_error, expected["unsupportedError"], "unsupportedError", errors)


def assert_probe_contract(probe: ScenarioProbe, expected: dict[str, Any]) -> None:
    errors: list[str] = []
    require_equal(probe.layers, expected["layers"], "layers", errors)
    require_equal(
        probe.water_terrain_tile_count,
        expected["waterTerrainTileCount"],
        "waterTerrainTileCount",
        errors,
    )
    if "riverTileCount" in expected:
        require_equal(probe.river_tile_count, expected["riverTileCount"], "riverTileCount", errors)
    if "roadTileCount" in expected:
        require_equal(probe.road_tile_count, expected["roadTileCount"], "roadTileCount", errors)
    if "eventTemplateCount" in expected:
        require_equal(probe.event_template_count, expected["eventTemplateCount"], "eventTemplateCount", errors)
    if "eventTemplateCountMin" in expected and probe.event_template_count < expected["eventTemplateCountMin"]:
        errors.append(
            f"eventTemplateCount: expected >= {expected['eventTemplateCountMin']!r}, got {probe.event_template_count!r}"
        )
    assert_walker_contract(probe, expected, errors)
    if errors:
        raise AssertionError(f"{Path(probe.path).name} contract failed: " + "; ".join(errors))


def assert_contract(probes_by_name: dict[str, ScenarioProbe], parse_errors_by_name: dict[str, str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    missing = sorted(set(ASSERTED_MAPS) - set(probes_by_name) - set(parse_errors_by_name))
    if missing:
        raise AssertionError(f"asserted H3M map(s) missing: {', '.join(missing)}")
    asserted_parse_errors = sorted(set(ASSERTED_MAPS) & set(parse_errors_by_name))
    if asserted_parse_errors:
        details = "; ".join(f"{name}: {parse_errors_by_name[name]}" for name in asserted_parse_errors)
        raise AssertionError(f"asserted H3M map parse failed: {details}")

    good_to_go = probes_by_name["Good to Go.h3m"]
    assert_probe_contract(good_to_go, EXPECTED_CONTRACTS["Good to Go.h3m"])
    results.append(
        {
            "map": "Good to Go.h3m",
            "status": EXPECTED_CONTRACTS["Good to Go.h3m"]["status"],
            "reason": "surface-only RoE scenario fully decodes through version-aware hero/creature/artifact payload widths",
            "eventTemplateCount": good_to_go.event_template_count,
            "waterTerrainTileCount": good_to_go.water_terrain_tile_count,
            "riverTileCount": good_to_go.river_tile_count,
            "roadTileCount": good_to_go.road_tile_count,
            "walkerComplete": good_to_go.walker_complete,
            "walkerDecodedCount": good_to_go.walker_decoded_count,
            "walkerUnsupportedObjectId": good_to_go.walker_unsupported_object_id,
            "walkerUnsupportedDecoderStatus": good_to_go.walker_unsupported_decoder_status,
            "walkerUnsupportedStopIndex": good_to_go.walker_unsupported_stop_index,
            "walkerUnsupportedRecordOffset": good_to_go.walker_unsupported_record_offset,
        }
    )

    great_race = probes_by_name["The Great Race.h3m"]
    assert_probe_contract(great_race, EXPECTED_CONTRACTS["The Great Race.h3m"])
    results.append(
        {
            "map": "The Great Race.h3m",
            "status": EXPECTED_CONTRACTS["The Great Race.h3m"]["status"],
            "reason": "surface-only SoD scenario now fully decodes through the generic walker, including desert-hills scenery ids 206/207",
            "eventTemplateCount": great_race.event_template_count,
            "waterTerrainTileCount": great_race.water_terrain_tile_count,
            "riverTileCount": great_race.river_tile_count,
            "roadTileCount": great_race.road_tile_count,
            "roadMappingStatus": EXPECTED_CONTRACTS["The Great Race.h3m"]["roadMappingStatus"],
            "riverMappingStatus": EXPECTED_CONTRACTS["The Great Race.h3m"]["riverMappingStatus"],
            "walkerComplete": great_race.walker_complete,
            "walkerDecodedCount": great_race.walker_decoded_count,
            "walkerUnsupportedObjectId": great_race.walker_unsupported_object_id,
            "walkerUnsupportedDecoderStatus": great_race.walker_unsupported_decoder_status,
            "walkerUnsupportedStopIndex": great_race.walker_unsupported_stop_index,
            "walkerUnsupportedRecordOffset": great_race.walker_unsupported_record_offset,
        }
    )
    return results


def iter_probe_paths(maps_dir: Path, scan_all_report_only: bool) -> list[Path]:
    if scan_all_report_only:
        return sorted(maps_dir.glob("*.h3m"), key=lambda item: item.name.lower())
    return [maps_dir / name for name in sorted(ASSERTED_MAPS)]


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    maps_dir = repo_root / "vcmi" / "Maps"
    if not maps_dir.is_dir():
        raise FileNotFoundError(f"VCMI map directory not found: {maps_dir}")

    probes: list[ScenarioProbe] = []
    parse_errors: list[dict[str, str]] = []
    probes_by_name: dict[str, ScenarioProbe] = {}
    parse_errors_by_name: dict[str, str] = {}

    for path in iter_probe_paths(maps_dir, args.scan_all_report_only):
        if not path.is_file():
            error = {"path": str(path.relative_to(repo_root)), "error": "FileNotFoundError: asserted map is missing"}
            parse_errors.append(error)
            parse_errors_by_name[path.name] = error["error"]
            continue
        try:
            probe = probe_h3m(path, repo_root)
        except Exception as exc:
            error = {"path": str(path.relative_to(repo_root)), "error": f"{type(exc).__name__}: {exc}"}
            parse_errors.append(error)
            parse_errors_by_name[path.name] = error["error"]
            continue
        probes.append(probe)
        probes_by_name[path.name] = probe
        print(json.dumps({"kind": "map", **probe.to_json()}, sort_keys=True))

    contract_results: list[dict[str, Any]] = []
    if not args.no_contract:
        contract_results = assert_contract(probes_by_name, parse_errors_by_name)
        for result in contract_results:
            print(json.dumps({"kind": "contract", **result}, sort_keys=True))
    else:
        asserted_parse_errors = sorted(set(ASSERTED_MAPS) & set(parse_errors_by_name))
        if asserted_parse_errors:
            details = "; ".join(f"{name}: {parse_errors_by_name[name]}" for name in asserted_parse_errors)
            raise AssertionError(f"asserted H3M map parse failed: {details}")

    print(
        json.dumps(
            {
                "kind": "summary",
                "mapsScanned": len(probes) + len(parse_errors),
                "mapsParsed": len(probes),
                "parseErrors": len(parse_errors),
                "contractAssertions": len(contract_results),
            },
            sort_keys=True,
        )
    )
    if parse_errors:
        print(json.dumps({"kind": "parseErrors", "items": parse_errors}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
