"""Run the read-only deformation audit for every generated mocap candidate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from audit_frame_deformation import audit_candidate


def audit_root(root: Path, units: list[str] | None = None) -> dict:
    selected = set(units or [])
    rows = []
    for candidate in sorted(root.glob("*/weights_only_v1/*_candidate.glb")):
        sid = candidate.parent.parent.name
        if selected and sid not in selected:
            continue
        try:
            result = audit_candidate(candidate)
            result["unit"] = sid
            rows.append(result)
        except Exception as exc:  # retain a diagnostic row instead of hiding a bad candidate
            rows.append({"unit": sid, "glb": candidate.as_posix(), "error": str(exc)})
    return {
        "schema": "homm3.mocap-frame-deformation-batch.v1",
        "proof": "generated-candidate diagnostic",
        "candidateRoot": root.as_posix(),
        "clipCount": len(rows),
        "unitCount": len({row["unit"] for row in rows}),
        "attentionUnits": sorted({row["unit"] for row in rows if row.get("flaggedRegions")}),
        "highStrainUnits": sorted({row["unit"] for row in rows if any(item.get("highStrain") for item in row.get("regions", {}).values())}),
        "errorUnits": sorted({row["unit"] for row in rows if row.get("error")}),
        "units": rows,
        "policy": "diagnostic-only; no mesh, joint, camera, or captured-motion edits",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("artifacts/homm3_mocap_v2/all_mocap_candidates"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--unit", action="append", dest="units")
    args = parser.parse_args()
    payload = json.dumps(audit_root(args.root.resolve(), args.units), indent=2) + "\n"
    args.out.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.out.resolve().write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
