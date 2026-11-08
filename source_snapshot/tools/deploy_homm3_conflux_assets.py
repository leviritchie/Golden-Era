#!/usr/bin/env python3
"""Check and stage HoMM3 Conflux asset sources.

This is a historical Conflux source-presence checker. It verifies that the
declared HoMM3 source archives/members are available, but it deliberately does
not create placeholder runtime assets. Current Conflux release payloads are
owned by the manifest, release overlay, generic asset deployment, and runtime
mirror paths; this checker is not a release-promotion gate.
"""

from __future__ import annotations

import argparse
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOMM3_DATA = ROOT / "HoMM 3 Complete" / "Data"

SOURCE_DECLARATIONS = {
    "H3sprite.lod": (
        "Cpixie.def",
        "CSprite.def",
        "CAELEM.def",
        "Cstorm.def",
        "CWELEM.def",
        "Cicee.def",
        "CFELEM.def",
        "Cnrg.def",
        "CEELEM.def",
        "Cmagel.def",
        "Cpsyel.def",
        "Cfbird.DEF",
        "Cphx.def",
        "AVGpixie.def",
        "AVWpixie.def",
        "AVGair0.def",
        "AVWstorm.def",
        "avgelem0.def",
        "AVWicee.def",
        "AVGfire0.def",
        "AVWnrg.def",
        "AVWmagel.def",
        "AVWpsye.def",
        "AVWfbird.def",
        "AVWphx.def",
    ),
    "H3ab_spr.lod": (
        "HallElem.def",
        "TBELhall.def",
        "TBELcstl.def",
        "TBELdw_0.def",
        "TBELdw_1.def",
        "TBELdw_2.def",
        "TBELdw_3.def",
        "TBELdw_4.def",
        "TBELdw_5.def",
        "TBELdw_6.def",
        "TBELup_0.def",
        "TBELup_1.def",
        "TBELup_2.def",
        "TBELup_3.def",
        "TBELup_4.def",
        "TBELup_5.def",
        "TBELup_6.def",
        "TBELHrd1.def",
        "TBELHrd2.def",
        "TBELSpec.def",
        "TBELHoly.def",
        "TBELmag2.def",
        "TBELmag3.def",
        "TBELmag4.def",
        "TBELmag5.def",
    ),
}


def list_lod_members(path: Path) -> set[str]:
    data = path.read_bytes()
    if data[:4] != b"LOD\0":
        raise RuntimeError(f"not an LOD archive: {path}")
    total = struct.unpack_from("<I", data, 8)[0]
    offset = 92
    names: set[str] = set()
    for _ in range(total):
        raw_name = data[offset : offset + 16]
        offset += 16
        nul = raw_name.find(b"\0")
        name = (raw_name[:nul] if nul >= 0 else raw_name).decode("latin1")
        offset += 16
        names.add(name.lower())
    return names


def check_sources() -> list[str]:
    errors: list[str] = []
    for lod_name, required_members in SOURCE_DECLARATIONS.items():
        lod_path = HOMM3_DATA / lod_name
        if not lod_path.is_file():
            errors.append(f"missing source archive: {lod_path}")
            continue
        members = list_lod_members(lod_path)
        for member in required_members:
            if member.lower() not in members:
                errors.append(f"{lod_name}: missing declared Conflux member {member}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-sources", action="store_true", help="Only verify declared source archive members.")
    args = parser.parse_args()

    errors = check_sources()
    if errors:
        for error in errors:
            print("ERROR: " + error)
        return 1

    print("Conflux source declarations are present.")
    if not args.check_sources:
        print("Asset deployment is intentionally not implemented in this historical checker; use the manifest/release-overlay asset pipeline instead.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
