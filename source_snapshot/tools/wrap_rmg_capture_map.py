#!/usr/bin/env python3
"""Wrap a captured RMG MapData JSON dump into a loadable Olden .map container.

Used when Homm3RmgMapCaptureBridge falls back to JsonUtility.ToJson(MapData).
Native ql.Save captures already write a gzip .map and do not need this tool.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "experiments" / "campaign_port_poc"))

from port_homecoming_poc import (  # noqa: E402
    OldenMapContainer,
    read_olden_map_container,
    write_olden_map_container,
)

DEFAULT_DONOR = Path(
    r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era"
    r"\HeroesOldenEra_Data\StreamingAssets\maps\Thirst_for_Power.map"
)


def fail(message: str) -> None:
    raise SystemExit(f"wrap_rmg_capture_map failed: {message}")


def build_meta(sid: str, map_data: dict, donor_meta: dict) -> dict:
    meta = dict(donor_meta)
    meta["title"] = sid
    meta["hashSum"] = hashlib.md5(sid.encode("utf-8")).hexdigest()
    size_x = map_data.get("sizeX_") if map_data.get("sizeX_") is not None else map_data.get("sizeX")
    size_z = map_data.get("sizeZ_") if map_data.get("sizeZ_") is not None else map_data.get("sizeZ")
    if size_x is not None:
        meta["sizeX"] = int(size_x)
    if size_z is not None:
        meta["sizeZ"] = int(size_z)
    meta["isScenario"] = True
    return meta


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map-data-json", type=Path, required=True)
    parser.add_argument("--sid", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--donor-map", type=Path, default=DEFAULT_DONOR)
    args = parser.parse_args()

    if not args.map_data_json.is_file():
        fail(f"missing MapData JSON: {args.map_data_json}")
    if not args.donor_map.is_file():
        fail(f"missing donor map: {args.donor_map}")

    map_data = json.loads(args.map_data_json.read_text(encoding="utf-8-sig"))
    if not isinstance(map_data, dict):
        fail("MapData JSON root must be an object")

    map_data["fileMapName"] = args.sid
    donor = read_olden_map_container(args.donor_map)
    donor_meta = donor.chunks[0]
    if not isinstance(donor_meta, dict):
        fail("donor chunk0 meta was not an object")

    meta = build_meta(args.sid, map_data, donor_meta)
    container = OldenMapContainer(
        version=donor.version,
        prefix_suffix=donor.prefix_suffix,
        chunks=[
            meta,
            map_data,
            {"dialogs": {}, "quests": {}},
            {"counters": {}, "quests": {}, "aiRolesId": ""},
        ],
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_olden_map_container(args.out, container, meta["hashSum"])
    print(f"wrote {args.out} sid={args.sid} hash={meta['hashSum']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
